"""HTTP adapter for the ChatKit protocol exposed by the airline SUT."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

import httpx

from ..config import SutConfig, safe_url
from ..errors import ProtocolError, SutUnavailableError, TraceIncompleteError
from .models import HealthStatus, ObservedEvent, SutSession, SutTraceSnapshot, SutTurnResult


_KNOWN_EVENT_TYPES = {"message", "handoff", "tool_call", "tool_output", "context_update"}
_SSE_ASSISTANT_DONE_TYPES = {"assistant_message"}
_MAX_SSE_LINE_CHARS = 1_000_000


class ChatKitAdapter:
    """Translate Gate operations to ChatKit requests without exposing its wire types."""

    def __init__(self, config: SutConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        timeout = httpx.Timeout(config.request_timeout_seconds)
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        self._closed = False

    @property
    def base_url(self) -> str:
        return self.config.base_url.rstrip("/")

    async def health_check(self) -> HealthStatus:
        started = time.perf_counter()
        try:
            response = await self._client.get(
                self._url(self.config.health_path), headers=self._headers()
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SutUnavailableError(
                f"SUT health check could not connect to {safe_url(self.base_url)}.",
                detail=type(exc).__name__,
            ) from exc
        except httpx.ProtocolError as exc:
            raise ProtocolError("SUT returned an invalid HTTP response during health check.", detail=type(exc).__name__) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000
        if 400 <= response.status_code < 500 and response.status_code not in {408, 429}:
            raise ProtocolError(
                f"SUT health endpoint returned HTTP {response.status_code}.",
                detail=f"status={response.status_code}",
            )
        healthy = response.status_code == 200
        if healthy:
            try:
                body = response.json()
            except ValueError as exc:
                raise ProtocolError("SUT health endpoint returned invalid JSON.") from exc
            healthy = isinstance(body, Mapping) and body.get("status") == "healthy"
        return HealthStatus(
            healthy=healthy,
            status_code=response.status_code,
            latency_ms=elapsed_ms,
        )

    async def create_session(self) -> SutSession:
        response = await self._request("GET", "/chatkit/bootstrap")
        payload = self._json_object(response, operation="create session")
        thread_id = payload.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ProtocolError("SUT bootstrap response is missing a valid thread_id.")
        return SutSession(thread_id=thread_id)

    async def send_turn(self, session: SutSession, user_input: str) -> SutTurnResult:
        self._ensure_open(session)
        if not isinstance(user_input, str) or not user_input.strip():
            raise ProtocolError("User input must be a non-empty string.")

        request_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        counts: Counter[str] = Counter()
        unknown: set[str] = set()
        unknown_events: list[dict[str, Any]] = []
        assistant_done = False
        payload = {
            "type": "threads.add_user_message",
            "params": {
                "thread_id": session.thread_id,
                "input": {
                    "content": [{"type": "input_text", "text": user_input}],
                    "attachments": [],
                    "inference_options": {},
                },
            },
        }

        try:
            async with self._client.stream(
                "POST",
                self._url("/chatkit"),
                json=payload,
                headers=self._headers(request_id),
            ) as response:
                self._raise_for_status(response, operation="send turn")
                async for line in response.aiter_lines():
                    if len(line) > _MAX_SSE_LINE_CHARS:
                        raise ProtocolError("ChatKit SSE event exceeded the configured size limit.")
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProtocolError("ChatKit returned a malformed SSE data event.") from exc
                    if not isinstance(event, Mapping) or not isinstance(event.get("type"), str):
                        raise ProtocolError("ChatKit SSE event is missing a string type.")
                    event_type = event["type"]
                    counts[event_type] += 1
                    if event_type not in {
                        "thread.created", "thread.updated", "thread.item.added",
                        "thread.item.updated", "thread.item.done", "thread.item.removed",
                        "stream_options", "client_effect",
                    }:
                        unknown.add(event_type)
                        unknown_events.append(dict(event))
                    if event_type == "error":
                        raise ProtocolError("ChatKit reported an error while processing the turn.")
                    item = event.get("item")
                    if (
                        event_type == "thread.item.done"
                        and isinstance(item, Mapping)
                        and item.get("type") in _SSE_ASSISTANT_DONE_TYPES
                    ):
                        assistant_done = True
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SutUnavailableError(
                f"SUT request failed while sending a turn to {safe_url(self.base_url)}.",
                detail=type(exc).__name__,
            ) from exc
        except httpx.ProtocolError as exc:
            raise ProtocolError("SUT returned an invalid HTTP stream during the turn.", detail=type(exc).__name__) from exc

        completed_at = datetime.now(timezone.utc)
        if not assistant_done:
            raise TraceIncompleteError(
                "ChatKit stream ended without a completed assistant message.",
                detail=f"request_id={request_id}; event_types={','.join(sorted(counts))}",
            )
        session.completed_turns += 1
        return SutTurnResult(
            thread_id=session.thread_id,
            user_input=user_input,
            started_at=started_at,
            completed_at=completed_at,
            assistant_message_completed=True,
            event_type_counts=dict(counts),
            unknown_event_types=sorted(unknown),
            unknown_events=unknown_events,
            request_id=request_id,
        )

    async def fetch_trace(
        self, session: SutSession, *, require_activity: bool | None = None
    ) -> SutTraceSnapshot:
        self._ensure_open(session)
        response = await self._request(
            "GET", "/chatkit/state", params={"thread_id": session.thread_id}
        )
        payload = self._json_object(response, operation="fetch trace")
        returned_thread_id = payload.get("thread_id")
        if returned_thread_id != session.thread_id:
            raise ProtocolError(
                "SUT state endpoint returned a different thread_id than requested."
            )

        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            raise ProtocolError("SUT state response is missing an events list.")
        events = [self._parse_event(item, index) for index, item in enumerate(raw_events)]
        raw_context = payload.get("context", {})
        raw_agents = payload.get("agents", [])
        raw_guardrails = payload.get("guardrails", [])
        if not isinstance(raw_context, Mapping):
            raise ProtocolError("SUT state context must be an object.")
        if not isinstance(raw_agents, list) or any(not isinstance(item, Mapping) for item in raw_agents):
            raise ProtocolError("SUT state agents must be a list of objects.")
        if not isinstance(raw_guardrails, list) or any(
            not isinstance(item, Mapping) for item in raw_guardrails
        ):
            raise ProtocolError("SUT state guardrails must be a list of objects.")
        should_require_activity = (
            session.completed_turns > 0 if require_activity is None else require_activity
        )
        if should_require_activity and not events and not raw_guardrails:
            raise TraceIncompleteError(
                "SUT returned no Agent events or guardrail observations for a completed turn."
            )

        known = {"thread_id", "current_agent", "context", "agents", "events", "guardrails"}
        return SutTraceSnapshot(
            thread_id=session.thread_id,
            current_agent=(payload.get("current_agent") if isinstance(payload.get("current_agent"), str) else None),
            context=dict(raw_context),
            agents=[dict(item) for item in raw_agents],
            events=events,
            guardrails=[dict(item) for item in raw_guardrails],
            extra_fields={key: value for key, value in payload.items() if key not in known},
            raw_payload=dict(payload),
        )

    async def close_session(self, session: SutSession) -> None:
        # The SUT exposes no delete/close operation. This prevents further use by
        # this adapter; the in-memory server retains the thread until process exit.
        session.closed = True

    async def aclose(self) -> None:
        if not self._closed and self._owns_client:
            await self._client.aclose()
        self._closed = True

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                self._url(path),
                params=params,
                headers=self._headers(),
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SutUnavailableError(
                f"SUT endpoint {path} is unavailable at {safe_url(self.base_url)}.",
                detail=type(exc).__name__,
            ) from exc
        except httpx.ProtocolError as exc:
            raise ProtocolError(f"SUT returned an invalid HTTP response for {path}.", detail=type(exc).__name__) from exc
        self._raise_for_status(response, operation=path)
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, operation: str) -> None:
        if response.is_success:
            return
        message = f"SUT returned HTTP {response.status_code} during {operation}."
        if response.status_code >= 500 or response.status_code in {408, 429}:
            raise SutUnavailableError(message, detail=f"status={response.status_code}")
        raise ProtocolError(message, detail=f"status={response.status_code}")

    @staticmethod
    def _json_object(response: httpx.Response, *, operation: str) -> Mapping[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise ProtocolError(f"SUT returned invalid JSON during {operation}.") from exc
        if not isinstance(value, Mapping):
            raise ProtocolError(f"SUT returned a non-object response during {operation}.")
        return value

    @staticmethod
    def _parse_event(value: Any, sequence: int) -> ObservedEvent:
        if not isinstance(value, Mapping):
            raise ProtocolError(f"SUT event at index {sequence} is not an object.")
        event_type = value.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise ProtocolError(f"SUT event at index {sequence} has no type.")
        metadata = value.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, Mapping):
            raise ProtocolError(f"SUT event at index {sequence} metadata must be an object.")
        known = {"id", "type", "agent", "content", "metadata", "timestamp"}
        agent = value.get("agent")
        return ObservedEvent(
            event_id=(value.get("id") if isinstance(value.get("id"), str) else None),
            event_type=event_type,
            agent=agent if isinstance(agent, str) else None,
            content=value.get("content"),
            metadata=dict(metadata),
            timestamp=value.get("timestamp"),
            extra_fields={key: item for key, item in value.items() if key not in known},
        )

    def _headers(self, request_id: str | None = None) -> dict[str, str]:
        return {"X-Request-ID": request_id or uuid4().hex}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _ensure_open(session: SutSession) -> None:
        if session.closed:
            raise ProtocolError("SUT session has already been closed by this adapter.")

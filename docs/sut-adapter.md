# SUT Adapter and Lifecycle Contract

P2 implementation for the locked OpenAI CS Agents Demo. The adapter is the only package that knows the ChatKit wire protocol; later evaluators should consume Gate-owned records and should not parse SSE or call ChatKit endpoints directly.

## Adapter operations

| Operation | SUT endpoint/behavior | Gate return |
|---|---|---|
| `health_check()` | `GET /health`, expects HTTP 200 and `{"status":"healthy"}` | `HealthStatus(healthy, status_code, latency_ms, checked_at)` |
| `create_session()` | `GET /chatkit/bootstrap` creates/returns a fresh thread in the SUT | `SutSession(thread_id)` |
| `send_turn(session, text)` | ChatKit `threads.add_user_message` to `/chatkit`, consumes SSE through completion | `SutTurnResult`, including input, completion, event type counts, request ID, unknown event types/payloads |
| `fetch_trace(session)` | `GET /chatkit/state?thread_id=...` | `SutTraceSnapshot` with typed observed events and preserved unknown fields |
| `close_session(session)` | No delete endpoint exists; marks the local session handle closed | prevents use through this adapter; does not delete server-side memory |
| `aclose()` | Closes the adapter-owned HTTP client | releases connection pool |

Each request gets an `X-Request-ID`. The SUT currently does not echo or record that header in its event snapshot; the ID is therefore local correlation metadata only.

## Session and turn rules

- Create one fresh session per case. Keep one session only for turns belonging to the same multi-turn case.
- `send_turn` does not retry. A timeout can happen after the SUT has executed a tool, so automatic retry could duplicate a non-idempotent action.
- A turn is accepted only when ChatKit ends with a completed assistant message. Clean stream termination without that evidence raises `TraceIncompleteError`.
- After a completed turn, `fetch_trace` requires activity by default because the session records completed turns. For a guardrail refusal the SUT may have no AgentEvent but should expose guardrail observations; both absent is an incomplete trace. Set `require_activity=False` only for an intentional empty-session snapshot.
- `close_session` is local-only. Server state remains in the SUT's in-memory store until the process exits; artifact persistence and trace redaction are P3 responsibilities.

## Event handling and privacy

- Known SUT AgentEvent types are `message`, `handoff`, `tool_call`, `tool_output`, and `context_update`.
- Every snapshot event is validated as an object with a non-empty string `type`; malformed structure raises `ProtocolError` instead of silently dropping it.
- Unknown event types and additional fields are kept in the returned records for later schema evolution. They are not logged. P3 must redact them before persistence.
- ChatKit workflow/reasoning updates use known ChatKit envelope types and are counted only as stream events; their text is intentionally not retained by the adapter.
- SSE lines over 1 MB and malformed JSON are rejected as protocol errors.
- Request/response bodies and user text are never written to logs. Diagnostic URL output removes user information, query strings, and fragments. SUT output tails are bounded and pass through the secret redactor.

## Lifecycle modes

`config/gate.example.yaml` supports:

- `external`: connect to a service started by the developer or CI; Gate never stops it.
- `process`: execute `sut.launch_command` without a shell, inherit the current environment, wait for health, then terminate/kill the launched process on exit.
- `compose`: execute configured `launch_command` and `shutdown_command` argument arrays, wait for health after startup, and invoke shutdown during cleanup.

Commands are argument arrays (for example `["python", "-m", "uvicorn", "main:app", "--port", "8000"]`), not shell strings. Supply `working_directory` when the command depends on the SUT checkout. Secrets must be provided in the inherited environment, not command arguments or YAML. The P2 process mode manages the direct process; use Compose mode when cleanup must cover a process tree or multiple services.

`startup_timeout_seconds` bounds health waiting and completed lifecycle commands. `shutdown_timeout_seconds` bounds process termination and compose shutdown. Health probes retry at 500 ms intervals until the startup deadline. The adapter never retries a conversation turn.

## Error mapping

| Failure | Category |
|---|---|
| Connection refused, connect/read timeout, network failure, HTTP 5xx/408/429 | `sut_unavailable` |
| HTTP 4xx (except 408/429), invalid JSON, missing fields, wrong thread ID, malformed SSE | `protocol_error` |
| Completed stream without assistant completion, or required snapshot with no events/guardrails | `trace_incomplete` |
| Invalid adapter/session usage or launch config | `configuration_error` / `protocol_error` |

Errors contain status/type information rather than server response bodies, which may include user content. Startup timeout may include a bounded, redacted SUT stdout/stderr tail in the diagnostic detail field.

## Diagnostic examples

Successful check:

```text
SUT healthy: http://127.0.0.1:8000 (HTTP 200, 4.2 ms)
```

Unavailable check:

```text
ERROR[sut_unavailable]: SUT did not become healthy at http://127.0.0.1:8000 within 60s.
```

The examples are output shapes; latency varies per run.

Successful turn receipt (IDs shortened for illustration):

```json
{
  "thread_id": "thr_example",
  "assistant_message_completed": true,
  "event_type_counts": {
    "thread.item.done": 2,
    "client_effect": 3
  },
  "unknown_event_types": [],
  "request_id": "request-example"
}
```

If the stream closes without an assistant completion event, the adapter returns a typed error rather than an empty success:

```text
ERROR[trace_incomplete]: ChatKit stream ended without a completed assistant message.
```

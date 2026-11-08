"""SUT-facing records. ChatKit-specific fields are isolated in this package."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..models import utc_now


@dataclass(slots=True)
class SutSession:
    thread_id: str
    created_at: datetime = field(default_factory=utc_now)
    closed: bool = False
    completed_turns: int = 0


@dataclass(slots=True)
class HealthStatus:
    healthy: bool
    status_code: int | None
    latency_ms: float
    checked_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class SutTurnResult:
    thread_id: str
    user_input: str
    started_at: datetime
    completed_at: datetime
    assistant_message_completed: bool
    event_type_counts: dict[str, int] = field(default_factory=dict)
    unknown_event_types: list[str] = field(default_factory=list)
    unknown_events: list[dict[str, Any]] = field(default_factory=list)
    request_id: str = ""


@dataclass(slots=True)
class ObservedEvent:
    event_id: str | None
    event_type: str
    agent: str | None
    content: Any
    metadata: dict[str, Any]
    timestamp: Any = None
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SutTraceSnapshot:
    thread_id: str
    current_agent: str | None
    context: dict[str, Any]
    agents: list[dict[str, Any]]
    events: list[ObservedEvent]
    guardrails: list[dict[str, Any]]
    fetched_at: datetime = field(default_factory=utc_now)
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdapterHealth:
    status: HealthStatus
    base_url: str

"""Protocol shared by HTTP adapters and the run lifecycle."""

from __future__ import annotations

from typing import Protocol

from .models import HealthStatus, SutSession, SutTraceSnapshot, SutTurnResult


class SutAdapter(Protocol):
    async def health_check(self) -> HealthStatus: ...

    async def create_session(self) -> SutSession: ...

    async def send_turn(self, session: SutSession, user_input: str) -> SutTurnResult: ...

    async def fetch_trace(
        self, session: SutSession, *, require_activity: bool | None = None
    ) -> SutTraceSnapshot: ...

    async def close_session(self, session: SutSession) -> None: ...

    async def aclose(self) -> None: ...

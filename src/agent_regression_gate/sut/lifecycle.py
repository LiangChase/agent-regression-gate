"""Start/check/stop a SUT without assuming a specific process manager."""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from collections.abc import Sequence
from typing import Any

from ..config import SutConfig, safe_url
from ..errors import ConfigurationError, SutUnavailableError
from ..logging_config import redact_text
from .base import SutAdapter
from .models import HealthStatus


class SutLifecycle:
    """Manage external, long-running process, or command-based compose modes."""

    def __init__(self, config: SutConfig, adapter: SutAdapter) -> None:
        self.config = config
        self.adapter = adapter
        self.last_health: HealthStatus | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._output_tail: deque[str] = deque(maxlen=60)
        self._started = False

    async def __aenter__(self) -> "SutLifecycle":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.stop()

    async def start(self) -> HealthStatus:
        if self._started:
            raise ConfigurationError("SUT lifecycle has already been started.")
        self._started = True
        try:
            mode = self.config.start_mode
            if mode == "process":
                await self._start_process()
            elif mode == "compose":
                await self._run_command(self.config.launch_command, label="start")
            elif mode != "external":
                raise ConfigurationError(f"Unsupported SUT start mode '{mode}'.")
            return await self._wait_until_healthy()
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self.config.start_mode == "process" and self._process is not None:
            process = self._process
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=self.config.shutdown_timeout_seconds)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass
            self._process = None
        elif self.config.start_mode == "compose" and self._started and self.config.shutdown_command:
            await self._run_command(self.config.shutdown_command, label="stop", allow_failure=True)
        self._started = False

    async def _start_process(self) -> None:
        cwd = str(self.config.working_directory) if self.config.working_directory else None
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.config.launch_command,
                cwd=cwd,
                env=os.environ.copy(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except (OSError, ValueError) as exc:
            raise SutUnavailableError(
                "Could not start the configured SUT process.", detail=type(exc).__name__
            ) from exc
        self._reader_task = asyncio.create_task(self._capture_output(self._process.stdout))

    async def _capture_output(self, stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        pending = bytearray()
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                if pending:
                    self._append_output_line(pending)
                return
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, remainder = pending.partition(b"\n")
                pending = bytearray(remainder)
                self._append_output_line(line)
            if len(pending) > 8192:
                self._append_output_line(pending[-2000:])
                pending.clear()

    def _append_output_line(self, line: bytes | bytearray) -> None:
        text = bytes(line).decode("utf-8", errors="replace").rstrip("\r")
        self._output_tail.append(redact_text(text[-2000:]))

    async def _run_command(
        self, command: Sequence[str], *, label: str, allow_failure: bool = False
    ) -> None:
        cwd = str(self.config.working_directory) if self.config.working_directory else None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=os.environ.copy(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except (OSError, ValueError) as exc:
            if allow_failure:
                return
            raise SutUnavailableError(
                f"Could not run the configured SUT {label} command.",
                detail=type(exc).__name__,
            ) from exc

        output = bytearray()

        async def drain_output_and_wait() -> int:
            assert process.stdout is not None
            while True:
                chunk = await process.stdout.read(8192)
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > 128_000:
                    del output[:-128_000]
            return await process.wait()

        timeout = (
            self.config.shutdown_timeout_seconds
            if label == "stop"
            else self.config.startup_timeout_seconds
        )
        try:
            return_code = await asyncio.wait_for(drain_output_and_wait(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            tail = bytes(output).decode("utf-8", errors="replace")[-4000:]
            raise SutUnavailableError(
                f"SUT {label} command timed out.", detail=redact_text(tail) or None
            )
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        self._output_tail.extend(
            redact_text(line.decode("utf-8", errors="replace").rstrip()[-2000:])
            for line in bytes(output).splitlines()[-20:]
        )
        if return_code != 0 and not allow_failure:
            raise SutUnavailableError(
                f"SUT {label} command exited with status {return_code}.",
                detail="\n".join(self._output_tail),
            )

    async def _wait_until_healthy(self) -> HealthStatus:
        deadline = time.monotonic() + self.config.startup_timeout_seconds
        last_error: Exception | None = None
        last_status_code: int | None = None
        while time.monotonic() < deadline:
            if self._process is not None and self._process.returncode is not None:
                break
            try:
                remaining = max(0.01, deadline - time.monotonic())
                status = await asyncio.wait_for(self.adapter.health_check(), timeout=remaining)
                self.last_health = status
                last_status_code = status.status_code
                if status.healthy:
                    return status
            except asyncio.TimeoutError as exc:
                last_error = exc
                break
            except SutUnavailableError as exc:
                last_error = exc
            await asyncio.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        detail_parts = []
        if last_error:
            category = getattr(getattr(last_error, "category", None), "value", "timeout")
            detail_parts.append(f"last_health_error={category}")
        if last_status_code is not None:
            detail_parts.append(f"last_http_status={last_status_code}")
        if self._output_tail:
            detail_parts.append("SUT output tail:\n" + "\n".join(self._output_tail))
        raise SutUnavailableError(
            f"SUT did not become healthy at {safe_url(self.config.base_url)} "
            f"within {self.config.startup_timeout_seconds:g}s.",
            detail="\n".join(detail_parts) or None,
        )

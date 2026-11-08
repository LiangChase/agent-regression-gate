"""Atomic storage for versioned normalized traces and sanitized raw snapshots."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from ..config import GateConfig
from ..errors import TraceStorageError
from .redaction import TraceRedactor
from .schema import RAW_SNAPSHOT_SCHEMA_VERSION, TRACE_SCHEMA_VERSION, TraceBundle, to_jsonable

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class TraceStore:
    def __init__(
        self,
        root: str | Path,
        *,
        persist_raw_snapshots: bool = True,
        redact_pii: bool = True,
        max_string_chars: int = 4000,
        max_bundle_bytes: int = 25_000_000,
    ) -> None:
        if max_bundle_bytes < 1:
            raise ValueError("max_bundle_bytes must be greater than zero")
        self.root = Path(root)
        self.persist_raw_snapshots = persist_raw_snapshots
        self.redact_pii = redact_pii
        self.max_string_chars = max_string_chars
        self.max_bundle_bytes = max_bundle_bytes

    @classmethod
    def from_config(cls, config: GateConfig) -> "TraceStore":
        return cls(
            config.run.reports_dir / "traces",
            persist_raw_snapshots=config.trace.persist_raw_snapshots,
            redact_pii=config.trace.redact_pii,
            max_string_chars=config.trace.max_string_chars,
            max_bundle_bytes=config.trace.max_bundle_bytes,
        )

    def save(self, bundle: TraceBundle) -> Path:
        run_id = _safe_component(bundle.trace.run_id, label="run_id")
        case_id = _safe_component(bundle.trace.case_id, label="case_id")
        target_dir = self.root / run_id
        target = target_dir / f"{case_id}.trace.json"
        document = bundle.to_document(include_raw=self.persist_raw_snapshots)
        document["schema_version"] = TRACE_SCHEMA_VERSION
        document["raw_snapshot_schema_version"] = RAW_SNAPSHOT_SCHEMA_VERSION
        document["trace_file_scope"] = "one case trace within a run"

        redactor = TraceRedactor(
            redact_pii=self.redact_pii,
            max_string_chars=self.max_string_chars,
        )
        safe_document = redactor.redact(to_jsonable(document))
        safe_document["redaction_summary"] = redactor.stats.to_dict()
        try:
            payload = json.dumps(
                safe_document,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise TraceStorageError("Trace contains values that cannot be serialized as JSON.") from exc
        if len(payload) > self.max_bundle_bytes:
            raise TraceStorageError(
                f"Sanitized trace is larger than the configured {self.max_bundle_bytes}-byte limit."
            )
        self._atomic_write(target, payload)
        return target

    def load_document(self, path: str | Path) -> dict[str, Any]:
        source = Path(path)
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceStorageError("Trace file could not be read as valid JSON.") from exc
        if not isinstance(document, dict):
            raise TraceStorageError("Trace document root must be a JSON object.")
        if document.get("schema_version") != TRACE_SCHEMA_VERSION:
            raise TraceStorageError(
                f"Unsupported trace schema version: {document.get('schema_version')!r}."
            )
        if document.get("raw_snapshot_schema_version") != RAW_SNAPSHOT_SCHEMA_VERSION:
            raise TraceStorageError(
                "Trace document uses an unsupported raw snapshot schema version."
            )
        trace = document.get("trace")
        if not isinstance(trace, dict) or trace.get("schema_version") != TRACE_SCHEMA_VERSION:
            raise TraceStorageError("Normalized trace is missing a supported schema version.")
        raw_snapshots = document.get("raw_snapshots")
        if not isinstance(raw_snapshots, list):
            raise TraceStorageError("Trace raw_snapshots must be a JSON array.")
        for index, snapshot in enumerate(raw_snapshots):
            if not isinstance(snapshot, dict) or snapshot.get("schema_version") != RAW_SNAPSHOT_SCHEMA_VERSION:
                raise TraceStorageError(
                    f"Raw snapshot {index} is missing a supported schema version."
                )
        return document

    @staticmethod
    def _atomic_write(target: Path, payload: bytes) -> None:
        temporary: str | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except OSError as exc:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            raise TraceStorageError("Trace could not be written atomically.") from exc


def _safe_component(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise TraceStorageError(f"Trace {label} is not a safe path component.")
    return value

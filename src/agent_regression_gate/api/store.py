"""SQLite persistence for the local single-user console."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalStore:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    fail_on TEXT NOT NULL,
                    case_count INTEGER NOT NULL,
                    filters_json TEXT NOT NULL,
                    summary_json TEXT,
                    gate_json TEXT,
                    report_json_path TEXT,
                    report_md_path TEXT,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
                CREATE TABLE IF NOT EXISTS baselines (
                    name TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    file_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS comparisons (
                    comparison_id TEXT PRIMARY KEY,
                    baseline_name TEXT NOT NULL,
                    current_run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    json_path TEXT NOT NULL,
                    markdown_path TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_comparisons_created ON comparisons(created_at DESC);
                CREATE TABLE IF NOT EXISTS runtime_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def recover_interrupted_runs(self) -> int:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE runs SET status='error', completed_at=?, error_message=? WHERE status IN ('queued','running')",
                (now_iso(), "The local API restarted before this run completed."),
            )
            return cursor.rowcount

    def create_run(self, run_id: str, *, fail_on: str, case_count: int, filters: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(run_id,status,created_at,fail_on,case_count,filters_json) VALUES(?,?,?,?,?,?)",
                (run_id, "queued", now_iso(), fail_on, case_count, json.dumps(filters, ensure_ascii=False)),
            )

    def update_run(self, run_id: str, **values: Any) -> None:
        allowed = {
            "status", "started_at", "completed_at", "summary_json", "gate_json",
            "report_json_path", "report_md_path", "error_message",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        for key in ("summary_json", "gate_json"):
            if key in updates and not isinstance(updates[key], str):
                updates[key] = json.dumps(updates[key], ensure_ascii=False)
        assignments = ",".join(f"{key}=?" for key in updates)
        with self.connect() as db:
            db.execute(f"UPDATE runs SET {assignments} WHERE run_id=?", (*updates.values(), run_id))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_dict(row) if row else None

    def count_runs(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) FROM runs").fetchone()
        return int(row[0])

    def list_runs(
        self, *, status: str | None = None, tag: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses, args = [], []
        if status:
            clauses.append("status=?")
            args.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        if not tag:
            args.extend([limit, offset])
        with self.connect() as db:
            query = f"SELECT * FROM runs {where} ORDER BY created_at DESC"
            if not tag:
                query += " LIMIT ? OFFSET ?"
            rows = db.execute(query, args).fetchall()
        values = [self._run_dict(row) for row in rows]
        if tag:
            values = [item for item in values if tag in item["filters"].get("case_tags", [])][offset:offset + limit]
        return values

    def get_runtime_settings(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT setting_key, setting_value FROM runtime_settings").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["setting_key"]] = json.loads(row["setting_value"])
            except (TypeError, ValueError):
                continue
        return result

    def save_runtime_settings(self, values: dict[str, Any]) -> None:
        with self.connect() as db:
            db.executemany(
                "INSERT INTO runtime_settings(setting_key,setting_value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at",
                [(key, json.dumps(value, ensure_ascii=False), now_iso()) for key, value in values.items()],
            )

    def save_baseline(self, *, name: str, run_id: str, reason: str, file_path: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO baselines(name,run_id,reason,saved_at,file_path) VALUES(?,?,?,?,?)",
                (name, run_id, reason, now_iso(), file_path),
            )

    def get_baseline(self, name: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM baselines WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def list_baselines(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM baselines ORDER BY saved_at DESC").fetchall()
        return [dict(row) for row in rows]

    def save_comparison(self, *, comparison_id: str, baseline_name: str, current_run_id: str,
                        status: str, json_path: str, markdown_path: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO comparisons VALUES(?,?,?,?,?,?,?)",
                (comparison_id, baseline_name, current_run_id, status, now_iso(), json_path, markdown_path),
            )

    def get_comparison(self, comparison_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM comparisons WHERE comparison_id=?", (comparison_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        for source, target in (("filters_json", "filters"), ("summary_json", "summary"), ("gate_json", "gate")):
            try:
                value[target] = json.loads(value.pop(source)) if value.get(source) else {}
            except (TypeError, ValueError):
                value[target] = {}
                value.pop(source, None)
        return value

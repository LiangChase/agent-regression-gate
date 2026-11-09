# P9 Local Web API Contract

The FastAPI service is a single-user local interface. Bind it to `127.0.0.1`; the Next.js server forwards same-origin `/api/*` requests to it. This service has no authentication or public deployment support.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Service and local-store readiness |
| GET | `/api/settings` | Safe SUT/model/storage metadata; credentials represented only as configured/not configured |
| PUT | `/api/settings` | Persist SUT URL, revision, request timeout and execution-mode overrides in local SQLite |
| POST | `/api/sut/check` | Check configured SUT health endpoint |
| GET | `/api/cases?risk=&tag=&q=` | Read-only version-controlled cases |
| GET | `/api/dashboard` | Recent run summary and gate counts |
| GET | `/api/runs?status=&tag=&limit=&offset=` | Persisted run history |
| POST | `/api/runs` | Queue one serial evaluation (`case_ids`, `tags`, `risks`, `fail_on`) |
| GET | `/api/runs/{run_id}` | Persisted metadata and sanitized report when complete |
| GET | `/api/runs/{run_id}/traces/{case_id}` | Sanitized trace evidence |
| GET | `/api/runs/{run_id}/report/{json\|md}` | Download run report |
| GET | `/api/baselines` | List reviewed snapshots |
| POST | `/api/baselines` | Explicitly promote a completed run with review reason; names are immutable |
| POST | `/api/comparisons` | Compare a baseline and completed run |
| GET | `/api/comparisons/{comparison_id}` | Read comparison evidence |
| GET | `/api/comparisons/{comparison_id}/report.md` | Download comparison report |

Starting a run returns HTTP 202 and a `run_id`. The browser polls its status (`queued`, `running`, `pass`, `fail`, `error`, `incomplete`). Only one run is active at a time. Queued/running records are marked `error` on restart; completed history remains in SQLite. Reports, traces and baseline payloads remain JSON/Markdown files under configured local directories.

## Data and security boundary

- Cases remain read-only YAML inputs; the UI does not modify behavior specifications.
- Runner, evaluator, report writer and comparison code are shared with CLI/CI.
- Model credentials are read by Python/SUT processes from environment variables; never returned as values or saved in browser storage.
- Trace/report access is limited to configured reports/traces paths. Trace serialization uses the existing redaction pipeline.
- CORS is disabled; same-origin proxying avoids cross-origin browser access.
- Bind only to loopback. Do not expose this unauthenticated version to a LAN or the public internet.
- `GATE_DATA_DIR` changes SQLite location. `GATE_CONFIG` selects Gate YAML; existing SUT/model environment settings remain available. Settings saved in the UI are local SQLite overrides and take precedence over the SUT URL, timeout, revision and execution mode loaded at service startup.

Interactive schema: `http://127.0.0.1:8001/api/docs`.

# Architecture Outline

## Project boundary

Agent Regression Gate is a test and release-quality tool. The business Agent remains the SUT. Gate owns cases, run correlation, SUT adapters, trace normalization, evaluators, comparison, gate decisions, and reports.

```text
web console (P9 implemented)
          │
       Gate API (P9 implemented)
          │
cases ──> execution runner ──> SUT adapter ──> business Agent
                 │                              │
                 └──── case input + trace <─────┘
                              │
                         evaluators
                              │
                    gate result + reports
                              │
                            CI check
```

The CLI and CI invoke the same core directly. The Web console uses the Gate API; it does not call the SUT directly or implement a second evaluator path. The single-user API persists run metadata and runtime SUT overrides in SQLite; reports and traces remain sanitized files.

## Package responsibilities

| Package/module | Responsibility | Phase |
|---|---|---|
| `config.py` | Layered config loading and validation | P1 |
| `models.py`, `errors.py` | Transport-neutral result models and stable error categories | P1 |
| `logging_config.py` | Correlation-aware structured logs and defensive redaction | P1 |
| `sut/` | ChatKit HTTP/SSE adapter, session boundary, and SUT lifecycle | P2 implemented |
| `tracing/` | Trace normalization, completeness, persistence, redaction | P3 implemented |
| `cases/` | Case schemas, loading, static validation | P4 implemented |
| `evaluators/` | Deterministic assertions and optional semantic evaluation | P4/P6 implemented |
| `execution/` | Serial case and run orchestration | P5 implemented |
| `comparison/` | Baseline compatibility checks and case/assertion diff | P6 implemented |
| `reporting/` | Sanitized JSON and Markdown run reports | P5 implemented |
| `cli.py` | Configuration, doctor, case validation, run, baseline, compare and score commands | P1–P6 |
| `api/` | Local FastAPI endpoints, SQLite run/baseline/settings metadata and background run orchestration | P9 implemented |
| `web/` | Next.js + TypeScript dashboard, case/run browser, trace viewer, baselines and settings | P9 implemented |

P0–P8 implement the CLI evaluation loop, optional semantic scoring, baseline comparison, deterministic fixture CI and documentation. P9 adds the loopback-only single-user console. The PR workflow exercises Gate end-to-end with a deterministic ChatKit fixture; its opt-in negative control deliberately produces a red run and retains evidence. `live-sut-gate` is required but only runs the pinned SUT when `config/sut.lock.yaml` changes or when dispatched manually; a lighter manual live smoke remains available for one AIR-01 run. Live runs may incur model cost.

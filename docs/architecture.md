# Architecture Outline

## Project boundary

Agent Regression Gate is a test and release-quality tool. The business Agent remains the SUT. Gate owns cases, run correlation, SUT adapters, trace normalization, evaluators, comparison, gate decisions, and reports.

```text
web console (P9; planned)
          │
       Gate API (P9; planned)
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

The CLI and CI invoke the same core directly. The future Web console will use the Gate API; it will not call the SUT directly or implement a second evaluator path.

## Package responsibilities

| Package/module | Responsibility | Phase |
|---|---|---|
| `config.py` | Layered config loading and validation | P1 |
| `models.py`, `errors.py` | Transport-neutral result models and stable error categories | P1 |
| `logging_config.py` | Correlation-aware structured logs and defensive redaction | P1 |
| `sut/` | ChatKit HTTP/SSE adapter, session boundary, and SUT lifecycle | P2 implemented |
| `tracing/` | Trace normalization, completeness, persistence, redaction | P3 implemented |
| `cases/` | Case schemas, loading, static validation | P4 implemented |
| `evaluators/` | Deterministic assertions and optional semantic evaluation | P4 implemented / P6 planned |
| `execution/` | Serial case and run orchestration | P5 implemented |
| `comparison/` | Baseline diff and gate policy aggregation | P6 planned |
| `reporting/` | Sanitized JSON and Markdown run reports | P5 implemented |
| `cli.py` | Configuration, doctor, case validation, and run commands | P1–P5 |

P1–P5 implement the local CLI foundation: adapter, traces, cases, deterministic evaluators, serial execution, reports, and gate exit codes. Baseline comparison, semantic scoring, CI regression demonstration, and the Web/API product surface remain planned work.

# Architecture Outline

## Project boundary

Agent Regression Gate is a test and release-quality tool. The business Agent remains the SUT. Gate owns cases, run correlation, SUT adapters, trace normalization, evaluators, comparison, gate decisions, and reports.

```text
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

## Package responsibilities

| Package/module | Responsibility | Phase |
|---|---|---|
| `config.py` | Layered config loading and validation | P1 |
| `models.py`, `errors.py` | Transport-neutral result models and stable error categories | P1 |
| `logging_config.py` | Correlation-aware structured logs and defensive redaction | P1 |
| `sut/` | ChatKit HTTP/SSE adapter, session boundary, and SUT lifecycle | P2 implemented |
| `tracing/` | Trace normalization, completeness, persistence, redaction | P3 |
| `cases/` | Case schemas, loading, static validation | P4 |
| `evaluators/` | Deterministic assertions and optional semantic evaluation | P4/P6 |
| `execution/` | Case and run orchestration | P5 |
| `comparison/` | Baseline diff and gate policy aggregation | P5/P6 |
| `reporting/` | JSON and Markdown report generation | P5 |
| `cli.py` | Stable command line boundary | P1 onward |

The P1 repository currently implements configuration checking and the foundation modules. Later-phase package directories are intentionally boundaries, not claims that adapters or evaluators already work.

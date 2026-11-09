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
| `evaluators/` | Deterministic assertions and optional semantic evaluation | P4/P6 implemented |
| `execution/` | Serial case and run orchestration | P5 implemented |
| `comparison/` | Baseline compatibility checks and case/assertion diff | P6 implemented |
| `reporting/` | Sanitized JSON and Markdown run reports | P5 implemented |
| `cli.py` | Configuration, doctor, case validation, run, baseline, compare and score commands | P1–P6 |

P0–P8 implement the CLI evaluation loop, optional semantic scoring, baseline comparison, deterministic fixture CI and documentation. The PR workflow exercises Gate end-to-end with a deterministic ChatKit fixture; its opt-in negative control deliberately produces a red run and retains evidence. The separate manual live smoke runs one case against the pinned SUT and may incur model cost. The Web/API product surface remains planned for P9.

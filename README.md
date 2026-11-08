# Agent Regression Gate

Agent Regression Gate is quality infrastructure for checking whether important agent behavior rules continue to hold as prompts, models, tools, or policies change. The airline customer service demo is the initial system under test (SUT); the gate itself is designed around cases, traces, evaluators, comparisons, and CI rather than one business domain.

## Development setup

Use Python 3.11 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item config/gate.example.yaml config/gate.yaml
gate --help
gate config-check
```

`config/gate.yaml` is intentionally ignored by Git. Keep credentials in environment variables or CI secrets; never add them to YAML, cases, traces, or reports.

## Configuration precedence

Built-in defaults are overridden by the YAML file, then `GATE_*` environment variables, then command-line overrides. The default config path is `config/gate.yaml`; set `GATE_CONFIG` or pass `--config` to use another file.

P1 implements the package, configuration validation, safe effective-config display, and core data/error/logging models. SUT adapters, case execution, evaluators, and report generation are subsequent phases and are not represented as implemented commands yet.

See [the phase plan](agent-regression-gate-phase-plan.md), [architecture outline](docs/architecture.md), and [SUT contract](docs/sut-contract.md).

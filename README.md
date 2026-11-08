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
gate --config config/gate.example.yaml doctor
```

`config/gate.yaml` is intentionally ignored by Git. Relative paths in it are resolved from the current working directory. Keep credentials in environment variables or CI secrets; never add them to YAML, cases, traces, or reports.

## Configuration precedence

Built-in defaults are overridden by the YAML file, then `GATE_*` environment variables, then command-line overrides. The default config path is `config/gate.yaml`; set `GATE_CONFIG` or pass `--config` to use another file.

P1–P3 provide the package/configuration foundation, ChatKit SUT adapter, and versioned trace normalization/storage. P4–P5 add YAML/JSON case validation, deterministic trace evaluators, serial case execution, sanitized JSON/Markdown reports, and gate exit codes. The initial 15 cases are a static suite; run them against the SUT to establish actual behavior. The SUT still uses its configured external model, so evaluator determinism does not guarantee deterministic model responses. Baseline comparison, semantic scoring, CI regression demonstration, and the browser product console are planned later.

Validate the bundled cases without contacting the SUT:

```powershell
gate --config config/gate.example.yaml validate-cases
```

Run one case against a healthy SUT (this sends a real prompt to the SUT's configured model provider):

```powershell
gate --config config/gate.example.yaml run --case AIR-01
```

By default, only critical assertion failures block the gate; infrastructure errors and incomplete traces always return non-zero. Reports are written under `reports/runs/` and traces under `reports/traces/`. Use `--tag`, `--risk`, `--fail-on`, and `--output` to narrow or tune a run. See [case format](docs/cases.md) and [CLI behavior/exit codes](docs/cli.md).

See [the phase plan](agent-regression-gate-phase-plan.md), [architecture outline](docs/architecture.md), and [SUT contract](docs/sut-contract.md).

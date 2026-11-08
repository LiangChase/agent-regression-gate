# CLI Run and Gate Behavior

```powershell
# Validate config and cases without contacting the SUT
gate --config config/gate.example.yaml config-check
gate --config config/gate.example.yaml validate-cases

# Run one case or filter by tags/risk
gate --config config/gate.example.yaml run --case AIR-01
gate --config config/gate.example.yaml run --tag flight-status --risk critical

# Treat high severity as blocking and choose a report basename
gate --config config/gate.example.yaml run --fail-on high --output reports/review/run-42
```

Each run is serial, creates a fresh SUT thread per concrete case instance, captures a trace after every turn, and continues to later cases after an individual case failure. It does not retry a timed out turn because the SUT may already have completed a side effect. `--mode` and `model.*` record Gate-side intent/metadata; they do not select or replace the model running inside the SUT. The example `deterministic` value does not make this SUT deterministic.

By default, critical assertion failures block. `--fail-on` accepts `critical`, `high`, `medium`, `low`, or `any`; a selected level blocks at that severity and every more severe level. Infrastructure errors and incomplete traces always block, independent of this setting.

| Exit code | Meaning |
|---:|---|
| 0 | Gate passed under the selected severity policy |
| 1 | One or more assertions at/above `--fail-on` failed |
| 2 | Invalid configuration, case file, or filter |
| 3 | SUT unavailable in diagnostic operations |
| 4 | SUT protocol error in diagnostic operations |
| 5 | One or more case traces are incomplete |
| 10 | SUT/lifecycle or evaluator execution error |
| 11 | Trace or report storage failed |

`gate run` writes `reports/runs/<run-id>.json` and `.md`, and each normalized trace to `reports/traces/<run-id>/<case-id>.trace.json` unless an alternate report basename is supplied. A run report includes an error case when startup fails; it does not call such a case a behavioral assertion failure.

Real `gate run` commands send the case turns to the model configured in the SUT process and may incur provider cost. Ordinary CI should use a controllable provider/mock before turning dynamic model scenarios into hard blocking checks.

See [the case format](cases.md) and [the sample report](examples/sample-airline-status-20261108/sample-run.md).

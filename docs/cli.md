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

# Explicitly save an approved report; run never changes baselines
gate --config config/gate.example.yaml baseline save --report reports/runs/<run-id>.json --name reviewed --reason "Reviewed SUT and case changes"

# Compare against a saved name or JSON path
gate --config config/gate.example.yaml compare --baseline reviewed --current reports/runs/<new-run-id>.json

# Optional semantic scoring; stub does not claim to assess response quality
gate --config config/gate.example.yaml score --report reports/runs/<run-id>.json --provider stub
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

## Baseline comparison

`baseline save` requires a report, a safe name and a review reason. It writes a versioned envelope under `run.baselines_dir`; it refuses to save a report without run and compatibility metadata. Saving an existing name replaces that file, so baseline changes remain a deliberate, reviewable action. `compare` writes JSON and Markdown outputs and returns zero when the comparison ran, including when reports are `not_comparable`; consumers must inspect the explicit status. Compatibility checks cover model settings, case-set fingerprint, trace schema and deterministic evaluator version. SUT revisions are shown side-by-side because comparing SUT revisions is a normal use of the tool.

The diff separates assertion-level new failures, fixed failures, persistent failures and changed passing observations. Added/removed case IDs and case status changes are also shown. On incompatible reports, case-set membership remains visible but assertion deltas are suppressed.

## Semantic score

The `score` command reads trace files referenced by a run report and writes a separate `<report>.semantic.json` file. `stub` reports `not_scored`; it is only a wiring check. `openai` and `deepseek` use their OpenAI-compatible chat completions endpoint, require their corresponding API key in the environment, and can be configured with `GATE_JUDGE_MODEL` and `GATE_JUDGE_BASE_URL`. Judge errors are explicitly recorded as errors. Scores are advisory and never change gate status or exit code.

## CI workflows

The PR workflow uses `scripts/ci_mock_sut.py`, a deterministic local protocol fixture; no model API key is needed. It runs all expanded cases and reproduces one intentional unauthorized-tool failure as an expected demonstration. Reports and fixture logs are uploaded even on failure. The separate `Live SUT smoke` workflow is manual and requires the `DEEPSEEK_API_KEY` repository secret; it checks out the revision in `config/sut.lock.yaml` and runs only AIR-01. It may incur provider charges and is not required for an ordinary PR.

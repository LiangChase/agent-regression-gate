# Scripts

`ci_mock_sut.py` is a deterministic, standard-library-only ChatKit-shaped fixture used by the pull-request workflow. It exercises the real Gate adapter, runner, trace normalization, deterministic evaluators, reports and gate exit code without external model access. `GATE_CI_DEMO_REGRESSION=1` deliberately emits an unallowlisted tool call for the AIR-15 blocking demonstration. It is CI scaffolding, not an airline-agent implementation or replacement SUT.

`live-sut-gate.yml` is a required PR check, but it only runs the real SUT when `config/sut.lock.yaml` changes; otherwise it exits successfully without requiring a model secret. The full gate uses the pinned SUT and checks AIR-01/03/05/10/15 with repeated sampling. The lighter manual `live-sut-smoke.yml` remains available for an explicit AIR-01 smoke run.

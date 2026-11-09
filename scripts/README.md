# Scripts

`ci_mock_sut.py` is a deterministic, standard-library-only ChatKit-shaped fixture used by the pull-request workflow. It exercises the real Gate adapter, runner, trace normalization, deterministic evaluators, reports and gate exit code without external model access. `GATE_CI_DEMO_REGRESSION=1` deliberately emits an unallowlisted tool call for the AIR-15 blocking demonstration. It is CI scaffolding, not an airline-agent implementation or replacement SUT.

The manual live smoke workflow checks out the SUT revision in `config/sut.lock.yaml` and uses the configured provider secret. It remains separate from required checks because live model output is probabilistic and can incur cost.

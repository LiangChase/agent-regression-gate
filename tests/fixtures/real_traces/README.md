# Frozen real SUT traces

These sanitized traces were captured from the pinned SUT revision
`1c76c4284fcad8e83e7075e1617df58177a47fee` on 2026-11-16. They are used by
`tests/integration/test_real_trace_replay.py` to replay the current
deterministic evaluators against real trace shapes.

The manifest records the observed gate judgment at freeze time. The replay
test must keep producing the same assertion results; if an evaluator, case
rule, or trace-contract change alters them, update the fixture only after a
reviewed live run.

## Refresh

1. Run the live critical set against the pinned SUT and keep the sanitized
   trace files and reports.
2. Copy one trace per critical concrete case into this directory.
3. Regenerate `manifest.json` from the reviewed report assertions.
4. Confirm the fixture scan still finds no API keys or Authorization headers.
5. Run `uv run pytest tests/integration/test_real_trace_replay.py -q`.

# Baselines

Save an explicitly reviewed, sanitized run with `gate baseline save`; a normal `gate run` never replaces one. The save command stores a versioned envelope containing the report, timestamp and required review reason. Review the diff output before updating an established baseline.

Machine-local baselines belong under `baselines/local/`, which is ignored. Commit only sanitized baseline artifacts that are useful as shared project evidence. Do not commit secrets, sensitive prompts, customer data or unreviewed live-model outputs.

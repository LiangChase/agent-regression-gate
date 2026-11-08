# Trace Schema and Persistence

Current normalized trace schema: **1**. Current parsed raw-snapshot schema: **1**. The envelope and its schemas are independently versioned so the adapter output can evolve without silently changing evaluator inputs.

## Stored document

`TraceStore.save()` writes one atomic JSON file per case trace beneath:

```text
<reports_dir>/traces/<run_id>/<case_id>.trace.json
```

The JSON envelope contains:

- `schema_version`: normalized Gate trace version.
- `raw_snapshot_schema_version`: raw ChatKit state-record version.
- `trace`: normalized run/case/thread metadata, turn inputs, ordered events, capture/tool-trace statuses, model/case metadata, and final context.
- `raw_snapshots`: each completed turn’s request receipt, unknown SSE events, and raw parsed `/chatkit/state` payload. This is empty when `trace.persist_raw_snapshots` is false.
- `redaction_summary`: counts of redacted fields/text matches and truncated strings.

Writes go to a temporary file in the destination directory, flush to disk, then atomically replace the final path. A partial write therefore does not become a valid trace file. The store rejects unsafe run/case path components and files larger than `trace.max_bundle_bytes`.

## Event normalization

| SUT event | Gate event | Notes |
|---|---|---|
| `message` | `message` | Agent response text, subject to source-side and Gate-side truncation |
| `handoff` | `handoff` | Source and target remain in metadata |
| `tool_call` | `tool_call` | Tool arguments remain in metadata; allowlist comes from the SUT agent catalog |
| callback-shaped `tool_call` without args and absent from tool catalog | `handoff_callback` | Kept distinct so it is not counted as a business tool invocation |
| `tool_output` | `tool_result` | Source type and event ID remain available |
| `context_update` | `context_update` | Changed fields stay in metadata and are redacted by key |
| guardrail snapshot entry | `guardrail` | Added once per captured turn because the SUT exposes current guardrail state separately from AgentEvents |
| other event type | `unknown` | Original type, metadata, and extra fields are preserved |

Events use the SUT snapshot array order. Cumulative snapshots are de-duplicated by SUT event ID; if snapshots are rewritten in a way that cannot be reconciled, completeness is marked incomplete. `turn_index` is 1-based, while `sequence` is global within the case trace.

## Completeness model

`capture_status` describes evidence collection, not whether an Agent rule passed:

- `complete`: every turn has a completed assistant response and new Agent/guardrail evidence; thread IDs align; observed tool call/result counts are consistent.
- `incomplete`: a turn lacks completion/evidence, snapshots cannot be safely reconciled, required tool evidence is missing, or tool call/result counts disagree.

`tool_trace_status` separately reports `not_required`, `present`, `missing`, or `incomplete`. The caller passes `require_tool_trace=True` only for cases that must invoke a tool. A text-only answer may have a complete capture while its tool trace is `not_required`; it cannot satisfy a case that requires tool evidence.

`Trace.status` remains `pending` for a complete but unevaluated trace, and `incomplete` when collection failed. Evaluators set pass/fail later. This prevents trace collection from pre-judging business behavior.

## Redaction and size limits

Before persistence, secret-like values and credential fields are always redacted. With the default `trace.redact_pii: true`, passenger names, confirmation/account numbers, email, phone, birth date, address, and special-service notes are also redacted by field name; email and common phone patterns in text are redacted. Each string is capped at `trace.max_string_chars` (default 4,000 characters); the document records aggregate redaction/truncation counts.

Raw snapshots are included by default to support adapter debugging, but they pass through the same redaction and size controls as normalized traces. Set `trace.persist_raw_snapshots: false` to retain only normalized data. Never use real customer conversations as cases; use synthetic fixtures. The SUT itself may already truncate AgentEvent strings to about 200 characters, which Gate cannot recover.

## Versioning rules

1. Additive optional fields may stay on the current version if old readers can safely ignore them.
2. Renaming/removing fields, changing units, changing event meaning, or changing required-field semantics increments that schema’s integer version.
3. Readers reject unsupported versions with a storage error; they must not silently coerce a future schema to the current one.
4. Keep unknown source fields in raw snapshots and `TraceEvent.extra_fields` so adapter changes remain inspectable.

See [`examples/sample-airline-status-20261108/AIR-01.trace.json`](examples/sample-airline-status-20261108/AIR-01.trace.json) for a sanitized real-SUT sample.

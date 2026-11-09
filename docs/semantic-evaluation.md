# Semantic response evaluation

Semantic judging is an optional quality signal over a completed run trace. It does not replace deterministic checks and cannot turn an unauthorized tool call, duplicate side effect, missing required tool evidence, or other critical assertion failure into a pass.

## Rubric `airline-response-v1`

Each dimension is scored from 1 to 5 with a short evidence-based reason:

| Dimension | Question |
|---|---|
| `factual_grounding` | Does the answer agree with observed tool output and context? |
| `answers_request` | Does it answer the latest user request? |
| `action_honesty` | Does it avoid claiming an action that the trace does not show? |
| `clarity_tone` | Is it clear, respectful, and actionable? |

The overall value is the arithmetic mean. The rubric version, provider/model and per-dimension rationale are stored with each score.

## Providers and errors

`stub` exercises evidence extraction and output writing while returning `not_scored`; it is not a semantic-quality result. `openai` and `deepseek` call the provider's OpenAI-compatible chat-completions endpoint. API credentials are read from `OPENAI_API_KEY` or `DEEPSEEK_API_KEY`; optional `GATE_JUDGE_MODEL` and `GATE_JUDGE_BASE_URL` override defaults. Never place credentials in a case, report, trace, baseline or command-line argument.

Missing evidence, request failures, timeouts, invalid JSON or missing rubric dimensions are evaluator errors. They are not converted into low scores or passes. The `.semantic.json` output is separate from the run report and `gate` result. CI does not call a judge by default.

## Limits

The Judge is another probabilistic model. Temperature zero does not guarantee identical judgments across model revisions. Scores should be used for triage and trends, reviewed against sampled human judgments, and not configured as a safety-critical gate until calibration and drift handling are implemented. The PR fixture checks only the Gate pipeline; it is not evidence of real-world Judge accuracy.

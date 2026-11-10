from __future__ import annotations

from agents import ModelRetrySettings, ModelSettings, retry_policies

# Runner-managed retries for model calls. The OpenAI client already retries
# transient failures, but a run can also fail across turns/handoffs; this keeps
# the runner retrying network timeouts and transient HTTP errors with backoff.
MODEL_RETRY_SETTINGS = ModelSettings(
    retry=ModelRetrySettings(
        max_retries=2,
        backoff={
            "initial_delay": 1.0,
            "max_delay": 8.0,
            "multiplier": 2.0,
            "jitter": True,
        },
        policy=retry_policies.any(
            retry_policies.network_error(),
            retry_policies.retry_after(),
            retry_policies.http_status([408, 409, 429, 500, 502, 503, 504]),
        ),
    )
)

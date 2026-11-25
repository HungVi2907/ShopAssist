"""Failover eligibility is task policy plus configured route order."""
from shopassist.llm_gateway.errors import ErrorCategory
from shopassist.llm_gateway.policies import TaskAttemptPolicy


class FailoverController:
    def __init__(self, *, enabled: bool):
        self.enabled = enabled

    def may_consider_next(self, policy: TaskAttemptPolicy,
                          category: ErrorCategory | None = None) -> bool:
        return policy.can_failover(enabled=self.enabled, category=category)

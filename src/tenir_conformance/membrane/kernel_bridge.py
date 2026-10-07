"""Bridge RFC-4 membrane scoring to the real TENIR PolicyEngine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tenir_governance.policy_engine import PolicyEngine


@dataclass(frozen=True)
class KernelDecision:
    admissible: bool
    score: float
    decision: str
    rationale: str


class KernelBridge:
    """Translate an RFC-4 payload into the reference PolicyEngine contract."""

    def __init__(self, policy: PolicyEngine | None = None) -> None:
        self.policy = policy or PolicyEngine.default()
        self.policy.validate()

    def evaluate(self, payload: Mapping[str, Any]) -> KernelDecision:
        """Evaluate P,V,K with the real PolicyEngine.

        The reference API exposes capacity_s plus evaluate_membrane rather than
        one evaluate(P,V,K) method. The bridge preserves that API boundary and
        does not move RFC-4 lifecycle state into the PolicyEngine.
        """
        pressure = float(payload["P"])
        velocity = float(payload["V"])
        capacity = float(payload["K"])
        score = self.policy.capacity_s(pressure, velocity, capacity)
        decision, rationale, _, _ = self.policy.evaluate_membrane(
            s_score=score,
            ds_de=0.0,
            d2s_de2=0.0,
            option_space=payload.get("option_space", 1.0),
            projected_events_to_zero=None,
            operating_mode="ENFORCE",
        )
        return KernelDecision(
            admissible=decision != "block",
            score=score,
            decision=decision,
            rationale=rationale,
        )

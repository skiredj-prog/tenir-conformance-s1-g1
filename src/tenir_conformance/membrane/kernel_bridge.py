"""Bridge RFC-4 membrane scoring to the real TENIR PolicyEngine (with local fallback)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

try:
    from tenir_governance.policy_engine import PolicyEngine
    _HAS_TENIR = True
except ImportError:  # pragma: no cover - local CI without package
    PolicyEngine = None  # type: ignore
    _HAS_TENIR = False


@dataclass(frozen=True)
class KernelDecision:
    admissible: bool
    score: float
    decision: str
    rationale: str


class KernelBridge:
    """Translate an RFC-4 payload into the reference PolicyEngine contract.

    If tenir_governance is unavailable, falls back to the canonical scalar
    S = K / (P*V + eps) so membrane tests remain executable offline.
    """

    def __init__(self, policy=None) -> None:
        self._use_real = _HAS_TENIR
        if _HAS_TENIR:
            self.policy = policy or PolicyEngine.default()
            self.policy.validate()
        else:
            self.policy = None
            self.eps = 1e-6

    def evaluate(self, payload: Mapping[str, Any]) -> KernelDecision:
        pressure = float(payload["P"])
        velocity = float(payload["V"])
        capacity = float(payload["K"])
        if self._use_real:
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
        # Offline fallback — same formula as reference kernel
        score = capacity / (pressure * velocity + self.eps)
        decision = "allow" if score >= 1.2 else ("flag" if score >= 0.5 else "block")
        return KernelDecision(
            admissible=decision != "block",
            score=score,
            decision=decision,
            rationale=f"offline_fallback S={score}",
        )

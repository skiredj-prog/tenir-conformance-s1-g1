"""Minimal RFC-4 property-preserving membrane for S1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .kernel_bridge import KernelBridge


class Disposition(str, Enum):
    PASS = "PASS"
    HOLD = "HOLD"
    HARD_VETO = "HARD_VETO"


class AttemptState(str, Enum):
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
    RESOLVED = "RESOLVED"


@dataclass
class Permit:
    lei: str
    attempt_id: str
    consumed: bool = False


@dataclass
class Attempt:
    lei: str
    attempt_id: str
    state: AttemptState = AttemptState.PENDING
    effect_observed: bool = False
    receipt_observed: bool = False


@dataclass
class EffectSink:
    effects: list[dict[str, Any]] = field(default_factory=list)

    def apply(self, lei: str, attempt_id: str, payload: Mapping[str, Any]) -> None:
        self.effects.append({"lei": lei, "attempt_id": attempt_id, "payload": dict(payload)})


@dataclass
class MembraneResult:
    disposition: Disposition
    client_state: str
    receipt_observed: bool
    effect_count: int
    kernel_score: float
    kernel_decision: str
    retry_permit_issued: bool


class Membrane:
    """RFC-4 membrane owning permit, attempt, receipt and reconciliation state."""

    def __init__(self, bridge: KernelBridge, sink: EffectSink | None = None) -> None:
        self.bridge = bridge
        self.sink = sink or EffectSink()
        self.permits: dict[str, Permit] = {}
        self.attempts: dict[str, Attempt] = {}

    def _has_unresolved(self, lei: str) -> bool:
        return any(a.lei == lei and a.state != AttemptState.RESOLVED for a in self.attempts.values())

    def process_transaction(
        self, *, lei: str, attempt_id: str, payload: Mapping[str, Any],
        request_lost: bool = False, receipt_lost: bool = False,
        target_rejected: bool = False,
    ) -> MembraneResult:
        if self._has_unresolved(lei):
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                                  len(self.sink.effects), 0.0, "NOT_EVALUATED", False)

        attempt = Attempt(lei=lei, attempt_id=attempt_id)
        self.attempts[attempt_id] = attempt
        self.permits[attempt_id] = Permit(lei=lei, attempt_id=attempt_id)

        kd = self.bridge.evaluate(payload)
        if not kd.admissible:
            attempt.state = AttemptState.UNKNOWN
            return MembraneResult(Disposition.HARD_VETO, AttemptState.UNKNOWN.value, False,
                                  len(self.sink.effects), kd.score, kd.decision, False)

        self.permits[attempt_id].consumed = True

        if request_lost:
            attempt.state = AttemptState.UNKNOWN
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                                  len(self.sink.effects), kd.score, kd.decision, False)

        if target_rejected:
            attempt.state = AttemptState.UNKNOWN
            if receipt_lost:
                return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                                      len(self.sink.effects), kd.score, kd.decision, False)
            attempt.receipt_observed = True
            attempt.state = AttemptState.RESOLVED
            return MembraneResult(Disposition.PASS, AttemptState.RESOLVED.value, True,
                                  len(self.sink.effects), kd.score, kd.decision, False)

        self.sink.apply(lei, attempt_id, payload)
        attempt.effect_observed = True
        if receipt_lost:
            attempt.state = AttemptState.UNKNOWN
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                                  len(self.sink.effects), kd.score, kd.decision, False)

        attempt.receipt_observed = True
        attempt.state = AttemptState.RESOLVED
        return MembraneResult(Disposition.PASS, AttemptState.RESOLVED.value, True,
                              len(self.sink.effects), kd.score, kd.decision, False)

    def retry(self, *, lei: str, attempt_id: str, payload: Mapping[str, Any]) -> MembraneResult:
        if self._has_unresolved(lei):
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                                  len(self.sink.effects), 0.0, "NOT_EVALUATED", False)
        return self.process_transaction(lei=lei, attempt_id=attempt_id, payload=payload)

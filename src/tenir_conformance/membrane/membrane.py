"""RFC-4 property-preserving membrane (S1/S2 + T7/T8 FAILED/retry_eligible)."""

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
    AWAITING_QUALIFICATION = "AWAITING_QUALIFICATION"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"
    RESOLVED = "RESOLVED"


@dataclass
class FakeClock:
    """Deterministic clock for tau_K experiments (milliseconds)."""

    now_ms: int = 1_000_000

    def tick(self, delta_ms: int = 1) -> int:
        self.now_ms += delta_ms
        return self.now_ms

    def advance_to(self, t_ms: int) -> int:
        if t_ms < self.now_ms:
            raise ValueError("clock cannot go backwards")
        self.now_ms = t_ms
        return self.now_ms


@dataclass
class Permit:
    lei: str
    attempt_id: str
    consumed: bool = False
    issued_at_ms: int = 0


@dataclass
class Attempt:
    lei: str
    attempt_id: str
    state: AttemptState = AttemptState.PENDING
    effect_observed: bool = False
    receipt_observed: bool = False
    qualified: bool = False
    timeout_fired: bool = False
    await_until_ms: int | None = None
    # T7/T8: terminal failure and whether a new attempt on same LEI is allowed
    retry_eligible: bool = False
    failure_reason: str | None = None


@dataclass
class EffectSink:
    effects: list[dict[str, Any]] = field(default_factory=list)

    def apply(self, lei: str, attempt_id: str, payload: Mapping[str, Any]) -> None:
        self.effects.append(
            {"lei": lei, "attempt_id": attempt_id, "payload": dict(payload)}
        )


@dataclass
class MembraneResult:
    disposition: Disposition
    client_state: str
    receipt_observed: bool
    effect_count: int
    kernel_score: float
    kernel_decision: str
    retry_permit_issued: bool
    timeout_event: bool = False
    retry_eligible: bool | None = None
    events: list[str] = field(default_factory=list)


class Membrane:
    """RFC-4 membrane: permit, attempt, receipt, tau_K, FAILED/retry_eligible."""

    def __init__(
        self,
        bridge: KernelBridge,
        sink: EffectSink | None = None,
        clock: FakeClock | None = None,
        tau_k_ms: int = 5_000,
    ) -> None:
        self.bridge = bridge
        self.sink = sink or EffectSink()
        self.clock = clock or FakeClock()
        self.tau_k_ms = tau_k_ms
        self.permits: dict[str, Permit] = {}
        self.attempts: dict[str, Attempt] = {}
        self.events: list[dict[str, Any]] = []

    def _log(self, event: str, **fields: Any) -> None:
        self.events.append(
            {"ts_ms": self.clock.now_ms, "event": event, **fields}
        )

    def _blocks_new_attempt(self, attempt: Attempt) -> bool:
        """Return True if this attempt still blocks a new attempt on the same LEI."""
        if attempt.state == AttemptState.RESOLVED:
            return False
        # T8: FAILED + retry_eligible allows a fresh attempt on the same LEI
        if attempt.state == AttemptState.FAILED and attempt.retry_eligible:
            return False
        return True

    def _has_unresolved(self, lei: str) -> bool:
        return any(
            a.lei == lei and self._blocks_new_attempt(a)
            for a in self.attempts.values()
        )

    def _client_projection(self, attempt: Attempt) -> tuple[Disposition, str]:
        if attempt.state == AttemptState.RESOLVED and attempt.qualified:
            return Disposition.PASS, AttemptState.RESOLVED.value
        if attempt.state == AttemptState.FAILED:
            return Disposition.HOLD, AttemptState.FAILED.value
        return Disposition.HOLD, AttemptState.UNKNOWN.value

    def process_transaction(
        self,
        *,
        lei: str,
        attempt_id: str,
        payload: Mapping[str, Any],
        request_lost: bool = False,
        receipt_lost: bool = False,
        target_rejected: bool = False,
    ) -> MembraneResult:
        if self._has_unresolved(lei):
            self._log("T1_guard_FALSE", lei=lei, reason="UNRESOLVED_SAME_LEI")
            return MembraneResult(
                Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                events=[e["event"] for e in self.events],
            )

        attempt = Attempt(lei=lei, attempt_id=attempt_id)
        self.attempts[attempt_id] = attempt
        self.permits[attempt_id] = Permit(
            lei=lei, attempt_id=attempt_id, issued_at_ms=self.clock.now_ms
        )
        self._log("PERMIT_ISSUED", lei=lei, attempt_id=attempt_id)

        kd = self.bridge.evaluate(payload)
        if not kd.admissible:
            attempt.state = AttemptState.UNKNOWN
            self._log("KERNEL_VETO", lei=lei, decision=kd.decision)
            return MembraneResult(
                Disposition.HARD_VETO, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events],
            )

        self.permits[attempt_id].consumed = True
        self._log("PERMIT_CONSUMED", lei=lei, attempt_id=attempt_id)

        if request_lost:
            attempt.state = AttemptState.UNKNOWN
            self._log("T3_ReceiptLost", lei=lei, attempt_id=attempt_id, kind="REQUEST_LOST")
            disp, st = self._client_projection(attempt)
            return MembraneResult(
                disp, st, False, len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events],
            )

        if target_rejected:
            attempt.state = AttemptState.UNKNOWN
            if receipt_lost:
                self._log("T3_TargetRejectedResponseLost", lei=lei, attempt_id=attempt_id)
                disp, st = self._client_projection(attempt)
                return MembraneResult(
                    disp, st, False, len(self.sink.effects), kd.score, kd.decision, False,
                    events=[e["event"] for e in self.events],
                )
            attempt.receipt_observed = True
            attempt.state = AttemptState.RESOLVED
            attempt.qualified = True
            self._log("TARGET_REJECTED_OBSERVED", lei=lei, attempt_id=attempt_id)
            return MembraneResult(
                Disposition.PASS, AttemptState.RESOLVED.value, True,
                len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events],
            )

        self.sink.apply(lei, attempt_id, payload)
        attempt.effect_observed = True
        self._log("EFFECT_APPLIED", lei=lei, attempt_id=attempt_id)

        if receipt_lost:
            attempt.state = AttemptState.UNKNOWN
            self._log("T3_ReceiptLost", lei=lei, attempt_id=attempt_id, kind="RECEIPT_LOST")
            disp, st = self._client_projection(attempt)
            return MembraneResult(
                disp, st, False, len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events],
            )

        attempt.receipt_observed = True
        attempt.state = AttemptState.RESOLVED
        attempt.qualified = True
        self._log("RECEIPT_OBSERVED", lei=lei, attempt_id=attempt_id)
        return MembraneResult(
            Disposition.PASS, AttemptState.RESOLVED.value, True,
            len(self.sink.effects), kd.score, kd.decision, False,
            events=[e["event"] for e in self.events],
        )

    def retry(
        self, *, lei: str, attempt_id: str, payload: Mapping[str, Any]
    ) -> MembraneResult:
        self.check_qualification_timeouts()
        if self._has_unresolved(lei):
            self._log("T1_guard_FALSE", lei=lei, reason="UNRESOLVED_SAME_LEI")
            return MembraneResult(
                Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=any(
                    a.timeout_fired for a in self.attempts.values() if a.lei == lei
                ),
                events=[e["event"] for e in self.events],
            )
        return self.process_transaction(
            lei=lei, attempt_id=attempt_id, payload=payload
        )

    def admit_and_await_qualification(
        self,
        *,
        lei: str,
        attempt_id: str,
        payload: Mapping[str, Any],
        apply_effect: bool = True,
    ) -> MembraneResult:
        if self._has_unresolved(lei):
            self._log("T1_guard_FALSE", lei=lei, reason="UNRESOLVED_SAME_LEI")
            return MembraneResult(
                Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                events=[e["event"] for e in self.events],
            )

        attempt = Attempt(lei=lei, attempt_id=attempt_id)
        self.attempts[attempt_id] = attempt
        self.permits[attempt_id] = Permit(
            lei=lei, attempt_id=attempt_id, issued_at_ms=self.clock.now_ms
        )
        self._log("PERMIT_ISSUED", lei=lei, attempt_id=attempt_id)

        kd = self.bridge.evaluate(payload)
        if not kd.admissible:
            attempt.state = AttemptState.UNKNOWN
            self._log("KERNEL_VETO", lei=lei, decision=kd.decision)
            return MembraneResult(
                Disposition.HARD_VETO, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events],
            )

        self.permits[attempt_id].consumed = True
        self._log("PERMIT_CONSUMED", lei=lei, attempt_id=attempt_id)

        if apply_effect:
            self.sink.apply(lei, attempt_id, payload)
            attempt.effect_observed = True
            self._log("EFFECT_APPLIED", lei=lei, attempt_id=attempt_id)

        attempt.state = AttemptState.AWAITING_QUALIFICATION
        attempt.await_until_ms = self.clock.now_ms + self.tau_k_ms
        self._log(
            "AWAITING_QUALIFICATION",
            lei=lei,
            attempt_id=attempt_id,
            await_until_ms=attempt.await_until_ms,
            tau_k_ms=self.tau_k_ms,
        )
        return MembraneResult(
            Disposition.HOLD, AttemptState.UNKNOWN.value, False,
            len(self.sink.effects), kd.score, kd.decision, False,
            events=[e["event"] for e in self.events],
        )

    def check_qualification_timeouts(self) -> list[str]:
        fired: list[str] = []
        now = self.clock.now_ms
        for attempt in self.attempts.values():
            if (
                attempt.state == AttemptState.AWAITING_QUALIFICATION
                and attempt.await_until_ms is not None
                and now >= attempt.await_until_ms
                and not attempt.timeout_fired
            ):
                attempt.timeout_fired = True
                attempt.state = AttemptState.UNKNOWN
                self._log(
                    "T_QualificationTimeout",
                    lei=attempt.lei,
                    attempt_id=attempt.attempt_id,
                    await_until_ms=attempt.await_until_ms,
                    now_ms=now,
                )
                fired.append(attempt.attempt_id)
        return fired

    def deliver_qualifying_receipt(
        self, *, attempt_id: str, bound: bool = True
    ) -> MembraneResult:
        if attempt_id not in self.attempts:
            raise KeyError(attempt_id)
        attempt = self.attempts[attempt_id]
        self.check_qualification_timeouts()

        if not bound:
            self._log("RECEIPT_REJECTED_UNBOUND", lei=attempt.lei, attempt_id=attempt_id)
            disp, st = self._client_projection(attempt)
            return MembraneResult(
                disp, st, False, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=attempt.timeout_fired,
                events=[e["event"] for e in self.events],
            )

        if attempt.timeout_fired or attempt.state == AttemptState.UNKNOWN:
            self._log(
                "LATE_RECEIPT_AFTER_TIMEOUT_NO_AUTO_COMMIT",
                lei=attempt.lei, attempt_id=attempt_id,
            )
            attempt.receipt_observed = True
            disp, st = self._client_projection(attempt)
            return MembraneResult(
                disp, st, True, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=True,
                events=[e["event"] for e in self.events],
            )

        if attempt.state == AttemptState.AWAITING_QUALIFICATION:
            attempt.receipt_observed = True
            attempt.qualified = True
            attempt.state = AttemptState.RESOLVED
            self._log("RECEIPT_QUALIFIED", lei=attempt.lei, attempt_id=attempt_id)
            return MembraneResult(
                Disposition.PASS, AttemptState.RESOLVED.value, True,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=False,
                events=[e["event"] for e in self.events],
            )

        disp, st = self._client_projection(attempt)
        return MembraneResult(
            disp, st, attempt.receipt_observed, len(self.sink.effects),
            0.0, "NOT_EVALUATED", False,
            timeout_event=attempt.timeout_fired,
            events=[e["event"] for e in self.events],
        )

    # ── T7 / T8: qualified failure and retry eligibility ──────────────────────

    def declare_failed(
        self,
        *,
        attempt_id: str,
        evidence_qualified: bool,
        retry_eligible: bool = True,
        reason: str = "QUALIFIED_NON_EXECUTION",
    ) -> MembraneResult:
        """
        T7 — UNKNOWN → FAILED (requires evidence qualification guard).

        Timeout alone must not call this path. A qualified outcome (e.g. proven
        non-execution, or explicit governance authority) is required.
        When retry_eligible=True (T8), a subsequent attempt on the same LEI is allowed.
        """
        if attempt_id not in self.attempts:
            raise KeyError(attempt_id)
        attempt = self.attempts[attempt_id]
        self.check_qualification_timeouts()

        if attempt.state == AttemptState.RESOLVED:
            self._log(
                "T7_REJECTED_ALREADY_RESOLVED",
                lei=attempt.lei,
                attempt_id=attempt_id,
            )
            disp, st = self._client_projection(attempt)
            return MembraneResult(
                disp, st, attempt.receipt_observed, len(self.sink.effects),
                0.0, "NOT_EVALUATED", False,
                timeout_event=attempt.timeout_fired,
                retry_eligible=attempt.retry_eligible,
                events=[e["event"] for e in self.events],
            )

        if attempt.state not in (
            AttemptState.UNKNOWN,
            AttemptState.AWAITING_QUALIFICATION,
            AttemptState.PENDING,
        ):
            if attempt.state == AttemptState.FAILED:
                self._log(
                    "T7_ALREADY_FAILED",
                    lei=attempt.lei,
                    attempt_id=attempt_id,
                )
                return MembraneResult(
                    Disposition.HOLD, AttemptState.FAILED.value,
                    attempt.receipt_observed, len(self.sink.effects),
                    0.0, "NOT_EVALUATED", False,
                    timeout_event=attempt.timeout_fired,
                    retry_eligible=attempt.retry_eligible,
                    events=[e["event"] for e in self.events],
                )
            self._log(
                "T7_REJECTED_BAD_STATE",
                lei=attempt.lei,
                attempt_id=attempt_id,
                state=attempt.state.value,
            )
            disp, st = self._client_projection(attempt)
            return MembraneResult(
                disp, st, attempt.receipt_observed, len(self.sink.effects),
                0.0, "NOT_EVALUATED", False,
                events=[e["event"] for e in self.events],
            )

        if not evidence_qualified:
            self._log(
                "T7_REJECTED_UNQUALIFIED_EVIDENCE",
                lei=attempt.lei,
                attempt_id=attempt_id,
                reason=reason,
            )
            disp, st = self._client_projection(attempt)
            return MembraneResult(
                disp, st, attempt.receipt_observed, len(self.sink.effects),
                0.0, "NOT_EVALUATED", False,
                timeout_event=attempt.timeout_fired,
                retry_eligible=False,
                events=[e["event"] for e in self.events],
            )

        attempt.state = AttemptState.FAILED
        attempt.qualified = True
        attempt.retry_eligible = retry_eligible
        attempt.failure_reason = reason
        self._log(
            "T7_DECLARE_FAILED",
            lei=attempt.lei,
            attempt_id=attempt_id,
            reason=reason,
            retry_eligible=retry_eligible,
        )
        return MembraneResult(
            Disposition.HOLD,
            AttemptState.FAILED.value,
            attempt.receipt_observed,
            len(self.sink.effects),
            0.0,
            "NOT_EVALUATED",
            False,
            timeout_event=attempt.timeout_fired,
            retry_eligible=retry_eligible,
            events=[e["event"] for e in self.events],
        )

    def retry_eligible_for(self, lei: str) -> bool:
        """True if no attempt on LEI currently blocks a new attempt (T8-aware)."""
        return not self._has_unresolved(lei)

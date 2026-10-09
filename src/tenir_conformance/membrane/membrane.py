"""RFC-4 property-preserving membrane (S1–S4 + T7/T8)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from .kernel_bridge import KernelBridge


class DuplicateAttemptID(Exception):
    """Raised when attempt_id is already registered (S3d identity uniqueness)."""


class UnresolvedSameLEI(Exception):
    """Raised when LEI is locked by an unresolved attempt (S3a–S3c)."""


class StaleReceiptError(Exception):
    """Raised when a receipt token is expired while the qualification window is still open (S4b)."""


class IncompleteEvidence(ValueError):
    """Evidence is missing mandatory schema fields or fails integrity/freshness checks."""


class BindingError(ValueError):
    """Evidence is not strictly bound to the selected attempt, nonce, and LEI."""


class ContradictoryEvidenceError(RuntimeError):
    """The complete evidence batch contains mutually incompatible claims."""


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
    ESCALATED = "ESCALATED"


@dataclass
class FakeClock:
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
    revoked: bool = False


@dataclass(frozen=True)
class Receipt:
    """Intrinsic receipt evidence (G0 S4 A6)."""

    attempt_id: str
    lei: str
    nonce: str
    expires_at_ms: int | None = None


@dataclass(frozen=True)
class Evidence:
    """G0 S5/S6 evidence item.

    The adapter must supply already-normalized properties and the upstream
    verifier's integrity/source-authority results. For S6 negative outcomes,
    non_execution_confirmed is an upstream attestation that the external
    operation produced no effect. This harness does not perform cryptographic
    signature verification.
    """

    evidence_id: str
    attempt_id: str
    lei: str
    nonce: str
    status: str
    properties: Mapping[str, Any]
    reference_scope: str
    reference_snapshot: str
    normalization_profile: str
    integrity_verified: bool
    source_authoritative: bool
    expires_at_ms: int | None = None
    required_properties: tuple[str, ...] = ()
    # Explicit upstream-verifier attestation that no external effect occurred.
    # The harness validates this assertion's presence/type; it does not verify signatures.
    non_execution_confirmed: bool = False


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
    retry_eligible: bool = False
    failure_reason: str | None = None
    nonce: str = ""


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
    timeout_event: bool = False
    retry_eligible: bool | None = None
    events: list[str] = field(default_factory=list)


class Membrane:
    """RFC-4 membrane: permit, attempt, receipt, evidence, S3–S6 guards, T7/T8."""

    def __init__(self, bridge: KernelBridge, sink: EffectSink | None = None,
                 clock: FakeClock | None = None, tau_k_ms: int = 5_000,
                 conflict_sensitive_properties: set[str] | frozenset[str] | None = None,
                 quarantine_release_authorizer: Callable[[str, str], bool] | None = None) -> None:
        self.bridge = bridge
        self.sink = sink or EffectSink()
        self.clock = clock or FakeClock()
        self.tau_k_ms = tau_k_ms
        self.permits: dict[str, Permit] = {}
        self.attempts: dict[str, Attempt] = {}
        self.events: list[dict[str, Any]] = []
        # Default is the canonical S5 example property; production adapters
        # should provide the authoritative conflict-sensitive property set.
        self.conflict_sensitive_properties = (
            frozenset({"exposure"}) if conflict_sensitive_properties is None
            else frozenset(conflict_sensitive_properties)
        )
        self.governance_quarantine: dict[str, dict[str, Any]] = {}
        self.governance_quarantine_history: list[dict[str, Any]] = []
        self._evidence_registry: dict[str, str] = {}
        # Fail closed: quarantine release requires an injected authority check.
        self.quarantine_release_authorizer = quarantine_release_authorizer

    def _log(self, event: str, **fields: Any) -> None:
        self.events.append({"ts_ms": self.clock.now_ms, "event": event, **fields})

    def _blocks_new_attempt(self, attempt: Attempt) -> bool:
        # A confirmed execution permanently locks the same logical operation.
        if attempt.state == AttemptState.RESOLVED:
            return True
        # Retry eligibility is policy/audit metadata, not an effect-lock override.
        # FAILED is releasable only when this attempt has no observed execution effect.
        if attempt.state == AttemptState.FAILED and not attempt.effect_observed:
            return False
        return True

    def _has_unresolved(self, lei: str) -> bool:
        if lei in self.governance_quarantine:
            return True
        return any(a.lei == lei and self._blocks_new_attempt(a) for a in self.attempts.values())

    def _client_projection(self, attempt: Attempt) -> tuple[Disposition, str]:
        if attempt.state == AttemptState.RESOLVED and attempt.qualified:
            return Disposition.PASS, AttemptState.RESOLVED.value
        if attempt.state == AttemptState.FAILED:
            return Disposition.HOLD, AttemptState.FAILED.value
        if attempt.state == AttemptState.ESCALATED:
            return Disposition.HOLD, AttemptState.ESCALATED.value
        return Disposition.HOLD, AttemptState.UNKNOWN.value

    def _register_attempt(self, *, lei: str, attempt_id: str, nonce: str = "") -> Attempt:
        if attempt_id in self.attempts:
            self._log("S3_DUPLICATE_ATTEMPT_ID", lei=lei, attempt_id=attempt_id)
            raise DuplicateAttemptID(f"Registration rejected: attempt_id '{attempt_id}' already exists.")
        if lei in self.governance_quarantine:
            quarantine = self.governance_quarantine[lei]
            self._log("GOVERNANCE_QUARANTINE_BLOCK", lei=lei, attempt_id=attempt_id,
                      incident_id=quarantine["incident_id"])
            raise UnresolvedSameLEI(f"Registration rejected: LEI '{lei}' is under governance quarantine.")
        if self._has_unresolved(lei):
            self._log("T1_guard_FALSE", lei=lei, attempt_id=attempt_id, reason="UNRESOLVED_SAME_LEI")
            raise UnresolvedSameLEI(f"Registration rejected: LEI '{lei}' is locked by an unresolved attempt.")
        attempt = Attempt(lei=lei, attempt_id=attempt_id, nonce=nonce)
        self.attempts[attempt_id] = attempt
        self.permits[attempt_id] = Permit(lei=lei, attempt_id=attempt_id, issued_at_ms=self.clock.now_ms)
        self._log("PERMIT_ISSUED", lei=lei, attempt_id=attempt_id, nonce=nonce)
        return attempt

    def process_transaction(self, *, lei: str, attempt_id: str, payload: Mapping[str, Any],
                            request_lost: bool = False, receipt_lost: bool = False,
                            target_rejected: bool = False) -> MembraneResult:
        try:
            attempt = self._register_attempt(lei=lei, attempt_id=attempt_id, nonce="")
        except DuplicateAttemptID:
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                events=[e["event"] for e in self.events])
        except UnresolvedSameLEI:
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                events=[e["event"] for e in self.events])
        kd = self.bridge.evaluate(payload)
        if not kd.admissible:
            attempt.state = AttemptState.UNKNOWN
            self._log("KERNEL_VETO", lei=lei, decision=kd.decision)
            return MembraneResult(Disposition.HARD_VETO, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events])
        self.permits[attempt_id].consumed = True
        self._log("PERMIT_CONSUMED", lei=lei, attempt_id=attempt_id)
        if request_lost:
            attempt.state = AttemptState.UNKNOWN
            self._log("T3_ReceiptLost", lei=lei, attempt_id=attempt_id, kind="REQUEST_LOST")
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, False, len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events])
        if target_rejected:
            attempt.state = AttemptState.UNKNOWN
            if receipt_lost:
                self._log("T3_TargetRejectedResponseLost", lei=lei, attempt_id=attempt_id)
                disp, st = self._client_projection(attempt)
                return MembraneResult(disp, st, False, len(self.sink.effects), kd.score, kd.decision, False,
                    events=[e["event"] for e in self.events])
            # A directly observed target rejection proves this attempt did not commit.
            # It is a qualified failure, not a successful resolution.
            attempt.receipt_observed = True
            attempt.state = AttemptState.FAILED
            attempt.qualified = True
            attempt.retry_eligible = False
            attempt.failure_reason = "TARGET_REJECTED"
            self._log("TARGET_REJECTED_OBSERVED", lei=lei, attempt_id=attempt_id)
            return MembraneResult(Disposition.HOLD, AttemptState.FAILED.value, True,
                len(self.sink.effects), kd.score, kd.decision, False, retry_eligible=False,
                events=[e["event"] for e in self.events])
        self.sink.apply(lei, attempt_id, payload)
        attempt.effect_observed = True
        self._log("EFFECT_APPLIED", lei=lei, attempt_id=attempt_id)
        if receipt_lost:
            attempt.state = AttemptState.UNKNOWN
            self._log("T3_ReceiptLost", lei=lei, attempt_id=attempt_id, kind="RECEIPT_LOST")
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, False, len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events])
        attempt.receipt_observed = True
        attempt.state = AttemptState.RESOLVED
        attempt.qualified = True
        self._log("RECEIPT_OBSERVED", lei=lei, attempt_id=attempt_id)
        return MembraneResult(Disposition.PASS, AttemptState.RESOLVED.value, True,
            len(self.sink.effects), kd.score, kd.decision, False,
            events=[e["event"] for e in self.events])

    def retry(self, *, lei: str, attempt_id: str, payload: Mapping[str, Any]) -> MembraneResult:
        self.check_qualification_timeouts()
        if self._has_unresolved(lei):
            self._log("T1_guard_FALSE", lei=lei, reason="UNRESOLVED_SAME_LEI")
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=any(a.timeout_fired for a in self.attempts.values() if a.lei == lei),
                events=[e["event"] for e in self.events])
        return self.process_transaction(lei=lei, attempt_id=attempt_id, payload=payload)

    def admit_and_await_qualification(self, *, lei: str, attempt_id: str, payload: Mapping[str, Any],
                                      apply_effect: bool = True, nonce: str = "") -> MembraneResult:
        try:
            attempt = self._register_attempt(lei=lei, attempt_id=attempt_id, nonce=nonce)
        except DuplicateAttemptID:
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                events=[e["event"] for e in self.events])
        except UnresolvedSameLEI:
            return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                events=[e["event"] for e in self.events])
        kd = self.bridge.evaluate(payload)
        if not kd.admissible:
            attempt.state = AttemptState.UNKNOWN
            self._log("KERNEL_VETO", lei=lei, decision=kd.decision)
            return MembraneResult(Disposition.HARD_VETO, AttemptState.UNKNOWN.value, False,
                len(self.sink.effects), kd.score, kd.decision, False,
                events=[e["event"] for e in self.events])
        self.permits[attempt_id].consumed = True
        self._log("PERMIT_CONSUMED", lei=lei, attempt_id=attempt_id)
        if apply_effect:
            self.sink.apply(lei, attempt_id, payload)
            attempt.effect_observed = True
            self._log("EFFECT_APPLIED", lei=lei, attempt_id=attempt_id)
        attempt.state = AttemptState.AWAITING_QUALIFICATION
        attempt.await_until_ms = self.clock.now_ms + self.tau_k_ms
        self._log("AWAITING_QUALIFICATION", lei=lei, attempt_id=attempt_id,
                  await_until_ms=attempt.await_until_ms, tau_k_ms=self.tau_k_ms)
        return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, False,
            len(self.sink.effects), kd.score, kd.decision, False,
            events=[e["event"] for e in self.events])

    def check_qualification_timeouts(self) -> list[str]:
        fired: list[str] = []
        now = self.clock.now_ms
        for attempt in self.attempts.values():
            if (attempt.state == AttemptState.AWAITING_QUALIFICATION
                    and attempt.await_until_ms is not None
                    and now >= attempt.await_until_ms
                    and not attempt.timeout_fired):
                attempt.timeout_fired = True
                attempt.state = AttemptState.UNKNOWN
                self._log("T_QualificationTimeout", lei=attempt.lei, attempt_id=attempt.attempt_id,
                          await_until_ms=attempt.await_until_ms, now_ms=now)
                fired.append(attempt.attempt_id)
        return fired

    def deliver_qualifying_receipt(
        self,
        receipt: "Receipt | None" = None,
        *,
        attempt_id: str | None = None,
        bound: bool | None = None,
        lei: str | None = None,
        nonce: str | None = None,
        expires_at_ms: int | None = None,
    ) -> MembraneResult:
        """Canonical: Receipt required for RESOLVED. Legacy kwargs cannot qualify."""
        if receipt is None:
            if attempt_id is None:
                raise TypeError("deliver_qualifying_receipt requires a Receipt")
            if attempt_id not in self.attempts:
                raise KeyError(attempt_id)
            attempt = self.attempts[attempt_id]
            self.check_qualification_timeouts()
            if bound is False:
                self._log("RECEIPT_REJECTED_UNBOUND", lei=attempt.lei, attempt_id=attempt_id, path="legacy")
            else:
                self._log("RECEIPT_REJECTED_BINDING", lei=attempt.lei, attempt_id=attempt_id,
                          reason="RECEIPT_OBJECT_REQUIRED", path="legacy")
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, False, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=attempt.timeout_fired, events=[e["event"] for e in self.events])

        attempt_id = receipt.attempt_id
        if attempt_id not in self.attempts:
            raise KeyError(attempt_id)
        attempt = self.attempts[attempt_id]
        self.check_qualification_timeouts()

        if receipt.attempt_id != attempt.attempt_id:
            self._log("RECEIPT_REJECTED_BINDING", lei=attempt.lei, attempt_id=attempt_id, reason="ATTEMPT_ID_MISMATCH")
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, False, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=attempt.timeout_fired, events=[e["event"] for e in self.events])
        if receipt.lei != attempt.lei:
            self._log("RECEIPT_REJECTED_BINDING", lei=attempt.lei, attempt_id=attempt_id, reason="LEI_MISMATCH")
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, False, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=attempt.timeout_fired, events=[e["event"] for e in self.events])
        if not attempt.nonce:
            self._log("RECEIPT_REJECTED_BINDING", lei=attempt.lei, attempt_id=attempt_id, reason="NONCE_NOT_REGISTERED")
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, False, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=attempt.timeout_fired, events=[e["event"] for e in self.events])
        if receipt.nonce != attempt.nonce:
            self._log("RECEIPT_REJECTED_BINDING", lei=attempt.lei, attempt_id=attempt_id, reason="NONCE_MISMATCH")
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, False, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=attempt.timeout_fired, events=[e["event"] for e in self.events])

        if attempt.timeout_fired or attempt.state == AttemptState.UNKNOWN:
            self._log("RECEIPT_REJECTED", lei=attempt.lei, attempt_id=attempt_id, reason="WINDOW_CLOSED")
            self._log("LATE_RECEIPT_AFTER_TIMEOUT_NO_AUTO_COMMIT", lei=attempt.lei, attempt_id=attempt_id)
            attempt.receipt_observed = True
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, True, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                timeout_event=True, events=[e["event"] for e in self.events])
        if attempt.state in (AttemptState.FAILED, AttemptState.RESOLVED):
            self._log("RECEIPT_REJECTED", lei=attempt.lei, attempt_id=attempt_id, reason="TERMINAL_LOCK",
                      state=attempt.state.value)
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, attempt.receipt_observed, len(self.sink.effects),
                0.0, "NOT_EVALUATED", False, timeout_event=attempt.timeout_fired,
                events=[e["event"] for e in self.events])

        if receipt.expires_at_ms is not None and self.clock.now_ms >= receipt.expires_at_ms:
            self._log("STALE_RECEIPT", lei=attempt.lei, attempt_id=attempt_id,
                      expires_at_ms=receipt.expires_at_ms, now_ms=self.clock.now_ms)
            attempt.state = AttemptState.UNKNOWN
            attempt.receipt_observed = True
            raise StaleReceiptError(
                f"Receipt token expired for attempt '{attempt_id}' "
                f"(expires_at_ms={receipt.expires_at_ms}, now_ms={self.clock.now_ms}).")

        if attempt.state == AttemptState.AWAITING_QUALIFICATION:
            attempt.receipt_observed = True
            if not attempt.effect_observed:
                self._log("RECEIPT_REJECTED_NO_OBSERVED_EFFECT", lei=attempt.lei,
                          attempt_id=attempt_id, reason="EFFECT_NOT_OBSERVED")
                return MembraneResult(Disposition.HOLD, AttemptState.UNKNOWN.value, True,
                    len(self.sink.effects), 0.0, "NOT_EVALUATED", False, timeout_event=False,
                    retry_eligible=False, events=[e["event"] for e in self.events])
            attempt.qualified = True
            attempt.state = AttemptState.RESOLVED
            self._log("RECEIPT_QUALIFIED", lei=attempt.lei, attempt_id=attempt_id)
            return MembraneResult(Disposition.PASS, AttemptState.RESOLVED.value, True,
                len(self.sink.effects), 0.0, "NOT_EVALUATED", False, timeout_event=False,
                events=[e["event"] for e in self.events])

        disp, st = self._client_projection(attempt)
        return MembraneResult(disp, st, attempt.receipt_observed, len(self.sink.effects),
            0.0, "NOT_EVALUATED", False, timeout_event=attempt.timeout_fired,
            events=[e["event"] for e in self.events])

    def declare_failed(self, *, attempt_id: str, evidence_qualified: bool,
                       retry_eligible: bool = True, reason: str = "QUALIFIED_NON_EXECUTION") -> MembraneResult:
        """T7 adjudication seam; currently not wired to a production caller.

        evidence_qualified is an upstream adjudicator's attestation, not a
        cryptographic check performed by this in-memory conformance harness.
        Integrations must call this only after validating authority and proof of
        non-execution. An already observed effect always prevents FAILED.
        """
        if attempt_id not in self.attempts:
            raise KeyError(attempt_id)
        attempt = self.attempts[attempt_id]
        self.check_qualification_timeouts()
        if attempt.state == AttemptState.RESOLVED:
            self._log("T7_REJECTED_ALREADY_RESOLVED", lei=attempt.lei, attempt_id=attempt_id)
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, attempt.receipt_observed, len(self.sink.effects),
                0.0, "NOT_EVALUATED", False, timeout_event=attempt.timeout_fired,
                retry_eligible=attempt.retry_eligible, events=[e["event"] for e in self.events])
        if attempt.state not in (AttemptState.UNKNOWN, AttemptState.AWAITING_QUALIFICATION, AttemptState.PENDING):
            if attempt.state == AttemptState.FAILED:
                self._log("T7_ALREADY_FAILED", lei=attempt.lei, attempt_id=attempt_id)
                return MembraneResult(Disposition.HOLD, AttemptState.FAILED.value,
                    attempt.receipt_observed, len(self.sink.effects), 0.0, "NOT_EVALUATED", False,
                    timeout_event=attempt.timeout_fired, retry_eligible=attempt.retry_eligible,
                    events=[e["event"] for e in self.events])
            self._log("T7_REJECTED_BAD_STATE", lei=attempt.lei, attempt_id=attempt_id, state=attempt.state.value)
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, attempt.receipt_observed, len(self.sink.effects),
                0.0, "NOT_EVALUATED", False, events=[e["event"] for e in self.events])
        if not evidence_qualified:
            self._log("T7_REJECTED_UNQUALIFIED_EVIDENCE", lei=attempt.lei, attempt_id=attempt_id, reason=reason)
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, attempt.receipt_observed, len(self.sink.effects),
                0.0, "NOT_EVALUATED", False, timeout_event=attempt.timeout_fired, retry_eligible=False,
                events=[e["event"] for e in self.events])
        if attempt.effect_observed:
            self._log("T7_REJECTED_EFFECT_ALREADY_OBSERVED", lei=attempt.lei,
                      attempt_id=attempt_id, reason=reason)
            disp, st = self._client_projection(attempt)
            return MembraneResult(disp, st, attempt.receipt_observed, len(self.sink.effects),
                0.0, "NOT_EVALUATED", False, timeout_event=attempt.timeout_fired,
                retry_eligible=False, events=[e["event"] for e in self.events])
        attempt.state = AttemptState.FAILED
        attempt.qualified = True
        attempt.retry_eligible = retry_eligible
        attempt.failure_reason = reason
        self._log("T7_DECLARE_FAILED", lei=attempt.lei, attempt_id=attempt_id, reason=reason,
                  retry_eligible=retry_eligible)
        return MembraneResult(Disposition.HOLD, AttemptState.FAILED.value, attempt.receipt_observed,
            len(self.sink.effects), 0.0, "NOT_EVALUATED", False, timeout_event=attempt.timeout_fired,
            retry_eligible=retry_eligible, events=[e["event"] for e in self.events])


    @staticmethod
    def _evidence_fingerprint(evidence: Evidence) -> str:
        payload = {
            "evidence_id": evidence.evidence_id,
            "attempt_id": evidence.attempt_id,
            "lei": evidence.lei,
            "nonce": evidence.nonce,
            "status": evidence.status,
            "properties": dict(evidence.properties),
            "reference_scope": evidence.reference_scope,
            "reference_snapshot": evidence.reference_snapshot,
            "normalization_profile": evidence.normalization_profile,
            "integrity_verified": evidence.integrity_verified,
            "source_authoritative": evidence.source_authoritative,
            "expires_at_ms": evidence.expires_at_ms,
            "required_properties": list(evidence.required_properties),
            "non_execution_confirmed": evidence.non_execution_confirmed,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _canonical_value(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    def _validate_evidence_batch(self, attempt: Attempt, evidence_batch: Sequence[Evidence]) -> tuple[Evidence, ...]:
        if not evidence_batch:
            raise IncompleteEvidence("Evidence batch must not be empty.")
        batch = tuple(evidence_batch)
        seen_ids: set[str] = set()
        fingerprints: dict[str, str] = {}
        allowed_statuses = {"COMMITTED", "FAILED", "REJECTED", "UNKNOWN", "IN_FLIGHT", "PENDING"}

        # Phase 1: schema, completeness, integrity and freshness. No state mutation.
        for evidence in batch:
            if not isinstance(evidence, Evidence):
                raise IncompleteEvidence("Every batch item must be an Evidence instance.")
            required_text = {
                "evidence_id": evidence.evidence_id,
                "attempt_id": evidence.attempt_id,
                "lei": evidence.lei,
                "nonce": evidence.nonce,
                "status": evidence.status,
                "reference_scope": evidence.reference_scope,
                "reference_snapshot": evidence.reference_snapshot,
                "normalization_profile": evidence.normalization_profile,
            }
            missing_text = [name for name, value in required_text.items()
                            if not isinstance(value, str) or not value.strip()]
            if missing_text:
                raise IncompleteEvidence(f"Missing required evidence fields: {sorted(missing_text)}")
            if evidence.evidence_id in seen_ids:
                raise IncompleteEvidence(f"Duplicate evidence_id within batch: {evidence.evidence_id}")
            seen_ids.add(evidence.evidence_id)
            if not isinstance(evidence.properties, Mapping):
                raise IncompleteEvidence(f"Evidence {evidence.evidence_id} properties must be a mapping.")
            missing_properties = set(evidence.required_properties) - set(evidence.properties)
            if missing_properties:
                raise IncompleteEvidence(
                    f"Evidence {evidence.evidence_id} is missing required properties: {sorted(missing_properties)}"
                )
            status = evidence.status.strip().upper()
            if status not in allowed_statuses:
                raise IncompleteEvidence(f"Unsupported evidence status: {evidence.status}")
            if not isinstance(evidence.non_execution_confirmed, bool):
                raise IncompleteEvidence(
                    f"Evidence non_execution_confirmed must be a boolean: {evidence.evidence_id}"
                )
            if evidence.integrity_verified is not True:
                raise IncompleteEvidence(f"Evidence integrity was not verified: {evidence.evidence_id}")
            if evidence.source_authoritative is not True:
                raise IncompleteEvidence(f"Evidence source is not authoritative: {evidence.evidence_id}")
            if evidence.expires_at_ms is not None and self.clock.now_ms >= evidence.expires_at_ms:
                raise IncompleteEvidence(f"Evidence is stale: {evidence.evidence_id}")
            fingerprint = self._evidence_fingerprint(evidence)
            previous_fingerprint = self._evidence_registry.get(evidence.evidence_id)
            if previous_fingerprint is not None and previous_fingerprint != fingerprint:
                raise IncompleteEvidence(
                    f"Evidence ID is not stable; payload changed for {evidence.evidence_id}"
                )
            fingerprints[evidence.evidence_id] = fingerprint

        profiles = {evidence.normalization_profile for evidence in batch}
        if len(profiles) != 1:
            raise IncompleteEvidence(
                "Evidence batch mixes normalization profiles; normalize all items under one profile first."
            )

        # Phase 2: strict binding to one exact attempt. No state mutation.
        if not attempt.nonce:
            raise BindingError("Target attempt has no registered nonce.")
        for evidence in batch:
            if evidence.attempt_id != attempt.attempt_id:
                raise BindingError(f"attempt_id mismatch for evidence {evidence.evidence_id}")
            if evidence.nonce != attempt.nonce:
                raise BindingError(f"nonce mismatch for evidence {evidence.evidence_id}")
            if evidence.lei != attempt.lei:
                raise BindingError(f"LEI mismatch for evidence {evidence.evidence_id}")

        # IDs become immutable once a fully validated, correctly bound item is observed.
        for evidence_id, fingerprint in fingerprints.items():
            self._evidence_registry.setdefault(evidence_id, fingerprint)
        return batch

    def _detect_evidence_conflicts(self, batch: Sequence[Evidence]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        final_outcomes = {"COMMITTED", "FAILED", "REJECTED"}
        for i, left in enumerate(batch):
            for right in batch[i + 1:]:
                left_status = left.status.strip().upper()
                right_status = right.status.strip().upper()
                ids = [left.evidence_id, right.evidence_id]
                if (left_status in final_outcomes and right_status in final_outcomes
                        and left_status != right_status):
                    conflicts.append({
                        "kind": "OutcomeConflict",
                        "evidence_ids": ids,
                        "left_status": left_status,
                        "right_status": right_status,
                    })
                comparable = (
                    left.reference_scope == right.reference_scope
                    and left.reference_snapshot == right.reference_snapshot
                    and left.normalization_profile == right.normalization_profile
                )
                if comparable:
                    shared_properties = self.conflict_sensitive_properties.intersection(
                        set(left.properties).intersection(right.properties)
                    )
                    for property_name in sorted(shared_properties):
                        if self._canonical_value(left.properties[property_name]) != self._canonical_value(
                                right.properties[property_name]):
                            conflicts.append({
                                "kind": "PropertyConflict",
                                "evidence_ids": ids,
                                "property": property_name,
                                "left_value": left.properties[property_name],
                                "right_value": right.properties[property_name],
                                "reference_scope": left.reference_scope,
                                "reference_snapshot": left.reference_snapshot,
                                "normalization_profile": left.normalization_profile,
                            })
        return conflicts

    def is_execution_permit_usable(self, attempt_id: str) -> bool:
        permit = self.permits.get(attempt_id)
        attempt = self.attempts.get(attempt_id)
        if permit is None or attempt is None:
            return False
        if permit.consumed or permit.revoked or attempt.lei in self.governance_quarantine:
            return False
        if attempt.state in (AttemptState.FAILED, AttemptState.RESOLVED, AttemptState.ESCALATED):
            return False
        return True

    def _record_evidence_contradiction(
        self, attempt: Attempt, conflicts: list[dict[str, Any]]
    ) -> MembraneResult:
        evidence_ids = sorted({evidence_id for conflict in conflicts
                               for evidence_id in conflict["evidence_ids"]})
        conflict_kinds = sorted({conflict["kind"] for conflict in conflicts})
        self._log(
            "EVIDENCE_CONTRADICTION",
            attempt_id=attempt.attempt_id,
            lei=attempt.lei,
            evidence_ids=evidence_ids,
            conflict_kinds=conflict_kinds,
            conflicts=conflicts,
        )

        # Revoke every permit associated with this attempt. Do not mint a replacement.
        for permit in self.permits.values():
            if permit.attempt_id == attempt.attempt_id:
                permit.revoked = True
                self._log("EXECUTION_PERMIT_REVOKED_CONTRADICTION", lei=attempt.lei,
                          attempt_id=attempt.attempt_id, evidence_ids=evidence_ids)

        terminal = attempt.state in (AttemptState.FAILED, AttemptState.RESOLVED)
        if terminal:
            quarantine = self.governance_quarantine.get(attempt.lei)
            if quarantine is None:
                fingerprint = hashlib.sha256(
                    (attempt.attempt_id + "|" + "|".join(evidence_ids)
                     + "|" + str(self.clock.now_ms)).encode("utf-8")
                ).hexdigest()[:16]
                quarantine = {
                    "state": "QUARANTINED",
                    "lei": attempt.lei,
                    "attempt_id": attempt.attempt_id,
                    "incident_id": "G0S5-" + fingerprint,
                    "evidence_ids": evidence_ids,
                    "opened_at_ms": self.clock.now_ms,
                    "reason": "EVIDENCE_CONTRADICTION",
                }
                self.governance_quarantine[attempt.lei] = quarantine
            else:
                quarantine["evidence_ids"] = sorted(set(quarantine["evidence_ids"]) | set(evidence_ids))
            self._log("GOVERNANCE_QUARANTINE_LOCK", lei=attempt.lei,
                      attempt_id=attempt.attempt_id, incident_id=quarantine["incident_id"],
                      evidence_ids=evidence_ids)
            self._log("EVIDENCE_ESCALATION_INCIDENT", lei=attempt.lei,
                      attempt_id=attempt.attempt_id, incident_id=quarantine["incident_id"],
                      evidence_ids=evidence_ids, preserved_state=attempt.state.value)
            client_state = "QUARANTINED"
        else:
            attempt.state = AttemptState.ESCALATED
            attempt.retry_eligible = False
            self._log("ATTEMPT_ESCALATED", lei=attempt.lei, attempt_id=attempt.attempt_id,
                      evidence_ids=evidence_ids, state=AttemptState.ESCALATED.value)
            client_state = AttemptState.ESCALATED.value

        return MembraneResult(
            Disposition.HOLD,
            client_state,
            attempt.receipt_observed,
            len(self.sink.effects),
            0.0,
            "EVIDENCE_CONTRADICTION",
            False,
            timeout_event=attempt.timeout_fired,
            retry_eligible=False,
            events=[event["event"] for event in self.events],
        )

    def evaluate_evidence_batch(
        self, *, attempt_id: str, evidence_batch: Sequence[Evidence]
    ) -> MembraneResult:
        """Validate a complete S5 batch before making any outcome transition.

        Evidence properties must already be normalized under normalization_profile.
        Authentication and source-authority booleans are assertions from the adapter's
        upstream verifier; this lab shim is not a cryptographic verifier.
        """
        if attempt_id not in self.attempts:
            raise KeyError(attempt_id)
        attempt = self.attempts[attempt_id]
        batch = self._validate_evidence_batch(attempt, evidence_batch)
        conflicts = self._detect_evidence_conflicts(batch)
        if conflicts:
            return self._record_evidence_contradiction(attempt, conflicts)

        statuses = {evidence.status.strip().upper() for evidence in batch}
        self._log("EVIDENCE_BATCH_NONCONTRADICTORY", lei=attempt.lei,
                  attempt_id=attempt.attempt_id,
                  evidence_ids=sorted(evidence.evidence_id for evidence in batch))

        # Evidence cannot rewrite an already terminal state. Matching COMMITTED
        # evidence is idempotent; conflicting-with-state handling remains fail-closed.
        if attempt.state in (AttemptState.FAILED, AttemptState.RESOLVED):
            if attempt.state == AttemptState.RESOLVED and statuses == {"COMMITTED"}:
                return MembraneResult(Disposition.PASS, AttemptState.RESOLVED.value,
                    True, len(self.sink.effects), 0.0, "EVIDENCE_CONFIRMED", False,
                    events=[event["event"] for event in self.events])
            self._log("EVIDENCE_TERMINAL_STATE_IMMUTABLE", lei=attempt.lei,
                      attempt_id=attempt.attempt_id, state=attempt.state.value,
                      evidence_statuses=sorted(statuses))
            return MembraneResult(Disposition.HOLD, attempt.state.value,
                attempt.receipt_observed, len(self.sink.effects), 0.0,
                "TERMINAL_STATE_IMMUTABLE", False,
                events=[event["event"] for event in self.events])

        if statuses == {"COMMITTED"}:
            attempt.state = AttemptState.RESOLVED
            attempt.effect_observed = True  # bound evidence confirms the external effect
            attempt.qualified = True
            attempt.receipt_observed = True
            attempt.retry_eligible = False
            self._log("EVIDENCE_BATCH_RESOLVED_COMMITTED", lei=attempt.lei,
                      attempt_id=attempt.attempt_id,
                      evidence_ids=sorted(evidence.evidence_id for evidence in batch))
            return MembraneResult(Disposition.PASS, AttemptState.RESOLVED.value, True,
                len(self.sink.effects), 0.0, "EVIDENCE_BATCH_COMMITTED", False,
                events=[event["event"] for event in self.events])

        if statuses in ({"FAILED"}, {"REJECTED"}) and attempt.effect_observed:
            self._log("EVIDENCE_NEGATIVE_CONTRADICTS_OBSERVED_EFFECT",
                      lei=attempt.lei, attempt_id=attempt.attempt_id,
                      evidence_ids=sorted(evidence.evidence_id for evidence in batch))
            return MembraneResult(Disposition.HOLD, self._client_projection(attempt)[1],
                attempt.receipt_observed, len(self.sink.effects), 0.0,
                "EVIDENCE_CONTRADICTS_OBSERVED_EFFECT", False,
                timeout_event=attempt.timeout_fired, retry_eligible=False,
                events=[event["event"] for event in self.events])

        if statuses in ({"FAILED"}, {"REJECTED"}):
            if not all(evidence.non_execution_confirmed is True for evidence in batch):
                self._log("EVIDENCE_BATCH_NON_EXECUTION_UNPROVEN", lei=attempt.lei,
                          attempt_id=attempt.attempt_id,
                          evidence_ids=sorted(evidence.evidence_id for evidence in batch))
                return MembraneResult(Disposition.HOLD, self._client_projection(attempt)[1],
                    attempt.receipt_observed, len(self.sink.effects), 0.0,
                    "EVIDENCE_BATCH_NON_EXECUTION_UNPROVEN", False,
                    timeout_event=attempt.timeout_fired, retry_eligible=False,
                    events=[event["event"] for event in self.events])
            attempt.state = AttemptState.FAILED
            attempt.qualified = True
            attempt.retry_eligible = False
            attempt.failure_reason = "CONSISTENT_NEGATIVE_EVIDENCE"
            self._log("EVIDENCE_BATCH_RESOLVED_FAILED", lei=attempt.lei,
                      attempt_id=attempt.attempt_id,
                      evidence_ids=sorted(evidence.evidence_id for evidence in batch),
                      non_execution_confirmed=True)
            return MembraneResult(Disposition.HOLD, AttemptState.FAILED.value, True,
                len(self.sink.effects), 0.0, "EVIDENCE_BATCH_FAILED", False,
                retry_eligible=False, events=[event["event"] for event in self.events])

        self._log("EVIDENCE_BATCH_INCONCLUSIVE", lei=attempt.lei,
                  attempt_id=attempt.attempt_id,
                  statuses=sorted(statuses),
                  evidence_ids=sorted(evidence.evidence_id for evidence in batch))
        return MembraneResult(Disposition.HOLD, self._client_projection(attempt)[1],
            attempt.receipt_observed, len(self.sink.effects), 0.0,
            "EVIDENCE_BATCH_INCONCLUSIVE", False,
            events=[event["event"] for event in self.events])


    def reconcile(
        self,
        *,
        attempt_id: str,
        evidence: Evidence,
        retry_eligible: bool = True,
    ) -> MembraneResult:
        """Reconcile a past external outcome without executing or issuing permits.

        Evidence integrity/source authority are upstream-verifier assertions. For
        FAILED, non_execution_confirmed must explicitly attest that no external
        effect occurred. This method never invokes the kernel or EffectSink.
        """
        if attempt_id not in self.attempts:
            raise KeyError(attempt_id)
        if not isinstance(retry_eligible, bool):
            raise TypeError("retry_eligible must be a bool annotation")

        attempt = self.attempts[attempt_id]
        batch = self._validate_evidence_batch(attempt, (evidence,))
        item = batch[0]
        outcome = item.status.strip().upper()

        if outcome not in {"COMMITTED", "FAILED"}:
            self._log("RECONCILIATION_INCONCLUSIVE", lei=attempt.lei,
                      attempt_id=attempt_id, evidence_id=item.evidence_id,
                      outcome=outcome)
            disp, state = self._client_projection(attempt)
            return MembraneResult(disp, state, attempt.receipt_observed,
                len(self.sink.effects), 0.0, "RECONCILIATION_INCONCLUSIVE", False,
                timeout_event=attempt.timeout_fired, retry_eligible=attempt.retry_eligible,
                events=[event["event"] for event in self.events])

        if outcome == "FAILED" and item.non_execution_confirmed is not True:
            self._log("RECONCILIATION_REJECTED_NO_NON_EXECUTION_PROOF",
                      lei=attempt.lei, attempt_id=attempt_id,
                      evidence_id=item.evidence_id)
            disp, state = self._client_projection(attempt)
            return MembraneResult(disp, state, attempt.receipt_observed,
                len(self.sink.effects), 0.0,
                "RECONCILIATION_NO_NON_EXECUTION_PROOF", False,
                timeout_event=attempt.timeout_fired, retry_eligible=False,
                events=[event["event"] for event in self.events])

        # Do not overwrite terminal outcomes. Matching evidence is idempotent;
        # an opposite outcome fails closed without mutating terminal state.
        if attempt.state in (AttemptState.FAILED, AttemptState.RESOLVED):
            consistent = (
                (attempt.state == AttemptState.RESOLVED and outcome == "COMMITTED"
                 and attempt.effect_observed)
                or (attempt.state == AttemptState.FAILED and outcome == "FAILED"
                    and item.non_execution_confirmed is True
                    and not attempt.effect_observed)
            )
            if consistent:
                self._log("RECONCILIATION_IDEMPOTENT_ACK", lei=attempt.lei,
                          attempt_id=attempt_id, evidence_id=item.evidence_id,
                          outcome=outcome, state=attempt.state.value)
                disp, state = self._client_projection(attempt)
                return MembraneResult(disp, state, attempt.receipt_observed,
                    len(self.sink.effects), 0.0, "RECONCILIATION_IDEMPOTENT_ACK", False,
                    timeout_event=attempt.timeout_fired, retry_eligible=attempt.retry_eligible,
                    events=[event["event"] for event in self.events])
            self._log("RECONCILIATION_TERMINAL_CONFLICT", lei=attempt.lei,
                      attempt_id=attempt_id, evidence_id=item.evidence_id,
                      outcome=outcome, state=attempt.state.value)
            return MembraneResult(Disposition.HOLD, attempt.state.value,
                attempt.receipt_observed, len(self.sink.effects), 0.0,
                "RECONCILIATION_TERMINAL_CONFLICT", False,
                timeout_event=attempt.timeout_fired, retry_eligible=False,
                events=[event["event"] for event in self.events])

        if attempt.state != AttemptState.UNKNOWN:
            self._log("RECONCILIATION_REJECTED_BAD_STATE", lei=attempt.lei,
                      attempt_id=attempt_id, state=attempt.state.value,
                      outcome=outcome)
            disp, state = self._client_projection(attempt)
            return MembraneResult(Disposition.HOLD, state, attempt.receipt_observed,
                len(self.sink.effects), 0.0, "RECONCILIATION_BAD_STATE", False,
                timeout_event=attempt.timeout_fired, retry_eligible=False,
                events=[event["event"] for event in self.events])

        if outcome == "COMMITTED":
            attempt.state = AttemptState.RESOLVED
            attempt.effect_observed = True  # confirmed by the bound external evidence
            attempt.qualified = True
            attempt.retry_eligible = False
            attempt.failure_reason = None
            self._log("RECONCILIATION_SUCCESS", lei=attempt.lei,
                      attempt_id=attempt_id, evidence_id=item.evidence_id,
                      outcome=outcome, non_execution_confirmed=False)
            return MembraneResult(Disposition.PASS, AttemptState.RESOLVED.value,
                attempt.receipt_observed, len(self.sink.effects), 0.0,
                "RECONCILIATION_SUCCESS", False,
                timeout_event=attempt.timeout_fired, retry_eligible=False,
                events=[event["event"] for event in self.events])

        if attempt.effect_observed:
            self._log("RECONCILIATION_NEGATIVE_CONTRADICTS_OBSERVED_EFFECT",
                      lei=attempt.lei, attempt_id=attempt_id,
                      evidence_id=item.evidence_id)
            return MembraneResult(Disposition.HOLD, self._client_projection(attempt)[1],
                attempt.receipt_observed, len(self.sink.effects), 0.0,
                "RECONCILIATION_CONTRADICTS_OBSERVED_EFFECT", False,
                timeout_event=attempt.timeout_fired, retry_eligible=False,
                events=[event["event"] for event in self.events])

        attempt.state = AttemptState.FAILED
        attempt.qualified = True
        attempt.retry_eligible = retry_eligible  # audit/policy annotation only
        attempt.failure_reason = "RECONCILIATION_CONFIRMED_NON_EXECUTION"
        self._log("RECONCILIATION_FAILURE_CONFIRMED_NON_EXECUTION",
                  lei=attempt.lei, attempt_id=attempt_id,
                  evidence_id=item.evidence_id, outcome=outcome,
                  non_execution_confirmed=True, retry_eligible=retry_eligible)
        return MembraneResult(Disposition.HOLD, AttemptState.FAILED.value,
            attempt.receipt_observed, len(self.sink.effects), 0.0,
            "RECONCILIATION_FAILURE_CONFIRMED_NON_EXECUTION", False,
            timeout_event=attempt.timeout_fired, retry_eligible=retry_eligible,
            events=[event["event"] for event in self.events])

    def resolve_governance_quarantine(
        self, *, lei: str, incident_id: str, authorized_by: str, rationale: str
    ) -> None:
        """Explicit, auditable release; never restores previously revoked permits."""
        for field_name, value in {
            "lei": lei,
            "incident_id": incident_id,
            "authorized_by": authorized_by,
            "rationale": rationale,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required to release governance quarantine.")
        quarantine = self.governance_quarantine.get(lei)
        if quarantine is None:
            raise KeyError(lei)
        if quarantine["incident_id"] != incident_id:
            raise ValueError("incident_id does not match the active quarantine.")
        if (
            self.quarantine_release_authorizer is None
            or not self.quarantine_release_authorizer(authorized_by, lei)
        ):
            self._log("GOVERNANCE_QUARANTINE_RELEASE_REJECTED", lei=lei,
                      incident_id=incident_id, authorized_by=authorized_by,
                      reason="AUTHORIZATION_DENIED")
            raise PermissionError("Governance quarantine release was not authorized.")
        released = dict(quarantine)
        released.update({
            "state": "RELEASED",
            "released_at_ms": self.clock.now_ms,
            "authorized_by": authorized_by,
            "rationale": rationale,
        })
        self.governance_quarantine_history.append(released)
        del self.governance_quarantine[lei]
        self._log("GOVERNANCE_QUARANTINE_RELEASED", lei=lei, attempt_id=quarantine["attempt_id"],
                  incident_id=incident_id, authorized_by=authorized_by, rationale=rationale)

    def retry_eligible_for(self, lei: str) -> bool:
        return not self._has_unresolved(lei)

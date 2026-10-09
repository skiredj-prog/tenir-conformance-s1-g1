"""G0 S7 — forged non-execution attestation conformance tests."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tenir_conformance.membrane import (
    AttemptState,
    Evidence,
    FakeClock,
    Membrane,
)
from tenir_conformance.membrane.attestation import load_trust_root
from tenir_conformance.membrane.kernel_bridge import KernelBridge
from s7_helpers import revoked_k1_trust_root, sign_attestation

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "scenarios" / "G0_S7_FORGED_NON_EXECUTION_ATTESTATION.md"
SCENARIO_PATH = ROOT / "scenarios" / "S7.json"
TRUST_ROOT_PATH = ROOT / "src" / "tenir_conformance" / "membrane" / "trust_root.yaml"
ARTIFACTS = ROOT / "artifacts" / "s7"
PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
NOW = 1_000_000
TAU = 5_000


def _permit_snapshot(m: Membrane) -> dict[str, dict[str, Any]]:
    return {
        aid: {
            "lei": permit.lei,
            "attempt_id": permit.attempt_id,
            "consumed": permit.consumed,
            "revoked": permit.revoked,
            "issued_at_ms": permit.issued_at_ms,
        }
        for aid, permit in sorted(m.permits.items())
    }


def _attempt_snapshot(m: Membrane) -> dict[str, dict[str, Any]]:
    return {
        aid: {
            "lei": attempt.lei,
            "attempt_id": attempt.attempt_id,
            "nonce": attempt.nonce,
            "state": attempt.state.value,
            "effect_observed": attempt.effect_observed,
            "qualified": attempt.qualified,
            "non_execution_confirmed": attempt.non_execution_confirmed,
        }
        for aid, attempt in sorted(m.attempts.items())
    }


def _prepare_unknown(*, trust_root=None) -> Membrane:
    m = Membrane(
        KernelBridge(),
        clock=FakeClock(now_ms=NOW),
        tau_k_ms=TAU,
        trust_root=trust_root,
    )
    result = m.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD,
        nonce="n1", request_lost=True,
    )
    assert result.client_state == AttemptState.UNKNOWN.value
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert m.permits["A1"].consumed is True
    assert m.attempts["A1"].effect_observed is False
    return m


def _write_artifacts(
    m: Membrane,
    subcase: str,
    *,
    attestation,
    state_before: dict[str, Any],
    permits_before: dict[str, Any],
    effects_before: list[dict[str, Any]],
    result,
    expected_reason: str,
    assertions: dict[str, Any],
    blocked_result=None,
    state_after_blocked: dict[str, Any] | None = None,
    permits_after_blocked: dict[str, Any] | None = None,
) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    trust_root_snapshot = m.trust_root
    record = m.evidence_registry[-1] if m.evidence_registry else None
    body = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario_id": "G0_S7",
        "subcase": subcase,
        "spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
        "scenario_sha256": hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest(),
        "trust_root_file_sha256": hashlib.sha256(TRUST_ROOT_PATH.read_bytes()).hexdigest(),
        "claim_scope": "tested sequential interleavings only",
        "expected_reason": expected_reason,
        "actual_decision": result.kernel_decision,
        "actual_state": m.attempts["A1"].state.value,
        "signed_payload_and_signature": attestation.to_record() if attestation else None,
        "trust_root_snapshot": trust_root_snapshot,
        "verification_trace": record,
        "attempt_state_before": state_before,
        "attempt_state_after_verification": _attempt_snapshot(m),
        "attempt_state_after_blocked_A2": state_after_blocked,
        "permit_registry_before": permits_before,
        "permit_registry_after_verification": _permit_snapshot(m),
        "permit_registry_after_blocked_A2": permits_after_blocked,
        "effect_sink_before": effects_before,
        "effect_sink_after_verification": list(m.sink.effects),
        "effect_sink_after_blocked_A2": list(m.sink.effects),
        "blocked_A2_result": (
            {
                "disposition": blocked_result.disposition.value,
                "client_state": blocked_result.client_state,
                "kernel_decision": blocked_result.kernel_decision,
                "effect_count": blocked_result.effect_count,
            }
            if blocked_result else None
        ),
        "transition_log": m.events,
        "assertions": assertions,
    }
    compact = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str) + "\n"
    (ARTIFACTS / f"evidence_{subcase}.jsonl").write_text(compact, encoding="utf-8")
    (ARTIFACTS / f"{subcase}_result.json").write_text(
        json.dumps({k: v for k, v in body.items() if k != "transition_log"},
                   sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_attestation.json").write_text(
        json.dumps(body["signed_payload_and_signature"], sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_trust_root.json").write_text(
        json.dumps(trust_root_snapshot, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_transition.json").write_text(
        json.dumps(m.events, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_permit.json").write_text(
        json.dumps({
            "before": permits_before,
            "after_verification": _permit_snapshot(m),
            "after_blocked_A2": permits_after_blocked,
        }, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_effect_sink.json").write_text(
        json.dumps({
            "before": effects_before,
            "after_verification": m.sink.effects,
            "after_blocked_A2": m.sink.effects,
        }, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _assert_rejection(
    subcase: str,
    attestation,
    *,
    expected_reason: str,
    expected_decision: str = "SIGNATURE_INVALID",
    trust_root=None,
):
    m = _prepare_unknown(trust_root=trust_root)
    state_before = _attempt_snapshot(m)
    permits_before = _permit_snapshot(m)
    effects_before = list(m.sink.effects)

    result = m.declare_failed(
        attempt_id="A1",
        evidence_qualified=True,
        attestation=attestation,
        reason="S7_NON_EXECUTION_ATTESTATION",
    )
    state_after_verification = _attempt_snapshot(m)
    permits_after_verification = _permit_snapshot(m)
    effects_after_verification = list(m.sink.effects)

    assert result.disposition.value == "HOLD"
    assert result.kernel_decision == expected_decision
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert m.retry_eligible_for("L") is False
    assert state_after_verification == state_before
    assert permits_after_verification == permits_before
    assert effects_after_verification == effects_before
    assert m.evidence_registry[-1]["status"] == "unverified"
    assert m.evidence_registry[-1]["verification_reason"] == expected_reason
    assert any(
        event["event"] == "NON_EXECUTION_ATTESTATION_REJECTED"
        and event["attestation_id"] == attestation.attestation_id
        and event["reason"] == expected_reason
        for event in m.events
    )

    # A2 has not been admitted. A new submission remains blocked by the LEI lock.
    blocked = m.process_transaction(
        lei="L", attempt_id="A2", payload=PAYLOAD, nonce="n2"
    )
    state_after_blocked = _attempt_snapshot(m)
    permits_after_blocked = _permit_snapshot(m)
    assert blocked.disposition.value == "HOLD"
    assert blocked.kernel_decision == "NOT_EVALUATED"
    assert "A2" not in m.attempts
    assert state_after_blocked == state_after_verification
    assert permits_after_blocked == permits_after_verification
    assert m.sink.effects == effects_after_verification

    assertions = {
        "invalid_attestation_retained_unverified": m.evidence_registry[-1]["status"] == "unverified",
        "reason_is_specific": m.evidence_registry[-1]["verification_reason"] == expected_reason,
        "A1_remains_unknown": m.attempts["A1"].state == AttemptState.UNKNOWN,
        "LEI_lock_holds": m.retry_eligible_for("L") is False,
        "A2_not_admitted": "A2" not in m.attempts,
        "permit_registry_unchanged_by_rejection": permits_after_verification == permits_before,
        "effect_sink_unchanged_by_rejection": effects_after_verification == effects_before,
        "rejection_event_contains_attestation_id": any(
            e["event"] == "NON_EXECUTION_ATTESTATION_REJECTED"
            and e["attestation_id"] == attestation.attestation_id
            for e in m.events
        ),
    }
    assert all(assertions.values())
    _write_artifacts(
        m, subcase, attestation=attestation,
        state_before=state_before, permits_before=permits_before,
        effects_before=effects_before, result=result,
        expected_reason=expected_reason, assertions=assertions,
        blocked_result=blocked, state_after_blocked=state_after_blocked,
        permits_after_blocked=permits_after_blocked,
    )
    return m


def test_s7a_unsigned_attestation_is_retained_and_rejected():
    att = sign_attestation(
        attestation_id="S7A-UNSIGNED", attempt_id="A1", lei="L",
        nonce="n1", signed=False,
    )
    _assert_rejection("S7a", att, expected_reason="missing_signature")


def test_s7b_unknown_signing_key_is_rejected():
    att = sign_attestation(
        attestation_id="S7B-UNKNOWN-KEY", attempt_id="A1", lei="L",
        nonce="n1", key_id="K9",
    )
    _assert_rejection("S7b", att, expected_reason="unknown_key")


def test_s7c_revoked_signing_key_is_rejected():
    att = sign_attestation(
        attestation_id="S7C-REVOKED-KEY", attempt_id="A1", lei="L",
        nonce="n1", key_epoch=1,
    )
    _assert_rejection(
        "S7c", att, expected_reason="revoked_key",
        trust_root=revoked_k1_trust_root(),
    )


def test_s7d_tampered_signed_payload_is_rejected():
    signed = sign_attestation(
        attestation_id="S7D-TAMPERED", attempt_id="A1", lei="L",
        nonce="n1",
    )
    tampered = replace(signed, nonce="n1-tampered")
    _assert_rejection("S7d", tampered, expected_reason="content_mismatch")


def test_s7e_valid_attestation_fails_a1_and_releases_a2():
    m = _prepare_unknown()
    att = sign_attestation(
        attestation_id="S7E-NOMINAL", attempt_id="A1", lei="L",
        nonce="n1",
    )
    state_before = _attempt_snapshot(m)
    permits_before = _permit_snapshot(m)
    effects_before = list(m.sink.effects)

    failed = m.declare_failed(
        attempt_id="A1",
        evidence_qualified=True,
        attestation=att,
        retry_eligible=True,
        reason="S7_VERIFIED_NON_EXECUTION",
    )
    assert failed.client_state == "FAILED"
    assert m.attempts["A1"].state == AttemptState.FAILED
    assert m.attempts["A1"].non_execution_confirmed is True
    assert m.retry_eligible_for("L") is True
    permits_after_verification = _permit_snapshot(m)
    assert permits_after_verification == permits_before
    assert len(m.sink.effects) == len(effects_before)
    assert m.evidence_registry[-1]["status"] == "verified"
    assert m.evidence_registry[-1]["verification_reason"] == "verified"

    second = m.process_transaction(
        lei="L", attempt_id="A2", payload=PAYLOAD, nonce="n2"
    )
    assert second.disposition.value == "PASS"
    assert second.client_state == "RESOLVED"
    assert "A2" in m.attempts and "A2" in m.permits
    assert len(m.sink.effects) == len(effects_before) + 1
    assertions = {
        "signature_verified_before_failed_transition": m.attempts["A1"].state == AttemptState.FAILED,
        "A1_failed_non_execution_established": m.attempts["A1"].non_execution_confirmed is True,
        "A1_permit_not_mutated_by_verification": permits_after_verification == permits_before,
        "A2_admitted_only_after_verified_failure": "A2" in m.attempts,
        "A2_has_distinct_permit": m.permits["A2"].attempt_id == "A2",
        "effect_sink_delta_is_one_for_A2": len(m.sink.effects) - len(effects_before) == 1,
        "attestation_registry_marks_verified": m.evidence_registry[-1]["status"] == "verified",
    }
    assert all(assertions.values())
    _write_artifacts(
        m, "S7e", attestation=att, state_before=state_before,
        permits_before=permits_before, effects_before=effects_before,
        result=failed, expected_reason="verified", assertions=assertions,
        blocked_result=None, state_after_blocked=_attempt_snapshot(m),
        permits_after_blocked=_permit_snapshot(m),
    )


def test_s7f_valid_attestation_replayed_across_leis_is_rejected():
    att = sign_attestation(
        attestation_id="S7F-CROSS-LEI", attempt_id="A1", lei="M",
        nonce="n1",
    )
    _assert_rejection(
        "S7f", att, expected_reason="BINDING_LEI_MISMATCH",
        expected_decision="BINDING_LEI_MISMATCH",
    )


def test_s7_reconcile_failed_requires_signed_attestation():
    clock = FakeClock(now_ms=NOW)
    m = Membrane(KernelBridge(), clock=clock, tau_k_ms=TAU)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=False, nonce="n1"
    )
    clock.advance_to(NOW + TAU)
    assert m.check_qualification_timeouts() == ["A1"]
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    permits_before = _permit_snapshot(m)
    evidence = Evidence(
        evidence_id="S7-RECONCILE-UNSIGNED",
        attempt_id="A1",
        lei="L",
        nonce="n1",
        status="FAILED",
        properties={},
        reference_scope="operation:LEI-L",
        reference_snapshot="snapshot:s7-v1",
        normalization_profile="s7-v1",
        integrity_verified=True,
        source_authoritative=True,
        expires_at_ms=NOW + 60_000,
        non_execution_confirmed=True,
        attestation=sign_attestation(
            attestation_id="S7-RECONCILE-UNSIGNED",
            attempt_id="A1", lei="L", nonce="n1", signed=False,
        ),
    )
    result = m.reconcile(attempt_id="A1", evidence=evidence)
    assert result.disposition.value == "HOLD"
    assert result.kernel_decision == "SIGNATURE_INVALID"
    assert result.client_state == "UNKNOWN"
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert m.retry_eligible_for("L") is False
    assert _permit_snapshot(m) == permits_before
    assert m.evidence_registry[-1]["status"] == "unverified"
    assert m.evidence_registry[-1]["verification_reason"] == "missing_signature"
    assert "A2" not in m.attempts

def test_s7_valid_signed_reconciliation_releases_lock_without_executing():
    clock = FakeClock(now_ms=NOW)
    m = Membrane(KernelBridge(), clock=clock, tau_k_ms=TAU)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=False, nonce="n1"
    )
    clock.advance_to(NOW + TAU)
    assert m.check_qualification_timeouts() == ["A1"]
    effects_before = list(m.sink.effects)
    permits_before = _permit_snapshot(m)

    attestation = sign_attestation(
        attestation_id="S7-RECONCILE-VALID",
        attempt_id="A1", lei="L", nonce="n1",
    )
    evidence = Evidence(
        evidence_id="S7-RECONCILE-VALID",
        attempt_id="A1",
        lei="L",
        nonce="n1",
        status="FAILED",
        properties={},
        reference_scope="operation:LEI-L",
        reference_snapshot="snapshot:s7-v1",
        normalization_profile="s7-v1",
        integrity_verified=True,
        source_authoritative=True,
        expires_at_ms=NOW + 60_000,
        non_execution_confirmed=True,
        attestation=attestation,
    )

    result = m.reconcile(attempt_id="A1", evidence=evidence)
    assert result.client_state == "FAILED"
    assert m.attempts["A1"].state == AttemptState.FAILED
    assert m.attempts["A1"].non_execution_confirmed is True
    assert m.retry_eligible_for("L") is True
    assert _permit_snapshot(m) == permits_before
    assert m.sink.effects == effects_before
    assert m.evidence_registry[-1]["status"] == "verified"

    second = m.process_transaction(
        lei="L", attempt_id="A2", payload=PAYLOAD, nonce="n2"
    )
    assert second.disposition.value == "PASS"
    assert "A2" in m.attempts and "A2" in m.permits
    assert len(m.sink.effects) == len(effects_before) + 1


def test_s7_unverified_negative_evidence_cannot_trigger_s5_escalation():
    clock = FakeClock(now_ms=NOW)
    m = Membrane(
        KernelBridge(),
        clock=clock,
        tau_k_ms=TAU,
        conflict_sensitive_properties={"exposure"},
    )
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n1"
    )
    clock.advance_to(NOW + TAU)
    assert m.check_qualification_timeouts() == ["A1"]
    assert m.attempts["A1"].state == AttemptState.UNKNOWN

    state_before = _attempt_snapshot(m)
    permits_before = _permit_snapshot(m)
    effects_before = list(m.sink.effects)
    unsigned = sign_attestation(
        attestation_id="S7-S5-UNVERIFIED",
        attempt_id="A1", lei="L", nonce="n1", signed=False,
    )
    negative = Evidence(
        evidence_id="S7-S5-FAILED",
        attempt_id="A1",
        lei="L",
        nonce="n1",
        status="FAILED",
        properties={},
        reference_scope="operation:LEI-L",
        reference_snapshot="snapshot:s7-v1",
        normalization_profile="s7-v1",
        integrity_verified=True,
        source_authoritative=True,
        expires_at_ms=NOW + 60_000,
        non_execution_confirmed=True,
        attestation=unsigned,
    )
    committed = Evidence(
        evidence_id="S7-S5-COMMITTED",
        attempt_id="A1",
        lei="L",
        nonce="n1",
        status="COMMITTED",
        properties={},
        reference_scope="operation:LEI-L",
        reference_snapshot="snapshot:s7-v1",
        normalization_profile="s7-v1",
        integrity_verified=True,
        source_authoritative=True,
        expires_at_ms=NOW + 60_000,
    )

    result = m.evaluate_evidence_batch(
        attempt_id="A1", evidence_batch=[negative, committed]
    )
    assert result.disposition.value == "HOLD"
    assert result.kernel_decision == "SIGNATURE_INVALID"
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert _attempt_snapshot(m) == state_before
    assert _permit_snapshot(m) == permits_before
    assert m.sink.effects == effects_before
    assert m.governance_quarantine == {}
    assert not any(event["event"] == "EVIDENCE_CONTRADICTION" for event in m.events)
    assert m.evidence_registry[-1]["status"] == "unverified"
    assert m.evidence_registry[-1]["verification_reason"] == "missing_signature"

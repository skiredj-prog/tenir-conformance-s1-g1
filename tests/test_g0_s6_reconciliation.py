"""G0 S6 — evidence-bound reconciliation and terminal LEI convergence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tenir_conformance.membrane import (
    AttemptState,
    BindingError,
    Evidence,
    FakeClock,
    IncompleteEvidence,
    Membrane,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "scenarios" / "G0_S6_SUCCESSFUL_RECONCILIATION.md"
SCENARIO_PATH = ROOT / "scenarios" / "S6.json"
ARTIFACTS = ROOT / "artifacts" / "s6"
PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
NOW = 1_000_000
TAU = 5_000


def _membrane(clock: FakeClock | None = None) -> Membrane:
    return Membrane(KernelBridge(), clock=clock or FakeClock(now_ms=NOW), tau_k_ms=TAU)


def _evidence(
    evidence_id: str,
    status: str,
    *,
    attempt_id: str = "A1",
    lei: str = "L",
    nonce: str = "n-s6",
    integrity_verified: bool = True,
    source_authoritative: bool = True,
    expires_at_ms: int = NOW + 60_000,
    non_execution_confirmed: bool = False,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        attempt_id=attempt_id,
        lei=lei,
        nonce=nonce,
        status=status,
        properties={},
        reference_scope="operation:LEI-L",
        reference_snapshot="snapshot:s6-v1",
        normalization_profile="reconciliation-v1",
        integrity_verified=integrity_verified,
        source_authoritative=source_authoritative,
        expires_at_ms=expires_at_ms,
        non_execution_confirmed=non_execution_confirmed,
    )


def _prepare_unknown(*, apply_effect: bool) -> tuple[Membrane, FakeClock]:
    clock = FakeClock(now_ms=NOW)
    membrane = _membrane(clock)
    membrane.admit_and_await_qualification(
        lei="L",
        attempt_id="A1",
        payload=PAYLOAD,
        apply_effect=apply_effect,
        nonce="n-s6",
    )
    clock.advance_to(NOW + TAU)
    assert membrane.check_qualification_timeouts() == ["A1"]
    assert membrane.attempts["A1"].state == AttemptState.UNKNOWN
    return membrane, clock


def _spec_sha256() -> str:
    return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()


def _scenario_sha256() -> str:
    return hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest()


def _dump_s6(
    membrane: Membrane,
    subcase: str,
    *,
    effects_before_reconcile: int,
    effects_after_reconcile: int,
    permits_before_reconcile: dict[str, dict[str, object]],
    permits_after_reconcile: dict[str, dict[str, object]],
    result,
    assertions: dict[str, object],
    extra: dict | None = None,
) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    permits = {
        key: {
            "lei": permit.lei,
            "attempt_id": permit.attempt_id,
            "consumed": permit.consumed,
            "revoked": permit.revoked,
            "issued_at_ms": permit.issued_at_ms,
        }
        for key, permit in membrane.permits.items()
    }
    attempt_map = {
        key: {
            "lei": attempt.lei,
            "state": attempt.state.value,
            "effect_observed": attempt.effect_observed,
            "qualified": attempt.qualified,
            "timeout_fired": attempt.timeout_fired,
            "retry_eligible": attempt.retry_eligible,
            "failure_reason": attempt.failure_reason,
        }
        for key, attempt in membrane.attempts.items()
    }
    body = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario_id": "G0_S6",
        "subcase": subcase,
        "spec_sha256": _spec_sha256(),
        "scenario_sha256": _scenario_sha256(),
        "claim_scope": "tested sequential interleavings only",
        "reconcile_result": {
            "disposition": result.disposition.value,
            "client_state": result.client_state,
            "kernel_decision": result.kernel_decision,
            "effect_count": result.effect_count,
            "retry_eligible": result.retry_eligible,
        },
        "effect_sink_count_before_reconcile": effects_before_reconcile,
        "effect_sink_count_after_reconcile": effects_after_reconcile,
        "effect_sink_delta_during_reconcile": effects_after_reconcile - effects_before_reconcile,
        "permit_registry_before_reconcile": permits_before_reconcile,
        "permit_registry_after_reconcile": permits_after_reconcile,
        "permit_ids_before_reconcile": sorted(permits_before_reconcile),
        "permit_ids_after_reconcile": sorted(permits_after_reconcile),
        "permit_registry_after_scenario": permits,
        "permit_ids_after_scenario": sorted(permits),
        "attempts_after_scenario": attempt_map,
        "effect_sink_after_scenario": membrane.sink.effects,
        "transition_log": membrane.events,
        "assertions": assertions,
        **(extra or {}),
    }
    (ARTIFACTS / f"evidence_G0_{subcase}.jsonl").write_text(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_result.json").write_text(
        json.dumps({k: v for k, v in body.items() if k not in {"transition_log", "effect_sink_after_scenario"}},
                   sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_transition.json").write_text(
        json.dumps(membrane.events, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_permit.json").write_text(
        json.dumps(body["permit_registry_after_reconcile"], sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_effect_sink.json").write_text(
        json.dumps({
            "before_reconcile": effects_before_reconcile,
            "after_reconcile": effects_after_reconcile,
            "delta_during_reconcile": effects_after_reconcile - effects_before_reconcile,
            "effects_after_scenario": membrane.sink.effects,
        }, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}_assertions.json").write_text(
        json.dumps(assertions, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _permit_snapshot(m: Membrane) -> dict[str, dict[str, object]]:
    return {
        key: {"lei": p.lei, "consumed": p.consumed, "revoked": p.revoked}
        for key, p in m.permits.items()
    }


def test_s6a_reconcile_committed_converges_without_execution_or_permit_mutation():
    m, _ = _prepare_unknown(apply_effect=True)
    assert m.attempts["A1"].effect_observed is True
    before_effects = len(m.sink.effects)
    permits_before = _permit_snapshot(m)
    a1_permit_consumed_before = m.permits["A1"].consumed

    result = m.reconcile(
        attempt_id="A1",
        evidence=_evidence("E-S6A-COMMITTED", "COMMITTED"),
    )
    effects_after_reconcile = len(m.sink.effects)
    permits_after_reconcile = _permit_snapshot(m)

    assert result.disposition.value == "PASS"
    assert result.client_state == "RESOLVED"
    assert m.attempts["A1"].state == AttemptState.RESOLVED
    assert m.attempts["A1"].qualified is True
    assert m.attempts["A1"].effect_observed is True
    assert len(m.sink.effects) == before_effects
    assert _permit_snapshot(m) == permits_before
    assert m.permits["A1"].consumed is a1_permit_consumed_before is True
    assert "RECONCILIATION_SUCCESS" in [e["event"] for e in m.events]

    a2 = m.admit_and_await_qualification(
        lei="L", attempt_id="A2", payload=PAYLOAD, apply_effect=False, nonce="n-s6-a2"
    )
    assert a2.disposition.value == "HOLD"
    assert a2.kernel_decision == "NOT_EVALUATED"
    assert "A2" not in m.attempts
    assert _permit_snapshot(m) == permits_before

    assertions = {
        "A1_api_decision": result.kernel_decision == "RECONCILIATION_SUCCESS",
        "A2_terminal_state": m.attempts["A1"].state == AttemptState.RESOLVED,
        "A3_effect_delta_zero": effects_after_reconcile - before_effects == 0,
        "A4_canonical_event": "RECONCILIATION_SUCCESS" in [e["event"] for e in m.events],
        "A5_permit_isolation": _permit_snapshot(m) == permits_before and m.permits["A1"].consumed,
        "A6_resolved_attempt_blocks_A2": "A2" not in m.attempts,
        "A7_claim_scope": "tested sequential interleavings only",
    }
    assert all(value is True for key, value in assertions.items() if key != "A7_claim_scope")
    _dump_s6(
        m, "S6a",
        effects_before_reconcile=before_effects,
        effects_after_reconcile=effects_after_reconcile,
        permits_before_reconcile=permits_before,
        permits_after_reconcile=permits_after_reconcile,
        result=result,
        assertions=assertions,
        extra={"a2_admission_disposition": a2.disposition.value},
    )


def test_s6b_reconcile_non_execution_releases_effect_lock_independent_of_retry_annotation():
    m, _ = _prepare_unknown(apply_effect=False)
    assert m.attempts["A1"].effect_observed is False
    before_effects = len(m.sink.effects)
    permits_before = _permit_snapshot(m)
    a1_permit_consumed_before = m.permits["A1"].consumed

    result = m.reconcile(
        attempt_id="A1",
        evidence=_evidence(
            "E-S6B-FAILED-NO-EFFECT",
            "FAILED",
            non_execution_confirmed=True,
        ),
        retry_eligible=False,
    )
    effects_after_reconcile = len(m.sink.effects)
    permits_after_reconcile = _permit_snapshot(m)

    assert result.disposition.value == "HOLD"
    assert result.client_state == "FAILED"
    assert m.attempts["A1"].state == AttemptState.FAILED
    assert m.attempts["A1"].qualified is True
    assert m.attempts["A1"].effect_observed is False
    assert m.attempts["A1"].retry_eligible is False
    assert len(m.sink.effects) == before_effects
    assert _permit_snapshot(m) == permits_before
    assert m.permits["A1"].consumed is a1_permit_consumed_before is True
    assert m.retry_eligible_for("L") is True
    assert "RECONCILIATION_FAILURE_CONFIRMED_NON_EXECUTION" in [e["event"] for e in m.events]

    # A2 gets a distinct permit through normal admission even though retry_eligible is false.
    a2 = m.admit_and_await_qualification(
        lei="L", attempt_id="A2", payload=PAYLOAD, apply_effect=False, nonce="n-s6-a2"
    )
    assert a2.kernel_decision != "NOT_EVALUATED"
    assert "A2" in m.attempts
    assert "A2" in m.permits and "A1" in m.permits
    assert m.permits["A2"].attempt_id == "A2"
    assert m.permits["A1"].consumed is True
    assert m.permits["A2"] is not m.permits["A1"]
    assert len(m.sink.effects) == before_effects

    assertions = {
        "A1_api_decision": result.kernel_decision == "RECONCILIATION_FAILURE_CONFIRMED_NON_EXECUTION",
        "A2_terminal_state": m.attempts["A1"].state == AttemptState.FAILED,
        "A3_effect_delta_zero": effects_after_reconcile - before_effects == 0,
        "A4_canonical_event": "RECONCILIATION_FAILURE_CONFIRMED_NON_EXECUTION" in [e["event"] for e in m.events],
        "A5_permit_isolation": permits_after_reconcile == permits_before and permits_after_reconcile["A1"]["consumed"],
        "A6_failed_no_effect_unlocks_even_retry_annotation_false": m.attempts["A1"].retry_eligible is False and "A2" in m.attempts,
        "A7_claim_scope": "tested sequential interleavings only",
    }
    assert all(value is True for key, value in assertions.items() if key != "A7_claim_scope")
    _dump_s6(
        m, "S6b",
        effects_before_reconcile=before_effects,
        effects_after_reconcile=effects_after_reconcile,
        permits_before_reconcile=permits_before,
        permits_after_reconcile=permits_after_reconcile,
        result=result,
        assertions=assertions,
        extra={"a2_admission_disposition": a2.disposition.value,
               "a2_permit_is_distinct": m.permits["A2"] is not m.permits["A1"]},
    )


def test_s6b_without_explicit_non_execution_proof_stays_unknown_and_locked():
    m, _ = _prepare_unknown(apply_effect=False)
    effects_before = len(m.sink.effects)
    permits_before = _permit_snapshot(m)

    result = m.reconcile(
        attempt_id="A1",
        evidence=_evidence("E-S6B-UNPROVEN", "FAILED", non_execution_confirmed=False),
    )

    assert result.disposition.value == "HOLD"
    assert result.kernel_decision == "RECONCILIATION_NO_NON_EXECUTION_PROOF"
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert m.retry_eligible_for("L") is False
    assert len(m.sink.effects) == effects_before
    assert _permit_snapshot(m) == permits_before
    assert "RECONCILIATION_REJECTED_NO_NON_EXECUTION_PROOF" in [e["event"] for e in m.events]


def test_s6b_negative_evidence_cannot_override_locally_observed_effect():
    m, _ = _prepare_unknown(apply_effect=True)
    effects_before = len(m.sink.effects)
    permits_before = _permit_snapshot(m)

    result = m.reconcile(
        attempt_id="A1",
        evidence=_evidence("E-S6B-CONTRADICTS-EFFECT", "FAILED",
                           non_execution_confirmed=True),
    )

    assert result.disposition.value == "HOLD"
    assert result.kernel_decision == "RECONCILIATION_CONTRADICTS_OBSERVED_EFFECT"
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert m.attempts["A1"].effect_observed is True
    assert m.retry_eligible_for("L") is False
    assert len(m.sink.effects) == effects_before
    assert _permit_snapshot(m) == permits_before
    assert "RECONCILIATION_NEGATIVE_CONTRADICTS_OBSERVED_EFFECT" in [e["event"] for e in m.events]


def test_s6_reconciliation_requires_strict_attempt_lei_nonce_binding():
    m, _ = _prepare_unknown(apply_effect=False)
    before_state = m.attempts["A1"].state
    before_effects = len(m.sink.effects)
    before_permits = _permit_snapshot(m)

    with pytest.raises(BindingError):
        m.reconcile(
            attempt_id="A1",
            evidence=_evidence("E-S6-BAD-LEI", "COMMITTED", lei="WRONG"),
        )

    assert m.attempts["A1"].state == before_state
    assert len(m.sink.effects) == before_effects
    assert _permit_snapshot(m) == before_permits


def test_s6_reconciliation_is_idempotent_and_terminal_conflict_fails_closed():
    m, _ = _prepare_unknown(apply_effect=True)
    committed = _evidence("E-S6-IDEMPOTENT-COMMITTED", "COMMITTED")
    first = m.reconcile(attempt_id="A1", evidence=committed)
    assert first.client_state == "RESOLVED"
    effects_after_first = len(m.sink.effects)
    permits_after_first = _permit_snapshot(m)

    repeated = m.reconcile(attempt_id="A1", evidence=committed)
    assert repeated.kernel_decision == "RECONCILIATION_IDEMPOTENT_ACK"
    assert m.attempts["A1"].state == AttemptState.RESOLVED
    assert len(m.sink.effects) == effects_after_first
    assert _permit_snapshot(m) == permits_after_first

    conflicting = m.reconcile(
        attempt_id="A1",
        evidence=_evidence(
            "E-S6-TERMINAL-CONFLICT",
            "FAILED",
            non_execution_confirmed=True,
        ),
    )
    assert conflicting.disposition.value == "HOLD"
    assert conflicting.kernel_decision == "EVIDENCE_CONTRADICTION"
    assert m.attempts["A1"].state == AttemptState.RESOLVED
    assert len(m.sink.effects) == effects_after_first
    assert m.governance_quarantine["L"]["state"] == "QUARANTINED"
    assert m.permits["A1"].revoked is True
    assert _permit_snapshot(m) != permits_after_first
    assert "EVIDENCE_CONTRADICTION" in [e["event"] for e in m.events]


def test_s6_spec_and_scenario_are_versioned_and_hashed():
    assert len(_spec_sha256()) == 64
    assert len(_scenario_sha256()) == 64
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    assert scenario["id"] == "G0_S6"
    assert scenario["api_target"] == "reconcile"
    assert scenario["assertions"] == ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]
    assert "non_execution_confirmed" in scenario["subcases"]["S6b"]["expected"]
    assert "retry_eligible is annotation only" in scenario["subcases"]["S6b"]["expected"]

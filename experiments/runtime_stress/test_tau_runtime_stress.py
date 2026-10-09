"""Tests for the isolated runtime stress-rig prototype."""
import asyncio

from experiments.runtime_stress.tau_runtime_stress import (
    EVPProof,
    MutableClock,
    TAURuntimeStressRig,
    run_stress_suite,
)


def test_four_stress_scenarios_have_expected_oracles():
    result = asyncio.run(run_stress_suite())
    assert result["mode"] == "synthetic simulation; not production integration"
    assert result["scenario_count"] == 4
    assert result["passed_count"] == 4
    assert result["all_passed"] is True
    assert {item["case_id"] for item in result["scenarios"]} == {
        "replay_concurrent",
        "tau_k_expiry",
        "cross_realm_contradiction",
        "hidden_effect_epistemic_limit",
    }


def test_invalid_and_misbound_proofs_are_rejected():
    async def scenario():
        clock = MutableClock()
        rig = TAURuntimeStressRig(clock=clock)
        attempt, reason = await rig.admit_attempt("LEI-PROOF", "PERMIT-PROOF")
        assert attempt is not None and reason == "ADMITTED"

        mismatch = await rig.process_evp_attestation(
            "LEI-PROOF",
            attempt.attempt_id,
            EVPProof("PROOF-MISMATCH", "LEI-OTHER", attempt.attempt_id,
                     "Realm-Alpha", True, clock()),
        )
        invalid = await rig.process_evp_attestation(
            "LEI-PROOF",
            attempt.attempt_id,
            EVPProof("PROOF-INVALID", "LEI-PROOF", attempt.attempt_id,
                     "Realm-Alpha", True, clock(), valid_signature=False),
        )
        assert mismatch == "PROOF_BINDING_MISMATCH"
        assert invalid == "INVALID_SIGNATURE"
        assert attempt.evidence == []

    asyncio.run(scenario())


def test_permit_is_not_consumed_by_expired_request():
    async def scenario():
        clock = MutableClock(101.0)
        rig = TAURuntimeStressRig(tau_k_window_seconds=0.2, clock=clock)
        attempt, reason = await rig.admit_attempt(
            "LEI-EXPIRED", "PERMIT-REUSABLE", request_time=100.0
        )
        assert attempt is None
        assert reason == "TAU_K_EXPIRED"
        assert "PERMIT-REUSABLE" not in rig.consumed_permits

        fresh, fresh_reason = await rig.admit_attempt(
            "LEI-EXPIRED", "PERMIT-REUSABLE", request_time=clock()
        )
        assert fresh is not None
        assert fresh_reason == "ADMITTED"

    asyncio.run(scenario())

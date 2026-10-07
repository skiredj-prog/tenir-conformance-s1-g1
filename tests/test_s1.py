"""Pytest suite for S1 G0 assertions against the G1 harness."""

from pathlib import Path
import json
import hashlib
import pytest

from tenir_conformance.s1_harness import FAULT_CASES, run_case


@pytest.mark.parametrize("case_id", ["S1a", "S1b", "S1c"])
def test_s1_retry_is_held_for_all_subcases(case_id: str):
    result = run_case(FAULT_CASES[case_id])

    assert result["exec"] == "UNKNOWN"
    assert result["recon"] == "PENDING"
    assert result["client_response"] == "HOLD"
    assert result["permit_issued_for_retry"] is False

    assert (
        result["oracle"]["final_effect_count"]
        == result["oracle"]["baseline_effect_count"]
    )
    assert (
        result["oracle"]["final_permit_count"]
        == result["oracle"]["baseline_permit_count"]
    )

    events = result["transition_events"]
    assert "T3_ReceiptLost" in events
    assert "T1_guard_FALSE" in events
    assert events.index("T3_ReceiptLost") < events.index("T1_guard_FALSE")


def test_s1_client_cannot_distinguish_target_truth_on_retry():
    """Client projection must be identical for S1a / S1b / S1c."""
    a = run_case(FAULT_CASES["S1a"])
    b = run_case(FAULT_CASES["S1b"])
    c = run_case(FAULT_CASES["S1c"])

    def client_projection(r):
        return {
            "exec": r["exec"],
            "recon": r["recon"],
            "client_response": r["client_response"],
            "permit_issued_for_retry": r["permit_issued_for_retry"],
            "client_observation": r["oracle"]["client_observation"],
        }

    assert client_projection(a) == client_projection(b) == client_projection(c)


def test_s1b_preserves_existing_effect():
    result = run_case(FAULT_CASES["S1b"])
    assert result["oracle"]["baseline_effect_count"] == 1
    assert result["oracle"]["final_effect_count"] == 1


def test_scenario_definition_hash_is_present():
    scenario = Path(__file__).parents[1] / "scenarios" / "S1.json"
    assert scenario.exists()
    payload = json.loads(scenario.read_text(encoding="utf-8"))
    assert payload["id"] == "S1"
    assert payload["title"] == "Evidence Lost After Commit"

    sha = hashlib.sha256(scenario.read_bytes()).hexdigest()
    assert len(sha) == 64

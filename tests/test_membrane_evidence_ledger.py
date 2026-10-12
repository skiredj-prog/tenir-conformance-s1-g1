"""Membrane evidence_registry is mirrored in a hash-chained ledger (RFC-4 section 4.2, CT-R4-008).

Each recorded attestation, verified or not, is appended to the ledger. verify_evidence_registry()
detects edits to the chain and any divergence between the registry and the ledger.
"""

import pytest

from tenir_conformance.membrane import BindingError
from test_non_execution_attested_conformance import ATTEMPT, _failed_evidence, _unknown_no_effect


def _one_verified_entry():
    m, _ = _unknown_no_effect()
    m.reconcile(attempt_id=ATTEMPT, evidence=_failed_evidence(non_execution_confirmed=True))
    assert len(m.evidence_registry) == 1
    return m


def test_verified_attestation_is_recorded_in_the_chain():
    m = _one_verified_entry()
    assert len(m.evidence_ledger.entries) == 1
    assert m.evidence_registry[0]["status"] == "verified"
    assert m.verify_evidence_registry() == (True, None)


def test_rejected_attestation_is_also_chained():
    m, _ = _unknown_no_effect()
    with pytest.raises(BindingError):
        m.reconcile(
            attempt_id=ATTEMPT,
            evidence=_failed_evidence(non_execution_confirmed=True, nonce="n-wrong-binding"),
        )
    assert len(m.evidence_registry) == len(m.evidence_ledger.entries)
    assert m.verify_evidence_registry() == (True, None)


def test_editing_a_registry_entry_is_detected():
    m = _one_verified_entry()
    m.evidence_registry[0]["status"] = "unverified"
    assert m.verify_evidence_registry() == (False, 0)


def test_deleting_a_registry_entry_is_detected():
    m = _one_verified_entry()
    del m.evidence_registry[0]
    assert m.verify_evidence_registry() == (False, 0)


def test_editing_a_ledger_record_is_detected_by_the_chain():
    m = _one_verified_entry()
    m.evidence_ledger.entries[0]["record"]["status"] = "unverified"
    assert m.verify_evidence_registry() == (False, 0)


def test_nested_edit_is_caught_by_the_cross_check_not_only_the_chain():
    m = _one_verified_entry()
    # The ledger is a deep copy, so the chain stays internally consistent...
    assert m.evidence_ledger.verify() == (True, None)
    # ...but the registry no longer matches the recorded entry.
    m.evidence_registry[0]["submitted_against"]["lei"] = "OTHER"
    assert m.evidence_ledger.verify() == (True, None)
    assert m.verify_evidence_registry() == (False, 0)

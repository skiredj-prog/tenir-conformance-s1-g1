"""CT-R4-008 (RFC-4 section 4): an evidence manifest altered after closure fails verification.

Covers the chain property of EvidenceLedger. Tail truncation is only detectable against
an externally anchored head; that limit is asserted explicitly below.
"""

from copy import deepcopy

from tenir_conformance.membrane.evidence_ledger import GENESIS, EvidenceLedger, _entry_hash


def _ledger(n: int = 3) -> EvidenceLedger:
    ledger = EvidenceLedger()
    for i in range(n):
        ledger.append({"evidence_id": f"E{i}", "value": i})
    return ledger


def test_intact_ledger_verifies_and_head_is_last_hash():
    ledger = _ledger()
    assert ledger.verify() == (True, None)
    assert ledger.head() == ledger.entries[-1]["hash"]
    assert ledger.head() != GENESIS


def test_empty_ledger_verifies_at_genesis():
    ledger = EvidenceLedger()
    assert ledger.head() == GENESIS
    assert ledger.verify() == (True, None)


def test_altered_record_fails_at_its_position():
    ledger = _ledger()
    ledger.entries[1]["record"]["value"] = 999
    assert ledger.verify() == (False, 1)


def test_recomputed_hash_after_edit_still_breaks_the_next_entry():
    ledger = _ledger()
    ledger.entries[0]["record"]["value"] = 999
    # The attacker recomputes entry 0's own hash; entry 1 still commits to the old hash.
    ledger.entries[0]["hash"] = _entry_hash(GENESIS, ledger.entries[0]["record"])
    assert ledger.verify() == (False, 1)


def test_reordered_entries_fail_at_first_swapped_position():
    ledger = _ledger()
    ledger.entries[0], ledger.entries[1] = ledger.entries[1], ledger.entries[0]
    assert ledger.verify() == (False, 0)


def test_removed_middle_entry_fails_at_the_gap():
    ledger = _ledger()
    del ledger.entries[1]
    assert ledger.verify() == (False, 1)


def test_truncated_tail_is_undetectable_without_anchor_and_detected_with_it():
    ledger = _ledger()
    anchored_head = ledger.head()
    del ledger.entries[-1]
    # Limit asserted explicitly: the chain alone accepts a truncated tail.
    assert ledger.verify() == (True, None)
    # With the externally anchored head, the truncation is detected.
    assert ledger.verify(expected_head=anchored_head) == (False, len(ledger.entries))


def test_forged_tail_with_recomputed_hash_is_detected_by_anchor():
    ledger = _ledger()
    anchored_head = ledger.head()
    forged = deepcopy(ledger)
    forged.entries[-1]["record"]["value"] = 999
    forged.entries[-1]["hash"] = _entry_hash(forged.entries[-1]["prev"], forged.entries[-1]["record"])
    # The forged tail is internally consistent, so the chain alone accepts it...
    assert forged.verify() == (True, None)
    # ...but the externally anchored head exposes it.
    assert forged.verify(expected_head=anchored_head) == (False, len(forged.entries))

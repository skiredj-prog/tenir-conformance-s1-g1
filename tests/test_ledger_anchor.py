"""Anchored verification of the evidence ledger (RFC-4 section 4.2, CT-R4-008).

Publishing the head at a checkpoint makes tail truncation detectable, which the chain
alone cannot do. These tests fix the anchor format and its three outcomes.
"""

import pytest

from tenir_conformance.membrane.evidence_ledger import (
    ANCHOR_FORMAT,
    EvidenceLedger,
    anchor,
    verify_against_anchor,
)


def _ledger(n: int = 3) -> EvidenceLedger:
    ledger = EvidenceLedger()
    for i in range(n):
        ledger.append({"evidence_id": f"E{i}", "value": i})
    return ledger


def test_anchor_of_intact_ledger_records_head_and_length():
    ledger = _ledger()
    published = anchor(ledger)
    assert published == {"format": ANCHOR_FORMAT, "head": ledger.head(), "length": 3}


def test_anchor_refuses_a_broken_ledger():
    ledger = _ledger()
    ledger.entries[1]["record"]["value"] = 999
    with pytest.raises(ValueError, match="position 1"):
        anchor(ledger)


def test_intact_ledger_verifies_against_its_anchor():
    ledger = _ledger()
    assert verify_against_anchor(ledger, anchor(ledger)) == (True, None)


def test_truncation_after_anchoring_is_detected():
    ledger = _ledger()
    published = anchor(ledger)
    del ledger.entries[-1]
    # Without the anchor the shorter chain looks valid; with it, the truncation is caught.
    assert ledger.verify() == (True, None)
    assert verify_against_anchor(ledger, published) == (False, 2)


def test_extension_after_anchoring_is_detected():
    ledger = _ledger()
    published = anchor(ledger)
    ledger.append({"evidence_id": "E3", "value": 3})
    assert verify_against_anchor(ledger, published) == (False, 4)


def test_unknown_anchor_format_is_rejected():
    ledger = _ledger()
    with pytest.raises(ValueError, match="unsupported anchor format"):
        verify_against_anchor(ledger, {"format": "other/v9", "head": ledger.head()})

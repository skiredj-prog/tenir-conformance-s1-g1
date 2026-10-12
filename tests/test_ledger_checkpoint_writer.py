"""write_checkpoint: one call produces a private entries file and a public anchor file."""

import json
import os

import pytest

from tenir_conformance.membrane.evidence_ledger import EvidenceLedger, load, verify_against_anchor, write_checkpoint


def _ledger(n: int = 3) -> EvidenceLedger:
    ledger = EvidenceLedger()
    for i in range(n):
        ledger.append({"evidence_id": f"E{i}", "value": i})
    return ledger


def test_checkpoint_writes_entries_and_anchor_with_matching_names(tmp_path):
    result = write_checkpoint(_ledger(), str(tmp_path), "2026-10-12")
    assert os.path.basename(result["entries"]) == "2026-10-12-3.entries.json"
    assert os.path.basename(result["anchor"]) == "2026-10-12-3.anchor.json"
    anchor_on_disk = json.loads(open(result["anchor"], encoding="utf-8").read())
    assert anchor_on_disk == {"format": result["format"], "head": result["head"], "length": 3}


def test_published_anchor_verifies_the_private_entries(tmp_path):
    result = write_checkpoint(_ledger(), str(tmp_path), "2026-10-12")
    published = json.loads(open(result["anchor"], encoding="utf-8").read())
    reloaded = load(result["entries"])
    assert verify_against_anchor(reloaded, published) == (True, None)


def test_broken_ledger_writes_nothing(tmp_path):
    ledger = _ledger()
    ledger.entries[1]["record"]["value"] = 999
    target = tmp_path / "checkpoints"
    with pytest.raises(ValueError, match="position 1"):
        write_checkpoint(ledger, str(target), "2026-10-12")
    assert not target.exists()


@pytest.mark.parametrize("stamp", ["2026-10", "12-10-2026", "2026-10-12/../x", "latest"])
def test_stamp_must_be_a_calendar_date(tmp_path, stamp):
    with pytest.raises(ValueError, match="stamp must be YYYY-MM-DD"):
        write_checkpoint(_ledger(), str(tmp_path), stamp)
    assert list(tmp_path.iterdir()) == []

"""Checkpoint: export a real membrane ledger, reload it, and produce a verifiable anchor."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tenir_conformance.membrane.evidence_ledger import anchor, dump, load, verify_against_anchor
from test_non_execution_attested_conformance import ATTEMPT, _failed_evidence, _unknown_no_effect

ROOT = Path(__file__).resolve().parents[1]


def _membrane_with_entry():
    m, _ = _unknown_no_effect()
    m.reconcile(attempt_id=ATTEMPT, evidence=_failed_evidence(non_execution_confirmed=True))
    assert len(m.evidence_ledger.entries) == 1
    return m


def test_real_membrane_ledger_survives_dump_and_load(tmp_path):
    m = _membrane_with_entry()
    path = tmp_path / "entries.json"
    dump(m.evidence_ledger, str(path))
    reloaded = load(str(path))
    assert reloaded.head() == m.evidence_ledger.head()
    assert reloaded.verify() == (True, None)


def test_anchor_from_reloaded_checkpoint_verifies_the_original(tmp_path):
    m = _membrane_with_entry()
    path = tmp_path / "entries.json"
    dump(m.evidence_ledger, str(path))
    published = anchor(load(str(path)))
    assert verify_against_anchor(m.evidence_ledger, published) == (True, None)


def test_tampered_checkpoint_file_is_refused_by_the_tool(tmp_path):
    m = _membrane_with_entry()
    path = tmp_path / "entries.json"
    dump(m.evidence_ledger, str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["record"]["status"] = "unverified"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "checkpoint_ledger.py"), str(path)],
        capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 1
    assert "refused" in result.stderr
    assert result.stdout == ""


def test_checkpoint_tool_prints_the_anchor_for_an_intact_file(tmp_path):
    m = _membrane_with_entry()
    path = tmp_path / "entries.json"
    dump(m.evidence_ledger, str(path))
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "checkpoint_ledger.py"), str(path)],
        capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == anchor(load(str(path)))


def test_unsupported_entries_format_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"format": "other/v9", "entries": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported entries format"):
        load(str(path))

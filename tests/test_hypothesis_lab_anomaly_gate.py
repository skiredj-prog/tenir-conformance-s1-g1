"""Hypothesis Lab anomaly gate.

The Lab is non-blocking by design: an adversarial model that FAILs as expected is a result,
not a failure. This test is the separate signal. It fails only when a verdict diverges from
the expectation recorded in hypothesis_lab/expected_adversarial.json, i.e. an expected FAIL
became PASS (or the reverse), which the Lab reports as ANOMALY.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_lab(expected_path=None):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    cmd = [sys.executable, str(ROOT / "hypothesis_lab" / "run_lab.py")]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env, timeout=600)


def test_every_hypothesis_matches_its_expectation():
    result = _run_lab()
    assert result.returncode == 0, result.stderr
    rows = [line for line in result.stdout.splitlines() if "expected=" in line]
    assert len(rows) == 13, f"expected 13 verdict rows, got {len(rows)}"
    anomalies = [row for row in rows if not row.rstrip().endswith("[OK]")]
    assert anomalies == [], "ANOMALY: verdict diverged from expectation:\n" + "\n".join(anomalies)


def test_verdict_distribution_matches_the_reported_profile():
    result = _run_lab()
    rows = [line for line in result.stdout.splitlines() if "expected=" in line]
    counts = {}
    for row in rows:
        status = row[1:row.index("]")].strip()
        counts[status] = counts.get(status, 0) + 1
    assert counts == {"FAIL": 7, "PASS": 5, "VACUOUS": 1}, counts

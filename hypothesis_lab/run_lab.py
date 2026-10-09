#!/usr/bin/env python3
"""REG Hypothesis Lab — non-blocking CI entrypoint.

Adversarial FAIL is an expected finding, not a runner failure.
Regression: expected FAIL becomes PASS/missing counterexample → ANOMALY.
Exit code is always 0 unless the lab tooling itself crashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from models.s12_cross_realm import run_s12_suite
from models.s11_transition_binding import run_s11_suite
from models.s8_concurrent_admission import run_s8_suite
from models.h4_signature_standing import run_h4_suite

EXPECTED_PATH = ROOT / "expected_adversarial.json"
OUT_DIR = Path(os.environ.get("HYPOTHESIS_LAB_OUT", ROOT / "artifacts"))
OUT_DIR.mkdir(parents=True, exist_ok=True)


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return os.environ.get("GITHUB_SHA", "unknown")


def subsequence_present(trace_actions: list[str], required: list[str]) -> bool:
    if not required:
        return True
    it = iter(trace_actions)
    for need in required:
        for a in it:
            if a == need:
                break
        else:
            return False
    return True


def main() -> int:
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    results = []
    results.extend(run_s12_suite())
    results.extend(run_s11_suite())
    results.extend(run_s8_suite())
    results.extend(run_h4_suite())

    anomalies: list[dict] = []
    rows = []
    for r in results:
        exp = expected["hypotheses"].get(r.hypothesis_id, {})
        exp_status = exp.get("expected_status")
        req = exp.get("required_actions_subsequence", [])
        actions = [s.action for s in (r.counterexample or [])]
        status_ok = exp_status is None or r.status == exp_status
        trace_ok = True
        if r.status == "FAIL" and req:
            trace_ok = subsequence_present(actions, req)
        if exp_status == "FAIL" and r.status != "FAIL":
            anomalies.append({
                "hypothesis_id": r.hypothesis_id,
                "kind": "EXPECTED_FAIL_MISSING",
                "got": r.status,
                "detail": "Adversarial model no longer produces a counterexample",
            })
        elif r.status == "FAIL" and req and not trace_ok:
            anomalies.append({
                "hypothesis_id": r.hypothesis_id,
                "kind": "COUNTEREXAMPLE_SHAPE_CHANGED",
                "got_actions": actions,
                "required_subsequence": req,
            })
        rows.append({
            **r.to_dict(),
            "expected_status": exp_status,
            "status_matches_expected": status_ok and (trace_ok if r.status == "FAIL" else True),
        })

    report = {
        "schema": "reg-hypothesis-lab-report/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "exploration": {
            "order": ["S12", "S11", "S8", "H4"],
            "completeness": "finite explicit-state BFS",
        },
        "verdicts": {
            "model": {
                "fail": sum(1 for r in results if r.status == "FAIL"),
                "pass": sum(1 for r in results if r.status == "PASS"),
                "vacuous": sum(1 for r in results if r.status == "VACUOUS"),
                "inconclusive": sum(1 for r in results if r.status == "INCONCLUSIVE"),
            },
            "adversarial_regression_anomalies": anomalies,
            "conformance": "NOT_EVALUATED_IN_THIS_STEP",
            "workflow_global": "NON_BLOCKING_LAB_STEP",
            "production_conformance_claim": False,
        },
        "results": rows,
        "expected_spec_sha256": hashlib.sha256(EXPECTED_PATH.read_bytes()).hexdigest(),
        "notes": [
            "Adversarial FAIL is an expected finding, not a CI product failure.",
            "Do not interpret model PASS as production REG conformance.",
            "Implementation evidence remains the tenir-conformance pytest suite.",
        ],
    }

    report_path = OUT_DIR / "hypothesis_lab_report.json"
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
    report_path.write_text(report_bytes.decode("utf-8"), encoding="utf-8")
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    (OUT_DIR / "hypothesis_lab_report.sha256").write_text(
        f"{report_sha}  hypothesis_lab_report.json\n", encoding="utf-8"
    )

    print("=" * 72)
    print("REG HYPOTHESIS LAB (non-blocking)")
    print(f"commit={report['git_commit']}")
    print("=" * 72)
    for row in rows:
        flag = "OK" if row["status_matches_expected"] else "ANOMALY"
        print(f"[{row['status']:12}] {row['hypothesis_id']:28} expected={row['expected_status']} [{flag}]")
        if row.get("counterexample"):
            acts = [c["action"] for c in row["counterexample"]]
            print(f"    trace: {' → '.join(acts)}")
    print("-" * 72)
    print(
        f"model: FAIL={report['verdicts']['model']['fail']} "
        f"PASS={report['verdicts']['model']['pass']} "
        f"VACUOUS={report['verdicts']['model']['vacuous']}"
    )
    print(f"anomalies: {len(anomalies)}")
    print(f"conformance: {report['verdicts']['conformance']}")
    print(f"workflow: {report['verdicts']['workflow_global']}")
    print(f"production_claim: {report['verdicts']['production_conformance_claim']}")
    print(f"report_sha256: {report_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""S1 evidence generator — writes raw artifacts for a single harness run."""

from pathlib import Path
import json
import hashlib
from datetime import datetime, timezone

from tenir_conformance.s1_harness import FAULT_CASES, run_case

ROOT = Path(__file__).parents[1]
SCENARIO = ROOT / "scenarios" / "S1.json"
OUT = ROOT / "artifacts" / "s1" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenario_sha = sha256_file(SCENARIO)

    all_results = {}
    for case_id, case in FAULT_CASES.items():
        result = run_case(case)
        all_results[case_id] = result

        case_dir = OUT / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        (case_dir / "transition.jsonl").write_text(
            "".join(
                json.dumps(e, sort_keys=True) + "\n"
                for e in result["transition_log"]
            ),
            encoding="utf-8",
        )
        (case_dir / "effect_sink.json").write_text(
            json.dumps(result["effect_sink"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (case_dir / "permit_log.json").write_text(
            json.dumps(result["permit_log"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (case_dir / "summary.json").write_text(
            json.dumps(
                {
                    "scenario": "S1",
                    "subcase": case_id,
                    "exec": result["exec"],
                    "recon": result["recon"],
                    "client_response": result["client_response"],
                    "target_truth": result["target_truth"],
                },
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

    (OUT / "scenario.json").write_bytes(SCENARIO.read_bytes())
    (OUT / "scenario.sha256").write_text(scenario_sha + "\n", encoding="utf-8")
    (OUT / "summary.json").write_text(
        json.dumps(
            {
                "scenario": "S1",
                "definition_sha256": scenario_sha,
                "subcases": {
                    k: {
                        "exec": v["exec"],
                        "recon": v["recon"],
                        "client_response": v["client_response"],
                    }
                    for k, v in all_results.items()
                },
                "status": "HARNESS_RUN_ONLY__NOT_A_CLAIM_OF_PRODUCTION_VALIDATION",
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"Evidence written to: {OUT}")
    print(f"Scenario SHA-256: {scenario_sha}")
    print("Status: HARNESS_RUN_ONLY — not a claim of REG/production validation")


if __name__ == "__main__":
    main()

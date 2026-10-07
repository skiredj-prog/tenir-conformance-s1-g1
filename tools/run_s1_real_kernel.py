#!/usr/bin/env python3
"""Generate evidence from the RFC-4 membrane backed by the real TENIR PolicyEngine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from tenir_conformance.membrane import KernelBridge, Membrane

ROOT = Path(__file__).parents[1]
SCENARIO = ROOT / "scenarios" / "S1.json"
OUT = ROOT / "artifacts" / "s1-real-kernel" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
EXPECTED_SCORE = 3.999984000064


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result_dict(result):
    return {
        "client_state": result.client_state,
        "disposition": result.disposition.value,
        "receipt_observed": result.receipt_observed,
        "effect_count": result.effect_count,
        "kernel_score": result.kernel_score,
        "kernel_decision": result.kernel_decision,
        "retry_permit_issued": result.retry_permit_issued,
    }


def write_case(case_id: str, membrane: Membrane, first, retry) -> None:
    case_dir = OUT / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    attempt = membrane.attempts["A"]
    permit = membrane.permits["A"]
    events = [
        {
            "event": "T1_PERMIT_ISSUED",
            "lei": "L",
            "attempt_id": "A",
            "consumed": permit.consumed,
        },
        {
            "event": "T2_KERNEL_EVALUATED",
            "lei": "L",
            "attempt_id": "A",
            "kernel_score": first.kernel_score,
            "kernel_decision": first.kernel_decision,
        },
        {
            "event": "T3_ATTEMPT_STATE",
            "lei": "L",
            "attempt_id": "A",
            "state": attempt.state.value,
            "effect_observed": attempt.effect_observed,
            "receipt_observed": attempt.receipt_observed,
        },
        {
            "event": "T4_RETRY_GUARD",
            "lei": "L",
            "attempt_id": "A-retry",
            "result": "BLOCKED",
            "client_state": retry.client_state,
            "disposition": retry.disposition.value,
            "kernel_evaluated": retry.kernel_decision != "NOT_EVALUATED",
        },
    ]
    (case_dir / "transition.jsonl").write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in events),
        encoding="utf-8",
    )
    (case_dir / "effect_sink.json").write_text(
        json.dumps({"count": len(membrane.sink.effects), "entries": membrane.sink.effects}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (case_dir / "permit.json").write_text(
        json.dumps({"lei": permit.lei, "attempt_id": permit.attempt_id, "consumed": permit.consumed}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (case_dir / "result.json").write_text(
        json.dumps({"first": result_dict(first), "retry": result_dict(retry)}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_case(case_id: str):
    membrane = Membrane(KernelBridge())
    kwargs = {
        "S1a": dict(request_lost=True, receipt_lost=False, target_rejected=False),
        "S1b": dict(request_lost=False, receipt_lost=True, target_rejected=False),
        "S1c": dict(request_lost=False, receipt_lost=True, target_rejected=True),
    }[case_id]
    first = membrane.process_transaction(lei="L", attempt_id="A", payload=PAYLOAD, **kwargs)
    retry = membrane.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert first.client_state == "UNKNOWN"
    assert first.disposition.value == "HOLD"
    assert retry.client_state == "UNKNOWN"
    assert retry.disposition.value == "HOLD"
    assert abs(first.kernel_score - EXPECTED_SCORE) < 1e-9
    assert first.kernel_decision == "allow"
    assert retry.kernel_decision == "NOT_EVALUATED"
    return membrane, first, retry


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenario_sha = sha256_file(SCENARIO)
    cases = {}

    for case_id in ("S1a", "S1b", "S1c"):
        membrane, first, retry = run_case(case_id)
        write_case(case_id, membrane, first, retry)
        cases[case_id] = {"first": result_dict(first), "retry": result_dict(retry)}

    (OUT / "scenario.json").write_bytes(SCENARIO.read_bytes())
    (OUT / "scenario.sha256").write_text(scenario_sha + "\n", encoding="utf-8")
    summary = {
        "scenario": "S1",
        "definition_sha256": scenario_sha,
        "subject": "RFC-4 membrane backed by reference TENIR PolicyEngine",
        "kernel_payload": PAYLOAD,
        "expected_kernel_score": EXPECTED_SCORE,
        "subcases": cases,
        "status": "EMPIRICAL_MEMBRANE_RUN__NOT_A_PRODUCTION_CONFORMANCE_CLAIM",
        "claim_boundary": "PolicyEngine supplies scoring/admissibility only; RFC-4 permit/attempt/retry state is owned by the membrane.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Real-kernel evidence written to: {OUT}")
    print(f"Scenario SHA-256: {scenario_sha}")
    print("Status: empirical membrane run — not a production conformance claim")


if __name__ == "__main__":
    main()

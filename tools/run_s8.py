"""Generate reproducible G0 S8 concurrency evidence for CI."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

from tenir_conformance.membrane import KernelBridge, Membrane

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
REPEAT_COUNT = 100
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "s8"
SCENARIO = ROOT / "scenarios" / "G0_S8_CONCURRENT_ADMISSION.md"


def snapshot(membrane: Membrane) -> dict:
    return {
        "attempts": {
            key: {
                "lei": value.lei,
                "state": value.state.value,
                "effect_observed": value.effect_observed,
                "qualified": value.qualified,
                "nonce": value.nonce,
            }
            for key, value in membrane.attempts.items()
        },
        "permits": {
            key: {
                "lei": value.lei,
                "attempt_id": value.attempt_id,
                "consumed": value.consumed,
                "revoked": value.revoked,
            }
            for key, value in membrane.permits.items()
        },
        "effects": list(membrane.sink.effects),
    }


def run_once(run_id: int, transition_lines: list[str], snapshot_lines: list[str]) -> dict:
    membrane = Membrane(KernelBridge())
    before = snapshot(membrane)
    trace: list[dict] = []
    trace_lock = threading.Lock()
    sequence = 0

    def record(kind: str, **fields) -> None:
        nonlocal sequence
        with trace_lock:
            sequence += 1
            trace.append({
                "run_id": run_id,
                "seq": sequence,
                "monotonic_ns": time.monotonic_ns(),
                "thread": threading.current_thread().name,
                "kind": kind,
                **fields,
            })

    original_log = membrane._log

    def traced_log(event: str, **fields) -> None:
        record("transition", event=event, **fields)
        original_log(event, **fields)

    membrane._log = traced_log

    original_register = membrane._register_attempt

    def traced_register(**kwargs):
        record("register_enter", attempt_id=kwargs.get("attempt_id"), lei=kwargs.get("lei"))
        try:
            attempt = original_register(**kwargs)
        except Exception as exc:
            record("register_rejected", attempt_id=kwargs.get("attempt_id"),
                   lei=kwargs.get("lei"), exception=type(exc).__name__, message=str(exc))
            raise
        record("register_return", attempt_id=attempt.attempt_id, lei=attempt.lei)
        return attempt

    membrane._register_attempt = traced_register

    original_guard = membrane._has_unresolved

    def traced_guard(lei: str) -> bool:
        record("guard_enter", lei=lei)
        unresolved = original_guard(lei)
        record("guard_return", lei=lei, unresolved=unresolved)
        return unresolved

    membrane._has_unresolved = traced_guard

    start = threading.Barrier(3)
    results: dict[str, dict] = {}
    exceptions: dict[str, str] = {}
    attempts = [("A1", "nonce-A1"), ("A2", "nonce-A2")]

    def worker(attempt_id: str, nonce: str) -> None:
        record("thread_ready", attempt_id=attempt_id, lei="L")
        try:
            start.wait(timeout=5)
            record("process_transaction_enter", attempt_id=attempt_id, lei="L")
            result = membrane.process_transaction(
                lei="L", attempt_id=attempt_id, payload=PAYLOAD, nonce=nonce
            )
            results[attempt_id] = {
                "disposition": result.disposition.value,
                "client_state": result.client_state,
                "kernel_decision": result.kernel_decision,
                "effect_count": result.effect_count,
            }
            record("process_transaction_return", attempt_id=attempt_id,
                   disposition=result.disposition.value, client_state=result.client_state)
        except BaseException as exc:
            exceptions[attempt_id] = f"{type(exc).__name__}: {exc}"
            record("thread_exception", attempt_id=attempt_id,
                   exception=type(exc).__name__, message=str(exc))
        finally:
            record("thread_exit", attempt_id=attempt_id)

    threads = [
        threading.Thread(target=worker, args=attempts[0], name="T1"),
        threading.Thread(target=worker, args=attempts[1], name="T2"),
    ]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)

    after = snapshot(membrane)
    thread_status = {
        thread.name: {"alive_after_join": thread.is_alive()}
        for thread in threads
    }
    event_counts: dict[str, int] = {}
    for event in membrane.events:
        name = event["event"]
        event_counts[name] = event_counts.get(name, 0) + 1

    passed = (
        not any(value["alive_after_join"] for value in thread_status.values())
        and not exceptions
        and len(results) == 2
        and len(after["attempts"]) == 1
        and len(after["permits"]) == 1
        and len(after["effects"]) <= 1
        and event_counts.get("T1_AttemptRegistered", 0) == 1
        and event_counts.get("T1_guard_FALSE", 0) == 1
        and sorted((r["client_state"], r["disposition"]) for r in results.values())
            == [("RESOLVED", "PASS"), ("UNKNOWN", "HOLD")]
    )

    for item in trace:
        transition_lines.append(json.dumps(item, sort_keys=True))
    snapshot_lines.append(json.dumps({
        "run_id": run_id,
        "before": before,
        "after": after,
        "results": results,
        "thread_status": thread_status,
        "exceptions": exceptions,
        "event_counts": event_counts,
        "passed": passed,
    }, sort_keys=True))

    return {
        "run_id": run_id,
        "passed": passed,
        "attempt_count": len(after["attempts"]),
        "permit_count": len(after["permits"]),
        "effect_count": len(after["effects"]),
        "exceptions": exceptions,
        "thread_status": thread_status,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenario_sha256 = hashlib.sha256(SCENARIO.read_bytes()).hexdigest()
    transition_lines: list[str] = []
    snapshot_lines: list[str] = []
    runs = [run_once(index, transition_lines, snapshot_lines)
            for index in range(1, REPEAT_COUNT + 1)]

    (OUT / "s8_transition_log.jsonl").write_text(
        "\n".join(transition_lines) + "\n", encoding="utf-8"
    )
    (OUT / "s8_registry_snapshots.jsonl").write_text(
        "\n".join(snapshot_lines) + "\n", encoding="utf-8"
    )
    summary = {
        "scenario": SCENARIO.name,
        "scenario_sha256": scenario_sha256,
        "source_sha": os.environ.get("GITHUB_SHA", "local-or-unspecified"),
        "repeat_count": REPEAT_COUNT,
        "passed_runs": sum(1 for run in runs if run["passed"]),
        "failed_runs": sum(1 for run in runs if not run["passed"]),
        "runs": runs,
        "scope": "single process, two threads, same LEI; not distributed concurrency",
    }
    (OUT / "s8_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "s8_scenario_sha256.txt").write_text(
        f"{scenario_sha256}  {SCENARIO.name}\n", encoding="utf-8"
    )
    print(json.dumps({
        "repeat_count": REPEAT_COUNT,
        "passed_runs": summary["passed_runs"],
        "failed_runs": summary["failed_runs"],
        "scenario_sha256": scenario_sha256,
    }, sort_keys=True))
    if summary["failed_runs"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

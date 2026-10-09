"""G0 S8 — bounded two-thread admission interleavings.

The barrier is placed after each thread has observed the same-LEI guard as
clear, but before either thread can register. This deterministically exposes
a check-then-act race without relying on scheduler luck.
"""
from __future__ import annotations

import threading
from collections import Counter

from tenir_conformance.membrane import KernelBridge, Membrane

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}


def test_s8a_barrier_synchronized_same_lei_admits_at_most_one(monkeypatch):
    membrane = Membrane(KernelBridge())
    both_checked = threading.Barrier(2)
    original_has_unresolved = membrane._has_unresolved

    def synchronized_guard(lei: str) -> bool:
        unresolved = original_has_unresolved(lei)
        lock = getattr(membrane, "_admission_lock", None)
        # Baseline: force both callers past the check before either registers.
        # Corrected implementation: do not wait inside the critical section,
        # otherwise the first thread would wait for a second thread blocked
        # on the same lock.
        if lei == "L" and not unresolved and not (lock is not None and lock.locked()):
            both_checked.wait(timeout=5)
        return unresolved

    monkeypatch.setattr(membrane, "_has_unresolved", synchronized_guard)
    start = threading.Barrier(3)
    results = {}
    exceptions = {}

    def worker(attempt_id: str, nonce: str) -> None:
        try:
            start.wait(timeout=5)
            results[attempt_id] = membrane.process_transaction(
                lei="L", attempt_id=attempt_id, payload=PAYLOAD, nonce=nonce
            )
        except BaseException as exc:
            exceptions[attempt_id] = repr(exc)

    threads = [
        threading.Thread(target=worker, args=("A1", "nonce-A1"), name="T1"),
        threading.Thread(target=worker, args=("A2", "nonce-A2"), name="T2"),
    ]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads), "thread did not terminate"
    assert exceptions == {}, f"thread exceptions: {exceptions}"
    assert set(results) == {"A1", "A2"}
    assert len(membrane.attempts) == 1, f"registered attempts: {list(membrane.attempts)}"
    permits_for_lei = [p for p in membrane.permits.values() if p.lei == "L"]
    assert len(permits_for_lei) == 1
    assert len(membrane.sink.effects) <= 1
    event_counts = Counter(e["event"] for e in membrane.events)
    assert event_counts["T1_AttemptRegistered"] == 1
    assert event_counts["T1_guard_FALSE"] == 1
    assert sorted((result.client_state, result.disposition.value) for result in results.values()) == [
        ("RESOLVED", "PASS"),
        ("UNKNOWN", "HOLD"),
    ]

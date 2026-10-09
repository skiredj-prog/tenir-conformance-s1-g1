"""G0 S8 — bounded two-thread admission interleavings.

The barrier is placed after each thread has observed the same-LEI guard as
clear, but before either thread can register. This deterministically exposes
a check-then-act race without relying on scheduler luck.
"""
from __future__ import annotations

import threading
import time
from collections import Counter

import pytest

from tenir_conformance.membrane import KernelBridge, Membrane

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}


@pytest.mark.parametrize("_iteration", range(100))
def test_s8a_barrier_synchronized_same_lei_admits_at_most_one(monkeypatch, _iteration):
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
        if lei == "L" and not unresolved and not (lock is not None and getattr(lock, "_is_owned", lambda: False)()):
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



def test_s8b_staggered_same_lei_admission_rejects_second(monkeypatch):
    membrane = Membrane(KernelBridge())
    registered = threading.Event()
    release_first = threading.Event()
    original_register = membrane._register_attempt
    results = {}
    exceptions = {}

    def pause_first_after_registration(**kwargs):
        attempt = original_register(**kwargs)
        if attempt.attempt_id == "A1":
            registered.set()
            if not release_first.wait(timeout=5):
                raise TimeoutError("test did not release first admission")
        return attempt

    monkeypatch.setattr(membrane, "_register_attempt", pause_first_after_registration)

    def worker(attempt_id, nonce):
        try:
            results[attempt_id] = membrane.process_transaction(
                lei="L", attempt_id=attempt_id, payload=PAYLOAD, nonce=nonce
            )
        except BaseException as exc:
            exceptions[attempt_id] = repr(exc)

    first = threading.Thread(target=worker, args=("A1", "nonce-A1"), name="T1")
    first.start()
    assert registered.wait(timeout=5)
    time.sleep(0.001)
    second = threading.Thread(target=worker, args=("A2", "nonce-A2"), name="T2")
    second.start()
    second.join(timeout=5)
    release_first.set()
    first.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert exceptions == {}
    assert len(membrane.attempts) == 1
    assert len([p for p in membrane.permits.values() if p.lei == "L"]) == 1
    assert len(membrane.sink.effects) == 1
    assert results["A2"].client_state == "UNKNOWN"
    assert results["A2"].disposition.value == "HOLD"


def test_s8d_different_leis_are_not_globally_serialized():
    membrane = Membrane(KernelBridge())
    start = threading.Barrier(3)
    results = {}
    exceptions = {}

    def worker(lei, attempt_id):
        try:
            start.wait(timeout=5)
            results[attempt_id] = membrane.process_transaction(
                lei=lei, attempt_id=attempt_id, payload=PAYLOAD, nonce=f"nonce-{attempt_id}"
            )
        except BaseException as exc:
            exceptions[attempt_id] = repr(exc)

    threads = [
        threading.Thread(target=worker, args=("L", "A1"), name="T1"),
        threading.Thread(target=worker, args=("M", "A2"), name="T2"),
    ]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert exceptions == {}
    assert set(membrane.attempts) == {"A1", "A2"}
    assert len(membrane.permits) == 2
    assert len(membrane.sink.effects) == 2
    assert all(result.client_state == "RESOLVED" for result in results.values())


def test_s8e_winner_completes_and_resolved_lei_remains_locked():
    membrane = Membrane(KernelBridge())
    result = membrane.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD, nonce="nonce-A1"
    )
    assert result.client_state == "RESOLVED"
    assert result.disposition.value == "PASS"
    assert membrane.attempts["A1"].state.value == "RESOLVED"
    assert len(membrane.sink.effects) == 1


def test_s8f_retry_after_resolved_winner_is_held_to_prevent_second_effect():
    membrane = Membrane(KernelBridge())
    winner = membrane.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD, nonce="nonce-A1"
    )
    retry = membrane.retry(
        lei="L", attempt_id="A2", payload=PAYLOAD, nonce="nonce-A2"
    )
    assert winner.client_state == "RESOLVED"
    assert retry.client_state == "UNKNOWN"
    assert retry.disposition.value == "HOLD"
    assert set(membrane.attempts) == {"A1"}
    assert len(membrane.sink.effects) == 1



def test_s8c_racing_consumers_cannot_consume_same_permit_or_dispatch_twice():
    membrane = Membrane(KernelBridge())
    attempt = membrane._register_attempt(
        lei="L", attempt_id="A1", nonce="nonce-A1", issue_permit=True
    )
    start = threading.Barrier(3)
    successes = []
    failures = []
    lock = threading.Lock()

    def consumer():
        start.wait(timeout=5)
        try:
            membrane._consume_permit(attempt)
            membrane.sink.apply("L", "A1", PAYLOAD)
            with lock:
                successes.append(True)
        except ValueError as exc:
            with lock:
                failures.append(str(exc))

    threads = [
        threading.Thread(target=consumer, name="T1"),
        threading.Thread(target=consumer, name="T2"),
    ]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(successes) == 1
    assert failures == ["PERMIT_ALREADY_CONSUMED"]
    assert membrane.permits["A1"].consumed is True
    assert len(membrane.sink.effects) == 1
    assert sum(e["event"] == "PERMIT_CONSUMED" for e in membrane.events) == 1
    assert sum(
        e.get("reason") == "PERMIT_ALREADY_CONSUMED" for e in membrane.events
    ) == 1

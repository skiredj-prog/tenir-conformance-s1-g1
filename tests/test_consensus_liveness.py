"""Liveness tests for FileLockConsensusBackend.

These tests verify that consensus operations terminate within a bounded time
(T_max = 5 seconds) and never hang. They cover:

  - Single operations terminate within T_max.
  - Concurrent operations all terminate within T_max.
  - Reconciliation terminates with one of CONFIRMED / FAILED / UNRESOLVED.
  - Insufficient budget returns immediately (no hang).
  - Max latency under concurrent load stays within T_max.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, "/workspace/tenir_governance_fixed")

from tenir_governance.operations.consensus_backend import FileLockConsensusBackend

RESOURCE_ID = "res-1"
T_MAX = 5.0  # seconds — liveness ceiling


def _make_backend(tmp_path, capacity=100):
    store_dir = str(tmp_path / "store")
    backend = FileLockConsensusBackend(store_dir)
    backend.register_resource(RESOURCE_ID, capacity)
    return backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_operations_terminate_within_t_max(tmp_path):
    """Each individual operation (reserve, commit, release, get_state) must
    complete well under T_max."""
    backend = _make_backend(tmp_path, capacity=100)

    t0 = time.monotonic()
    r = backend.reserve("k1", 10, RESOURCE_ID)
    t_reserve = time.monotonic() - t0
    assert r.status == "RESERVED"
    assert t_reserve < T_MAX

    t0 = time.monotonic()
    c = backend.commit(r.reservation_id)
    t_commit = time.monotonic() - t0
    assert c.status == "COMMITTED"
    assert t_commit < T_MAX

    t0 = time.monotonic()
    s = backend.get_state(RESOURCE_ID)
    t_state = time.monotonic() - t0
    assert s.committed == 10
    assert t_state < T_MAX


def test_concurrent_operations_all_terminate(tmp_path):
    """Multiple threads performing operations concurrently must all finish
    within T_max."""
    backend = _make_backend(tmp_path, capacity=1000)
    n_threads = 8
    amount = 10
    barrier = threading.Barrier(n_threads)
    results: list[dict] = [None] * n_threads
    errors: list[Exception] = [None] * n_threads

    def worker(idx):
        try:
            barrier.wait(timeout=T_MAX)
            t0 = time.monotonic()
            r = backend.reserve(f"key-{idx}", amount, RESOURCE_ID)
            assert r.status == "RESERVED"
            c = backend.commit(r.reservation_id)
            assert c.status == "COMMITTED"
            elapsed = time.monotonic() - t0
            results[idx] = {"reserve": r.status, "commit": c.status, "elapsed": elapsed}
        except Exception as exc:  # noqa: BLE001
            errors[idx] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    t_start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=T_MAX + 2)

    # All threads must have finished.
    assert all(t.is_alive() is False for t in threads), "one or more threads hung"

    total_elapsed = time.monotonic() - t_start
    assert total_elapsed < T_MAX, f"all threads took {total_elapsed:.3f}s > T_max"

    for i in range(n_threads):
        assert errors[i] is None, f"thread {i} raised: {errors[i]}"
        assert results[i] is not None
        assert results[i]["elapsed"] < T_MAX

    state = backend.get_state(RESOURCE_ID)
    assert state.committed == n_threads * amount
    assert state.reserved == 0


def test_reconciliation_terminates(tmp_path):
    """reconcile() must terminate and return one of CONFIRMED, FAILED, or
    UNRESOLVED — never hang."""
    backend = _make_backend(tmp_path, capacity=100)

    # Reserve first so there is something to reconcile.
    r = backend.reserve("recon-key", 10, RESOURCE_ID)
    assert r.status == "RESERVED"

    # No provider callback -> reconcile must return UNRESOLVED and terminate.
    t0 = time.monotonic()
    rr = backend.reconcile("recon-key")
    elapsed = time.monotonic() - t0
    assert rr.status in ("CONFIRMED", "FAILED", "UNRESOLVED")
    assert elapsed < T_MAX

    # With a provider that confirms the effect -> CONFIRMED.
    backend2 = _make_backend_with_provider(tmp_path, capacity=100,
                                           provider=lambda key: True)
    r2 = backend2.reserve("recon-confirmed", 10, RESOURCE_ID)
    assert r2.status == "RESERVED"
    t0 = time.monotonic()
    rr2 = backend2.reconcile("recon-confirmed")
    elapsed2 = time.monotonic() - t0
    assert rr2.status == "CONFIRMED"
    assert elapsed2 < T_MAX

    # With a provider that denies the effect -> FAILED.
    backend3 = _make_backend_with_provider(tmp_path, capacity=100,
                                           provider=lambda key: False)
    r3 = backend3.reserve("recon-failed", 10, RESOURCE_ID)
    assert r3.status == "RESERVED"
    t0 = time.monotonic()
    rr3 = backend3.reconcile("recon-failed")
    elapsed3 = time.monotonic() - t0
    assert rr3.status == "FAILED"
    assert elapsed3 < T_MAX

    # With a provider that returns None (indeterminate) -> UNRESOLVED.
    backend4 = _make_backend_with_provider(tmp_path, capacity=100,
                                           provider=lambda key: None)
    r4 = backend4.reserve("recon-unresolved", 10, RESOURCE_ID)
    assert r4.status == "RESERVED"
    t0 = time.monotonic()
    rr4 = backend4.reconcile("recon-unresolved")
    elapsed4 = time.monotonic() - t0
    assert rr4.status == "UNRESOLVED"
    assert elapsed4 < T_MAX


def _make_backend_with_provider(tmp_path, capacity, provider):
    store_dir = str(tmp_path / f"store_{id(provider)}")
    backend = FileLockConsensusBackend(store_dir, provider_reconcile=provider)
    backend.register_resource(RESOURCE_ID, capacity)
    return backend


def test_insufficient_budget_returns_immediately(tmp_path):
    """Reserving more than capacity must return INSUFFICIENT_BUDGET instantly,
    not hang."""
    backend = _make_backend(tmp_path, capacity=50)

    # Fill the budget.
    r = backend.reserve("fill", 50, RESOURCE_ID)
    assert r.status == "RESERVED"

    # Now try to reserve 1 more — must fail immediately.
    t0 = time.monotonic()
    r2 = backend.reserve("overflow", 1, RESOURCE_ID)
    elapsed = time.monotonic() - t0
    assert r2.status == "INSUFFICIENT_BUDGET"
    assert elapsed < 1.0, f"insufficient-budget call took {elapsed:.3f}s"

    # Reconciliation on a non-existent key must also return immediately.
    t0 = time.monotonic()
    rr = backend.reconcile("nonexistent-key")
    elapsed2 = time.monotonic() - t0
    assert rr.status == "NOT_FOUND"
    assert elapsed2 < 1.0


def test_max_latency_under_concurrent_load(tmp_path):
    """Under concurrent load, the maximum per-operation latency must stay
    below T_max."""
    backend = _make_backend(tmp_path, capacity=500)
    n_threads = 10
    ops_per_thread = 5
    latencies: list[float] = []
    lat_lock = threading.Lock()
    barrier = threading.Barrier(n_threads)
    failures: list[str] = []

    def worker(idx):
        try:
            barrier.wait(timeout=T_MAX)
            for j in range(ops_per_thread):
                t0 = time.monotonic()
                r = backend.reserve(f"k-{idx}-{j}", 5, RESOURCE_ID)
                t1 = time.monotonic()
                if r.status != "RESERVED":
                    failures.append(f"thread {idx} op {j}: {r.status}")
                    continue
                c = backend.commit(r.reservation_id)
                t2 = time.monotonic()
                if c.status != "COMMITTED":
                    failures.append(f"thread {idx} commit {j}: {c.status}")
                with lat_lock:
                    latencies.append(t1 - t0)   # reserve latency
                    latencies.append(t2 - t1)   # commit latency
        except Exception as exc:  # noqa: BLE001
            failures.append(f"thread {idx} exception: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=T_MAX + 2)

    assert all(not t.is_alive() for t in threads), "a thread hung"
    assert not failures, f"operation failures: {failures}"
    assert len(latencies) == n_threads * ops_per_thread * 2

    max_latency = max(latencies)
    assert max_latency < T_MAX, f"max latency {max_latency:.3f}s >= T_max {T_MAX}"

    # Verify final state: all committed, none reserved.
    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 0
    assert state.committed == n_threads * ops_per_thread * 5
    assert state.reserved + state.committed <= 500


def test_release_terminates_and_restores_budget(tmp_path):
    """release() must terminate within T_max and restore available budget."""
    backend = _make_backend(tmp_path, capacity=100)

    r = backend.reserve("rel-key", 30, RESOURCE_ID)
    assert r.status == "RESERVED"

    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 30
    assert state.available == 70

    t0 = time.monotonic()
    rr = backend.release(r.reservation_id)
    elapsed = time.monotonic() - t0
    assert rr.status == "RELEASED"
    assert elapsed < T_MAX

    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 0
    assert state.available == 100


def test_duplicate_key_reserve_terminates(tmp_path):
    """Reserving the same key twice (idempotency) must return immediately both
    times, not hang."""
    backend = _make_backend(tmp_path, capacity=100)

    t0 = time.monotonic()
    r1 = backend.reserve("dup-key", 10, RESOURCE_ID)
    elapsed1 = time.monotonic() - t0
    assert r1.status == "RESERVED"
    assert elapsed1 < T_MAX

    t0 = time.monotonic()
    r2 = backend.reserve("dup-key", 10, RESOURCE_ID)
    elapsed2 = time.monotonic() - t0
    assert r2.status == "RESERVED"
    assert r2.reservation_id == r1.reservation_id
    assert elapsed2 < T_MAX

    # Only one reservation on disk.
    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 10
    assert len(state.reservations) == 1
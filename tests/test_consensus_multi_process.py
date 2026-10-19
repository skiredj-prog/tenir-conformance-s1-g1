"""Multi-process consensus tests for FileLockConsensusBackend.

These tests spawn 2+ subprocesses (via subprocess.Popen) that each import
FileLockConsensusBackend from tenir_governance and operate against a shared
store directory. They verify:

  - Idempotency across processes: two processes reserving the same key
    produce only one winner.
  - I8 invariant: reserved + committed <= capacity, across processes.
  - Cross-process reserve -> commit -> release cycle.
  - Concurrent reservations do not exceed capacity.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, "/workspace/tenir_governance_fixed")

from tenir_governance.operations.consensus_backend import FileLockConsensusBackend

WORKER = os.path.join(os.path.dirname(__file__), "_consensus_worker.py")
RESOURCE_ID = "res-1"
CAPACITY = 100

T_MAX = 5.0  # seconds — liveness ceiling for subprocess completion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_instruction(tmp_path, name, instr):
    p = tmp_path / f"{name}.instr.json"
    p.write_text(json.dumps(instr), encoding="utf-8")
    return p


def _result_path(tmp_path, name):
    return tmp_path / f"{name}.result.json"


def _spawn(tmp_path, name, instr, env=None):
    """Spawn a worker subprocess for the given instruction; return Popen."""
    instr_path = _write_instruction(tmp_path, name, instr)
    res_path = _result_path(tmp_path, name)
    if res_path.exists():
        res_path.unlink()
    full_env = os.environ.copy()
    full_env["PYTHONPATH"] = "/workspace/tenir_governance_fixed"
    if env:
        full_env.update(env)
    proc = subprocess.Popen(
        [sys.executable, WORKER, str(instr_path), str(res_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=full_env,
    )
    return proc, res_path


def _await(proc, res_path, timeout=T_MAX):
    """Wait for a subprocess, assert it exited 0, return parsed result JSON."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        out, err = proc.communicate()
        raise AssertionError(
            f"subprocess timed out after {timeout}s\nstdout={out!r}\nstderr={err!r}"
        )
    assert proc.returncode == 0, (
        f"worker exited {proc.returncode}\n"
        f"stdout={proc.stdout.read().decode()!r}\n"
        f"stderr={proc.stderr.read().decode()!r}"
    )
    return json.loads(res_path.read_text(encoding="utf-8"))


def _setup_store(tmp_path, capacity=CAPACITY):
    """Create a shared store dir and register a resource, returning the store dir path."""
    store_dir = str(tmp_path / "store")
    backend = FileLockConsensusBackend(store_dir)
    backend.register_resource(RESOURCE_ID, capacity)
    return store_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_same_key_two_processes_one_winner(tmp_path):
    """Two processes reserving the SAME idempotency key must yield exactly one
    RESERVED result and one idempotent reuse — never two independent winners."""
    store_dir = _setup_store(tmp_path)

    # Both workers attempt to reserve the same key for the same amount.
    p1, r1 = _spawn(tmp_path, "w1", {
        "store_dir": store_dir, "resource_id": RESOURCE_ID,
        "action": "reserve", "key": "shared-key", "amount": 10,
    })
    p2, r2 = _spawn(tmp_path, "w2", {
        "store_dir": store_dir, "resource_id": RESOURCE_ID,
        "action": "reserve", "key": "shared-key", "amount": 10,
    })

    res1 = _await(p1, r1)
    res2 = _await(p2, r2)

    # Both must report RESERVED (idempotency), but they must share the same
    # reservation_id — proving only one underlying reservation was created.
    assert res1["status"] == "RESERVED"
    assert res2["status"] == "RESERVED"
    assert res1["reservation_id"] is not None
    assert res1["reservation_id"] == res2["reservation_id"], (
        "Two processes produced different reservation IDs for the same key — "
        "idempotency across processes failed"
    )

    # Verify only one reservation record exists on disk.
    backend = FileLockConsensusBackend(store_dir)
    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 10
    assert state.committed == 0
    assert len(state.reservations) == 1


def test_i8_invariant_holds_across_processes(tmp_path):
    """I8: reserved + committed <= capacity must hold after multiple processes
    reserve and commit independently."""
    store_dir = _setup_store(tmp_path, capacity=CAPACITY)

    # 4 processes each reserve 20 units (total 80, under capacity 100).
    procs = []
    results = []
    for i in range(4):
        p, r = _spawn(tmp_path, f"r{i}", {
            "store_dir": store_dir, "resource_id": RESOURCE_ID,
            "action": "reserve", "key": f"k{i}", "amount": 20,
        })
        procs.append((p, r))

    for p, r in procs:
        results.append(_await(p, r))

    # All four must succeed.
    assert all(res["status"] == "RESERVED" for res in results)

    backend = FileLockConsensusBackend(store_dir)
    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 80
    assert state.committed == 0
    assert state.reserved + state.committed <= CAPACITY  # I8

    # Now two processes commit their reservations.
    commit_procs = []
    for i in range(2):
        rid = results[i]["reservation_id"]
        p, r = _spawn(tmp_path, f"c{i}", {
            "store_dir": store_dir, "resource_id": RESOURCE_ID,
            "action": "commit", "reservation_id": rid,
        })
        commit_procs.append((p, r))

    for p, r in commit_procs:
        cres = _await(p, r)
        assert cres["status"] == "COMMITTED"

    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 40
    assert state.committed == 40
    assert state.reserved + state.committed <= CAPACITY  # I8 still holds


def test_cross_process_reserve_commit_release(tmp_path):
    """Full lifecycle across three separate processes: reserve, commit, release."""
    store_dir = _setup_store(tmp_path, capacity=50)

    # Process 1: reserve
    p1, r1 = _spawn(tmp_path, "reserve", {
        "store_dir": store_dir, "resource_id": RESOURCE_ID,
        "action": "reserve", "key": "lifecycle", "amount": 15,
    })
    res1 = _await(p1, r1)
    assert res1["status"] == "RESERVED"
    rid = res1["reservation_id"]
    assert rid is not None

    backend = FileLockConsensusBackend(store_dir)
    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 15
    assert state.committed == 0

    # Process 2: commit
    p2, r2 = _spawn(tmp_path, "commit", {
        "store_dir": store_dir, "resource_id": RESOURCE_ID,
        "action": "commit", "reservation_id": rid,
    })
    res2 = _await(p2, r2)
    assert res2["status"] == "COMMITTED"

    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 0
    assert state.committed == 15
    assert state.reserved + state.committed <= 50  # I8

    # Process 3: attempt to release an already-committed reservation — must fail
    p3, r3 = _spawn(tmp_path, "release", {
        "store_dir": store_dir, "resource_id": RESOURCE_ID,
        "action": "release", "reservation_id": rid,
    })
    res3 = _await(p3, r3)
    assert res3["status"] == "ALREADY_COMMITTED"

    # State unchanged after failed release.
    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 0
    assert state.committed == 15


def test_concurrent_reservations_do_not_exceed_capacity(tmp_path):
    """Spawn many processes concurrently; each tries to reserve 10 units
    against capacity 100. Exactly 10 should win; the rest must get
    INSUFFICIENT_BUDGET. Total reserved must never exceed capacity."""
    store_dir = _setup_store(tmp_path, capacity=100)
    n_workers = 15
    amount = 10
    expected_winners = 100 // amount  # 10

    procs = []
    for i in range(n_workers):
        p, r = _spawn(tmp_path, f"burst-{i}", {
            "store_dir": store_dir, "resource_id": RESOURCE_ID,
            "action": "reserve", "key": f"burst-{i}", "amount": amount,
        })
        procs.append((p, r))

    results = []
    for p, r in procs:
        results.append(_await(p, r))

    winners = [res for res in results if res["status"] == "RESERVED"]
    losers = [res for res in results if res["status"] == "INSUFFICIENT_BUDGET"]

    assert len(winners) == expected_winners, (
        f"expected {expected_winners} winners, got {len(winners)}"
    )
    assert len(losers) == n_workers - expected_winners

    # I8: reserved <= capacity, committed == 0.
    backend = FileLockConsensusBackend(store_dir)
    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == expected_winners * amount
    assert state.committed == 0
    assert state.reserved + state.committed <= 100


def test_concurrent_reserve_then_commit_i8(tmp_path):
    """Multiple processes reserve distinct keys then commit them; I8 must hold
    at every checkpoint we observe."""
    store_dir = _setup_store(tmp_path, capacity=60)

    # 3 processes reserve 20 each (total 60 == capacity).
    procs = []
    for i in range(3):
        p, r = _spawn(tmp_path, f"rc-res-{i}", {
            "store_dir": store_dir, "resource_id": RESOURCE_ID,
            "action": "reserve", "key": f"rc-{i}", "amount": 20,
        })
        procs.append((p, r))

    rids = []
    for p, r in procs:
        res = _await(p, r)
        assert res["status"] == "RESERVED"
        rids.append(res["reservation_id"])

    backend = FileLockConsensusBackend(store_dir)
    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 60
    assert state.reserved + state.committed <= 60

    # Commit all three from separate processes.
    cprocs = []
    for i, rid in enumerate(rids):
        p, r = _spawn(tmp_path, f"rc-com-{i}", {
            "store_dir": store_dir, "resource_id": RESOURCE_ID,
            "action": "commit", "reservation_id": rid,
        })
        cprocs.append((p, r))

    for p, r in cprocs:
        res = _await(p, r)
        assert res["status"] == "COMMITTED"

    state = backend.get_state(RESOURCE_ID)
    assert state.reserved == 0
    assert state.committed == 60
    assert state.reserved + state.committed <= 60  # I8
"""Jepsen-style fault injection tests for FileLockConsensusBackend.

These tests validate crash-stop recovery, budget invariant (I8) preservation
after crashes, durable state visibility across processes, partition simulation
via fcntl.flock contention, and byzantine-input rejection — all against the
FileLockConsensusBackend reference adapter backed by DurableBudgetCoordinator.

The backend uses fcntl.flock for cross-process serialization and persists
state to JSON files on disk, so a crashed process leaves durable state that a
restarted process can read. We simulate "network partition" on this single-host
system by having one process hold the exclusive lock while another waits,
verifying that safety (I8) holds throughout the contention window.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import textwrap

import pytest

sys.path.insert(0, "/workspace/tenir_governance_fixed")

from tenir_governance.operations.consensus_backend import FileLockConsensusBackend

# ---------------------------------------------------------------------------
# Worker script — a small standalone program that performs backend operations.
# Each invocation creates its own FileLockConsensusBackend instance pointing at
# the same store_dir, so multiple subprocesses share the durable state files.
# ---------------------------------------------------------------------------

_WORKER_SCRIPT = textwrap.dedent(
    """\
    import sys, os, time, json, fcntl
    sys.path.insert(0, "/workspace/tenir_governance_fixed")
    from tenir_governance.operations.consensus_backend import FileLockConsensusBackend

    store_dir = sys.argv[1]
    action = sys.argv[2]

    def _flush(msg):
        print(msg, flush=True)

    if action == "setup":
        backend = FileLockConsensusBackend(store_dir)
        backend.register_resource("r1", 100)
        _flush("SETUP_DONE")

    elif action == "reserve":
        key = sys.argv[3]
        amount = int(sys.argv[4])
        backend = FileLockConsensusBackend(store_dir)
        r = backend.reserve(key, amount, "r1")
        _flush(f"RESERVE:{r.status}:{r.reservation_id or ''}")

    elif action == "commit":
        rid = sys.argv[3]
        backend = FileLockConsensusBackend(store_dir)
        c = backend.commit(rid)
        _flush(f"COMMIT:{c.status}")

    elif action == "release":
        rid = sys.argv[3]
        backend = FileLockConsensusBackend(store_dir)
        rel = backend.release(rid)
        _flush(f"RELEASE:{rel.status}")

    elif action == "state":
        backend = FileLockConsensusBackend(store_dir)
        s = backend.get_state("r1")
        _flush(f"STATE:{s.available}:{s.reserved}:{s.committed}:{s.capacity}")

    elif action == "reserve_and_commit":
        # reserve then immediately commit — used for crash-recovery tests where
        # we kill mid-operation.  The --delay flag inserts a sleep between the
        # reserve and the commit so the parent can SIGKILL in the window.
        # An optional --pre-delay sleeps BEFORE the reserve, allowing the
        # parent to kill before any operation completes.
        key = sys.argv[3]
        amount = int(sys.argv[4])
        delay = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
        pre_delay = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
        if pre_delay > 0:
            time.sleep(pre_delay)
        backend = FileLockConsensusBackend(store_dir)
        r = backend.reserve(key, amount, "r1")
        _flush(f"RESERVE:{r.status}:{r.reservation_id or ''}")
        if delay > 0:
            time.sleep(delay)
        if r.reservation_id:
            c = backend.commit(r.reservation_id)
            _flush(f"COMMIT:{c.status}")
        else:
            _flush("COMMIT:SKIPPED")

    elif action == "hold_lock":
        # Acquire the reservations lock externally and hold it for a given
        # duration, simulating a "partition" where one process is unreachable
        # (holding the shared resource).  The other process must wait.
        duration = float(sys.argv[3])
        lock_path = os.path.join(store_dir, "reservations.json.lock")
        if not os.path.exists(lock_path):
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
            os.close(fd)
        f = open(lock_path, "r+")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        _flush("LOCK_HELD")
        time.sleep(duration)
        f.close()
        _flush("LOCK_RELEASED")

    elif action == "byzantine":
        # Send a sequence of invalid operations and report each result.
        backend = FileLockConsensusBackend(store_dir)
        results = []
        # non-existent reservation id commit
        c = backend.commit("nonexistent-rid-9999")
        results.append(f"badcommit:{c.status}")
        # non-existent reservation id release
        rel = backend.release("nonexistent-rid-9999")
        results.append(f"badrelease:{rel.status}")
        # zero amount reserve
        r0 = backend.reserve("byz_zero", 0, "r1")
        results.append(f"zero:{r0.status}")
        # commit on a non-existent resource by reserving then committing
        # with a tampered reservation file (simulate corruption)
        res_path = os.path.join(store_dir, "reservations.json")
        if os.path.exists(res_path):
            try:
                with open(res_path) as rf:
                    data = json.load(rf)
                # inject a fake reservation with a huge amount
                data["fake-rid"] = {
                    "key": "fake", "amount": 99999,
                    "resource_id": "r1", "state": "RESERVED",
                    "created_at": time.time(),
                }
                with open(res_path, "w") as wf:
                    json.dump(data, wf)
            except Exception:
                pass
        c2 = backend.commit("fake-rid")
        results.append(f"fakecommit:{c2.status}")
        _flush(";".join(results))
    """
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def worker_script(store_dir):
    """Write the worker script to the store dir and return its path."""
    path = os.path.join(store_dir, "_worker.py")
    with open(path, "w") as f:
        f.write(_WORKER_SCRIPT)
    return path


@pytest.fixture
def ready_backend(store_dir, worker_script):
    """Set up a registered resource and return the store_dir + script path."""
    p = subprocess.run(
        [sys.executable, worker_script, store_dir, "setup"],
        capture_output=True, text=True, timeout=10,
    )
    assert "SETUP_DONE" in p.stdout, f"setup failed: {p.stderr}"
    return store_dir


def _run_worker(script, store_dir, *args, timeout=15):
    """Run the worker script and return stdout (stripped)."""
    p = subprocess.run(
        [sys.executable, script, store_dir, *args],
        capture_output=True, text=True, timeout=timeout,
    )
    return p.stdout.strip()


def _parse_state(output: str):
    """Parse 'STATE:avail:reserved:committed:capacity' into ints."""
    parts = output.split(":")
    return {
        "available": int(parts[1]),
        "reserved": int(parts[2]),
        "committed": int(parts[3]),
        "capacity": int(parts[4]),
    }


# ---------------------------------------------------------------------------
# 1. Crash-stop recovery: kill mid-operation, restart, verify consistency
# ---------------------------------------------------------------------------

class TestCrashStopRecovery:
    """Kill a subprocess mid-operation, restart, and verify state is consistent."""

    def test_crash_mid_reserve_commit_then_restart_state_consistent(
        self, ready_backend, worker_script
    ):
        store_dir = ready_backend

        # Launch a process that reserves 30, sleeps 3s, then commits.
        # We SIGKILL it during the sleep window (after reserve, before commit).
        proc = subprocess.Popen(
            [sys.executable, worker_script, store_dir,
             "reserve_and_commit", "crash_key", "30", "3"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        # Wait for the RESERVE line to appear (reserve completed, durable).
        line = proc.stdout.readline().decode().strip()
        assert line.startswith("RESERVE:RESERVED:"), f"unexpected: {line}"
        reservation_id = line.split(":")[2]

        # Kill the process before it commits.
        time.sleep(0.5)  # ensure we're in the sleep window
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)

        # Verify the process is dead.
        assert proc.poll() is not None

        # Restart: a fresh process reads durable state.
        state_out = _run_worker(worker_script, store_dir, "state")
        state = _parse_state(state_out)

        # The reserve (30) should be visible as reserved budget, but NOT committed.
        # available = 100 - 30 = 70, reserved = 30, committed = 0
        assert state["capacity"] == 100
        assert state["reserved"] == 30, f"reserved should be 30, got {state['reserved']}"
        assert state["committed"] == 0, f"committed should be 0, got {state['committed']}"
        assert state["available"] == 70

        # The crashed process's reservation must be visible to the new process
        # (durable state).  Commit it from the new process to prove it's real.
        commit_out = _run_worker(worker_script, store_dir, "commit", reservation_id)
        assert commit_out == "COMMIT:COMMITTED", f"unexpected: {commit_out}"

        # After commit: available=70, reserved=0, committed=30
        state_out2 = _run_worker(worker_script, store_dir, "state")
        state2 = _parse_state(state_out2)
        assert state2["reserved"] == 0
        assert state2["committed"] == 30
        assert state2["available"] == 70

    def test_crash_before_reserve_leaves_clean_state(
        self, ready_backend, worker_script
    ):
        """Crash a process before it reserves — state should be untouched."""
        store_dir = ready_backend

        # Launch and kill before any operation completes.
        # Use a pre-delay so the process is sleeping when killed.
        proc = subprocess.Popen(
            [sys.executable, worker_script, store_dir,
             "reserve_and_commit", "early_crash", "20", "5", "3"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(0.5)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)

        # State should be pristine.
        state_out = _run_worker(worker_script, store_dir, "state")
        state = _parse_state(state_out)
        assert state == {"available": 100, "reserved": 0, "committed": 0, "capacity": 100}


# ---------------------------------------------------------------------------
# 2. I8 holds after a crash (no budget leak)
# ---------------------------------------------------------------------------

class TestI8AfterCrash:
    """I8 invariant: reserved + committed <= capacity, always, even after crash."""

    def test_no_budget_leak_after_crash(self, ready_backend, worker_script):
        store_dir = ready_backend

        # Reserve 40 and commit successfully.
        out = _run_worker(worker_script, store_dir, "reserve", "k1", "40")
        rid = out.split(":")[2]
        assert _run_worker(worker_script, store_dir, "commit", rid) == "COMMIT:COMMITTED"

        # Now start a second reserve+commit of 30, crash before commit.
        proc = subprocess.Popen(
            [sys.executable, worker_script, store_dir,
             "reserve_and_commit", "crash_key", "30", "3"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        line = proc.stdout.readline().decode().strip()
        assert line.startswith("RESERVE:RESERVED:")
        time.sleep(0.5)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)

        # I8 check: reserved + committed <= capacity
        state_out = _run_worker(worker_script, store_dir, "state")
        state = _parse_state(state_out)

        # committed=40 (from k1), reserved=30 (from crashed crash_key)
        assert state["committed"] == 40
        assert state["reserved"] == 30
        assert state["reserved"] + state["committed"] <= state["capacity"], (
            "I8 violated: reserved + committed > capacity"
        )

        # After the crash, we can still reserve the remaining 30.
        out2 = _run_worker(worker_script, store_dir, "reserve", "k2", "30")
        assert out2.startswith("RESERVE:RESERVED:"), f"should have 30 left: {out2}"

        # But trying to reserve 1 more should fail (100 - 40 - 30 - 30 = 0).
        out3 = _run_worker(worker_script, store_dir, "reserve", "k3", "1")
        assert out3 == "RESERVE:INSUFFICIENT_BUDGET:", f"should be insufficient: {out3}"

    def test_i8_holds_across_multiple_crash_cycles(self, ready_backend, worker_script):
        """Reserve+crash multiple times; I8 must hold after each cycle."""
        store_dir = ready_backend

        for i in range(3):
            proc = subprocess.Popen(
                [sys.executable, worker_script, store_dir,
                 "reserve_and_commit", f"crash_{i}", "25", "3"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            line = proc.stdout.readline().decode().strip()
            assert line.startswith("RESERVE:RESERVED:"), f"cycle {i}: {line}"
            time.sleep(0.3)
            proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=5)

            state_out = _run_worker(worker_script, store_dir, "state")
            state = _parse_state(state_out)
            assert state["reserved"] + state["committed"] <= state["capacity"], (
                f"I8 violated after crash cycle {i}: {state}"
            )

        # 3 crashes × 25 reserved = 75 reserved, 0 committed, 25 available.
        state_out = _run_worker(worker_script, store_dir, "state")
        state = _parse_state(state_out)
        assert state["reserved"] == 75
        assert state["committed"] == 0
        assert state["available"] == 25


# ---------------------------------------------------------------------------
# 3. Crashed process's reservation is visible to other processes after restart
# ---------------------------------------------------------------------------

class TestDurableStateVisibility:
    """A crashed process's reservation must be durable and visible to others."""

    def test_reservation_visible_after_restart(self, ready_backend, worker_script):
        store_dir = ready_backend

        # Process A reserves 50 and is killed before committing.
        proc = subprocess.Popen(
            [sys.executable, worker_script, store_dir,
             "reserve_and_commit", "durable_key", "50", "3"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        line = proc.stdout.readline().decode().strip()
        assert line.startswith("RESERVE:RESERVED:")
        rid_a = line.split(":")[2]
        time.sleep(0.5)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)

        # Process B (completely new process) should see the reservation.
        # It can verify by checking state and by trying to reserve the
        # remaining 50 (not 100).
        state_out = _run_worker(worker_script, store_dir, "state")
        state = _parse_state(state_out)
        assert state["reserved"] == 50, f"reservation not visible: {state}"
        assert state["available"] == 50

        # Process B reserves 50 — should succeed (exactly the remainder).
        out_b = _run_worker(worker_script, store_dir, "reserve", "b_key", "50")
        assert out_b.startswith("RESERVE:RESERVED:"), f"B should reserve 50: {out_b}"

        # Process B tries 1 more — should fail.
        out_c = _run_worker(worker_script, store_dir, "reserve", "c_key", "1")
        assert out_c == "RESERVE:INSUFFICIENT_BUDGET:"

        # Process B can commit A's reservation (proving it's a real, durable record).
        commit_a = _run_worker(worker_script, store_dir, "commit", rid_a)
        assert commit_a == "COMMIT:COMMITTED"

    def test_multiple_processes_see_same_durable_state(self, ready_backend, worker_script):
        """Several new processes must all read the same durable state."""
        store_dir = ready_backend

        # Reserve and commit 30.
        out = _run_worker(worker_script, store_dir, "reserve", "k1", "30")
        rid = out.split(":")[2]
        _run_worker(worker_script, store_dir, "commit", rid)

        # Three independent processes read state — all must agree.
        states = []
        for _ in range(3):
            s = _run_worker(worker_script, store_dir, "state")
            states.append(_parse_state(s))

        for st in states:
            assert st == {"available": 70, "reserved": 0, "committed": 30, "capacity": 100}

        # All three must agree with each other.
        assert states[0] == states[1] == states[2]


# ---------------------------------------------------------------------------
# 4. Partition simulation: one process holds lock, another waits — safety holds
# ---------------------------------------------------------------------------

class TestPartitionSimulation:
    """Simulate 'partition' via fcntl.flock contention on a single host."""

    def test_lock_contention_serializes_operations(self, ready_backend, worker_script):
        """While one process holds the lock, another must wait, then proceed safely."""
        store_dir = ready_backend

        # Process A holds the exclusive lock for 2 seconds.
        holder = subprocess.Popen(
            [sys.executable, worker_script, store_dir, "hold_lock", "2"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # Wait for confirmation that the lock is held.
        held_line = holder.stdout.readline().decode().strip()
        assert held_line == "LOCK_HELD", f"unexpected: {held_line}"
        time.sleep(0.3)  # ensure we're inside the hold window

        # Process B tries to reserve — must block until the lock is released.
        start = time.time()
        out_b = _run_worker(worker_script, store_dir, "reserve", "b_key", "40", "10")
        elapsed = time.time() - start

        # B should have waited ~1.7s (2s hold - 0.3s sleep) before succeeding.
        assert elapsed > 1.0, f"B did not wait for lock: elapsed={elapsed:.2f}s"
        assert out_b.startswith("RESERVE:RESERVED:"), f"B failed: {out_b}"

        # Holder releases.
        holder.wait(timeout=10)
        released_line = holder.stdout.read().decode().strip()
        assert released_line == "LOCK_RELEASED"

        # I8 must hold: 40 reserved, 0 committed, 60 available.
        state = _parse_state(_run_worker(worker_script, store_dir, "state"))
        assert state["reserved"] == 40
        assert state["committed"] == 0
        assert state["available"] == 60
        assert state["reserved"] + state["committed"] <= state["capacity"]

    def test_concurrent_reserves_do_not_exceed_capacity(
        self, ready_backend, worker_script
    ):
        """Two processes reserve concurrently; total must not exceed capacity."""
        store_dir = ready_backend

        # Both try to reserve 60 (total 120 > 100). Exactly one must succeed.
        procs = []
        for key in ("p1", "p2"):
            p = subprocess.Popen(
                [sys.executable, worker_script, store_dir, "reserve", key, "60"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            procs.append(p)

        results = []
        for p in procs:
            p.wait(timeout=15)
            results.append(p.stdout.read().decode().strip())

        statuses = [r.split(":")[1] for r in results]
        # Exactly one RESERVED, one INSUFFICIENT_BUDGET.
        assert statuses.count("RESERVED") == 1, f"expected 1 success, got {statuses}"
        assert statuses.count("INSUFFICIENT_BUDGET") == 1, f"expected 1 fail, got {statuses}"

        # I8 must hold.
        state = _parse_state(_run_worker(worker_script, store_dir, "state"))
        assert state["reserved"] == 60
        assert state["reserved"] + state["committed"] <= state["capacity"]


# ---------------------------------------------------------------------------
# 5. Byzantine behavior: invalid operations rejected without corrupting state
# ---------------------------------------------------------------------------

class TestByzantineRejection:
    """A process sending invalid operations must be rejected without state corruption."""

    def test_invalid_operations_rejected(self, ready_backend, worker_script):
        store_dir = ready_backend

        out = _run_worker(worker_script, store_dir, "byzantine", timeout=15)
        results = dict(r.split(":", 1) for r in out.split(";"))

        # Non-existent reservation id commit — must be NOT_FOUND.
        assert results["badcommit"] == "NOT_FOUND", (
            f"bad commit should be NOT_FOUND, got {results['badcommit']}"
        )

        # Non-existent reservation id release — must be NOT_FOUND.
        assert results["badrelease"] == "NOT_FOUND", (
            f"bad release should be NOT_FOUND, got {results['badrelease']}"
        )

        # The fake reservation with amount 99999 should fail to commit
        # because the coordinator enforces I8 (reserved >= amount fails
        # since 99999 > capacity).
        assert results["fakecommit"] == "ERROR", (
            f"fake commit (99999) should be ERROR, got {results['fakecommit']}"
        )

    def test_byzantine_input_does_not_corrupt_state(self, ready_backend, worker_script):
        """After byzantine operations, valid operations must still work correctly
        and the I8 invariant (reserved + committed <= capacity) must hold."""
        store_dir = ready_backend

        # Send byzantine garbage.
        _run_worker(worker_script, store_dir, "byzantine", timeout=15)

        # I8 must hold: reserved + committed <= capacity.
        # The byzantine ops may have added a zero-amount reservation (harmless)
        # and a fake 99999 reservation (but it can't be committed since the
        # coordinator enforces I8).  The budget state itself must be consistent.
        state = _parse_state(_run_worker(worker_script, store_dir, "state"))
        assert state["reserved"] + state["committed"] <= state["capacity"], (
            f"I8 violated after byzantine input: {state}"
        )

        # Valid operations must still work correctly.
        out = _run_worker(worker_script, store_dir, "reserve", "valid_key", "50")
        assert out.startswith("RESERVE:RESERVED:"), f"valid reserve failed: {out}"
        rid = out.split(":")[2]

        commit_out = _run_worker(worker_script, store_dir, "commit", rid)
        assert commit_out == "COMMIT:COMMITTED"

        state2 = _parse_state(_run_worker(worker_script, store_dir, "state"))
        assert state2["committed"] == 50
        assert state2["available"] == 50
        assert state2["reserved"] + state2["committed"] <= state2["capacity"]


# ---------------------------------------------------------------------------
# 6. Recovery after crash does not re-commit already committed operations
# ---------------------------------------------------------------------------

class TestNoRecommitAfterCrash:
    """A committed operation must not be re-committed during recovery."""

    def test_commit_is_idempotent_after_crash(self, ready_backend, worker_script):
        """Commit an operation, crash a process, restart, and re-commit — must be ALREADY_COMMITTED."""
        store_dir = ready_backend

        # Reserve and commit 30.
        out = _run_worker(worker_script, store_dir, "reserve", "k1", "30")
        rid = out.split(":")[2]
        assert _run_worker(worker_script, store_dir, "commit", rid) == "COMMIT:COMMITTED"

        # Simulate a crash: start a process that will be killed.
        proc = subprocess.Popen(
            [sys.executable, worker_script, store_dir,
             "reserve_and_commit", "crash_dummy", "10", "3"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # Wait for the reserve to complete (durable), then kill before commit.
        line = proc.stdout.readline().decode().strip()
        assert line.startswith("RESERVE:RESERVED:")
        crash_rid = line.split(":")[2]
        time.sleep(0.3)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)

        # After "recovery", re-committing the already-committed reservation
        # must return ALREADY_COMMITTED, not COMMITTED.
        recommit = _run_worker(worker_script, store_dir, "commit", rid)
        assert recommit == "COMMIT:ALREADY_COMMITTED", (
            f"re-commit should be ALREADY_COMMITTED, got {recommit}"
        )

        # State must reflect only one commit (30), not double.
        # The crashed process left a reservation of 10 in RESERVED state;
        # release it to get a clean comparison.
        _run_worker(worker_script, store_dir, "release", crash_rid)
        state = _parse_state(_run_worker(worker_script, store_dir, "state"))
        assert state["committed"] == 30, f"double commit detected: {state}"
        assert state["reserved"] == 0

    def test_committed_budget_not_double_counted(self, ready_backend, worker_script):
        """After crash recovery, committed budget must not be counted twice."""
        store_dir = ready_backend

        # Reserve and commit 40.
        out = _run_worker(worker_script, store_dir, "reserve", "k1", "40")
        rid = out.split(":")[2]
        _run_worker(worker_script, store_dir, "commit", rid)

        # Crash a process.
        proc = subprocess.Popen(
            [sys.executable, worker_script, store_dir,
             "reserve_and_commit", "crash", "20", "3"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        line = proc.stdout.readline().decode().strip()
        assert line.startswith("RESERVE:RESERVED:")
        crash_rid = line.split(":")[2]
        time.sleep(0.3)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)

        # Re-commit the already-committed reservation (simulating recovery retry).
        _run_worker(worker_script, store_dir, "commit", rid)

        # Only 40 should be committed. The crashed process left 20 reserved;
        # release it for a clean comparison.
        _run_worker(worker_script, store_dir, "release", crash_rid)
        state = _parse_state(_run_worker(worker_script, store_dir, "state"))
        assert state["committed"] == 40, f"budget double-counted: {state}"
        assert state["available"] == 60

        # We can still reserve 60 (the full remainder).
        out2 = _run_worker(worker_script, store_dir, "reserve", "k2", "60")
        assert out2.startswith("RESERVE:RESERVED:"), f"should reserve 60: {out2}"

        # But not 61.
        out3 = _run_worker(worker_script, store_dir, "reserve", "k3", "61")
        assert out3 == "RESERVE:INSUFFICIENT_BUDGET:"
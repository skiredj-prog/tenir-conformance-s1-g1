"""Linearizability validation tests for ConsensusBackend histories.

These tests use the Wing-Gong LinearizabilityChecker to verify that concurrent
histories of reserve/commit/release operations are linearizable — i.e., there
exists a sequential ordering of the operations that (a) respects the real-time
precedence order and (b) produces the same results under the sequential
specification.

Positive cases: valid histories must be linearizable.
Negative cases: histories that violate I8 (two reserves exceeding capacity both
succeed) must NOT be linearizable.

We also verify that consensus_sequential_spec correctly models the
FileLockConsensusBackend by comparing spec predictions against actual backend
behavior for identical operation sequences.
"""
from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, "/workspace/tenir_governance_fixed")

from tenir_governance.operations.linearizability_checker import (
    LinearizabilityChecker,
    Invocation,
    Response,
    Operation,
    consensus_sequential_spec,
)
from tenir_governance.operations.consensus_backend import FileLockConsensusBackend


# ---------------------------------------------------------------------------
# Helpers for building histories
# ---------------------------------------------------------------------------

def _inv(op, args, client_id, event_id):
    return Invocation(op, args, client_id, event_id)


def _resp(result, client_id, event_id):
    return Response(result, client_id, event_id)


def _op(op, args, client_id, inv_id, result, resp_id):
    """Build a complete Operation (invocation + response)."""
    return Operation(
        _inv(op, args, client_id, inv_id),
        _resp(result, client_id, resp_id),
    )


# Event ID allocation helper: keeps invocation/response IDs globally unique
# and ordered so that real-time precedence is encoded correctly.
class EventIdCounter:
    def __init__(self):
        self._n = 0

    def next(self):
        v = self._n
        self._n += 1
        return v


# ---------------------------------------------------------------------------
# 1. Positive case: valid sequential history is linearizable
# ---------------------------------------------------------------------------

class TestValidSequentialHistory:
    """A valid sequential history must be linearizable (trivially)."""

    def test_simple_reserve_commit_sequential(self):
        """reserve(k1, 30) -> commit(res-0) is linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 30, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("commit", ("res-0",), 0, e.next(),
                {"status": "COMMITTED"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"should be linearizable: {result.reason}"

    def test_reserve_release_sequential(self):
        """reserve(k1, 30) -> release(res-0) is linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 30, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("release", ("res-0",), 0, e.next(),
                {"status": "RELEASED"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"should be linearizable: {result.reason}"

    def test_multiple_reserves_within_capacity(self):
        """Two reserves of 40 each (total 80 <= 100) both succeed — linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 40, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("reserve", ("k2", 40, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-1"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"should be linearizable: {result.reason}"

    def test_reserve_then_insufficient(self):
        """reserve 60 succeeds, reserve 60 more fails (only 40 left) — linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 60, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("reserve", ("k2", 60, "r1"), 0, e.next(),
                {"status": "INSUFFICIENT_BUDGET"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"should be linearizable: {result.reason}"

    def test_full_reserve_commit_release_cycle(self):
        """reserve -> commit -> reserve -> release -> reserve — all valid."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 50, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("commit", ("res-0",), 0, e.next(),
                {"status": "COMMITTED"}, e.next()),
            _op("reserve", ("k2", 50, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-1"}, e.next()),
            _op("release", ("res-1",), 0, e.next(),
                {"status": "RELEASED"}, e.next()),
            _op("reserve", ("k3", 50, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-2"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"should be linearizable: {result.reason}"

    def test_idempotent_reserve_same_key(self):
        """Reserving the same key with the same amount twice returns same reservation."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 30, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("reserve", ("k1", 30, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"should be linearizable: {result.reason}"

    def test_duplicate_key_different_amount(self):
        """Reserving same key with different amount returns DUPLICATE_KEY."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 30, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("reserve", ("k1", 50, "r1"), 0, e.next(),
                {"status": "DUPLICATE_KEY"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"should be linearizable: {result.reason}"


# ---------------------------------------------------------------------------
# 2. Negative case: I8 violation is NOT linearizable
# ---------------------------------------------------------------------------

class TestI8ViolationNotLinearizable:
    """Histories that violate I8 must NOT be linearizable."""

    def test_two_reserves_exceeding_capacity_both_succeed(self):
        """Two reserves of 60 each (120 > 100) both returning RESERVED is NOT linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 60, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("reserve", ("k2", 60, "r1"), 1, e.next(),
                {"status": "RESERVED", "reservation_id": "res-1"}, e.next()),
        ]

        result = checker.check(ops)
        assert not result.linearizable, (
            "I8 violation (120 > 100) should NOT be linearizable"
        )

    def test_three_reserves_all_exceeding_capacity(self):
        """Three reserves of 40 each from different clients where the spec
        would only allow two (80 <= 100) — the third succeeding is a violation."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        # The history claims all three succeeded, but capacity is 100 and
        # 40 * 3 = 120 > 100.  This is not linearizable.
        ops = [
            _op("reserve", ("k1", 40, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("reserve", ("k2", 40, "r1"), 1, e.next(),
                {"status": "RESERVED", "reservation_id": "res-1"}, e.next()),
            _op("reserve", ("k3", 40, "r1"), 2, e.next(),
                {"status": "RESERVED", "reservation_id": "res-2"}, e.next()),
        ]

        result = checker.check(ops)
        assert not result.linearizable, (
            "Three reserves of 40 (total 120 > 100) should NOT be linearizable"
        )

    def test_reserve_exceeding_capacity_returns_reserved(self):
        """A single reserve of 150 > 100 returning RESERVED is not linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 150, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
        ]

        result = checker.check(ops)
        assert not result.linearizable, (
            "Reserve 150 > 100 capacity returning RESERVED should NOT be linearizable"
        )

    def test_commit_nonexistent_returns_committed(self):
        """Committing a non-existent reservation and getting COMMITTED is not linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("commit", ("res-999",), 0, e.next(),
                {"status": "COMMITTED"}, e.next()),
        ]

        result = checker.check(ops)
        assert not result.linearizable, (
            "Committing non-existent reservation should NOT be linearizable"
        )

    def test_double_commit_returns_committed_twice(self):
        """Committing the same reservation twice and both returning COMMITTED
        (not ALREADY_COMMITTED the second time) is not linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 30, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("commit", ("res-0",), 0, e.next(),
                {"status": "COMMITTED"}, e.next()),
            _op("commit", ("res-0",), 1, e.next(),
                {"status": "COMMITTED"}, e.next()),  # should be ALREADY_COMMITTED
        ]

        result = checker.check(ops)
        assert not result.linearizable, (
            "Double commit both returning COMMITTED should NOT be linearizable"
        )


# ---------------------------------------------------------------------------
# 3. Concurrent reserve+commit operations are linearizable
# ---------------------------------------------------------------------------

class TestConcurrentOperations:
    """Concurrent (overlapping) operations that are individually valid must be linearizable."""

    def test_concurrent_reserves_within_capacity(self):
        """Two clients concurrently reserve 40 each (total 80 <= 100) — linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        # Client 0 and client 1 operations overlap (interleaved event IDs).
        i0 = e.next()
        i1 = e.next()  # client 1 starts before client 0 finishes
        r0 = e.next()  # client 0 responds
        r1 = e.next()  # client 1 responds

        ops = [
            _op("reserve", ("k1", 40, "r1"), 0, i0,
                {"status": "RESERVED", "reservation_id": "res-0"}, r0),
            _op("reserve", ("k2", 40, "r1"), 1, i1,
                {"status": "RESERVED", "reservation_id": "res-1"}, r1),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"concurrent reserves within capacity should be linearizable: {result.reason}"

    def test_concurrent_reserve_and_commit_different_clients(self):
        """Client 0 reserves, client 1 concurrently commits a different reservation."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        # Sequential setup: reserve k1 (50), commit res-0, then concurrent
        # reserve k2 (30) by client 0 and commit res-0 (already done) by client 1.
        # We test a simpler concurrent scenario: two clients, one reserves,
        # one commits a prior reservation, overlapping.
        ops = [
            # Prior completed operation (client 0, fully done before concurrency)
            _op("reserve", ("k1", 50, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
        ]
        # Concurrent: client 0 reserves k2 (30), client 1 commits res-0
        i_res = e.next()
        i_commit = e.next()
        r_commit = e.next()
        r_res = e.next()
        ops.extend([
            _op("reserve", ("k2", 30, "r1"), 0, i_res,
                {"status": "RESERVED", "reservation_id": "res-1"}, r_res),
            _op("commit", ("res-0",), 1, i_commit,
                {"status": "COMMITTED"}, r_commit),
        ])

        result = checker.check(ops)
        assert result.linearizable, f"concurrent reserve+commit should be linearizable: {result.reason}"

    def test_concurrent_reserve_commit_release(self):
        """Three clients: one reserves, one commits, one releases — all valid, overlapping."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        # Setup: client 0 reserves k1 (40) and k2 (30) sequentially.
        ops = [
            _op("reserve", ("k1", 40, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("reserve", ("k2", 30, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-1"}, e.next()),
        ]

        # Concurrent phase: client 1 commits res-0, client 2 releases res-1,
        # client 0 reserves k3 (30) — all overlapping.
        i_commit = e.next()
        i_release = e.next()
        i_reserve = e.next()
        r_commit = e.next()
        r_release = e.next()
        r_reserve = e.next()

        ops.extend([
            _op("commit", ("res-0",), 1, i_commit,
                {"status": "COMMITTED"}, r_commit),
            _op("release", ("res-1",), 2, i_release,
                {"status": "RELEASED"}, r_release),
            _op("reserve", ("k3", 30, "r1"), 0, i_reserve,
                {"status": "RESERVED", "reservation_id": "res-2"}, r_reserve),
        ])

        result = checker.check(ops)
        assert result.linearizable, f"concurrent reserve/commit/release should be linearizable: {result.reason}"

    def test_concurrent_reserves_at_capacity_boundary(self):
        """Two clients each reserve 50 (total exactly 100) — both succeed, linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        i0 = e.next()
        i1 = e.next()
        r0 = e.next()
        r1 = e.next()

        ops = [
            _op("reserve", ("k1", 50, "r1"), 0, i0,
                {"status": "RESERVED", "reservation_id": "res-0"}, r0),
            _op("reserve", ("k2", 50, "r1"), 1, i1,
                {"status": "RESERVED", "reservation_id": "res-1"}, r1),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"two 50-reserves at boundary should be linearizable: {result.reason}"

    def test_concurrent_reserve_one_succeeds_one_fails(self):
        """Two clients reserve 60 each (120 > 100): one succeeds, one fails — linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        i0 = e.next()
        i1 = e.next()
        r0 = e.next()
        r1 = e.next()

        ops = [
            _op("reserve", ("k1", 60, "r1"), 0, i0,
                {"status": "RESERVED", "reservation_id": "res-0"}, r0),
            _op("reserve", ("k2", 60, "r1"), 1, i1,
                {"status": "INSUFFICIENT_BUDGET"}, r1),
        ]

        result = checker.check(ops)
        assert result.linearizable, f"one success one fail should be linearizable: {result.reason}"


# ---------------------------------------------------------------------------
# 4. Sequential spec correctly models ConsensusBackend
# ---------------------------------------------------------------------------

class TestSequentialSpecMatchesBackend:
    """Verify that consensus_sequential_spec produces the same results as the
    actual FileLockConsensusBackend for identical operation sequences."""

    def test_spec_matches_backend_reserve(self, tmp_path):
        """Spec and backend agree on reserve results."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        # Reserve 30
        b_result = backend.reserve("k1", 30, "r1")
        s_state, s_result = consensus_sequential_spec(
            "reserve", state, ("k1", 30, "r1")
        )

        assert b_result.status == s_result["status"] == "RESERVED"
        assert b_result.amount_reserved == 30
        # Spec tracks reserved amount
        assert s_state["reserved"] == 30

        # Backend state should match spec state
        b_state = backend.get_state("r1")
        assert b_state.reserved == s_state["reserved"] == 30
        assert b_state.available == (s_state["capacity"] - s_state["reserved"] - s_state["consumed"]) == 70

    def test_spec_matches_backend_reserve_commit(self, tmp_path):
        """Spec and backend agree across reserve -> commit sequence."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        # Reserve 40
        b_res = backend.reserve("k1", 40, "r1")
        state, s_res = consensus_sequential_spec("reserve", state, ("k1", 40, "r1"))
        assert b_res.status == s_res["status"] == "RESERVED"

        # Get the reservation IDs (they differ in format but both exist)
        b_rid = b_res.reservation_id
        s_rid = s_res["reservation_id"]
        assert b_rid is not None
        assert s_rid is not None

        # Commit
        b_commit = backend.commit(b_rid)
        state, s_commit = consensus_sequential_spec("commit", state, (s_rid,))
        assert b_commit.status == s_commit["status"] == "COMMITTED"

        # States match
        b_state = backend.get_state("r1")
        assert b_state.reserved == state["reserved"] == 0
        assert b_state.committed == state["consumed"] == 40
        assert b_state.available == (state["capacity"] - state["reserved"] - state["consumed"]) == 60

    def test_spec_matches_backend_reserve_release(self, tmp_path):
        """Spec and backend agree across reserve -> release sequence."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        b_res = backend.reserve("k1", 50, "r1")
        state, s_res = consensus_sequential_spec("reserve", state, ("k1", 50, "r1"))
        assert b_res.status == s_res["status"] == "RESERVED"

        b_rel = backend.release(b_res.reservation_id)
        state, s_rel = consensus_sequential_spec("release", state, (s_res["reservation_id"],))
        assert b_rel.status == s_rel["status"] == "RELEASED"

        b_state = backend.get_state("r1")
        assert b_state.reserved == state["reserved"] == 0
        assert b_state.committed == state["consumed"] == 0
        assert b_state.available == (state["capacity"] - state["reserved"] - state["consumed"]) == 100

    def test_spec_matches_backend_insufficient_budget(self, tmp_path):
        """Spec and backend agree on INSUFFICIENT_BUDGET."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        # Reserve 80
        backend.reserve("k1", 80, "r1")
        state, _ = consensus_sequential_spec("reserve", state, ("k1", 80, "r1"))

        # Try to reserve 30 more (only 20 available)
        b_res = backend.reserve("k2", 30, "r1")
        state, s_res = consensus_sequential_spec("reserve", state, ("k2", 30, "r1"))

        assert b_res.status == s_res["status"] == "INSUFFICIENT_BUDGET"

        # State unchanged
        b_state = backend.get_state("r1")
        assert b_state.reserved == state["reserved"] == 80
        assert b_state.available == (state["capacity"] - state["reserved"] - state["consumed"]) == 20

    def test_spec_matches_backend_already_committed(self, tmp_path):
        """Spec and backend agree on ALREADY_COMMITTED for double commit."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        b_res = backend.reserve("k1", 30, "r1")
        state, s_res = consensus_sequential_spec("reserve", state, ("k1", 30, "r1"))

        # First commit
        backend.commit(b_res.reservation_id)
        state, _ = consensus_sequential_spec("commit", state, (s_res["reservation_id"],))

        # Second commit (double)
        b_commit2 = backend.commit(b_res.reservation_id)
        state, s_commit2 = consensus_sequential_spec("commit", state, (s_res["reservation_id"],))

        assert b_commit2.status == s_commit2["status"] == "ALREADY_COMMITTED"

    def test_spec_matches_backend_not_found(self, tmp_path):
        """Spec and backend agree on NOT_FOUND for non-existent reservation."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        b_commit = backend.commit("nonexistent-rid")
        state, s_commit = consensus_sequential_spec("commit", state, ("nonexistent-rid",))

        assert b_commit.status == s_commit["status"] == "NOT_FOUND"

        b_rel = backend.release("nonexistent-rid")
        state, s_rel = consensus_sequential_spec("release", state, ("nonexistent-rid",))

        assert b_rel.status == s_rel["status"] == "NOT_FOUND"

    def test_spec_matches_backend_idempotent_reserve(self, tmp_path):
        """Spec and backend agree on idempotent reserve (same key, same amount)."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        # First reserve
        b_res1 = backend.reserve("k1", 30, "r1")
        state, s_res1 = consensus_sequential_spec("reserve", state, ("k1", 30, "r1"))
        assert b_res1.status == s_res1["status"] == "RESERVED"

        # Second reserve with same key and amount — idempotent
        b_res2 = backend.reserve("k1", 30, "r1")
        state, s_res2 = consensus_sequential_spec("reserve", state, ("k1", 30, "r1"))
        assert b_res2.status == s_res2["status"] == "RESERVED"

        # Same reservation ID returned (idempotent)
        assert b_res2.reservation_id == b_res1.reservation_id
        assert s_res2["reservation_id"] == s_res1["reservation_id"]

        # Budget not double-counted
        b_state = backend.get_state("r1")
        assert b_state.reserved == state["reserved"] == 30

    def test_spec_matches_backend_duplicate_key(self, tmp_path):
        """Spec and backend agree on DUPLICATE_KEY for same key, different amount."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        backend.reserve("k1", 30, "r1")
        state, _ = consensus_sequential_spec("reserve", state, ("k1", 30, "r1"))

        b_res = backend.reserve("k1", 50, "r1")
        state, s_res = consensus_sequential_spec("reserve", state, ("k1", 50, "r1"))

        assert b_res.status == s_res["status"] == "DUPLICATE_KEY"

    def test_spec_matches_backend_full_cycle(self, tmp_path):
        """Spec and backend agree across a full reserve -> commit -> reserve -> release cycle."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        # reserve k1 (40)
        b1 = backend.reserve("k1", 40, "r1")
        state, s1 = consensus_sequential_spec("reserve", state, ("k1", 40, "r1"))
        assert b1.status == s1["status"] == "RESERVED"

        # commit res-0
        b2 = backend.commit(b1.reservation_id)
        state, s2 = consensus_sequential_spec("commit", state, (s1["reservation_id"],))
        assert b2.status == s2["status"] == "COMMITTED"

        # reserve k2 (50)
        b3 = backend.reserve("k2", 50, "r1")
        state, s3 = consensus_sequential_spec("reserve", state, ("k2", 50, "r1"))
        assert b3.status == s3["status"] == "RESERVED"

        # release res-1
        b4 = backend.release(b3.reservation_id)
        state, s4 = consensus_sequential_spec("release", state, (s3["reservation_id"],))
        assert b4.status == s4["status"] == "RELEASED"

        # Final state comparison
        b_state = backend.get_state("r1")
        assert b_state.reserved == state["reserved"] == 0
        assert b_state.committed == state["consumed"] == 40
        assert b_state.available == (state["capacity"] - state["reserved"] - state["consumed"]) == 60

    def test_spec_models_get_state(self, tmp_path):
        """The sequential spec's get_state operation matches backend get_state."""
        backend = FileLockConsensusBackend(str(tmp_path))
        backend.register_resource("r1", 100)
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}

        # Perform some operations
        backend.reserve("k1", 30, "r1")
        state, _ = consensus_sequential_spec("reserve", state, ("k1", 30, "r1"))

        backend.reserve("k2", 20, "r1")
        state, _ = consensus_sequential_spec("reserve", state, ("k2", 20, "r1"))

        # Compare get_state
        b_state = backend.get_state("r1")
        _, s_state = consensus_sequential_spec("get_state", state, ("r1",))

        assert b_state.available == s_state["available"] == 50
        assert b_state.reserved == s_state["reserved"] == 50
        assert b_state.committed == s_state["consumed"] == 0
        assert b_state.capacity == s_state["capacity"] == 100


# ---------------------------------------------------------------------------
# 5. Linearization output verification
# ---------------------------------------------------------------------------

class TestLinearizationOutput:
    """Verify that the checker returns a valid linearization for linearizable histories."""

    def test_linearization_is_valid_sequence(self):
        """The returned linearization should be a valid sequential execution."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 40, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
            _op("reserve", ("k2", 30, "r1"), 1, e.next(),
                {"status": "RESERVED", "reservation_id": "res-1"}, e.next()),
            _op("commit", ("res-0",), 0, e.next(),
                {"status": "COMMITTED"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable
        assert len(result.linearization) == 3

        # Replay the linearization through the spec and verify results match.
        state = {"capacity": 100, "reserved": 0, "consumed": 0, "reservations": {}}
        for op in result.linearization:
            state, spec_result = consensus_sequential_spec(
                op.op, state, op.invocation.args
            )
            assert spec_result["status"] == op.response.result["status"], (
                f"linearization result mismatch for {op.op}: "
                f"spec={spec_result['status']}, history={op.response.result['status']}"
            )

    def test_empty_history_is_linearizable(self):
        """An empty history is trivially linearizable."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        result = checker.check([])
        assert result.linearizable
        assert result.linearization == []

    def test_single_reserve_linearization(self):
        """A single reserve has a trivial linearization."""
        checker = LinearizabilityChecker(consensus_sequential_spec)
        e = EventIdCounter()

        ops = [
            _op("reserve", ("k1", 50, "r1"), 0, e.next(),
                {"status": "RESERVED", "reservation_id": "res-0"}, e.next()),
        ]

        result = checker.check(ops)
        assert result.linearizable
        assert len(result.linearization) == 1
        assert result.linearization[0].op == "reserve"
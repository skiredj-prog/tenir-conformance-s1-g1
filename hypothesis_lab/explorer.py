"""Finite-state adversarial explorer for REG Hypothesis Lab.

Outcomes:
  FAIL         — reachable state violates invariant; shortest trace returned
  PASS         — complete exploration of finite model; no violation
  VACUOUS      — invariant holds only because trigger is unreachable
  INCONCLUSIVE — state/depth cap hit before closure
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, Iterable


@dataclass(frozen=True)
class TraceStep:
    action: str
    state: Hashable


@dataclass
class ExploreResult:
    status: str
    hypothesis_id: str
    invariant: str
    states_visited: int
    depth_max: int
    counterexample: list[TraceStep] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "hypothesis_id": self.hypothesis_id,
            "invariant": self.invariant,
            "states_visited": self.states_visited,
            "depth_max": self.depth_max,
            "counterexample": (
                [{"action": s.action, "state": list(s.state) if isinstance(s.state, tuple) else s.state}
                 for s in self.counterexample]
                if self.counterexample else None
            ),
            "notes": self.notes,
        }


def explore(
    *,
    hypothesis_id: str,
    invariant_name: str,
    initial: Hashable,
    actions: dict[str, Callable[[Hashable], Iterable[Hashable]]],
    violates: Callable[[Hashable], bool],
    trigger_present: Callable[[Hashable], bool] | None = None,
    max_states: int = 50_000,
    max_depth: int = 40,
) -> ExploreResult:
    from collections import deque

    parent: dict[Hashable, tuple[Hashable | None, str | None]] = {initial: (None, None)}
    q: deque[tuple[Hashable, int]] = deque([(initial, 0)])
    visited = {initial}
    depth_max = 0
    violation: Hashable | None = None

    while q:
        state, depth = q.popleft()
        depth_max = max(depth_max, depth)
        if violates(state):
            violation = state
            break
        if depth >= max_depth:
            continue
        for name, fn in actions.items():
            for nxt in fn(state):
                if nxt in visited:
                    continue
                visited.add(nxt)
                parent[nxt] = (state, name)
                if len(visited) > max_states:
                    return ExploreResult(
                        status="INCONCLUSIVE",
                        hypothesis_id=hypothesis_id,
                        invariant=invariant_name,
                        states_visited=len(visited),
                        depth_max=depth_max,
                        notes=[f"state cap {max_states} exceeded"],
                    )
                q.append((nxt, depth + 1))

    if violation is not None:
        trace: list[TraceStep] = []
        cur: Hashable | None = violation
        while cur is not None:
            prev, act = parent[cur]
            if act is not None:
                trace.append(TraceStep(action=act, state=cur))
            cur = prev
        trace.reverse()
        return ExploreResult(
            status="FAIL",
            hypothesis_id=hypothesis_id,
            invariant=invariant_name,
            states_visited=len(visited),
            depth_max=depth_max,
            counterexample=trace,
            notes=["shortest reachable counterexample"],
        )

    if trigger_present is not None and not any(trigger_present(s) for s in visited):
        return ExploreResult(
            status="VACUOUS",
            hypothesis_id=hypothesis_id,
            invariant=invariant_name,
            states_visited=len(visited),
            depth_max=depth_max,
            notes=["invariant never triggered: antecedent unreachable in this model"],
        )

    return ExploreResult(
        status="PASS",
        hypothesis_id=hypothesis_id,
        invariant=invariant_name,
        states_visited=len(visited),
        depth_max=depth_max,
        notes=["complete finite exploration; no violation"],
    )

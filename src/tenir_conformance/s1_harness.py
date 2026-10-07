"""
S1 G1 Harness — Evidence Lost After Commit

Minimal executable state machine that realises the G0 assertions for S1a/S1b/S1c.

IMPORTANT EPISTEMIC BOUNDARY
----------------------------
This harness is a self-contained toy. It does NOT call any real REG/TENIR
PolicyEngine, gateway, or distributed system. Passing tests only prove that
*this harness* satisfies the G0 assertions. They do not validate REG itself.

To turn this into genuine empirical evidence against a real subject, replace
the internal state machine with an adapter that drives the actual kernel
under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any


class ExecState(str, Enum):
    UNKNOWN = "UNKNOWN"
    COMMITTED = "COMMITTED"


class ReconState(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class Disposition(str, Enum):
    HOLD = "HOLD"
    ALLOW = "ALLOW"


@dataclass
class FakeClock:
    now_ms: int = 1_000_000

    def tick(self, delta_ms: int = 1) -> int:
        self.now_ms += delta_ms
        return self.now_ms


@dataclass
class Effect:
    lei: str
    attempt_id: str
    payload: str


@dataclass
class EffectSink:
    entries: list[Effect] = field(default_factory=list)

    def execute(self, effect: Effect) -> None:
        self.entries.append(effect)

    def count(self) -> int:
        return len(self.entries)

    def snapshot(self) -> dict[str, Any]:
        return {
            "count": self.count(),
            "entries": [
                {
                    "lei": e.lei,
                    "attempt_id": e.attempt_id,
                    "payload": e.payload,
                }
                for e in self.entries
            ],
        }


@dataclass
class Permit:
    lei: str
    attempt_id: str
    state: str = "ISSUED"
    nonce: str = ""


@dataclass
class PermitStore:
    permits: list[Permit] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def issue(self, clock: FakeClock, lei: str, attempt_id: str, nonce: str) -> Permit:
        permit = Permit(lei=lei, attempt_id=attempt_id, nonce=nonce)
        self.permits.append(permit)
        self.events.append({
            "ts_ms": clock.tick(),
            "event": "PERMIT_ISSUED",
            "lei": lei,
            "attempt_id": attempt_id,
            "nonce": nonce,
        })
        return permit

    def has_unresolved(self, lei: str) -> bool:
        return any(p.lei == lei and p.state == "ISSUED" for p in self.permits)

    def issued_count(self, lei: str) -> int:
        return sum(1 for p in self.permits if p.lei == lei and p.state == "ISSUED")


class TransitionLog:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.events: list[dict[str, Any]] = []

    def append(self, event: str, **fields: Any) -> None:
        self.events.append({
            "ts_ms": self.clock.tick(),
            "event": event,
            **fields,
        })

    def event_names(self) -> list[str]:
        return [e["event"] for e in self.events]

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(e, sort_keys=True) + "\n" for e in self.events),
            encoding="utf-8",
        )


@dataclass(frozen=True)
class FaultCase:
    case_id: str
    target_effect: int
    target_receipt: int
    target_outcome: str


class S1Gateway:
    """
    Minimal G1 state machine.

    The client sees only protocol state and disposition.
    Target truth is not exposed by retry().
    """

    def __init__(
        self,
        *,
        clock: FakeClock,
        sink: EffectSink,
        permits: PermitStore,
        log: TransitionLog,
    ) -> None:
        self.clock = clock
        self.sink = sink
        self.permits = permits
        self.log = log
        self.exec_state: dict[str, ExecState] = {}
        self.recon_state: dict[str, ReconState] = {}

    def seed_issued_attempt(
        self, lei: str, attempt_id: str, nonce: str, *, target_effect: bool,
    ) -> None:
        self.permits.issue(self.clock, lei, attempt_id, nonce)
        self.exec_state[attempt_id] = (
            ExecState.COMMITTED if target_effect else ExecState.UNKNOWN
        )
        self.recon_state[attempt_id] = ReconState.PENDING

        if target_effect:
            self.sink.execute(
                Effect(lei=lei, attempt_id=attempt_id, payload="A")
            )
        self.log.append(
            "SEED_ATTEMPT",
            lei=lei,
            attempt_id=attempt_id,
            exec_truth=self.exec_state[attempt_id].value,
            receipt_observed=False,
        )

    def receipt_lost(self, lei: str, attempt_id: str) -> None:
        self.log.append(
            "T3_ReceiptLost",
            lei=lei,
            attempt_id=attempt_id,
            client_observation="NO_RECEIPT",
        )

    def t1_issue_permit_guard(self, lei: str) -> bool:
        allowed = not self.permits.has_unresolved(lei)
        self.log.append(
            "T1_guard_TRUE" if allowed else "T1_guard_FALSE",
            lei=lei,
            unresolved_same_lei=self.permits.has_unresolved(lei),
        )
        return allowed

    def retry_without_reconciliation(
        self, *, lei: str, attempt_id: str, fresh_nonce: str
    ) -> dict[str, Any]:
        self.receipt_lost(lei, attempt_id)

        if self.t1_issue_permit_guard(lei):
            self.permits.issue(self.clock, lei, attempt_id, fresh_nonce)
            self.sink.execute(
                Effect(lei=lei, attempt_id=attempt_id, payload="A")
            )
            response = Disposition.ALLOW.value
            exec_state = ExecState.COMMITTED.value
        else:
            response = Disposition.HOLD.value
            exec_state = ExecState.UNKNOWN.value

        return {
            "exec": exec_state,
            "recon": ReconState.PENDING.value,
            "client_response": response,
            "permit_issued_for_retry": response == Disposition.ALLOW.value,
            "effect_count": self.sink.count(),
        }


FAULT_CASES = {
    "S1a": FaultCase(
        case_id="S1a",
        target_effect=0,
        target_receipt=0,
        target_outcome="REQUEST_LOST",
    ),
    "S1b": FaultCase(
        case_id="S1b",
        target_effect=1,
        target_receipt=0,
        target_outcome="COMMITTED_RESPONSE_LOST",
    ),
    "S1c": FaultCase(
        case_id="S1c",
        target_effect=0,
        target_receipt=0,
        target_outcome="REJECTED_RESPONSE_LOST",
    ),
}


def run_case(case: FaultCase) -> dict[str, Any]:
    clock = FakeClock()
    sink = EffectSink()
    permits = PermitStore()
    log = TransitionLog(clock)
    gateway = S1Gateway(
        clock=clock,
        sink=sink,
        permits=permits,
        log=log,
    )

    lei = "L"
    attempt_id = "A"

    gateway.seed_issued_attempt(
        lei=lei,
        attempt_id=attempt_id,
        nonce="nonce-A",
        target_effect=bool(case.target_effect),
    )

    baseline_effect_count = sink.count()
    baseline_permit_count = permits.issued_count(lei)

    result = gateway.retry_without_reconciliation(
        lei=lei,
        attempt_id="A-retry",
        fresh_nonce="nonce-retry",
    )

    result.update({
        "scenario": "S1",
        "subcase": case.case_id,
        "target_truth": {
            "effect_count": case.target_effect,
            "receipt": case.target_receipt,
            "outcome": case.target_outcome,
        },
        "oracle": {
            "baseline_effect_count": baseline_effect_count,
            "final_effect_count": sink.count(),
            "baseline_permit_count": baseline_permit_count,
            "final_permit_count": permits.issued_count(lei),
            "client_observation": "NO_RECEIPT",
        },
        "transition_events": log.event_names(),
        "transition_log": log.events,
        "permit_log": permits.events,
        "effect_sink": sink.snapshot(),
    })
    return result

"""S2 — Qualification Timeout against the RFC-4 membrane."""

from pathlib import Path
import json
import hashlib

from tenir_conformance.membrane.membrane import (
    FakeClock,
    Membrane,
    AttemptState,
    Receipt,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
TAU_K_MS = 5_000
ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "G0_S2_Qualification_Timeout.md"
SCENARIO_PATH = ROOT / "scenarios" / "S2.json"
ARTIFACTS = ROOT / "artifacts" / "s2"


def _spec_sha() -> str:
    if SPEC_PATH.is_file():
        return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()
    return ""


def _scenario_sha() -> str:
    if SCENARIO_PATH.is_file():
        return hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest()
    return ""


def _dump_s2(membrane: Membrane, subcase: str, extra: dict | None = None) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    extra = extra or {}
    events = list(membrane.events)
    body = {
        "subcase": subcase,
        "spec_sha256": _spec_sha(),
        "scenario_sha256": _scenario_sha(),
        "effect_sink_count": len(membrane.sink.effects),
        "attempts": {
            k: {"lei": a.lei, "state": a.state.value, "timeout_fired": a.timeout_fired, "qualified": a.qualified}
            for k, a in membrane.attempts.items()
        },
        "permits": {k: {"lei": p.lei, "consumed": p.consumed} for k, p in membrane.permits.items()},
        "transition_log": events,
        **extra,
    }
    with (ARTIFACTS / f"evidence_G0_{subcase}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(body, sort_keys=True) + "\n")
    (ARTIFACTS / f"{subcase}_transition.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    (ARTIFACTS / f"{subcase}_permit.json").write_text(json.dumps(body["permits"], indent=2), encoding="utf-8")
    (ARTIFACTS / f"{subcase}_effect_sink.json").write_text(json.dumps(membrane.sink.effects, indent=2), encoding="utf-8")
    (ARTIFACTS / f"{subcase}_result.json").write_text(
        json.dumps({"subcase": subcase, "spec_sha256": body["spec_sha256"],
                    "scenario_sha256": body["scenario_sha256"], **extra}, indent=2), encoding="utf-8")


def _membrane(clock: FakeClock | None = None) -> Membrane:
    return Membrane(KernelBridge(), clock=clock or FakeClock(now_ms=1_000_000), tau_k_ms=TAU_K_MS)


def test_s2a_pure_qualification_timeout_hold_and_blocks_retry():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    first = m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    assert first.disposition.value == "HOLD"
    baseline_effects = len(m.sink.effects)
    clock.advance_to(1_000_000 + TAU_K_MS)
    fired = m.check_qualification_timeouts()
    assert fired == ["A"]
    retry = m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert retry.disposition.value == "HOLD"
    assert retry.kernel_decision == "NOT_EVALUATED"
    assert len(m.sink.effects) == baseline_effects
    event_names = [e["event"] for e in m.events]
    assert "T_QualificationTimeout" in event_names
    assert "T1_guard_FALSE" in event_names
    _dump_s2(m, "S2a", {"disposition": retry.disposition.value, "client_state": retry.client_state,
                         "timeout_fired": True, "claim_scope": "sequential interleavings only"})


def test_s2b_timeout_then_late_receipt_does_not_auto_commit():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    late = m.deliver_qualifying_receipt(Receipt(attempt_id="A", lei="L", nonce="n-s2"))
    assert late.timeout_event is True
    assert late.disposition.value == "HOLD"
    assert m.attempts["A"].state == AttemptState.UNKNOWN
    assert m.attempts["A"].qualified is False
    event_names = [e["event"] for e in m.events]
    assert "LATE_RECEIPT_AFTER_TIMEOUT_NO_AUTO_COMMIT" in event_names
    _dump_s2(m, "S2b", {"disposition": late.disposition.value, "client_state": late.client_state,
                         "timeout_event": late.timeout_event, "claim_scope": "sequential interleavings only"})


def test_s2c_receipt_inside_window_does_not_fire_timeout():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    clock.tick(1_000)
    result = m.deliver_qualifying_receipt(Receipt(attempt_id="A", lei="L", nonce="n-s2"))
    assert result.timeout_event is False
    assert result.disposition.value == "PASS"
    assert result.client_state == "RESOLVED"
    assert m.attempts["A"].qualified is True
    event_names = [e["event"] for e in m.events]
    assert "T_QualificationTimeout" not in event_names
    assert "RECEIPT_QUALIFIED" in event_names
    _dump_s2(m, "S2c", {"disposition": "PASS", "client_state": "RESOLVED",
                         "timeout_fired": False, "claim_scope": "sequential interleavings only"})


def test_s2_unbound_receipt_rejected():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=False, nonce="n-s2")
    bad = m.deliver_qualifying_receipt(attempt_id="A", bound=False)
    assert bad.disposition.value == "HOLD"
    assert m.attempts["A"].qualified is False
    assert "RECEIPT_REJECTED_UNBOUND" in [e["event"] for e in m.events]


def test_s2_scenario_definition_present_and_hashed():
    scenario = Path(__file__).parents[1] / "scenarios" / "S2.json"
    assert scenario.exists()
    payload = json.loads(scenario.read_text(encoding="utf-8"))
    assert payload["id"] == "S2"
    assert len(hashlib.sha256(scenario.read_bytes()).hexdigest()) == 64


def test_s2_retry_does_not_call_kernel_after_timeout():
    class CountingBridge(KernelBridge):
        def __init__(self):
            super().__init__()
            self.calls = 0
        def evaluate(self, payload):
            self.calls += 1
            return super().evaluate(payload)
    clock = FakeClock(now_ms=1_000_000)
    bridge = CountingBridge()
    m = Membrane(bridge, clock=clock, tau_k_ms=TAU_K_MS)
    m.admit_and_await_qualification(lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    assert bridge.calls == 1
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert bridge.calls == 1


def test_timeout_fires_exactly_at_tau_k_boundary():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    await_until = m.attempts["A"].await_until_ms
    clock.advance_to(await_until - 1)
    assert m.check_qualification_timeouts() == []
    clock.advance_to(await_until)
    assert m.check_qualification_timeouts() == ["A"]


def test_check_qualification_timeouts_is_idempotent():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=False, nonce="n-s2")
    clock.advance_to(1_000_000 + TAU_K_MS)
    assert m.check_qualification_timeouts() == ["A"]
    n_events = len(m.events)
    assert m.check_qualification_timeouts() == []
    assert len(m.events) == n_events


def test_timeout_without_effect_still_blocks_retry():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=False, nonce="n-s2")
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    retry = m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert retry.disposition.value == "HOLD"
    assert retry.kernel_decision == "NOT_EVALUATED"


def test_timeout_independent_per_lei():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A-L", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    other = m.admit_and_await_qualification(lei="M", attempt_id="A-M", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    assert other.kernel_decision != "NOT_EVALUATED"
    assert m.attempts["A-M"].state == AttemptState.AWAITING_QUALIFICATION


def test_retry_implicitly_fires_timeout_before_guard():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    clock.advance_to(1_000_000 + TAU_K_MS)
    retry = m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert m.attempts["A"].timeout_fired is True
    assert retry.disposition.value == "HOLD"


def test_two_attempts_same_lei_second_blocked_before_timeout():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    second = m.admit_and_await_qualification(lei="L", attempt_id="A2", payload=PAYLOAD, apply_effect=True, nonce="n-s2")
    assert second.kernel_decision == "NOT_EVALUATED"
    assert "A2" not in m.attempts

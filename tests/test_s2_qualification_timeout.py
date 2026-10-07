"""S2 — Qualification Timeout against the RFC-4 membrane."""

from pathlib import Path
import json
import hashlib

from tenir_conformance.membrane.membrane import (
    FakeClock,
    Membrane,
    AttemptState,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
TAU_K_MS = 5_000


def _membrane(clock: FakeClock | None = None) -> Membrane:
    return Membrane(
        KernelBridge(),
        clock=clock or FakeClock(now_ms=1_000_000),
        tau_k_ms=TAU_K_MS,
    )


def test_s2a_pure_qualification_timeout_hold_and_blocks_retry():
    """No receipt before tau_K -> timeout -> HOLD/UNKNOWN -> retry blocked."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)

    first = m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True
    )
    assert first.disposition.value == "HOLD"
    assert first.client_state == "UNKNOWN"
    assert m.attempts["A"].state == AttemptState.AWAITING_QUALIFICATION
    baseline_effects = len(m.sink.effects)
    assert baseline_effects == 1

    clock.advance_to(1_000_000 + TAU_K_MS)
    fired = m.check_qualification_timeouts()
    assert fired == ["A"]
    assert m.attempts["A"].timeout_fired is True
    assert m.attempts["A"].state == AttemptState.UNKNOWN

    retry = m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert retry.disposition.value == "HOLD"
    assert retry.client_state == "UNKNOWN"
    assert retry.kernel_decision == "NOT_EVALUATED"
    assert retry.retry_permit_issued is False
    assert len(m.sink.effects) == baseline_effects

    event_names = [e["event"] for e in m.events]
    assert "T_QualificationTimeout" in event_names
    assert "T1_guard_FALSE" in event_names
    assert event_names.index("T_QualificationTimeout") < event_names.index(
        "T1_guard_FALSE"
    )


def test_s2b_timeout_then_late_receipt_does_not_auto_commit():
    """After tau_K, a late receipt must not auto-commit."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)

    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True
    )
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    assert m.attempts["A"].timeout_fired is True

    late = m.deliver_qualifying_receipt(attempt_id="A", bound=True)
    assert late.timeout_event is True
    assert late.disposition.value == "HOLD"
    assert late.client_state == "UNKNOWN"
    assert m.attempts["A"].state == AttemptState.UNKNOWN
    assert m.attempts["A"].qualified is False

    retry = m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert retry.disposition.value == "HOLD"
    assert retry.kernel_decision == "NOT_EVALUATED"
    assert len(m.sink.effects) == 1

    event_names = [e["event"] for e in m.events]
    assert "LATE_RECEIPT_AFTER_TIMEOUT_NO_AUTO_COMMIT" in event_names


def test_s2c_receipt_inside_window_does_not_fire_timeout():
    """Negative control: qualifying receipt before tau_K -> no timeout event."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)

    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True
    )
    clock.tick(1_000)
    result = m.deliver_qualifying_receipt(attempt_id="A", bound=True)

    assert result.timeout_event is False
    assert result.disposition.value == "PASS"
    assert result.client_state == "RESOLVED"
    assert m.attempts["A"].qualified is True
    assert m.attempts["A"].timeout_fired is False

    event_names = [e["event"] for e in m.events]
    assert "T_QualificationTimeout" not in event_names
    assert "RECEIPT_QUALIFIED" in event_names


def test_s2_unbound_receipt_rejected():
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=False
    )
    bad = m.deliver_qualifying_receipt(attempt_id="A", bound=False)
    assert bad.disposition.value == "HOLD"
    assert m.attempts["A"].qualified is False
    event_names = [e["event"] for e in m.events]
    assert "RECEIPT_REJECTED_UNBOUND" in event_names


def test_s2_scenario_definition_present_and_hashed():
    scenario = Path(__file__).parents[1] / "scenarios" / "S2.json"
    assert scenario.exists()
    payload = json.loads(scenario.read_text(encoding="utf-8"))
    assert payload["id"] == "S2"
    assert payload["locked_name"] == "Qualification Timeout"
    assert "S2a" in payload["subcases"]
    sha = hashlib.sha256(scenario.read_bytes()).hexdigest()
    assert len(sha) == 64


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
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True
    )
    assert bridge.calls == 1
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert bridge.calls == 1

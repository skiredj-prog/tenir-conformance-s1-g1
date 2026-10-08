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
    """Write the five physical S2 evidence artifacts (G0 empiricism)."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    extra = extra or {}
    events = list(membrane.events)
    body = {
        "subcase": subcase,
        "spec_sha256": _spec_sha(),
        "scenario_sha256": _scenario_sha(),
        "effect_sink_count": len(membrane.sink.effects),
        "attempts": {
            k: {
                "lei": a.lei,
                "state": a.state.value,
                "timeout_fired": a.timeout_fired,
                "qualified": a.qualified,
            }
            for k, a in membrane.attempts.items()
        },
        "permits": {
            k: {"lei": p.lei, "consumed": p.consumed}
            for k, p in membrane.permits.items()
        },
        "transition_log": events,
        **extra,
    }
    with (ARTIFACTS / f"evidence_G0_{subcase}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(body, sort_keys=True) + "\n")
    (ARTIFACTS / f"{subcase}_transition.json").write_text(
        json.dumps(events, indent=2), encoding="utf-8"
    )
    (ARTIFACTS / f"{subcase}_permit.json").write_text(
        json.dumps(body["permits"], indent=2), encoding="utf-8"
    )
    (ARTIFACTS / f"{subcase}_effect_sink.json").write_text(
        json.dumps(membrane.sink.effects, indent=2), encoding="utf-8"
    )
    (ARTIFACTS / f"{subcase}_result.json").write_text(
        json.dumps(
            {
                "subcase": subcase,
                "spec_sha256": body["spec_sha256"],
                "scenario_sha256": body["scenario_sha256"],
                **{k: v for k, v in extra.items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


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
    _dump_s2(
        m,
        "S2a",
        {
            "disposition": retry.disposition.value,
            "client_state": retry.client_state,
            "timeout_fired": True,
            "claim_scope": "sequential interleavings only",
        },
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

    _dump_s2(
        m,
        "S2b",
        {
            "disposition": late.disposition.value,
            "client_state": late.client_state,
            "timeout_event": late.timeout_event,
            "claim_scope": "sequential interleavings only",
        },
    )


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

    _dump_s2(
        m,
        "S2c",
        {
            "disposition": "PASS",
            "client_state": "RESOLVED",
            "timeout_fired": False,
            "claim_scope": "sequential interleavings only",
        },
    )


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


# ── Additional timeout edge cases ───────────────────────────────────────────


def test_timeout_fires_exactly_at_tau_k_boundary():
    """Window closes at now == await_until_ms; one ms earlier must not fire."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True
    )
    await_until = m.attempts["A"].await_until_ms
    assert await_until == 1_000_000 + TAU_K_MS

    clock.advance_to(await_until - 1)
    assert m.check_qualification_timeouts() == []
    assert m.attempts["A"].timeout_fired is False
    assert m.attempts["A"].state == AttemptState.AWAITING_QUALIFICATION

    clock.advance_to(await_until)
    assert m.check_qualification_timeouts() == ["A"]
    assert m.attempts["A"].timeout_fired is True
    assert m.attempts["A"].state == AttemptState.UNKNOWN


def test_check_qualification_timeouts_is_idempotent():
    """Second check after fire must not duplicate events or re-fire."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=False
    )
    clock.advance_to(1_000_000 + TAU_K_MS)
    assert m.check_qualification_timeouts() == ["A"]
    n_events = len(m.events)
    assert m.check_qualification_timeouts() == []
    assert m.check_qualification_timeouts() == []
    assert len(m.events) == n_events
    assert sum(1 for e in m.events if e["event"] == "T_QualificationTimeout") == 1


def test_timeout_without_effect_still_blocks_retry():
    """apply_effect=False path: timeout still yields HOLD and blocks retry."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=False
    )
    assert len(m.sink.effects) == 0
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    retry = m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert retry.disposition.value == "HOLD"
    assert retry.client_state == "UNKNOWN"
    assert retry.kernel_decision == "NOT_EVALUATED"
    assert len(m.sink.effects) == 0


def test_timeout_independent_per_lei():
    """Timeout on LEI L must not block a fresh attempt on LEI M."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A-L", payload=PAYLOAD, apply_effect=True
    )
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    assert m.attempts["A-L"].timeout_fired is True

    other = m.admit_and_await_qualification(
        lei="M", attempt_id="A-M", payload=PAYLOAD, apply_effect=True
    )
    assert other.disposition.value == "HOLD"
    assert other.kernel_decision != "NOT_EVALUATED"
    assert m.attempts["A-M"].state == AttemptState.AWAITING_QUALIFICATION
    assert m.attempts["A-M"].timeout_fired is False


def test_retry_implicitly_fires_timeout_before_guard():
    """retry() must call check_qualification_timeouts before T1 guard."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True
    )
    clock.advance_to(1_000_000 + TAU_K_MS)
    retry = m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert m.attempts["A"].timeout_fired is True
    assert retry.disposition.value == "HOLD"
    event_names = [e["event"] for e in m.events]
    assert "T_QualificationTimeout" in event_names
    assert "T1_guard_FALSE" in event_names
    assert event_names.index("T_QualificationTimeout") < event_names.index(
        "T1_guard_FALSE"
    )


def test_two_attempts_same_lei_second_blocked_before_timeout():
    """Even before tau_K, second admit on same LEI is blocked (unresolved)."""
    clock = FakeClock(now_ms=1_000_000)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True
    )
    second = m.admit_and_await_qualification(
        lei="L", attempt_id="A2", payload=PAYLOAD, apply_effect=True
    )
    assert second.disposition.value == "HOLD"
    assert second.kernel_decision == "NOT_EVALUATED"
    assert "A2" not in m.attempts
    assert len(m.sink.effects) == 1

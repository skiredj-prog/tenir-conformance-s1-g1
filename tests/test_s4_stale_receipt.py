"""G0 S4 — Stale Receipt; strict A6 Receipt mandatory for RESOLVED."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tenir_conformance.membrane.membrane import (
    AttemptState,
    FakeClock,
    Membrane,
    Receipt,
    StaleReceiptError,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "G0_S4_Stale_Receipt.md"
SCENARIO_PATH = ROOT / "scenarios" / "S4.json"
ARTIFACTS = ROOT / "artifacts" / "s4"
TAU = 5_000


def _m(clock=None):
    return Membrane(KernelBridge(), clock=clock or FakeClock(now_ms=1_000_000), tau_k_ms=TAU)


def _spec_sha() -> str:
    assert SPEC_PATH.is_file()
    return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()


def _scenario_sha() -> str:
    return hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest()


def _dump(membrane: Membrane, subcase: str, extra: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    events = list(membrane.events)
    body = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "subcase": subcase,
        "spec_sha256": _spec_sha(),
        "scenario_sha256": _scenario_sha(),
        "effect_sink_count": len(membrane.sink.effects),
        "attempts": {
            k: {"lei": a.lei, "state": a.state.value, "timeout_fired": a.timeout_fired,
                "qualified": a.qualified, "nonce": a.nonce}
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
                    "scenario_sha256": body["scenario_sha256"],
                    "client": extra.get("client"), "disposition": extra.get("disposition")}, indent=2),
        encoding="utf-8",
    )


def test_s4a_window_closed_late_receipt():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n-s4a")
    baseline = len(m.sink.effects)
    assert baseline == 1
    clock.advance_to(1_000_000 + TAU)
    m.check_qualification_timeouts()
    r = m.deliver_qualifying_receipt(Receipt(attempt_id="A1", lei="L", nonce="n-s4a"))
    assert r.disposition.value == "HOLD"
    assert m.attempts["A1"].state != AttemptState.RESOLVED
    assert len(m.sink.effects) == baseline
    events = [e["event"] for e in m.events]
    assert "RECEIPT_REJECTED" in events or "LATE_RECEIPT_AFTER_TIMEOUT_NO_AUTO_COMMIT" in events
    _dump(m, "S4a", {"client": r.client_state, "disposition": r.disposition.value,
                      "claim_scope": "sequential interleavings only"})


def test_s4b_open_window_expired_token():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n-s4b")
    baseline = len(m.sink.effects)
    with pytest.raises(StaleReceiptError):
        m.deliver_qualifying_receipt(
            Receipt(attempt_id="A1", lei="L", nonce="n-s4b", expires_at_ms=1_000_000 - 1)
        )
    assert m.attempts["A1"].state != AttemptState.RESOLVED
    assert len(m.sink.effects) == baseline
    assert "STALE_RECEIPT" in [e["event"] for e in m.events]
    _dump(m, "S4b", {"client": "StaleReceiptError", "disposition": "REJECT",
                      "claim_scope": "sequential interleavings only"})


def test_s4_fresh_receipt_still_qualifies():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n-ok")
    r = m.deliver_qualifying_receipt(
        Receipt(attempt_id="A1", lei="L", nonce="n-ok", expires_at_ms=1_000_000 + 60_000)
    )
    assert r.disposition.value == "PASS"
    assert m.attempts["A1"].state == AttemptState.RESOLVED


def test_s4_spec_hashes():
    assert len(_spec_sha()) == 64
    assert len(_scenario_sha()) == 64


def test_s4_binding_mismatch_rejects():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n-ok")
    baseline = len(m.sink.effects)
    r = m.deliver_qualifying_receipt(Receipt(attempt_id="A1", lei="WRONG", nonce="n-ok"))
    assert r.disposition.value == "HOLD"
    assert m.attempts["A1"].state != AttemptState.RESOLVED
    assert "RECEIPT_REJECTED_BINDING" in [e["event"] for e in m.events]
    r2 = m.deliver_qualifying_receipt(Receipt(attempt_id="A1", lei="L", nonce="n-bad"))
    assert r2.disposition.value == "HOLD"
    assert len(m.sink.effects) == baseline


def test_s4_stale_path_does_not_issue_new_permit():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n")
    clock.advance_to(1_000_000 + TAU)
    m.check_qualification_timeouts()
    before = set(m.permits.keys())
    m.deliver_qualifying_receipt(Receipt(attempt_id="A1", lei="L", nonce="n"))
    assert set(m.permits.keys()) == before == {"A1"}
    assert m.attempts["A1"].state != AttemptState.RESOLVED


def test_s4_receipt_attempt_id_mismatch():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n")
    with pytest.raises(KeyError):
        m.deliver_qualifying_receipt(Receipt(attempt_id="A-OTHER", lei="L", nonce="n"))


def test_s4_legacy_kwargs_cannot_resolve():
    """A6: legacy kwargs path must not transition to RESOLVED."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n")
    r = m.deliver_qualifying_receipt(attempt_id="A1", bound=True, lei="L", nonce="n")
    assert r.disposition.value == "HOLD"
    assert m.attempts["A1"].state == AttemptState.AWAITING_QUALIFICATION
    assert m.attempts["A1"].qualified is False
    assert any(e.get("reason") == "RECEIPT_OBJECT_REQUIRED" for e in m.events)


def test_s4_empty_nonce_rejects_qualification():
    """A6: attempt without registered nonce cannot be qualified."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="")
    r = m.deliver_qualifying_receipt(Receipt(attempt_id="A1", lei="L", nonce="anything"))
    assert r.disposition.value == "HOLD"
    assert m.attempts["A1"].state != AttemptState.RESOLVED
    assert any(e.get("reason") == "NONCE_NOT_REGISTERED" for e in m.events
               if e.get("event") == "RECEIPT_REJECTED_BINDING")



def test_s4_receipt_cannot_resolve_without_observed_effect():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=False, nonce="n-no-effect"
    )
    result = m.deliver_qualifying_receipt(
        Receipt(attempt_id="A1", lei="L", nonce="n-no-effect")
    )
    assert result.disposition.value == "HOLD"
    assert m.attempts["A1"].state == AttemptState.AWAITING_QUALIFICATION
    assert m.attempts["A1"].qualified is False
    assert m.attempts["A1"].effect_observed is False
    assert len(m.sink.effects) == 0
    assert "RECEIPT_REJECTED_NO_OBSERVED_EFFECT" in [e["event"] for e in m.events]

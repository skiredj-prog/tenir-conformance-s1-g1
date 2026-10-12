"""Isolated, deterministic TAU/tau_K/EVP stress-rig prototype.

This is a synthetic model. It does not call the production Membrane, perform
cryptographic EVP verification, or prove what happened in an external system.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class EVPProof:
    proof_id: str
    lei: str
    attempt_id: int
    realm_id: str
    effect_observed: bool
    timestamp: float
    valid_signature: bool = True


@dataclass
class AttemptState:
    attempt_id: int
    status: str = "DISPATCHED"
    evidence: list[EVPProof] = field(default_factory=list)


class MutableClock:
    """Injectable monotonic-like clock for deterministic tests."""

    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, delta: float) -> None:
        if delta < 0:
            raise ValueError("clock cannot move backwards")
        self.value += delta


class TAURuntimeStressRig:
    """Small, async model of single-use permits and EVP claim handling."""

    def __init__(
        self,
        tau_k_window_seconds: float = 0.2,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if tau_k_window_seconds <= 0:
            raise ValueError("tau_K window must be positive")
        self.tau_k = tau_k_window_seconds
        self.clock = clock or time.monotonic
        self.lei_states: dict[str, str] = {}
        self.history: dict[str, list[AttemptState]] = {}
        self.consumed_permits: set[str] = set()
        # Counts positive EVP claims, not independently verified real-world effects.
        self.reported_effects_register: dict[str, int] = {}
        self._positive_claimed_attempts: set[tuple[str, int]] = set()
        self.lock = asyncio.Lock()

    async def admit_attempt(
        self,
        lei: str,
        permit_id: str,
        request_time: float | None = None,
    ) -> tuple[AttemptState | None, str]:
        async with self.lock:
            now = self.clock()
            started = now if request_time is None else request_time

            if started > now:
                return None, "FUTURE_REQUEST_TIME"
            if now - started > self.tau_k:
                return None, "TAU_K_EXPIRED"
            if self.lei_states.get(lei) == "QUARANTINE_LOCK":
                return None, "QUARANTINED"
            if permit_id in self.consumed_permits:
                return None, "PERMIT_REPLAY"

            prior = self.history.get(lei, [])
            for attempt in prior:
                if attempt.status != "FAILED":
                    return None, "PRIOR_ATTEMPT_UNRESOLVED"

            self.lei_states.setdefault(lei, "ACTIVE")
            self.history.setdefault(lei, [])
            self.reported_effects_register.setdefault(lei, 0)
            attempt = AttemptState(attempt_id=len(prior) + 1)
            self.consumed_permits.add(permit_id)
            self.history[lei].append(attempt)
            return attempt, "ADMITTED"

    async def process_evp_attestation(
        self, lei: str, attempt_id: int, proof: EVPProof
    ) -> str:
        async with self.lock:
            if self.lei_states.get(lei) == "QUARANTINE_LOCK":
                return "REJECTED_QUARANTINED"

            attempts = self.history.get(lei, [])
            target = next((a for a in attempts if a.attempt_id == attempt_id), None)
            if target is None:
                return "UNKNOWN_ATTEMPT"
            if not proof.valid_signature:
                return "INVALID_SIGNATURE"
            if proof.lei != lei or proof.attempt_id != attempt_id:
                return "PROOF_BINDING_MISMATCH"
            if any(existing.proof_id == proof.proof_id for existing in target.evidence):
                return "DUPLICATE_PROOF"

            previous_claims = {item.effect_observed for item in target.evidence}
            target.evidence.append(proof)

            if previous_claims and proof.effect_observed not in previous_claims:
                self.lei_states[lei] = "QUARANTINE_LOCK"
                target.status = "CONFLICTED"
                return "QUARANTINE_CONTRADICTION"

            if proof.effect_observed:
                key = (lei, attempt_id)
                if key not in self._positive_claimed_attempts:
                    self._positive_claimed_attempts.add(key)
                    self.reported_effects_register[lei] += 1
                target.status = "RESOLVED"
                return "ACCEPTED_EFFECT_CLAIM"

            target.status = "FAILED"
            return "ACCEPTED_NO_EFFECT_CLAIM"


async def _scenario_replay() -> dict[str, object]:
    clock = MutableClock()
    rig = TAURuntimeStressRig(clock=clock)
    results = await asyncio.gather(
        *(
            rig.admit_attempt("LEI-REPLAY", "PERMIT-SHARED", request_time=clock())
            for _ in range(32)
        )
    )
    accepted = sum(attempt is not None for attempt, _ in results)
    return {
        "case_id": "replay_concurrent",
        "passed": accepted == 1,
        "requests": len(results),
        "admissions": accepted,
        "rejections": len(results) - accepted,
        "reason_codes": sorted({reason for _, reason in results}),
    }


async def _scenario_tau_k_expiry() -> dict[str, object]:
    clock = MutableClock(100.5)
    rig = TAURuntimeStressRig(tau_k_window_seconds=0.2, clock=clock)
    attempt, reason = await rig.admit_attempt(
        "LEI-EXPIRY", "PERMIT-EXPIRED", request_time=100.0
    )
    return {
        "case_id": "tau_k_expiry",
        "passed": attempt is None and reason == "TAU_K_EXPIRED",
        "admitted": attempt is not None,
        "reason": reason,
        "age_seconds": clock() - 100.0,
        "window_seconds": rig.tau_k,
    }


async def _scenario_cross_realm_contradiction() -> dict[str, object]:
    clock = MutableClock()
    rig = TAURuntimeStressRig(clock=clock)
    attempt, admission_reason = await rig.admit_attempt(
        "LEI-CROSS-REALM", "PERMIT-CROSS", request_time=clock()
    )
    assert attempt is not None, "fresh permit should be admitted"
    first = await rig.process_evp_attestation(
        "LEI-CROSS-REALM",
        attempt.attempt_id,
        EVPProof("PROOF-A", "LEI-CROSS-REALM", attempt.attempt_id,
                 "Realm-Alpha", True, clock()),
    )
    second = await rig.process_evp_attestation(
        "LEI-CROSS-REALM",
        attempt.attempt_id,
        EVPProof("PROOF-B", "LEI-CROSS-REALM", attempt.attempt_id,
                 "Realm-Beta", False, clock()),
    )
    later, later_reason = await rig.admit_attempt(
        "LEI-CROSS-REALM", "PERMIT-NEXT", request_time=clock()
    )
    return {
        "case_id": "cross_realm_contradiction",
        "passed": (
            admission_reason == "ADMITTED"
            and first == "ACCEPTED_EFFECT_CLAIM"
            and second == "QUARANTINE_CONTRADICTION"
            and rig.lei_states["LEI-CROSS-REALM"] == "QUARANTINE_LOCK"
            and later is None
            and later_reason == "QUARANTINED"
        ),
        "first_proof_result": first,
        "second_proof_result": second,
        "later_admission_reason": later_reason,
        "lei_state": rig.lei_states["LEI-CROSS-REALM"],
    }


async def _scenario_hidden_effect_limit() -> dict[str, object]:
    clock = MutableClock()
    rig = TAURuntimeStressRig(clock=clock)
    lei = "LEI-E3-LIMIT"
    attempt, _ = await rig.admit_attempt(lei, "PERMIT-E3", request_time=clock())
    assert attempt is not None, "fresh permit should be admitted"

    # Test-driver ground truth is deliberately separate from the proof seen by the rig.
    external_effect_really_happened = True
    result = await rig.process_evp_attestation(
        lei,
        attempt.attempt_id,
        EVPProof("PROOF-FALSE", lei, attempt.attempt_id, "Realm-Gamma",
                 False, clock(), valid_signature=True),
    )
    observed_by_rig = rig.reported_effects_register[lei] > 0
    return {
        "case_id": "hidden_effect_epistemic_limit",
        "passed": external_effect_really_happened and not observed_by_rig,
        "attestation_result": result,
        "external_effect_really_happened_test_driver_only": external_effect_really_happened,
        "effect_inferred_from_received_proofs": observed_by_rig,
        "interpretation": (
            "Expected limitation: a signed but false claim cannot be disproved "
            "without an independent trustworthy signal."
        ),
    }


async def run_stress_suite() -> dict[str, object]:
    scenarios = [
        await _scenario_replay(),
        await _scenario_tau_k_expiry(),
        await _scenario_cross_realm_contradiction(),
        await _scenario_hidden_effect_limit(),
    ]
    return {
        "rig": "TAU runtime stress prototype",
        "mode": "synthetic simulation; not production integration",
        "scenario_count": len(scenarios),
        "passed_count": sum(bool(item["passed"]) for item in scenarios),
        "all_passed": all(bool(item["passed"]) for item in scenarios),
        "scenarios": scenarios,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional path to write JSON evidence")
    args = parser.parse_args()
    result = asyncio.run(run_stress_suite())
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

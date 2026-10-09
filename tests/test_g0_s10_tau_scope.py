"""G0 S10 — signed TAU scope boundary conformance tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tenir_conformance.membrane import KernelBridge, Membrane
from tenir_conformance.membrane.kernel_bridge import KernelDecision
from tenir_conformance.membrane.tau_contract import DEFAULT_PUBLIC_KEY_HEX, TAUContract

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scenarios" / "G0_S10_TAU_SCOPE_BOUNDARY.md"
ARTIFACTS = ROOT / "artifacts" / "s10"
PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
TEST_ONLY_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)


class CountingBridge:
    def __init__(self, admissible: bool = True):
        self.calls = 0
        self.admissible = admissible

    def evaluate(self, payload):
        self.calls += 1
        return KernelDecision(self.admissible, 2.0,
                              "allow" if self.admissible else "block",
                              "S10 test bridge")


def _signed_manifest(*, leis=None, actions=None, principals=None, tau_id="TAU-TEST"):
    core = {
        "schema": "tenir.tau-contract.v1",
        "tau_id": tau_id,
        "version": "1.0.0",
        "signed_by": "TENIR-CONFORMANCE-TEST-ROOT",
        "scope": {
            "lei": list(leis or ["LEI-1"]),
            "action_classes": list(actions or ["transfer"]),
            "principals": list(principals or ["P1"]),
        },
        "invariant": {
            "text": "Only in-scope transitions may reach the kernel.",
            "formal": "lei∈S_LEI ∧ action_class∈S_ACTION ∧ principal∈S_PRINCIPAL",
        },
        "evidence_requirements": {
            "FAILED": ["authoritative outcome evidence", "integrity verified",
                       "bound to attempt and nonce"]
        },
        "exhaustion_policy": "fail_closed",
    }
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    signed_bytes = json.dumps({"manifest": core, "sha256": digest},
                              sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False).encode("utf-8")
    signature = Ed25519PrivateKey.from_private_bytes(TEST_ONLY_SEED).sign(signed_bytes)
    return {
        **core,
        "manifest_sha256": digest,
        "signature": {
            "algorithm": "Ed25519",
            "key_id": core["signed_by"],
            "signature_hex": signature.hex(),
        },
    }


def _record(case, *, expected, actual, kernel_calls, tau_id, digest, extra=None):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    body = {
        "scenario_id": "G0_S10",
        "subcase": case,
        "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
        "tau_id": tau_id,
        "manifest_sha256": digest,
        "expected": expected,
        "actual": actual,
        "kernel_calls": kernel_calls,
        "claim_scope": "deterministic unit conformance; in-process membrane harness",
        "details": extra or {},
    }
    (ARTIFACTS / f"evidence_{case}.json").write_text(
        json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _run_rejected(case, *, lei="LEI-1", action="transfer", principal="P1",
                  allowed_leis=None, allowed_actions=None, allowed_principals=None,
                  expected_reason):
    contract = _signed_manifest(leis=allowed_leis, actions=allowed_actions,
                                principals=allowed_principals)
    bridge = CountingBridge()
    membrane = Membrane(bridge, tau_contract=contract)
    result = membrane.process_transaction(
        lei=lei, attempt_id=f"{case}-A1", payload=PAYLOAD, nonce="n1",
        action_class=action, principal=principal,
    )
    assert result.disposition.value == "HOLD"
    assert result.kernel_decision == expected_reason
    assert bridge.calls == 0
    assert result.effect_count == 0
    assert not membrane.attempts
    _record(case, expected=expected_reason, actual=result.kernel_decision,
            kernel_calls=bridge.calls, tau_id=contract["tau_id"],
            digest=contract["manifest_sha256"],
            extra={"attempts": len(membrane.attempts), "effects": result.effect_count})
    return result


def test_s10a_lei_out_of_scope_rejected_before_kernel():
    _run_rejected("S10a", lei="LEI-2", expected_reason="TAU_LEI_OUT_OF_SCOPE")


def test_s10b_action_class_out_of_scope_rejected_before_kernel():
    _run_rejected("S10b", action="withdraw", expected_reason="TAU_ACTION_OUT_OF_SCOPE")


def test_s10c_principal_out_of_scope_rejected_before_kernel():
    _run_rejected("S10c", principal="P2", expected_reason="TAU_PRINCIPAL_OUT_OF_SCOPE")


def test_s10d_in_scope_admission_calls_kernel_once():
    contract = _signed_manifest()
    bridge = CountingBridge()
    membrane = Membrane(bridge, tau_contract=contract)
    result = membrane.process_transaction(
        lei="LEI-1", attempt_id="S10d-A1", payload=PAYLOAD, nonce="n1",
        action_class="transfer", principal="P1",
    )
    assert result.disposition.value == "PASS"
    assert bridge.calls == 1
    assert result.effect_count == 1
    _record("S10d", expected="PASS; kernel_calls=1; effects=1",
            actual=result.disposition.value, kernel_calls=bridge.calls,
            tau_id=contract["tau_id"], digest=contract["manifest_sha256"],
            extra={"effects": result.effect_count})


def test_s10e_case_variant_does_not_match():
    _run_rejected("S10e", action="Transfer", expected_reason="TAU_ACTION_OUT_OF_SCOPE")


def test_s10f_prefix_does_not_match():
    _run_rejected("S10f", action="transfer.admin", expected_reason="TAU_ACTION_OUT_OF_SCOPE")


def test_s10g_same_payload_under_two_taus_has_divergent_verdicts():
    allow_contract = _signed_manifest(tau_id="TAU-ALLOW")
    deny_contract = _signed_manifest(leis=["LEI-2"], tau_id="TAU-DENY")
    allow_bridge, deny_bridge = CountingBridge(), CountingBridge()
    allow_membrane = Membrane(allow_bridge, tau_contract=allow_contract)
    deny_membrane = Membrane(deny_bridge, tau_contract=deny_contract)
    allowed = allow_membrane.process_transaction(
        lei="LEI-1", attempt_id="S10g-A1", payload=PAYLOAD, nonce="n1",
        action_class="transfer", principal="P1",
    )
    denied = deny_membrane.process_transaction(
        lei="LEI-1", attempt_id="S10g-A2", payload=PAYLOAD, nonce="n2",
        action_class="transfer", principal="P1",
    )
    assert allowed.disposition.value == "PASS"
    assert denied.disposition.value == "HOLD"
    assert allow_bridge.calls == 1
    assert deny_bridge.calls == 0
    _record("S10g", expected="PASS versus HOLD for identical payload",
            actual=f"{allowed.disposition.value} versus {denied.disposition.value}",
            kernel_calls=allow_bridge.calls + deny_bridge.calls,
            tau_id=f"{allow_contract['tau_id']}|{deny_contract['tau_id']}",
            digest=f"{allow_contract['manifest_sha256']}|{deny_contract['manifest_sha256']}",
            extra={"allowed_kernel_calls": allow_bridge.calls,
                   "denied_kernel_calls": deny_bridge.calls})


def test_tau_001_startup_refuses_missing_manifest():
    bridge = CountingBridge()
    with pytest.raises(ValueError, match="TAU_MANIFEST_REQUIRED"):
        Membrane(bridge, tau_contract=None)
    assert bridge.calls == 0
    _record("TAU-001", expected="TAU_MANIFEST_REQUIRED",
            actual="TAU_MANIFEST_REQUIRED", kernel_calls=bridge.calls,
            tau_id="NONE", digest="NONE")


def test_tau_002_modified_manifest_after_signing_is_rejected():
    manifest = _signed_manifest()
    original_digest = manifest["manifest_sha256"]
    manifest["scope"]["action_classes"] = ["transfer", "withdraw"]
    with pytest.raises(ValueError, match="TAU_MANIFEST_HASH_MISMATCH"):
        TAUContract.load(manifest)
    _record("TAU-002", expected="TAU_MANIFEST_HASH_MISMATCH",
            actual="TAU_MANIFEST_HASH_MISMATCH", kernel_calls=0,
            tau_id=manifest["tau_id"], digest=original_digest,
            extra={"modified_field": "scope.action_classes",
                   "signature_preserved": True})

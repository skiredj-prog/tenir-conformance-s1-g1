"""S12a–S12h cross-Realm conformance tests.

These tests validate the lab membrane's declared cross-Realm admission contract.
They do not claim production REG conformance.
"""
from __future__ import annotations

import copy
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tenir_conformance.membrane import (
    CrossRealmTransition,
    Disposition,
    Membrane,
    RealmPolicy,
    canonical_bytes,
    payload_sha256,
)
from tenir_conformance.membrane.kernel_bridge import KernelDecision

_TEST_SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
_TEST_PUBLIC_KEY = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
_TEST_SIGNER = "TENIR-CONFORMANCE-TEST-ROOT"
_PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0, "exposure": 0.5}


class _CountingAdmitBridge:
    def __init__(self):
        self.calls = 0

    def evaluate(self, payload):
        self.calls += 1
        return KernelDecision(True, 2.0, "allow", "S12 probe")


def _signed_realm(*, realm_id: str, invariants=None, max_exposure=1.0,
                  allowed_principals=None, required_postconditions=None) -> dict:
    core = {
        "schema": "tenir.realm-policy.v1",
        "realm_id": realm_id,
        "version": "1.0.0",
        "signed_by": _TEST_SIGNER,
        "invariants": list(invariants or []),
        "policy": {
            "allowed_action_classes": ["default"],
            "allowed_principals": list(allowed_principals or ["default"]),
            "required_postconditions": list(
                ["effect-applied"] if required_postconditions is None else required_postconditions
            ),
            "max_exposure": max_exposure,
        },
    }
    digest = hashlib.sha256(canonical_bytes(core)).hexdigest()
    signed_payload = canonical_bytes({"manifest": core, "sha256": digest})
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_TEST_SEED))
    return {
        **core,
        "manifest_sha256": digest,
        "signature": {
            "algorithm": "Ed25519",
            "key_id": _TEST_SIGNER,
            "signature_hex": private_key.sign(signed_payload).hex(),
        },
    }


def _exposure_at_most(limit: float, invariant_id: str = "EXPOSURE_LIMIT") -> dict:
    return {
        "id": invariant_id,
        "predicate": {
            "op": "lte",
            "left": {"var": "exposure"},
            "right": {"const": limit},
        },
    }


def _transition(*, source_realm="R_A", target_realm="R_B", principal="default",
                postconditions=("effect-applied",), source_preconditions=("source-valid",),
                payload=None, exposure=0.5, scope=None) -> CrossRealmTransition:
    actual_payload = _PAYLOAD if payload is None else payload
    return CrossRealmTransition(
        tau_id="TAU-DEFAULT-TEST",
        source_realm=source_realm,
        target_realm=target_realm,
        action_class="default",
        principal=principal,
        scope={} if scope is None else scope,
        payload_digest=payload_sha256(actual_payload),
        evidence_refs=("s12-evidence",),
        source_preconditions=source_preconditions,
        target_postconditions=postconditions,
        declared_at="2026-10-09T00:00:00Z",
        declared_effect_attributes={"exposure": exposure},
        declared_exposure=exposure,
    )


def _evaluate(document: dict, *, transition=None, source_document=None):
    # Load/verify documents before a membrane can reach the kernel.
    target_policy = RealmPolicy.load(document, public_key_hex=_TEST_PUBLIC_KEY)
    policies = {target_policy.realm_id: target_policy}
    if source_document is not None:
        source_policy = RealmPolicy.load(source_document, public_key_hex=_TEST_PUBLIC_KEY)
        policies[source_policy.realm_id] = source_policy
    bridge = _CountingAdmitBridge()
    membrane = Membrane(bridge, realm_policies=policies)
    txn = transition or _transition()
    result = membrane.process_transaction(
        lei="S12-LEI",
        attempt_id="S12-A1",
        transition=txn,
        payload=_PAYLOAD,
        nonce="s12-nonce",
    )
    return result, bridge, membrane


def test_s12a_permissive_target_realm_passes():
    document = _signed_realm(realm_id="R_B", max_exposure=1.0)
    result, bridge, membrane = _evaluate(document)
    assert result.disposition == Disposition.PASS
    assert result.effect_count == 1
    assert bridge.calls == 1
    assert "EFFECT_APPLIED" in result.events


def test_s12b_target_invariant_violation_hard_vetoes_before_kernel():
    document = _signed_realm(
        realm_id="R_B", max_exposure=1.0,
        invariants=[_exposure_at_most(0.25, "PRESERVE_LOW_EXPOSURE")],
    )
    result, bridge, membrane = _evaluate(document)
    assert result.disposition == Disposition.HARD_VETO
    assert result.kernel_decision == "REALM_INVARIANT_VIOLATED:PRESERVE_LOW_EXPOSURE"
    assert bridge.calls == 0
    assert result.effect_count == 0
    assert "TARGET_REALM_POLICY_REJECTED" in result.events


def test_s12d_invalid_authority_in_target_realm_hard_vetoes_before_kernel():
    document = _signed_realm(realm_id="R_B", allowed_principals=["default"])
    txn = _transition(principal="untrusted-principal")
    result, bridge, membrane = _evaluate(document, transition=txn)
    assert result.disposition == Disposition.HARD_VETO
    assert result.kernel_decision == "PRINCIPAL_NOT_ALLOWED"
    assert bridge.calls == 0
    assert result.effect_count == 0


def test_s12e_missing_required_target_postcondition_holds_before_kernel():
    document = _signed_realm(
        realm_id="R_B", required_postconditions=["effect-applied"]
    )
    txn = _transition(postconditions=("different-postcondition",))
    result, bridge, membrane = _evaluate(document, transition=txn)
    assert result.disposition == Disposition.HOLD
    assert result.kernel_decision == "TARGET_REALM_POLICY_REJECTED"
    assert bridge.calls == 0
    assert result.effect_count == 0


def test_s12f_source_admissibility_does_not_imply_crossing_admissibility_and_both_are_recorded():
    source = _signed_realm(
        realm_id="R_A", max_exposure=1.0, required_postconditions=[]
    )
    target = _signed_realm(
        realm_id="R_B", max_exposure=1.0,
        invariants=[_exposure_at_most(0.25, "TARGET_EXPOSURE_BOUND")],
    )
    result, bridge, membrane = _evaluate(target, source_document=source)
    assert result.disposition == Disposition.HARD_VETO
    assert bridge.calls == 0
    source_events = [e for e in membrane.events if e["event"] == "SOURCE_REALM_ADMISSIBILITY_EVALUATED"]
    target_events = [e for e in membrane.events if e["event"] == "TARGET_REALM_POLICY_REJECTED"]
    assert len(source_events) == 1 and source_events[0]["verdict"] == "PASS"
    assert len(target_events) == 1 and target_events[0]["reason"] == "REALM_INVARIANT_VIOLATED:TARGET_EXPOSURE_BOUND"
    assert source_events[0]["verdict"] != result.disposition.value


def test_s12g_different_realm_labels_same_content_produce_same_verdict():
    target = _signed_realm(realm_id="R_B", max_exposure=1.0)
    first = _transition(source_realm="LABEL_A")
    second = _transition(source_realm="LABEL_B")
    result_a, bridge_a, _ = _evaluate(target, transition=first)
    result_b, bridge_b, _ = _evaluate(target, transition=second)
    assert first.source_realm != second.source_realm
    assert first.payload_digest == second.payload_digest
    assert result_a.disposition == result_b.disposition == Disposition.PASS
    assert bridge_a.calls == bridge_b.calls == 1


def test_s12h_altered_signed_realm_document_is_rejected_before_evaluation():
    valid = _signed_realm(realm_id="R_B", max_exposure=1.0)
    altered = copy.deepcopy(valid)
    altered["policy"]["max_exposure"] = 0.01
    bridge = _CountingAdmitBridge()
    with pytest.raises(ValueError, match="REALM_POLICY_HASH_MISMATCH"):
        RealmPolicy.load(altered, public_key_hex=_TEST_PUBLIC_KEY)
    assert bridge.calls == 0

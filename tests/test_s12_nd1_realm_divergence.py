"""S12 ND-1 gate: same Realm ID, different declarative policy must diverge."""
from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tenir_conformance.membrane import (
    CrossRealmTransition, Disposition, Membrane, RealmPolicy, canonical_bytes, payload_sha256,
)
from tenir_conformance.membrane.kernel_bridge import KernelDecision

_TEST_SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
_TEST_PUBLIC_KEY = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
_TEST_SIGNER = "TENIR-CONFORMANCE-TEST-ROOT"
_PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0, "exposure": 0.5}


def _signed_realm_yaml(*, invariants: list[dict], max_exposure: float) -> dict:
    core = {
        "schema": "tenir.realm-policy.v1", "realm_id": "R_B", "version": "1.0.0",
        "signed_by": _TEST_SIGNER, "invariants": invariants,
        "policy": {"allowed_action_classes": ["default"], "allowed_principals": ["default"],
                   "required_postconditions": ["effect-applied"], "max_exposure": max_exposure},
    }
    digest = hashlib.sha256(canonical_bytes(core)).hexdigest()
    signed_payload = canonical_bytes({"manifest": core, "sha256": digest})
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_TEST_SEED))
    return {**core, "manifest_sha256": digest, "signature": {
        "algorithm": "Ed25519", "key_id": _TEST_SIGNER,
        "signature_hex": private_key.sign(signed_payload).hex(),
    }}


class _AdmitBridge:
    def evaluate(self, payload):
        return KernelDecision(True, 2.0, "allow", "ND-1 probe")


def _run(document: dict) -> tuple[Disposition, str]:
    policy = RealmPolicy.load(document, public_key_hex=_TEST_PUBLIC_KEY)
    transition = CrossRealmTransition(
        tau_id="TAU-ND1", source_realm="R_A", target_realm="R_B", action_class="default",
        principal="default", scope={"case": "ND-1"}, payload_digest=payload_sha256(_PAYLOAD),
        evidence_refs=("nd1-evidence",), source_preconditions=("source-valid",),
        target_postconditions=("effect-applied",), declared_at="2026-10-09T00:00:00Z",
        declared_effect_attributes={"exposure": 0.5}, declared_exposure=0.5,
    )
    membrane = Membrane(_AdmitBridge(), realm_policies={"R_B": policy})
    result = membrane.process_transaction(lei="ND1-LEI", attempt_id="ND1-A1",
        transition=transition, payload=_PAYLOAD, nonce="nd1-nonce")
    return result.disposition, result.kernel_decision


def test_nd1_same_realm_id_different_invariants_and_max_exposure_diverge():
    permissive = _signed_realm_yaml(invariants=[{
        "id": "EXPOSURE_WITHIN_POLICY", "predicate": {"op": "lte",
        "left": {"var": "exposure"}, "right": {"var": "policy.max_exposure"}},
    }], max_exposure=1.0)
    restrictive = _signed_realm_yaml(invariants=[{
        "id": "EXPOSURE_WITHIN_POLICY", "predicate": {"op": "lte",
        "left": {"var": "exposure"}, "right": {"var": "policy.max_exposure"}},
    }, {
        "id": "PRESERVE_LOW_EXPOSURE", "predicate": {"op": "lte",
        "left": {"var": "exposure"}, "right": {"const": 0.25}},
    }], max_exposure=0.1)
    assert permissive["realm_id"] == restrictive["realm_id"] == "R_B"
    assert permissive != restrictive
    permissive_verdict, permissive_reason = _run(permissive)
    restrictive_verdict, restrictive_reason = _run(restrictive)
    assert permissive_verdict == Disposition.PASS, (permissive_verdict, permissive_reason)
    assert restrictive_verdict == Disposition.HOLD, (restrictive_verdict, restrictive_reason)
    assert permissive_verdict != restrictive_verdict
    assert restrictive_reason == "REALM_INVARIANT_VIOLATED:MAX_EXPOSURE"

"""Test-only Ed25519 signer for G0 S7 and legacy negative-outcome fixtures.

The seed below is the published RFC 8032 Ed25519 test vector, intentionally public.
It must never be used as a production signing key.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tenir_conformance.membrane.attestation import (
    NonExecutionAttestation,
    load_trust_root,
)

# RFC 8032 test vector 1. Public test material, never a production secret.
TEST_ONLY_PRIVATE_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)


def sign_attestation(
    *,
    attestation_id: str,
    attempt_id: str = "A1",
    lei: str = "L",
    nonce: str = "n1",
    non_execution_confirmed: bool = True,
    key_id: str | None = "K1",
    key_epoch: int = 1,
    signed: bool = True,
    algorithm: str = "Ed25519",
) -> NonExecutionAttestation:
    draft = NonExecutionAttestation(
        attestation_id=attestation_id,
        attempt_id=attempt_id,
        lei=lei,
        nonce=nonce,
        non_execution_confirmed=non_execution_confirmed,
        key_id=key_id,
        key_epoch=key_epoch,
        signature=None,
        algorithm=algorithm,
    )
    if not signed:
        return draft
    signature = Ed25519PrivateKey.from_private_bytes(TEST_ONLY_PRIVATE_SEED).sign(
        draft.signing_bytes()
    )
    return replace(draft, signature=signature.hex())


def revoked_k1_trust_root() -> dict[str, Any]:
    """Trust-root snapshot after K1 is revoked at epoch 2."""
    root = load_trust_root()
    root["root_epoch"] = 2
    root["keys"]["K1"]["revoked_at_epoch"] = 2
    return root

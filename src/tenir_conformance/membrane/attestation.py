"""Ed25519 non-execution attestations for G0 S7.

A valid signature authenticates a specific claim and its signer under a declared
trust root. It does not establish that the claim is truthful in the external world.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass(frozen=True)
class NonExecutionAttestation:
    """Signed, attempt-specific claim that an operation did not execute."""

    attestation_id: str
    attempt_id: str
    lei: str
    nonce: str
    non_execution_confirmed: bool
    key_id: str | None
    key_epoch: int
    signature: str | None
    algorithm: str = "Ed25519"

    def signed_payload(self) -> dict[str, Any]:
        """Canonical fields covered by the signature; signature itself is excluded."""
        return {
            "schema": "tenir.non-execution-attestation.v1",
            "outcome": "FAILED",
            "attestation_id": self.attestation_id,
            "attempt_id": self.attempt_id,
            "lei": self.lei,
            "nonce": self.nonce,
            "non_execution_confirmed": self.non_execution_confirmed,
            "key_id": self.key_id,
            "key_epoch": self.key_epoch,
            "algorithm": self.algorithm,
        }

    def signing_bytes(self) -> bytes:
        return json.dumps(
            self.signed_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def to_record(self) -> dict[str, Any]:
        return {**self.signed_payload(), "signature": self.signature}


def load_trust_root(source: Mapping[str, Any] | str | Path | None = None) -> dict[str, Any]:
    """Load and validate a versioned YAML trust root or an in-memory snapshot."""
    if source is None:
        source = Path(__file__).with_name("trust_root.yaml")
    if isinstance(source, Mapping):
        # Copy through JSON so a caller cannot mutate the membrane's root by alias.
        root = json.loads(json.dumps(dict(source)))
    else:
        path = Path(source)
        with path.open("r", encoding="utf-8") as stream:
            root = yaml.safe_load(stream)

    if not isinstance(root, dict):
        raise ValueError("INVALID_TRUST_ROOT: root must be a mapping")
    if root.get("version") != 1:
        raise ValueError("INVALID_TRUST_ROOT: unsupported version")
    if not isinstance(root.get("root_id"), str) or not root["root_id"].strip():
        raise ValueError("INVALID_TRUST_ROOT: root_id is required")
    root_epoch = root.get("root_epoch")
    if not isinstance(root_epoch, int) or isinstance(root_epoch, bool) or root_epoch < 1:
        raise ValueError("INVALID_TRUST_ROOT: root_epoch must be a positive integer")
    keys = root.get("keys")
    if not isinstance(keys, dict) or not keys:
        raise ValueError("INVALID_TRUST_ROOT: at least one key is required")

    for key_id, key in keys.items():
        if not isinstance(key_id, str) or not key_id.strip() or not isinstance(key, dict):
            raise ValueError("INVALID_TRUST_ROOT: malformed key entry")
        if key.get("algorithm") != "Ed25519":
            raise ValueError(f"INVALID_TRUST_ROOT: unsupported algorithm for {key_id}")
        public_key_hex = key.get("public_key_hex")
        try:
            public_key = bytes.fromhex(public_key_hex) if isinstance(public_key_hex, str) else b""
        except ValueError as exc:
            raise ValueError(f"INVALID_TRUST_ROOT: malformed public key for {key_id}") from exc
        if len(public_key) != 32:
            raise ValueError(f"INVALID_TRUST_ROOT: Ed25519 public key must be 32 bytes for {key_id}")
        key_epoch = key.get("key_epoch")
        if not isinstance(key_epoch, int) or isinstance(key_epoch, bool) or key_epoch < 1:
            raise ValueError(f"INVALID_TRUST_ROOT: key_epoch must be positive for {key_id}")
        if key.get("status", "active") not in {"active", "revoked"}:
            raise ValueError(f"INVALID_TRUST_ROOT: invalid status for {key_id}")
        revoked_at_epoch = key.get("revoked_at_epoch")
        if revoked_at_epoch is not None and (
            not isinstance(revoked_at_epoch, int)
            or isinstance(revoked_at_epoch, bool)
            or revoked_at_epoch < 1
        ):
            raise ValueError(f"INVALID_TRUST_ROOT: invalid revoked_at_epoch for {key_id}")

    return root


def verify_attestation(
    attestation: NonExecutionAttestation | None,
    trust_root: Mapping[str, Any],
    *,
    expected_attempt_id: str,
    expected_lei: str,
    expected_nonce: str,
) -> tuple[bool, str]:
    """Verify signature, current key trust, and exact attempt/LEI/nonce binding.

    The order is intentional: a valid signature replayed across LEIs reports a
    binding error, while a changed signed payload reports content_mismatch.
    """
    if attestation is None or not isinstance(attestation, NonExecutionAttestation):
        return False, "missing_signature"
    if not isinstance(attestation.signature, str) or not attestation.signature.strip():
        return False, "missing_signature"
    if not isinstance(attestation.key_id, str) or not attestation.key_id.strip():
        return False, "unknown_key"

    key = trust_root.get("keys", {}).get(attestation.key_id)
    if not isinstance(key, Mapping):
        return False, "unknown_key"

    root_epoch = trust_root.get("root_epoch")
    revoked_at_epoch = key.get("revoked_at_epoch")
    if (
        key.get("status") == "revoked"
        or (
            isinstance(revoked_at_epoch, int)
            and isinstance(root_epoch, int)
            and root_epoch >= revoked_at_epoch
        )
    ):
        return False, "revoked_key"

    if attestation.algorithm != "Ed25519" or key.get("algorithm") != attestation.algorithm:
        return False, "unsupported_algorithm"
    if attestation.key_epoch != key.get("key_epoch"):
        return False, "key_epoch_mismatch"

    try:
        signature = bytes.fromhex(attestation.signature)
        public_key_bytes = bytes.fromhex(key["public_key_hex"])
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature, attestation.signing_bytes())
    except (InvalidSignature, ValueError, TypeError, KeyError):
        return False, "content_mismatch"

    if attestation.non_execution_confirmed is not True:
        return False, "non_execution_not_confirmed"
    if attestation.lei != expected_lei:
        return False, "BINDING_LEI_MISMATCH"
    if attestation.attempt_id != expected_attempt_id:
        return False, "BINDING_ATTEMPT_MISMATCH"
    if attestation.nonce != expected_nonce:
        return False, "BINDING_NONCE_MISMATCH"
    return True, "verified"

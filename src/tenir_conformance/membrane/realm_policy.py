"""Signed, hash-verified target-Realm policy manifests."""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .transition import canonical_bytes

REALM_POLICY_SCHEMA = "tenir.realm-policy.v1"


@dataclass(frozen=True)
class RealmPolicy:
    """A Realm policy accepted only after digest and Ed25519 signature verification."""

    realm_id: str
    version: str
    signed_by: str
    allowed_action_classes: tuple[str, ...]
    allowed_principals: tuple[str, ...]
    required_postconditions: tuple[str, ...]
    manifest_sha256: str
    # Set only by load() after digest and signature verification. Not caller-settable.
    verified: bool = field(default=False, init=False)

    @classmethod
    def load(
        cls,
        source: "RealmPolicy | Mapping[str, Any] | str | Path",
        *,
        public_key_hex: str,
    ) -> "RealmPolicy":
        if not isinstance(public_key_hex, str) or len(public_key_hex) != 64:
            raise ValueError("REALM_POLICY_TRUST_KEY_REQUIRED")
        if isinstance(source, cls):
            if not source.verified:
                raise ValueError("REALM_POLICY_NOT_VERIFIED")
            return source
        if isinstance(source, Mapping):
            raw = dict(source)
        else:
            with Path(source).open("r", encoding="utf-8") as stream:
                raw = yaml.safe_load(stream)
        if not isinstance(raw, dict):
            raise ValueError("REALM_POLICY_INVALID: root must be a mapping")

        signature = raw.get("signature")
        claimed_digest = raw.get("manifest_sha256")
        core = {k: v for k, v in raw.items()
                if k not in {"signature", "manifest_sha256"}}
        if core.get("schema") != REALM_POLICY_SCHEMA:
            raise ValueError("REALM_POLICY_INVALID: unsupported schema")
        for field in ("realm_id", "version", "signed_by"):
            if not isinstance(core.get(field), str) or not core[field].strip():
                raise ValueError(f"REALM_POLICY_INVALID: {field} required")
        policy = core.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("REALM_POLICY_INVALID: policy required")
        normalized: dict[str, tuple[str, ...]] = {}
        for field in ("allowed_action_classes", "allowed_principals", "required_postconditions"):
            values = policy.get(field)
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"REALM_POLICY_INVALID: policy.{field} must be a list of non-empty strings")
            if field != "required_postconditions" and not values:
                raise ValueError(f"REALM_POLICY_INVALID: policy.{field} must not be empty")
            if len(values) != len(set(values)):
                raise ValueError(f"REALM_POLICY_INVALID: policy.{field} contains duplicates")
            normalized[field] = tuple(values)

        digest = hashlib.sha256(canonical_bytes(core)).hexdigest()
        if not isinstance(claimed_digest, str) or not hmac.compare_digest(digest, claimed_digest):
            raise ValueError("REALM_POLICY_HASH_MISMATCH")
        if not isinstance(signature, dict) or signature.get("algorithm") != "Ed25519":
            raise ValueError("REALM_POLICY_SIGNATURE_REQUIRED")
        if signature.get("key_id") != core["signed_by"]:
            raise ValueError("REALM_POLICY_SIGNER_MISMATCH")
        try:
            public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
            signed_payload = canonical_bytes({"manifest": core, "sha256": digest})
            public_key.verify(bytes.fromhex(signature["signature_hex"]), signed_payload)
        except (InvalidSignature, ValueError, TypeError, KeyError) as exc:
            raise ValueError("REALM_POLICY_SIGNATURE_INVALID") from exc

        accepted = cls(
            realm_id=core["realm_id"],
            version=core["version"],
            signed_by=core["signed_by"],
            allowed_action_classes=normalized["allowed_action_classes"],
            allowed_principals=normalized["allowed_principals"],
            required_postconditions=normalized["required_postconditions"],
            manifest_sha256=digest,
        )
        # frozen dataclass: verification state is set internally only after
        # successful digest and signature checks above.
        object.__setattr__(accepted, "verified", True)
        return accepted

    def admits(self, *, action_class: str, principal: str,
               declared_postconditions: tuple[str, ...] | list[str]) -> bool:
        return (
            action_class in self.allowed_action_classes
            and principal in self.allowed_principals
            and set(self.required_postconditions).issubset(set(declared_postconditions))
        )

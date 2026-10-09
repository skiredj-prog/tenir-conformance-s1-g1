"""Signed TAU governance contract and exact scope admission checks.

The bundled manifest/key are public conformance-test fixtures, not production
credentials. Deployments must provide a manifest signed by their configured root.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

TAU_SCHEMA = "tenir.tau-contract.v1"
DEFAULT_MANIFEST = Path(__file__).with_name("tau.yaml")
# RFC 8032 public test vector; deliberately public and test-only.
DEFAULT_PUBLIC_KEY_HEX = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class TAUContract:
    """Validated signed TAU manifest; only exact values or explicit '*' match."""

    manifest: Mapping[str, Any]
    manifest_sha256: str

    @property
    def tau_id(self) -> str:
        return str(self.manifest["tau_id"])

    @property
    def version(self) -> str:
        return str(self.manifest["version"])

    @classmethod
    def load(
        cls,
        source: "TAUContract | Mapping[str, Any] | str | Path | None" = "default",
        *,
        public_key_hex: str = DEFAULT_PUBLIC_KEY_HEX,
    ) -> "TAUContract":
        if source is None:
            raise ValueError("TAU_MANIFEST_REQUIRED")
        if isinstance(source, cls):
            # Revalidate rather than trust a caller-created dataclass instance.
            raw = dict(source.manifest)
        elif source == "default":
            with DEFAULT_MANIFEST.open("r", encoding="utf-8") as stream:
                raw = yaml.safe_load(stream)
        elif isinstance(source, Mapping):
            raw = json.loads(json.dumps(dict(source)))
        else:
            with Path(source).open("r", encoding="utf-8") as stream:
                raw = yaml.safe_load(stream)

        if not isinstance(raw, dict):
            raise ValueError("TAU_MANIFEST_INVALID: root must be a mapping")
        signature = raw.get("signature")
        claimed_digest = raw.get("manifest_sha256")
        core = {k: v for k, v in raw.items()
                if k not in {"signature", "manifest_sha256"}}
        if core.get("schema") != TAU_SCHEMA:
            raise ValueError("TAU_MANIFEST_INVALID: unsupported schema")
        for field in ("tau_id", "version", "signed_by"):
            if not isinstance(core.get(field), str) or not core[field].strip():
                raise ValueError(f"TAU_MANIFEST_INVALID: {field} required")
        scope = core.get("scope")
        if not isinstance(scope, dict):
            raise ValueError("TAU_MANIFEST_INVALID: scope required")
        for field in ("lei", "action_classes", "principals"):
            values = scope.get(field)
            if not isinstance(values, list) or not values or any(
                not isinstance(v, str) or not v for v in values
            ):
                raise ValueError(f"TAU_MANIFEST_INVALID: scope.{field} must be non-empty strings")
        invariant = core.get("invariant")
        if not isinstance(invariant, dict) or not all(
            isinstance(invariant.get(k), str) and invariant[k].strip()
            for k in ("text", "formal")
        ):
            raise ValueError("TAU_MANIFEST_INVALID: invariant text and formal forms required")
        evidence = core.get("evidence_requirements")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("FAILED"), list) or not evidence["FAILED"]:
            raise ValueError("TAU_MANIFEST_INVALID: evidence_requirements.FAILED required")
        if core.get("exhaustion_policy") not in {"fail_closed", "fail_degraded"}:
            raise ValueError("TAU_MANIFEST_INVALID: invalid exhaustion_policy")
        if not isinstance(claimed_digest, str) or len(claimed_digest) != 64:
            raise ValueError("TAU_MANIFEST_INVALID: SHA-256 required")
        digest = hashlib.sha256(_canonical(core)).hexdigest()
        if not hmac.compare_digest(digest, claimed_digest):
            raise ValueError("TAU_MANIFEST_HASH_MISMATCH")
        if not isinstance(signature, dict) or signature.get("algorithm") != "Ed25519":
            raise ValueError("TAU_MANIFEST_SIGNATURE_REQUIRED")
        if signature.get("key_id") != core["signed_by"]:
            raise ValueError("TAU_MANIFEST_SIGNER_MISMATCH")
        try:
            public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
            public_key.verify(
                bytes.fromhex(signature["signature_hex"]),
                _canonical({"manifest": core, "sha256": digest}),
            )
        except (InvalidSignature, ValueError, TypeError, KeyError) as exc:
            raise ValueError("TAU_MANIFEST_SIGNATURE_INVALID") from exc
        return cls(manifest=raw, manifest_sha256=digest)

    def scope_check(self, *, lei: str, action_class: str, principal: str) -> tuple[bool, str]:
        """Check exact membership. '*' is a literal, explicit all-values grant."""
        scope = self.manifest["scope"]
        for field, value, reason in (
            ("lei", lei, "TAU_LEI_OUT_OF_SCOPE"),
            ("action_classes", action_class, "TAU_ACTION_OUT_OF_SCOPE"),
            ("principals", principal, "TAU_PRINCIPAL_OUT_OF_SCOPE"),
        ):
            if not isinstance(value, str) or not value:
                return False, reason
            allowed = scope[field]
            if value not in allowed and "*" not in allowed:
                return False, reason
        return True, "TAU_SCOPE_ADMITTED"

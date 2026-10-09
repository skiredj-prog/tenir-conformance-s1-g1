"""Signed, hash-verified target-Realm policy manifests."""
from __future__ import annotations

import hashlib
import hmac
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .transition import canonical_bytes

REALM_POLICY_SCHEMA = "tenir.realm-policy.v1"


def _resolve_operand(node: Any, attributes: Mapping[str, Any], max_exposure: float | None) -> Any:
    """Resolve a JSON predicate operand without evaluating source text."""
    if isinstance(node, dict):
        if set(node) == {"var"} and isinstance(node["var"], str):
            name = node["var"]
            if name == "policy.max_exposure":
                return max_exposure
            if name in attributes:
                return attributes[name]
            raise ValueError(f"REALM_PREDICATE_UNKNOWN_ATTRIBUTE:{name}")
        if set(node) == {"const"}:
            return node["const"]
        raise ValueError("REALM_PREDICATE_INVALID_OPERAND")
    if isinstance(node, (str, int, float, bool)) or node is None:
        return node
    raise ValueError("REALM_PREDICATE_INVALID_OPERAND")


def _evaluate_predicate(node: Any, attributes: Mapping[str, Any],
                        max_exposure: float | None) -> bool:
    """Evaluate the deliberately small D9 JSON predicate tree."""
    if not isinstance(node, dict) or not isinstance(node.get("op"), str):
        raise ValueError("REALM_PREDICATE_INVALID_TREE")
    op = node["op"]
    if op in {"and", "or"}:
        args = node.get("args")
        if not isinstance(args, list) or not args:
            raise ValueError("REALM_PREDICATE_INVALID_TREE")
        values = [_evaluate_predicate(arg, attributes, max_exposure) for arg in args]
        return all(values) if op == "and" else any(values)
    if op == "not":
        if set(node) != {"op", "arg"}:
            raise ValueError("REALM_PREDICATE_INVALID_TREE")
        return not _evaluate_predicate(node["arg"], attributes, max_exposure)
    if op not in {"eq", "ne", "lt", "lte", "gt", "gte"} or set(node) != {"op", "left", "right"}:
        raise ValueError("REALM_PREDICATE_INVALID_TREE")
    left = _resolve_operand(node["left"], attributes, max_exposure)
    right = _resolve_operand(node["right"], attributes, max_exposure)
    try:
        if op == "eq":
            return left == right
        if op == "ne":
            return left != right
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
        if op == "gt":
            return left > right
        return left >= right
    except TypeError as exc:
        raise ValueError("REALM_PREDICATE_TYPE_MISMATCH") from exc


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
    invariants: tuple[Mapping[str, Any], ...] = ()
    max_exposure: float | None = None
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
        for field_name in ("realm_id", "version", "signed_by"):
            if not isinstance(core.get(field_name), str) or not core[field_name].strip():
                raise ValueError(f"REALM_POLICY_INVALID: {field_name} required")
        policy = core.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("REALM_POLICY_INVALID: policy required")
        normalized: dict[str, tuple[str, ...]] = {}
        for field_name in ("allowed_action_classes", "allowed_principals", "required_postconditions"):
            values = policy.get(field_name)
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"REALM_POLICY_INVALID: policy.{field_name} must be a list of non-empty strings")
            if field_name != "required_postconditions" and not values:
                raise ValueError(f"REALM_POLICY_INVALID: policy.{field_name} must not be empty")
            if len(values) != len(set(values)):
                raise ValueError(f"REALM_POLICY_INVALID: policy.{field_name} contains duplicates")
            normalized[field_name] = tuple(values)

        raw_invariants = core.get("invariants", [])
        if not isinstance(raw_invariants, list):
            raise ValueError("REALM_POLICY_INVALID: invariants must be a list")
        invariants: list[dict[str, Any]] = []
        invariant_ids: set[str] = set()
        for invariant in raw_invariants:
            if not isinstance(invariant, dict):
                raise ValueError("REALM_POLICY_INVALID: each invariant must be a mapping")
            invariant_id = invariant.get("id")
            predicate = invariant.get("predicate")
            if not isinstance(invariant_id, str) or not invariant_id.strip() or invariant_id in invariant_ids:
                raise ValueError("REALM_POLICY_INVALID: invariant id must be unique and non-empty")
            if not isinstance(predicate, dict):
                raise ValueError(f"REALM_POLICY_INVALID: invariant {invariant_id} requires a predicate tree")
            invariant_ids.add(invariant_id)
            # Validate the predicate grammar at load time; actual values are checked at admission.
            _validate_predicate(predicate)
            invariants.append({"id": invariant_id, "predicate": predicate})

        max_exposure = policy.get("max_exposure")
        if max_exposure is not None and (
            isinstance(max_exposure, bool) or not isinstance(max_exposure, (int, float))
            or not math.isfinite(max_exposure) or max_exposure < 0
        ):
            raise ValueError("REALM_POLICY_INVALID: policy.max_exposure must be a finite non-negative number")

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
            invariants=tuple(invariants),
            max_exposure=max_exposure,
        )
        object.__setattr__(accepted, "verified", True)
        return accepted

    def refusal_reason(self, *, action_class: str, principal: str,
                       declared_postconditions: tuple[str, ...] | list[str],
                       declared_effect_attributes: Mapping[str, Any] | None = None,
                       declared_exposure: float | None = None) -> str | None:
        if action_class not in self.allowed_action_classes:
            return "ACTION_CLASS_NOT_ALLOWED"
        if principal not in self.allowed_principals:
            return "PRINCIPAL_NOT_ALLOWED"
        if not set(self.required_postconditions).issubset(set(declared_postconditions)):
            return "REQUIRED_POSTCONDITION_MISSING"
        attributes = declared_effect_attributes or {}
        if not isinstance(attributes, Mapping):
            return "REALM_PREDICATE_INVALID_ATTRIBUTES"
        if self.max_exposure is not None:
            if (isinstance(declared_exposure, bool) or not isinstance(declared_exposure, (int, float))
                    or not math.isfinite(declared_exposure)):
                return "REALM_INVARIANT_VIOLATED:MAX_EXPOSURE"
            if declared_exposure > self.max_exposure:
                return "REALM_INVARIANT_VIOLATED:MAX_EXPOSURE"
        for invariant in self.invariants:
            try:
                satisfied = _evaluate_predicate(invariant["predicate"], attributes, self.max_exposure)
            except (TypeError, ValueError):
                return f"REALM_INVARIANT_VIOLATED:{invariant['id']}"
            if not satisfied:
                return f"REALM_INVARIANT_VIOLATED:{invariant['id']}"
        return None

    def admits(self, *, action_class: str, principal: str,
               declared_postconditions: tuple[str, ...] | list[str],
               declared_effect_attributes: Mapping[str, Any] | None = None,
               declared_exposure: float | None = None) -> bool:
        return self.refusal_reason(
            action_class=action_class,
            principal=principal,
            declared_postconditions=declared_postconditions,
            declared_effect_attributes=declared_effect_attributes,
            declared_exposure=declared_exposure,
        ) is None


def _validate_predicate(node: Any) -> None:
    """Validate predicate structure independently of runtime values."""
    if not isinstance(node, dict) or not isinstance(node.get("op"), str):
        raise ValueError("REALM_PREDICATE_INVALID_TREE")
    op = node["op"]
    if op in {"and", "or"}:
        if set(node) != {"op", "args"} or not isinstance(node["args"], list) or not node["args"]:
            raise ValueError("REALM_PREDICATE_INVALID_TREE")
        for child in node["args"]:
            _validate_predicate(child)
        return
    if op == "not":
        if set(node) != {"op", "arg"}:
            raise ValueError("REALM_PREDICATE_INVALID_TREE")
        _validate_predicate(node["arg"])
        return
    if op in {"eq", "ne", "lt", "lte", "gt", "gte"} and set(node) == {"op", "left", "right"}:
        for operand in (node["left"], node["right"]):
            if isinstance(operand, dict):
                if set(operand) == {"var"} and isinstance(operand["var"], str):
                    continue
                if set(operand) == {"const"} and (
                    operand["const"] is None or isinstance(operand["const"], (str, int, float, bool))
                ):
                    continue
                raise ValueError("REALM_PREDICATE_INVALID_OPERAND")
            if not (operand is None or isinstance(operand, (str, int, float, bool))):
                raise ValueError("REALM_PREDICATE_INVALID_OPERAND")
        return
    raise ValueError("REALM_PREDICATE_INVALID_TREE")

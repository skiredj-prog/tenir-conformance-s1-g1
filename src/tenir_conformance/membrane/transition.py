"""G0 S11 governed Transition object and process-stable canonical hashing."""
from __future__ import annotations

import hashlib
import rfc8785
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise TypeError("JCS_OBJECT_KEYS_MUST_BE_STRINGS")
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Return RFC 8785 JSON Canonicalization Scheme UTF-8 bytes."""
    normalized = _json_value(value)
    return rfc8785.dumps(normalized)


@dataclass(frozen=True)
class Transition:
    tau_id: str
    source_realm: str
    target_realm: str
    action_class: str
    principal: str
    scope: Mapping[str, Any]
    payload_digest: str | bytes
    evidence_refs: Sequence[str]
    source_preconditions: Sequence[str]
    target_postconditions: Sequence[str]
    declared_at: str

    def __post_init__(self) -> None:
        for name in ("tau_id", "source_realm", "target_realm", "action_class",
                     "principal", "declared_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"TRANSITION_FIELD_REQUIRED:{name}")
        if not isinstance(self.scope, Mapping):
            raise TypeError("TRANSITION_SCOPE_MUST_BE_MAPPING")
        if not isinstance(self.payload_digest, (str, bytes)):
            raise TypeError("TRANSITION_PAYLOAD_DIGEST_MUST_BE_STR_OR_BYTES")
        if isinstance(self.payload_digest, str):
            digest = self.payload_digest.removeprefix("sha256:")
            if len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
                raise ValueError("TRANSITION_PAYLOAD_DIGEST_INVALID")
        if not all(isinstance(x, str) and x for x in self.evidence_refs):
            raise ValueError("TRANSITION_EVIDENCE_REFS_INVALID")
        if not all(isinstance(x, str) and x for x in self.source_preconditions):
            raise ValueError("TRANSITION_SOURCE_PRECONDITIONS_INVALID")
        if not all(isinstance(x, str) and x for x in self.target_postconditions):
            raise ValueError("TRANSITION_TARGET_POSTCONDITIONS_INVALID")

    def canonical_record(self) -> dict[str, Any]:
        return {
            "tau_id": self.tau_id,
            "source_realm": self.source_realm,
            "target_realm": self.target_realm,
            "action_class": self.action_class,
            "principal": self.principal,
            "scope": _json_value(self.scope),
            "payload_digest": _json_value(self.payload_digest),
            "evidence_refs": list(self.evidence_refs),
            "source_preconditions": list(self.source_preconditions),
            "target_postconditions": list(self.target_postconditions),
            "declared_at": self.declared_at,
        }


def canonical_hash(transition: Transition) -> str:
    """SHA-256 over every required field in deterministic canonical JSON."""
    if not isinstance(transition, Transition):
        raise TypeError("canonical_hash requires a Transition")
    return hashlib.sha256(canonical_bytes(transition.canonical_record())).hexdigest()


def payload_sha256(payload: Mapping[str, Any]) -> str:
    """Digest the exact canonical payload that is passed to the kernel."""
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()

"""RFC-4 membrane implementation (S1–S4 + T7/T8)."""

from .attestation import NonExecutionAttestation, load_trust_root, verify_attestation
from .kernel_bridge import KernelBridge
from .tau_contract import TAUContract
from .realm_policy import RealmPolicy
from .transition import CrossRealmTransition, Transition, canonical_bytes, canonical_hash, payload_sha256
from .membrane import (
    Disposition,
    Membrane,
    FakeClock,
    AttemptState,
    Receipt,
    DuplicateAttemptID,
    UnresolvedSameLEI,
    StaleReceiptError,
    Evidence,
    IncompleteEvidence,
    BindingError,
    ContradictoryEvidenceError,
)

__all__ = [
    "KernelBridge",
    "TAUContract",
    "RealmPolicy",
    "Transition",
    "CrossRealmTransition",
    "canonical_bytes",
    "canonical_hash",
    "payload_sha256",
    "NonExecutionAttestation",
    "load_trust_root",
    "verify_attestation",
    "Membrane",
    "Disposition",
    "FakeClock",
    "AttemptState",
    "Receipt",
    "DuplicateAttemptID",
    "UnresolvedSameLEI",
    "StaleReceiptError",
    "Evidence",
    "IncompleteEvidence",
    "BindingError",
    "ContradictoryEvidenceError",
]

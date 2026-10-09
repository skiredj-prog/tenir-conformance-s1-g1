"""RFC-4 membrane implementation (S1–S4 + T7/T8)."""

from .attestation import NonExecutionAttestation, load_trust_root, verify_attestation
from .kernel_bridge import KernelBridge
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

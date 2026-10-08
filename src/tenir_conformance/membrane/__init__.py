"""RFC-4 membrane implementation (S1–S4 + T7/T8)."""

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
)

__all__ = [
    "KernelBridge",
    "Membrane",
    "Disposition",
    "FakeClock",
    "AttemptState",
    "Receipt",
    "DuplicateAttemptID",
    "UnresolvedSameLEI",
    "StaleReceiptError",
]

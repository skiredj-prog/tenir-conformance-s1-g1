"""RFC-4 membrane implementation (S1 + S2 + S3 + T7/T8)."""

from .kernel_bridge import KernelBridge
from .membrane import (
    Disposition,
    Membrane,
    FakeClock,
    AttemptState,
    DuplicateAttemptID,
    UnresolvedSameLEI,
)

__all__ = [
    "KernelBridge",
    "Membrane",
    "Disposition",
    "FakeClock",
    "AttemptState",
    "DuplicateAttemptID",
    "UnresolvedSameLEI",
]

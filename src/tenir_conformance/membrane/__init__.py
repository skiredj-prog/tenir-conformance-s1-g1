"""RFC-4 membrane implementation (S1 + S2)."""

from .kernel_bridge import KernelBridge
from .membrane import Disposition, Membrane, FakeClock, AttemptState

__all__ = ["KernelBridge", "Membrane", "Disposition", "FakeClock", "AttemptState"]

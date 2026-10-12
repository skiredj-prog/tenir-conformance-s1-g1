"""Checkpoint policy for a running membrane, configured from the environment at start-up.

Configuration is read once, when the process starts. It is not reloaded while running.

Environment variables:
  TENIR_CHECKPOINT_ENABLED   "1" to enable; anything else (or unset) disables. Default: disabled.
  TENIR_CHECKPOINT_DIR       output directory. Required when enabled. Must not be inside a Git repository.
  TENIR_CHECKPOINT_EVERY_ENTRIES  checkpoint after this many new entries. Integer >= 1. Default 100.
  TENIR_CHECKPOINT_DAILY     "1" to checkpoint on the first new entries of each day. "0" disables. Default "1".

Fixed, not configurable: only the anchor file is publishable; the entries file stays private
(see write_checkpoint).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from .evidence_ledger import EvidenceLedger, write_checkpoint

DEFAULT_EVERY_ENTRIES = 100


@dataclass(frozen=True)
class CheckpointConfig:
    directory: str
    every_entries: int
    daily: bool


def _inside_git_repository(path: str) -> bool:
    current = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def load_config(env: Mapping[str, str]) -> CheckpointConfig | None:
    """Return the configuration, or None when checkpoints are disabled. Raises ValueError if invalid."""
    enabled = env.get("TENIR_CHECKPOINT_ENABLED", "0")
    if enabled != "1":
        return None
    directory = env.get("TENIR_CHECKPOINT_DIR", "").strip()
    if not directory:
        raise ValueError("TENIR_CHECKPOINT_DIR is required when checkpoints are enabled")
    if _inside_git_repository(directory):
        raise ValueError("TENIR_CHECKPOINT_DIR must not be inside a Git repository")
    raw_every = env.get("TENIR_CHECKPOINT_EVERY_ENTRIES", str(DEFAULT_EVERY_ENTRIES))
    try:
        every = int(raw_every)
    except ValueError as error:
        raise ValueError(f"TENIR_CHECKPOINT_EVERY_ENTRIES must be an integer, got {raw_every!r}") from error
    if every < 1:
        raise ValueError("TENIR_CHECKPOINT_EVERY_ENTRIES must be >= 1")
    raw_daily = env.get("TENIR_CHECKPOINT_DAILY", "1")
    if raw_daily not in ("0", "1"):
        raise ValueError(f"TENIR_CHECKPOINT_DAILY must be 0 or 1, got {raw_daily!r}")
    return CheckpointConfig(directory=directory, every_entries=every, daily=raw_daily == "1")


class CheckpointTrigger:
    """Decides when to write a checkpoint. Call maybe_checkpoint() after each recorded entry."""

    def __init__(self, config: CheckpointConfig) -> None:
        self.config = config
        self._last_day: date | None = None
        self._last_length = 0

    def maybe_checkpoint(self, ledger: EvidenceLedger, today: date) -> dict[str, Any] | None:
        length = len(ledger.entries)
        new_entries = length - self._last_length
        if new_entries <= 0:
            return None
        by_count = new_entries >= self.config.every_entries
        by_day = self.config.daily and (self._last_day is None or today != self._last_day)
        if not (by_count or by_day):
            return None
        result = write_checkpoint(ledger, self.config.directory, today.isoformat())
        self._last_day = today
        self._last_length = length
        return result

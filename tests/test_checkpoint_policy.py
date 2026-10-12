"""Checkpoint policy: configuration from the environment, and when a checkpoint is written."""

import os
from datetime import date

import pytest

from tenir_conformance.membrane.checkpoint_policy import CheckpointTrigger, load_config
from tenir_conformance.membrane.evidence_ledger import EvidenceLedger, write_checkpoint

DAY1 = date(2026, 10, 12)
DAY2 = date(2026, 10, 13)


def _env(tmp_path, **extra):
    base = {"TENIR_CHECKPOINT_ENABLED": "1", "TENIR_CHECKPOINT_DIR": str(tmp_path / "out")}
    base.update(extra)
    return base


def _ledger(n):
    ledger = EvidenceLedger()
    for i in range(n):
        ledger.append({"evidence_id": f"E{i}", "value": i})
    return ledger


def test_disabled_by_default(tmp_path):
    assert load_config({}) is None
    assert load_config({"TENIR_CHECKPOINT_ENABLED": "0"}) is None


def test_enabled_with_defaults(tmp_path):
    config = load_config(_env(tmp_path))
    assert config.every_entries == 100
    assert config.daily is True
    assert config.directory == str(tmp_path / "out")


def test_enabled_requires_a_directory():
    with pytest.raises(ValueError, match="TENIR_CHECKPOINT_DIR is required"):
        load_config({"TENIR_CHECKPOINT_ENABLED": "1"})


@pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5"])
def test_invalid_entry_threshold_is_refused(tmp_path, value):
    with pytest.raises(ValueError, match="TENIR_CHECKPOINT_EVERY_ENTRIES"):
        load_config(_env(tmp_path, TENIR_CHECKPOINT_EVERY_ENTRIES=value))


@pytest.mark.parametrize("value", ["yes", "true", "2"])
def test_invalid_daily_flag_is_refused(tmp_path, value):
    with pytest.raises(ValueError, match="TENIR_CHECKPOINT_DAILY"):
        load_config(_env(tmp_path, TENIR_CHECKPOINT_DAILY=value))


def test_directory_inside_a_git_repository_is_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="inside a Git repository"):
        load_config({"TENIR_CHECKPOINT_ENABLED": "1", "TENIR_CHECKPOINT_DIR": str(repo / "checkpoints")})


def test_no_checkpoint_without_new_entries(tmp_path):
    trigger = CheckpointTrigger(load_config(_env(tmp_path)))
    assert trigger.maybe_checkpoint(_ledger(0), DAY1) is None


def test_daily_checkpoint_on_first_new_entries_of_a_day(tmp_path):
    trigger = CheckpointTrigger(load_config(_env(tmp_path)))
    ledger = _ledger(2)
    assert trigger.maybe_checkpoint(ledger, DAY1) is not None
    assert trigger.maybe_checkpoint(ledger, DAY1) is None  # same day, nothing new
    ledger.append({"evidence_id": "E9", "value": 9})
    assert trigger.maybe_checkpoint(ledger, DAY1) is None  # same day, below threshold
    assert trigger.maybe_checkpoint(ledger, DAY2) is not None  # new day, new entries


def test_entry_threshold_triggers_within_a_day(tmp_path):
    env = _env(tmp_path, TENIR_CHECKPOINT_EVERY_ENTRIES="3", TENIR_CHECKPOINT_DAILY="0")
    trigger = CheckpointTrigger(load_config(env))
    ledger = _ledger(2)
    assert trigger.maybe_checkpoint(ledger, DAY1) is None
    ledger.append({"evidence_id": "E2", "value": 2})
    assert trigger.maybe_checkpoint(ledger, DAY1) is not None


def test_daily_disabled_does_not_checkpoint_on_a_new_day(tmp_path):
    env = _env(tmp_path, TENIR_CHECKPOINT_DAILY="0", TENIR_CHECKPOINT_EVERY_ENTRIES="50")
    trigger = CheckpointTrigger(load_config(env))
    assert trigger.maybe_checkpoint(_ledger(2), DAY1) is None


def test_restarted_chain_cannot_overwrite_an_existing_checkpoint(tmp_path):
    out = str(tmp_path / "out")
    write_checkpoint(_ledger(3), out, "2026-10-12")
    # A restarted membrane produces a different chain with the same length on the same day.
    other = EvidenceLedger()
    for i in range(3):
        other.append({"evidence_id": f"X{i}", "value": i})
    with pytest.raises(FileExistsError):
        write_checkpoint(other, out, "2026-10-12")
    assert len(os.listdir(out)) == 2

"""Hash-chained, append-only evidence ledger (RFC-4 section 4.2, CT-R4-008).

Each entry commits to the hash of the previous entry. Altering an entry's record,
reordering entries, or removing an entry from the middle breaks verification at the
first affected position.

Limits, stated explicitly:
* The chain alone cannot detect truncation of the tail. Detection requires the caller
  to anchor the head externally and pass it to ``verify(expected_head=...)``.
* This structure is standalone. It is not wired into ``Membrane.evidence_registry``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from .transition import canonical_bytes

GENESIS = "0" * 64


def _entry_hash(prev_hash: str, record: Mapping[str, Any]) -> str:
    material = canonical_bytes({"prev": prev_hash, "record": dict(record)})
    return hashlib.sha256(material).hexdigest()


@dataclass
class EvidenceLedger:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def head(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def append(self, record: Mapping[str, Any]) -> str:
        prev = self.head()
        digest = _entry_hash(prev, record)
        self.entries.append({"record": dict(record), "prev": prev, "hash": digest})
        return digest

    def verify(self, *, expected_head: str | None = None) -> tuple[bool, int | None]:
        """Return (True, None) if intact; otherwise (False, index of first bad position).

        If ``expected_head`` is given, the final head must match it. A mismatch is
        reported at ``len(entries)``, i.e. past the last entry, to signal truncation or
        extension relative to the anchor.
        """
        prev = GENESIS
        for index, entry in enumerate(self.entries):
            if entry["prev"] != prev or _entry_hash(prev, entry["record"]) != entry["hash"]:
                return False, index
            prev = entry["hash"]
        if expected_head is not None and prev != expected_head:
            return False, len(self.entries)
        return True, None


ANCHOR_FORMAT = "evidence-ledger-anchor/v1"


def anchor(ledger: EvidenceLedger) -> dict[str, Any]:
    """Return a publishable anchor for an intact ledger.

    Refuses to anchor a ledger whose chain does not verify: publishing a broken head
    would make a corrupted ledger look authoritative.
    """
    ok, index = ledger.verify()
    if not ok:
        raise ValueError(f"ledger is not intact at position {index}; refusing to anchor")
    return {"format": ANCHOR_FORMAT, "head": ledger.head(), "length": len(ledger.entries)}


def verify_against_anchor(ledger: EvidenceLedger, published: Mapping[str, Any]) -> tuple[bool, int | None]:
    """Verify a ledger against a previously published anchor.

    Detects tampering, truncation (the anchored head is no longer reached), and extension
    (the ledger has moved past the anchored head).
    """
    if published.get("format") != ANCHOR_FORMAT:
        raise ValueError(f"unsupported anchor format: {published.get('format')!r}")
    return ledger.verify(expected_head=published["head"])


ENTRIES_FORMAT = "evidence-ledger-entries/v1"


def dump(ledger: EvidenceLedger, path: str) -> None:
    """Write the ledger entries to a JSON file. The file is a checkpoint input, not an anchor."""
    import json

    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"format": ENTRIES_FORMAT, "entries": ledger.entries},
                  handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def load(path: str) -> EvidenceLedger:
    """Read a ledger from a JSON file written by dump(). Does not verify the chain."""
    import json

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("format") != ENTRIES_FORMAT:
        raise ValueError(f"unsupported entries format: {data.get('format')!r}")
    return EvidenceLedger(entries=list(data["entries"]))

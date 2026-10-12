"""Produce the anchor for a ledger checkpoint file.

Usage:
    PYTHONPATH=src python tools/checkpoint_ledger.py ledger-entries.json

Prints the anchor JSON to stdout. Exits non-zero if the chain does not verify, so a broken
ledger cannot be published as an anchor.
"""

import json
import sys

from tenir_conformance.membrane.evidence_ledger import anchor, load


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        published = anchor(load(argv[1]))
    except ValueError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(published, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

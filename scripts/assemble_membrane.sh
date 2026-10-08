#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cat scripts/membrane_parts/part0.txt \
    scripts/membrane_parts/part1.txt \
    scripts/membrane_parts/part2.txt \
  > src/tenir_conformance/membrane/membrane.py
python -m py_compile src/tenir_conformance/membrane/membrane.py
echo "membrane assembled: $(wc -c < src/tenir_conformance/membrane/membrane.py) bytes"
grep -q RECEIPT_OBJECT_REQUIRED src/tenir_conformance/membrane/membrane.py
grep -q NONCE_NOT_REGISTERED src/tenir_conformance/membrane/membrane.py
echo "strict A6 markers OK"

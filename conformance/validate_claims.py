#!/usr/bin/env python3
"""Fail-closed validation for version-bound conformance claims (stdlib only)."""
import json
import re
import sys
from pathlib import Path

STATUSES = {"DEMONSTRATED", "PARTIAL_EVIDENCE", "GAP", "NOT_DEMONSTRATED", "NOT_APPLICABLE", "NOT_CLAIMED"}
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")

def validate(claim):
    errors = []
    def need(obj, key, path):
        if not isinstance(obj, dict) or key not in obj:
            errors.append(f"{path}.{key}: missing")
            return None
        return obj[key]
    for k in ("schema_version", "product", "release", "implementation_commit", "reference", "suite", "evidence", "status"):
        need(claim, k, "claim")
    if claim.get("schema_version") != "1.0.0":
        errors.append("unsupported schema_version")
    for k in ("product", "release"):
        if not isinstance(claim.get(k), str) or not claim[k].strip():
            errors.append(f"{k}: nonempty string required")
    ref = claim.get("reference")
    for k in ("name", "version", "digest", "applicability"):
        need(ref, k, "reference")
    if isinstance(ref, dict):
        for k in ("name", "version"):
            if not isinstance(ref.get(k), str) or not ref[k].strip():
                errors.append(f"reference.{k}: nonempty string required")
        if ref.get("digest") is not None and (not isinstance(ref["digest"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", ref["digest"])):
            errors.append("reference.digest: invalid")
        if not isinstance(ref.get("applicability"), list) or any(not isinstance(x, str) or not x for x in ref["applicability"]):
            errors.append("reference.applicability: invalid")
        elif len(ref["applicability"]) != len(set(ref["applicability"])):
            errors.append("reference.applicability: duplicate")
    suite = claim.get("suite")
    for k in ("version", "commit"):
        need(suite, k, "suite")
    for path, value in (("implementation_commit", claim.get("implementation_commit")), ("suite.commit", suite.get("commit") if isinstance(suite, dict) else None)):
        if value is not None and (not isinstance(value, str) or not SHA.fullmatch(value)):
            errors.append(f"{path}: invalid SHA")
    ev = claim.get("evidence")
    if not isinstance(ev, list):
        errors.append("evidence: array required")
        ev = []
    for i, item in enumerate(ev):
        for k in ("id", "sha256", "run_id", "timestamp"):
            need(item, k, f"evidence[{i}]")
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("sha256"), str) or not DIGEST.fullmatch(item["sha256"]):
            errors.append(f"evidence[{i}].sha256: invalid")
        for k in ("id", "run_id", "timestamp"):
            if not isinstance(item.get(k), str) or not item[k].strip():
                errors.append(f"evidence[{i}].{k}: invalid")
    status = claim.get("status")
    if status not in STATUSES:
        errors.append("status: invalid")
    if status == "DEMONSTRATED":
        if not SHA.fullmatch(claim.get("implementation_commit") or ""):
            errors.append("DEMONSTRATED requires pinned implementation commit")
        if not isinstance(ref, dict) or not isinstance(ref.get("digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", ref["digest"]):
            errors.append("DEMONSTRATED requires pinned reference digest")
        if not isinstance(ref, dict) or not ref.get("applicability"):
            errors.append("DEMONSTRATED requires explicit applicable clauses")
        if not isinstance(suite, dict) or not suite.get("version") or not SHA.fullmatch(suite.get("commit") or ""):
            errors.append("DEMONSTRATED requires versioned and pinned suite")
        if not ev:
            errors.append("DEMONSTRATED requires evidence")
    return errors

def main(paths):
    if not paths:
        paths = [str(p) for p in sorted(Path("conformance").glob("**/*.json")) if not p.name.endswith(".schema.json")]
    if not paths:
        print("ERROR: no claim files found", file=sys.stderr)
        return 1
    failures = 0
    for path in paths:
        try:
            claim = json.loads(Path(path).read_text(encoding="utf-8"))
            errors = validate(claim)
        except (OSError, ValueError, TypeError) as exc:
            errors = [str(exc)]
        for err in errors:
            print(f"FAIL {path}: {err}")
        if errors:
            failures += 1
        else:
            print(f"PASS {path}")
    return int(failures > 0)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

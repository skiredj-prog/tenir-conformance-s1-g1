"""Worker script spawned by test_consensus_multi_process.py subprocess tests.

Each worker imports FileLockConsensusBackend from tenir_governance and
performs the operation(s) specified by a JSON instruction file, writing a
JSON result file. This keeps the subprocess interface simple and stable.

Usage:
    python3 tests/_consensus_worker.py <instruction_json> <result_json>

Instruction JSON schema:
{
    "store_dir": "/path/to/shared/store",
    "resource_id": "res-1",
    "capacity": 100,            // only used for "register" action
    "action": "reserve" | "commit" | "release" | "reconcile" | "register" | "reserve_many",
    "key": "idem-key",          // for reserve / reconcile
    "amount": 10,               // for reserve / reserve_many
    "reservation_id": "uuid",   // for commit / release
    "count": 5,                 // for reserve_many (distinct keys)
    "delay_before": 0.0,        // seconds to sleep before acting
    "delay_after": 0.0          // seconds to sleep after acting
}
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, "/workspace/tenir_governance_fixed")

from tenir_governance.operations.consensus_backend import FileLockConsensusBackend


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: _consensus_worker.py <instruction_json> <result_json>",
              file=sys.stderr)
        return 2

    instruction_path = sys.argv[1]
    result_path = sys.argv[2]

    with open(instruction_path, "r") as f:
        instr = json.load(f)

    store_dir = instr["store_dir"]
    backend = FileLockConsensusBackend(store_dir)

    action = instr["action"]
    resource_id = instr.get("resource_id", "res-1")

    if instr.get("delay_before", 0.0) > 0:
        time.sleep(instr["delay_before"])

    result: dict = {"action": action, "ok": True}

    if action == "register":
        capacity = instr["capacity"]
        backend.register_resource(resource_id, capacity)
        result["registered"] = True
        result["capacity"] = capacity

    elif action == "reserve":
        key = instr["key"]
        amount = instr["amount"]
        r = backend.reserve(key, amount, resource_id)
        result["status"] = r.status
        result["reservation_id"] = r.reservation_id
        result["amount_reserved"] = r.amount_reserved

    elif action == "reserve_many":
        count = instr["count"]
        amount = instr["amount"]
        key_prefix = instr.get("key_prefix", "key")
        statuses = []
        reservation_ids = []
        for i in range(count):
            r = backend.reserve(f"{key_prefix}-{i}", amount, resource_id)
            statuses.append(r.status)
            reservation_ids.append(r.reservation_id)
        result["statuses"] = statuses
        result["reservation_ids"] = reservation_ids
        result["reserved_count"] = sum(1 for s in statuses if s == "RESERVED")

    elif action == "commit":
        rid = instr["reservation_id"]
        r = backend.commit(rid)
        result["status"] = r.status

    elif action == "release":
        rid = instr["reservation_id"]
        r = backend.release(rid)
        result["status"] = r.status

    elif action == "reconcile":
        key = instr["key"]
        r = backend.reconcile(key)
        result["status"] = r.status
        result["effect_observed"] = r.effect_observed

    elif action == "get_state":
        st = backend.get_state(resource_id)
        result["available"] = st.available
        result["reserved"] = st.reserved
        result["committed"] = st.committed
        result["capacity"] = st.capacity

    else:
        result["ok"] = False
        result["error"] = f"unknown action: {action}"

    if instr.get("delay_after", 0.0) > 0:
        time.sleep(instr["delay_after"])

    with open(result_path, "w") as f:
        json.dump(result, f)

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
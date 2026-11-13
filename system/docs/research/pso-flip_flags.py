"""Flip the door flags directly in RAM - "with its mind", as the operator asked.

The gate model in `pso_coop_gates.py` documents the native stage-flag array, reverse-engineered from the barrier's own flag accessor at `0x80229220`:

```
STAGE_FLAG_BASE      = 0x80515CC8     # 18 groups (one per floor 0..17) x 32 bytes, MSB-first bits
STAGE_FLAG_GROUP_PTR = 0x805D5FC0     # holds the current floor == the accessor's group index
STAGE_GROUP_SIZE     = 32
```

and the sentence that makes this work: **"native_state (+0xAC) is futile - it is recomputed each frame FROM this flag."** The door does not store "open" anywhere writable; it asks this flag array
every frame. So setting the bit *is* flipping the switch, and no button press is needed.

Two modes:

* `--report` reads the current floor and dumps the group as hex plus which bits are set, so the state can be seen before touching it;
* `--set-all` sets every bit in the current floor's group, which is the blunt version of "open everything on this floor".

Each write is verified by reading the group back, because a write that does not land is exactly the failure mode that has wasted effort all session.
"""
import argparse
import time

from pso_pad import Pad, call

STAGE_FLAG_BASE = 0x80515CC8
STAGE_FLAG_GROUP_PTR = 0x805D5FC0
STAGE_GROUP_SIZE = 32


def read(pad, address, length):
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": address, "length": length}}, "POST")
    try:
        return bytes.fromhex(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def write(pad, address, blob):
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": address,
                                       "hex_bytes": blob.hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(12):
        time.sleep(0.5)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return row
    return {}


def bits(blob):
    out = []
    for index in range(len(blob) * 8):
        if blob[index // 8] & (0x80 >> (index % 8)):
            out.append(index)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-all", action="store_true", help="set every flag bit for the current floor")
    parser.add_argument("--clear-all", action="store_true", help="clear every flag bit for the current floor")
    args = parser.parse_args()

    pad = Pad()
    print("session:", pad.sid)

    floor_blob = read(pad, STAGE_FLAG_GROUP_PTR, 4)
    if not floor_blob:
        raise SystemExit("could not read the floor pointer")
    floor = int.from_bytes(floor_blob, "big")
    print("STAGE_FLAG_GROUP_PTR ->", hex(floor), "(", floor, ")")
    if not 0 <= floor < 18:
        print("note: that is outside 0..17, so it may not be a floor index; trying it anyway")

    address = STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE
    group = read(pad, address, STAGE_GROUP_SIZE)
    if not group:
        raise SystemExit("could not read the flag group")
    print(f"group at 0x{address:08X}: {group.hex(' ')}")
    print("bits set:", bits(group))

    if args.set_all or args.clear_all:
        target = bytes([0xFF] * STAGE_GROUP_SIZE) if args.set_all else bytes(STAGE_GROUP_SIZE)
        print(f"writing {target.hex(' ')} ...")
        row = write(pad, address, target)
        print("write:", row.get("state"), str(row.get("error"))[:120])
        time.sleep(0.6)
        after = read(pad, address, STAGE_GROUP_SIZE)
        print("after:", after.hex(" ") if after else None)
        print("bits set now:", bits(after) if after else None)
        print("VERIFIED" if after == target else "NOT VERIFIED - the write did not stick")

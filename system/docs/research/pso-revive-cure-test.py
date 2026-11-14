"""revive-cure-test: does the virtual Scape Doll's native revival clear the paralysis status?

If it does, the operator's stuck paralysis is gone without an item, and a RAM diff before/after identifies the status
field (the real goal: flip the flag and keep it flipped). Writes only the player's current-HP word (a normal audited
write) and lets the installed dispatcher's survival hook revive the character in place.
"""
from __future__ import annotations

import json
import os
import pathlib
import struct
import sys
import time
import urllib.request

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate\status")
CAVE = 0x80004C00
SURVIVAL = CAVE + 0x340


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=60):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def main() -> int:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    alive = [row for row in rows if row.get("state") in ("running", "starting")]
    sid = alive[0]["session_id"]
    worker = sid.split("-")[0]

    def rpc(op, **args):
        return call(f"/api/sessions/{sid}/rpc", {"op": op, "args": args}, "POST", 60)

    def read(address, length):
        raw = rpc("read_memory", address=address, length=length)
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def write(address, data):
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": worker,
                                 "input": {"session_id": sid, "address": address,
                                           "hex_bytes": data.hex()}}, "POST", 30)
        job_id = job.get("id") if isinstance(job, dict) else None
        deadline = time.monotonic() + 15
        while job_id and time.monotonic() < deadline:
            row = call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") == "succeeded":
                return True
            if isinstance(row, dict) and row.get("state") in ("failed", "cancelled"):
                raise RuntimeError(str(row.get("error"))[:300])
            time.sleep(0.1)
        raise RuntimeError(f"write failed: {str(job)[:300]}")

    def player():
        return (rpc("state") or {}).get("player") or {}

    def tap(key):
        for down in (True, False):
            call("/api/jobs", {"tool": "session_op", "require_worker": worker,
                               "input": {"session_id": sid, "op": "send_input",
                                         "args": {"events": [{"key": key, "down": down}]}}}, "POST")
            time.sleep(0.05)

    def attack_states(seconds=1.4):
        pointer = int(player()["ptr"], 16)
        tap("a")
        seen = set()
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            seen.add((int.from_bytes(read(pointer + 0xA8, 4), "big"),
                      int.from_bytes(read(pointer + 0x326, 2), "big")))
            time.sleep(0.04)
        return sorted(seen)

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    before = player()
    pointer = int(before["ptr"], 16)
    snapshot_before = read(pointer, 0x800)
    survival = int.from_bytes(read(SURVIVAL, 4), "big")
    states_before = attack_states()
    print(f"before: hp {before.get('hp')} ptr {pointer:#x} survival_flag {survival} "
          f"attack_states {states_before}", flush=True)
    if survival != 1:
        print("virtual Scape Doll is not armed (survival flag != 1); refusing to kill the character")
        return 2
    (OUT / f"pre-revive-{stamp}.bin").write_bytes(snapshot_before)
    hp_address = pointer + 0x32C
    if int.from_bytes(read(hp_address, 2), "big") == 0:
        print("already dead; waiting for the survival revive instead of writing HP")
    else:
        print(f"writing current HP 0 at {hp_address:#x}", flush=True)
        write(hp_address, b"\x00\x00")
    revived = {}
    for _ in range(40):
        time.sleep(0.25)
        state = player()
        if int(state.get("hp") or 0) > 0:
            revived = state
            break
    if not revived:
        print("no revival observed; the character may be dead or in a cutscene")
        return 1
    pointer = int(revived["ptr"], 16)
    snapshot_after = read(pointer, 0x800)
    (OUT / f"post-revive-{stamp}.bin").write_bytes(snapshot_after)
    states = attack_states()
    print(f"after: hp {revived.get('hp')} attack_states {states}", flush=True)
    diff = [offset for offset in range(0, min(len(snapshot_before), len(snapshot_after)))
            if snapshot_before[offset] != snapshot_after[offset]]
    report = {"before": before, "after": revived, "survival_flag": survival,
              "attack_states_before": states_before, "attack_states_after": states,
              "changed_offsets": [hex(offset) for offset in diff[:200]],
              "changed_count": len(diff)}
    path = OUT / f"revive-cure-{stamp}.json"
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"changed bytes in player header: {len(diff)}; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


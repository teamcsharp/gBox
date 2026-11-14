"""status-brute - find the PSO player status word by clearing candidate fields and testing whether attack works.

Measured fact: a paralysed player's attack press leaves the actor's action-state word (+0x326) at idle (1); a normal
press moves it into an attack state. So the field that carries the status can be found by trial: zero one candidate
small field, press attack once, and keep the write only if the action state moves. Every failed candidate is restored
byte-for-byte before the next one, and the search skips pointer-sized values (RAM/code addresses) and the known
position/HP fields.

    python pso-status-brute.py scan
    python pso-status-brute.py scan --max-offset 0x300
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import time
import urllib.request

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate\status")
ACTION_STATE = 0x326
KNOWN = {0x000, 0x038, 0x03C, 0x040, 0x2B8, 0x324, 0x326, 0x32C}
RAM_LO, RAM_HI = 0x80000000, 0x81800000
CODE_LO, CODE_HI = 0x8000C000, 0x80600000


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


class Session:
    def __init__(self) -> None:
        rows = call("/api/sessions")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        alive = [row for row in rows if row.get("state") in ("running", "starting")]
        if not alive:
            raise SystemExit("no live session")
        self.sid = alive[0]["session_id"]
        self.worker = self.sid.split("-")[0]

    def rpc(self, op, **args):
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST", 30)

    def read(self, address: int, length: int) -> bytes:
        raw = self.rpc("read_memory", address=address, length=length)
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def write(self, address: int, data: bytes) -> bool:
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": self.worker,
                                 "input": {"session_id": self.sid, "address": address,
                                           "hex_bytes": data.hex()}}, "POST", 30)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            row = call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") == "succeeded":
                return True
            if isinstance(row, dict) and row.get("state") in ("failed", "cancelled"):
                return False
            time.sleep(0.15)
        return False

    def player_ptr(self) -> int:
        return int(((self.rpc("state") or {}).get("player") or {}).get("ptr"), 16)

    def tap_attack(self) -> None:
        for down in (True, False):
            call("/api/jobs", {"tool": "session_op", "require_worker": self.worker,
                               "input": {"session_id": self.sid, "op": "send_input",
                                         "args": {"events": [{"key": "a", "down": down}]}}}, "POST", 20)
            time.sleep(0.05)


def attack_works(session: Session, ptr: int, *, window_s: float = 0.9) -> tuple:
    baseline = session.read(ptr + ACTION_STATE, 2)
    base = struct.unpack(">H", baseline)[0] if len(baseline) == 2 else None
    session.tap_attack()
    states = []
    end = time.monotonic() + window_s
    while time.monotonic() < end:
        raw = session.read(ptr + ACTION_STATE, 2)
        value = struct.unpack(">H", raw)[0] if len(raw) == 2 else None
        if not states or states[-1] != value:
            states.append(value)
        time.sleep(0.035)
    return any(value != base for value in states), base, states


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="find the PSO status word by clearing candidates")
    sub = parser.add_subparsers(dest="mode", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--base", default="", help="actor address override")
    scan.add_argument("--min-offset", default="0x28")
    scan.add_argument("--max-offset", default="0x440")
    args = parser.parse_args(argv)
    session = Session()
    ptr = int(args.base, 16) if args.base else session.player_ptr()
    OUT.mkdir(parents=True, exist_ok=True)
    lo, hi = int(args.min_offset, 0), int(args.max_offset, 0)
    data = session.read(ptr, hi)
    works, base_state, states = attack_works(session, ptr)
    print(f"player {ptr:#x}: baseline attack_moved={works} action_states={states}")
    if works:
        print("attack already works - no paralysis to clear")
        return 0
    tried, found = [], None
    started = time.monotonic()
    for offset in range(lo, hi - 3, 4):
        if offset in KNOWN:
            continue
        value = struct.unpack_from(">I", data, offset)[0]
        # only small values can be a status/counter word; RAM or code pointers are not candidates
        if value == 0 or value > 0x2000 or RAM_LO <= value < RAM_HI or CODE_LO <= value < CODE_HI:
            continue
        original = data[offset:offset + 4]
        if not session.write(ptr + offset, b"\x00\x00\x00\x00"):
            print(f"  {offset:#05x}: write failed")
            continue
        time.sleep(0.12)
        moved, base_state, states = attack_works(session, ptr, window_s=0.7)
        tried.append({"offset": offset, "was": original.hex(), "attack_moved": moved, "states": states})
        if moved:
            found = {"offset": offset, "was": original.hex(), "states": states}
            print(f"  FOUND at +{offset:#05x}: was {original.hex()}, attack states {states}")
            break
        session.write(ptr + offset, original)
        if len(tried) <= 5 or len(tried) % 15 == 0:
            print(f"  tried {len(tried)} candidates; last +{offset:#05x} (was {original.hex()}) - no")
    receipt = {"player": hex(ptr), "found": found, "tried": len(tried), "candidates": tried,
               "seconds": round(time.monotonic() - started, 1)}
    path = OUT / "status-brute.json"
    path.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print(f"tried {len(tried)} candidates in {receipt['seconds']}s; found={found is not None}; wrote {path}")
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())

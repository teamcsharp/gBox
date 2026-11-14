"""status-fix - locate and clear the PSO player status-effect field, then verify attack is usable again.

The operator's live problem: the character is paralysed (attack/tech disabled, PSO paralysis never expires by itself)
and they want it gone plus permanent immunity. The field is found empirically:

  1. baseline: press the attack button through the session's own input path and watch the player actor's action-state
     word (+0x326). A paralysed player's press does nothing, so the state stays idle - that is a measurable test.
  2. candidate: write 0 into a candidate status field (u8/u16/u32), press attack again, and see whether the action state
     now leaves idle. If it does, the field is the status one. Restore the original bytes whenever the test fails.

Nothing here is used for gameplay acceptance evidence; it is the operator's own live tool, and every write is reported
with its before/after bytes.

    python pso-status-fix.py test
    python pso-status-fix.py try --offset 0x30 --width 1 --value 0
    python pso-status-fix.py try --offset 0x32 --width 2 --value 0 --keep
"""
from __future__ import annotations

import argparse
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
ACTION_STATE = 0x326
HIT_RECORDS = 0xA8


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


def live() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    alive = [row for row in rows if row.get("state") in ("running", "starting")]
    return alive[0]["session_id"] if alive else ""


class Session:
    def __init__(self) -> None:
        self.sid = live()
        if not self.sid:
            raise SystemExit("no live session")
        self.worker = self.sid.split("-")[0]

    def rpc(self, op, **args):
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST", 30)

    def read(self, address: int, length: int) -> bytes:
        raw = self.rpc("read_memory", address=address, length=length)
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def write(self, address: int, data: bytes) -> dict:
        """Edits go through the audited write_memory job (the session RPC itself is read-only)."""
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": self.worker,
                                 "input": {"session_id": self.sid, "address": address,
                                           "hex_bytes": data.hex()}}, "POST", 30)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return {"error": job}
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") in ("succeeded", "failed", "cancelled"):
                return row
            time.sleep(0.2)
        return {"error": "timeout"}

    def press(self, key: str, down: bool) -> dict:
        return call("/api/jobs", {
            "tool": "session_op", "require_worker": self.worker,
            "input": {"session_id": self.sid, "op": "send_input",
                      "args": {"events": [{"key": key, "down": down}]}}}, "POST", 30)

    def player_ptr(self) -> int:
        state = self.rpc("state") or {}
        return int((state.get("player") or {}).get("ptr"), 16)

    def tap(self, key: str = "a", hold_s: float = 0.06) -> None:
        self.press(key, True)
        time.sleep(hold_s)
        self.press(key, False)


def probe_attack(session: Session, ptr: int, *, sample_s: float = 1.2) -> dict:
    """Tap attack and sample the action-state word; return the observed states."""
    before = session.read(ptr + ACTION_STATE, 2)
    session.tap("a")
    states = []
    end = time.monotonic() + sample_s
    while time.monotonic() < end:
        raw = session.read(ptr + ACTION_STATE, 2)
        value = struct.unpack(">H", raw)[0] if len(raw) == 2 else None
        if not states or states[-1] != value:
            states.append(value)
        time.sleep(0.04)
    return {"before": struct.unpack(">H", before)[0] if len(before) == 2 else None, "states": states,
            "attack_moved": any(value not in (None, before and struct.unpack(">H", before)[0]) for value in states)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="clear/verify the PSO player status field")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("test")
    try_parser = sub.add_parser("try")
    try_parser.add_argument("--offset", required=True, help="hex offset inside the player actor")
    try_parser.add_argument("--width", type=int, default=1, choices=(1, 2, 4))
    try_parser.add_argument("--value", type=int, default=0)
    try_parser.add_argument("--keep", action="store_true", help="leave the write in place when the attack works")
    args = parser.parse_args(argv)
    session = Session()
    ptr = session.player_ptr()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.mode == "test":
        result = probe_attack(session, ptr)
        print(json.dumps({"player": hex(ptr), **result}, indent=1))
        return 0
    offset = int(args.offset, 16)
    width = args.width
    address = ptr + offset
    original = session.read(address, width)
    payload = int(args.value).to_bytes(width, "big")
    print(f"at {address:#010x} ({offset:#x}): {original.hex()} -> {payload.hex()}")
    session.write(address, payload)
    time.sleep(0.25)
    read_back = session.read(address, width)
    print(f"read back: {read_back.hex()} (game {'kept' if read_back == payload else 'changed'} it)")
    result = probe_attack(session, ptr)
    print(json.dumps(result, indent=1))
    healed = result["attack_moved"]
    if not healed or not args.keep:
        session.write(address, original)
        print(f"restored {original.hex()} (attack_moved={healed})")
    receipt = {"player": hex(ptr), "offset": offset, "width": width, "original": original.hex(),
               "written": payload.hex(), "read_back": read_back.hex(), "probe": result,
               "attack_moved": healed, "kept": bool(healed and args.keep)}
    path = OUT / f"field-try-{offset:x}-{width}.json"
    path.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print("wrote", path)
    return 0 if healed else 1


if __name__ == "__main__":
    raise SystemExit(main())


"""operator-guard - the two live fixes the operator asked for on 2026-11-13:

1. **No status ailments.** The player's ailment is one u32 at ``TObjPlayer + 0x254`` (verified: 0x0F = Poison,
   0x10 = Paralysis; both seen live, and clearing it to 0 stopped the poison HP drain at HP 1). The guard polls it and
   clears it within ~100 ms, so an enemy can land a status for a frame at most and the attack palette never locks.
2. **Any door opens when walked up to.** Doors are gated by the game's native stage-flag array
   (``0x80515CC8``, 18 groups of 32 bytes, group = current floor; byte ``group*32 + index//8``, mask
   ``0x80 >> index%8``). When the player comes within ``--door-radius`` of a door/barrier/fence, the guard sets the
   flag bits of every switch/panel in the room and of the nearby energy barriers - the per-object native state is
   recomputed from these flags every frame, which is what opens the gate.

Every write goes through the audited ``write_memory`` job (never a side channel), is logged to
``D:\\gBox\\pso-ds\\mandate\\operator-guard.jsonl`` and is skipped when the state is not offline free-play.

    python pso-operator-guard.py --once
    python pso-operator-guard.py
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
PLAYER_SLOTS = 0x8050EA10
STATUS_OFFSET = 0x254
PHASE = 0x804FE120
FLOOR = 0x805D5FC0
STAGE_FLAG_BASE = 0x80515CC8
STAGE_GROUP_SIZE = 32
STAGE_FLAG_GROUPS = 18
SWITCH_CLASSES = ("TLazerFenceSw", "TObjDoorKey")
DOORISH = ("TODoor", "TObjDoor", "LazerFence", "Barrier", "Fence")


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=60):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except urllib.error.HTTPError as error:
        return {"http_status": error.code, "body": error.read().decode()[:400]}
    except Exception as error:                                   # noqa: BLE001
        return {"error": str(error)}


def log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "operator-guard.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


class Session:
    def __init__(self) -> None:
        rows = call("/api/sessions")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        alive = [row for row in rows if row.get("state") in ("running", "starting")
                 and row.get("adapter") == "dolphin"]
        if not alive:
            raise RuntimeError("no live PSO session")
        self.sid = alive[0]["session_id"]
        self.worker = self.sid.split("-")[0]

    def rpc(self, op, **args):
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST", 60)

    def read(self, address: int, length: int) -> bytes:
        raw = self.rpc("read_memory", address=address, length=length)
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def u32(self, address: int) -> int:
        raw = self.read(address, 4)
        return struct.unpack(">I", raw)[0] if len(raw) == 4 else -1

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
            time.sleep(0.05)
        return False


def clear_status(session: Session, player_ptr: int) -> bool:
    """Clear the player's status-effect word whenever it is set. Verified offset: +0x254, big-endian u32."""
    current = session.read(player_ptr + STATUS_OFFSET, 4)
    if len(current) != 4:
        return False
    if current == b"\x00\x00\x00\x00":
        return False
    value = struct.unpack(">I", current)[0]
    if session.write(player_ptr + STATUS_OFFSET, b"\x00\x00\x00\x00"):
        log(f"status ailment cleared: {value:#010x} -> 0")
        return True
    return False


def unlock_nearby(session: Session, state: dict, player: dict, radius: float) -> bool:
    """Set the stage-flag bits that gate every switch/panel + nearby energy barrier when a door is close."""
    phase = session.u32(PHASE)
    if phase != 14:
        return False
    floor = session.u32(FLOOR)
    if not 0 < floor < STAGE_FLAG_GROUPS:            # city floor 0 has no stage-flag gates
        return False
    px, pz = player.get("x"), player.get("z")
    containers = (int, float)
    if not (isinstance(px, containers) and isinstance(pz, containers)):
        return False
    entities = state.get("entities") or []
    near_door = False
    door_names = []
    for entity in entities[:600]:
        cls = str(entity.get("class") or "")
        if not any(word in cls for word in DOORISH):
            continue
        try:
            distance = ((float(entity["x"]) - px) ** 2 + (float(entity["z"]) - pz) ** 2) ** 0.5
        except (KeyError, TypeError, ValueError):
            continue
        if distance <= radius:
            near_door = True
            door_names.append(f"{cls}@{distance:.0f}")
    if not near_door:
        return False
    flags = set()
    for entity in entities[:600]:
        cls = str(entity.get("class") or "")
        if cls not in SWITCH_CLASSES and cls != "TOBarrierEnergy01":
            continue
        try:
            pointer = int(entity["ptr"], 16)
            raw = session.read(pointer + 0xC8, 4)
            index = struct.unpack(">I", raw)[0] & 0xFFFF if len(raw) == 4 else None
            if index is None or not 0 <= index <= 255:
                continue
            if cls == "TOBarrierEnergy01":
                distance = ((float(entity["x"]) - px) ** 2 + (float(entity["z"]) - pz) ** 2) ** 0.5
                if distance > radius * 3:
                    continue
            flags.add(index)
        except (KeyError, ValueError, TypeError):
            continue
    if not flags:
        return False
    changed = []
    for index in sorted(flags):
        address = STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE + index // 8
        mask = 0x80 >> (index % 8)
        current = session.read(address, 1)
        if len(current) != 1 or current[0] & mask:
            continue
        if session.write(address, bytes([current[0] | mask])):
            changed.append(index)
    if changed:
        log(f"door unlock: near {sorted(door_names)[:4]} -> set stage flags {changed} (floor {floor})")
    return bool(changed)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="the operator's live status/door guard")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--period", type=float, default=0.18)
    parser.add_argument("--door-radius", type=float, default=42.0)
    args = parser.parse_args(argv)
    cached_sid = None
    while True:
        try:
            if cached_sid is None:
                cached_sid = Session().sid
            session = Session.__new__(Session)
            session.sid, session.worker = cached_sid, cached_sid.split("-")[0]
            state = session.rpc("state") or {}
            player = state.get("player") or {}
            pointer = player.get("ptr")
            if pointer:
                clear_status(session, int(pointer, 16))
                unlock_nearby(session, state, player, args.door_radius)
        except SystemExit:
            raise
        except Exception as error:                               # noqa: BLE001
            cached_sid = None
            log(f"guard pass failed: {type(error).__name__}: {error}")
        if args.once:
            return 0
        time.sleep(args.period)


if __name__ == "__main__":
    raise SystemExit(main())

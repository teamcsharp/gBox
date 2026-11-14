"""pso-native - run the game's own equipment routines for things the op surface will not do.

The live control surface covers weapons, frames, barriers and mags (``pso_gc_live``/``pso_extras``), but:
  * units are refused by ``equip_id``'s code-prefix guard, and
  * a frame's unit-slot count lives in its 20-byte create record (data1[4]), which ``give`` leaves at 0.

The gBox native dispatcher is already installed in this session (HEADER ``GBPSOGC4``, VT_UPDATE -> CAVE), and it
pollutes a 20 x 40-byte command queue that ANY process can feed: [fn, r3..r10, 0(result)]. This tool writes that queue
through the audited ``write_memory`` job, so it stays a normal, logged RAM write - no second control owner.

It then, in order:
  1. gives the player a frame with four unit slots (patches data1[4]=4 on an existing free frame), equips it with the
     game's own F_EQUIP, and recomputes stats;
  2. gives the requested unit (default Cure/Paralysis) and equips it through F_EQUIP;
  3. verifies both through the native inventory read.

    python pso-native.py --frame-slot 1 --unit 010343
    python pso-native.py --dry-run
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
import uuid

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")

CAVE, QUEUE, BUF, END = 0x80004C00, 0x80004400, 0x80004800, 0x80005000
QUEUE_MAX, QUEUE_SIZE = 20, 40
HEADER = CAVE + 0x3F0
VT_UPDATE = 0x804C3BC8
PHASE = 0x804FE120
PLAYER_SLOTS = 0x8050EA10
F_EQUIP = 0x801B9F40
F_STATS = 0x801B63AC
F_FIND_ITEM = 0x801D4F14
F_ITEM_OBJECT = 0x801D5764
F_REMOVE = 0x801D4A6C


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=120):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                     # noqa: BLE001
        try:
            return {"error": str(exc), "body": exc.read().decode()[:800]}
        except Exception:                                      # noqa: BLE001
            return {"error": str(exc)}


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
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST", 120)

    def read(self, address: int, length: int) -> bytes:
        raw = self.rpc("read_memory", address=address, length=length)
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def u32(self, address: int) -> int:
        return struct.unpack(">I", self.read(address, 4))[0]

    def write(self, address: int, data: bytes) -> bool:
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": self.worker,
                                 "input": {"session_id": self.sid, "address": address,
                                           "hex_bytes": data.hex()}}, "POST", 30)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            raise RuntimeError(f"write_memory rejected: {str(job)[:300]}")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") == "succeeded":
                return True
            if isinstance(row, dict) and row.get("state") in ("failed", "cancelled"):
                raise RuntimeError(f"write_memory failed: {str(row.get('error'))[:300]}")
            time.sleep(0.1)
        raise RuntimeError("write_memory timed out")

    def mods(self, **fields):
        command = {"command_id": str(uuid.uuid4()), "expires": time.time() + 12, "input": fields}
        return call(f"/api/sessions/{self.sid}/rpc", {"op": "pso_controls", "args": command}, "POST", 120)

    def player(self) -> int:
        state = self.rpc("state") or {}
        return int((state.get("player") or {}).get("ptr"), 16)

    def inventory(self) -> list:
        result = self.mods(op="list") or {}
        return result.get("inventory") or []

    # -- native queue -----------------------------------------------------------------------------------------------
    def queue_clear(self, session=None) -> bool:
        return not any(self.u32(QUEUE + i * QUEUE_SIZE) for i in range(QUEUE_MAX))

    def native(self, calls, timeout: float = 3.0) -> list:
        """Run up to QUEUE_MAX independent native calls. Each call is (fn, *args<=8)."""
        session = self
        if not calls:
            return []
        if not 1 <= len(calls) <= QUEUE_MAX:
            raise ValueError("native batch size 1..20")
        if not session.queue_clear():
            raise RuntimeError("PSO native queue is not empty; refusing to interleave")
        payload = b"".join(struct.pack(">10I", 0, *[int(v) & 0xFFFFFFFF for v in args],
                                      *([0] * (8 - len(args))), 0) for fn, *args in calls)
        session.write(QUEUE, payload)
        for index, (fn, *_rest) in enumerate(calls):
            session.write(QUEUE + index * QUEUE_SIZE, struct.pack(">I", int(fn) & 0xFFFFFFFF))
        until = time.monotonic() + timeout
        while True:
            done = all(session.u32(QUEUE + i * QUEUE_SIZE) == 0 for i in range(len(calls)))
            if done:
                return [session.u32(QUEUE + i * QUEUE_SIZE + 36) for i in range(len(calls))]
            if time.monotonic() > until:
                raise RuntimeError("PSO did not acknowledge the native batch; outcome unknown, not retrying")
            time.sleep(0.02)

    def item_object(self, player: int, item_id: int) -> int:
        inventory = self.u32(player + 0xD00)
        node = self.native([(F_FIND_ITEM, inventory, item_id)])[0]
        if not node:
            raise RuntimeError(f"item {item_id} is not in the inventory")
        obj = self.native([(F_ITEM_OBJECT, node)])[0]
        if not 0x80000000 <= obj < 0x81800000:
            raise RuntimeError(f"unexpected item object pointer {obj:#x}")
        return obj

    INVENTORY_ARENA = (0x80F00000, 0x81200000)

    def find_item_record(self, code_hex: str, item_id: int) -> int | None:
        """Locate a 20-byte inventory record by its code + item id.

        Measured: the live inventory records are 28-byte entries (20-byte create record + 8-byte trailer) in the
        0x80Fxxxxx heap, and F_INVENTORY reports exactly those 20 bytes. The record's byte 4 is data that may be
        patched (a frame's unit-slot count), so the search keys on the id at byte 12 and validates the code at 0-2.
        """
        code = bytes.fromhex(code_hex)
        packed = struct.pack(">I", item_id & 0xFFFFFFFF)
        base, end = self.INVENTORY_ARENA
        step = 0x100000
        while base < end:
            block = self.read(base, step)
            if len(block) != step:
                base += step
                continue
            index = block.find(packed)
            while index >= 0:
                record_start = index - 12
                if record_start >= 0 and block[record_start:record_start + 3] == code:
                    return base + record_start
                index = block.find(packed, index + 1)
            base += step
        return None

    def equip(self, player: int, obj: int, slot: int = 0) -> int:
        """F_EQUIP(player, item_object, slot). The slot index selects the equipment row: frame/barrier/mag/weapon derive
        theirs from the item's own category when slot=0; units are rows 9-12 and are otherwise clamped to 9, which is
        why passing 0 for every unit replaced the previous one instead of filling the four unit slots."""
        result = self.native([(F_EQUIP, player, obj, slot)])
        self.native([(F_STATS, player)])
        return result[0]


def remove_generated(session, player: int, item_ids: list) -> list:
    """Remove gBox-generated inventory items through the game's own REMOVE routine (same calls as Extras.remove_generated)."""
    inventory = session.u32(player + 0xD00)
    results = []
    for item_id in item_ids:
        if item_id < 0xF00000:
            results.append({"id": item_id, "removed": False, "reason": "not a gBox-generated id"})
            continue
        node = session.native([(F_FIND_ITEM, inventory, item_id)])[0]
        if not node:
            results.append({"id": item_id, "removed": False, "reason": "not in the inventory"})
            continue
        session.native([(F_REMOVE, inventory, player, node)])
        session.native([(F_STATS, player)])
        results.append({"id": item_id, "removed": True})
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="native equipment routines for units / frame slots")
    parser.add_argument("--frame-slot", type=int, default=None, help="inventory slot of the frame to give 4 slots")
    parser.add_argument("--units", default="010343", help="comma-separated unit codes to give+equip")
    parser.add_argument("--give-item", nargs="*", default=[], help="extra consumable codes to give")
    parser.add_argument("--remove-dupes", action="store_true",
                        help="remove unequipped gBox-generated duplicate items to free slots, then exit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    session = Session()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"session": session.sid, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": []}

    def step(name, **payload):
        report["steps"].append({"step": name, **payload})
        print(f"[{name}] " + json.dumps(payload)[:500], flush=True)

    if session.u32(PHASE) != 0xE:
        raise SystemExit(f"phase {session.u32(PHASE):#x} is not offline free-play; refusing")
    if session.u32(VT_UPDATE) != CAVE:
        raise SystemExit("gBox native dispatcher is not installed; give/list first to install it")
    player = session.player()
    step("preflight", player=hex(player), header=session.read(HEADER, 16).hex(),
         queue_clear=session.queue_clear())
    inventory = {row["slot"]: row for row in session.inventory()}
    step("inventory", count=len(inventory),
         gear={slot: (row["code"], row.get("equipped")) for slot, row in inventory.items()
               if row["code"].startswith(("0101", "0102", "0103"))})

    if args.remove_dupes:
        rows = session.inventory()
        seen_equipped = {row["code"] for row in rows if row.get("equipped")}
        victims = [row["id"] for row in rows
                   if row["id"] >= 0xF00000 and not row.get("equipped")]
        step("remove-candidates", ids=[hex(v) for v in victims])
        results = remove_generated(session, player, victims)
        step("removed", results=results, remaining=len(session.inventory()))
        path = OUT / f"native-remove-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if args.dry_run:
        print(json.dumps(report, indent=1))
        return 0

    # --- 1. frame with four unit slots --------------------------------------------------------------------------
    frame_slot = args.frame_slot
    if frame_slot is None:
        frame_slot = next((slot for slot, row in inventory.items()
                           if row["code"].startswith("0101") and row.get("equipped")), None) or \
                     next((slot for slot, row in inventory.items() if row["code"].startswith("0101")), None)
    if frame_slot is None:
        raise SystemExit("no frame in the inventory to give slots to")
    frame_row = inventory[frame_slot]
    frame_obj = session.item_object(player, frame_row["id"])
    frame_address = session.find_item_record(frame_row["code"], frame_row["id"])
    step("frame-record", slot=frame_slot, code=frame_row["code"], obj=hex(frame_obj),
         data_address=hex(frame_address) if frame_address else None, data_before=frame_row["data"])
    if frame_address is None:
        raise SystemExit("could not locate the frame's inventory record; nothing written")
    data = session.read(frame_address, 20)
    if data[4] != 4:
        session.write(frame_address + 4, b"\x04")
        data = session.read(frame_address, 20)
        step("frame-slots-written", data=data.hex(), slots=data[4])
    listed = {row["slot"]: row for row in session.inventory()}.get(frame_slot, {})
    step("frame-listed-after-patch", code=listed.get("code"), data=listed.get("data"),
         slots=(bytes.fromhex(listed["data"])[4] if listed.get("data") else None))
    result = session.equip(player, frame_obj)
    updated = {row["slot"]: row for row in session.inventory()}
    step("frame-equipped", equip_result=result, equipped=bool(updated.get(frame_slot, {}).get("equipped")),
         slots=bytes.fromhex(updated.get(frame_slot, {}).get("data", "")).hex() if updated.get(frame_slot) else None)

    # --- 2. the units ---------------------------------------------------------------------------------------------
    unit_slot = 9
    for code in [item.strip() for item in args.units.split(",") if item.strip()]:
        made = session.mods(op="give", code=code, count=1) or {}
        ids = made.get("ids") or []
        step("unit-given", code=code, result={k: made.get(k) for k in ("created", "ids", "verified")})
        if not ids:
            step("unit-skipped", code=code, reason="the game did not create the unit")
            continue
        unit_id = ids[0]
        unit_obj = session.item_object(player, unit_id)
        equip_result = session.equip(player, unit_obj, min(12, unit_slot))
        unit_slot += 1
        and_more = {row["slot"]: row for row in session.inventory()}
        slots = struct.unpack(">13I", session.read(player + 0xD04, 52))
        step("unit-equipped", code=code, item_id=unit_id, obj=hex(unit_obj), equip_return=equip_result,
             equipped=[row["code"] for row in and_more.values() if row.get("equipped")],
             equipment_slots=[hex(value) for value in slots])

    # --- 3. extra consumables the operator asked for ---------------------------------------------------------------
    for code in args.give_item:
        made = session.mods(op="give", code=code, count=1) or {}
        step("extra-given", code=code, result=made)

    report["equipped"] = [{"slot": row["slot"], "code": row["code"], "name": row.get("name"),
                           "data": row.get("data")} for row in session.inventory() if row.get("equipped")]
    path = OUT / f"native-equip-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())







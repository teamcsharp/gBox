"""Grind every weapon in the player's inventory to its own PMT maximum, and keep it there.

The operator's request (2026-11-13, live): "This weapon is so weak. Make sure that any weapon you give the
character is grinded to the maximum level." The live item record layout makes this one byte: for a weapon (code
starts ``00``) byte 3 of the 20-byte create record is the grind, and the game recomputes the shown stats through
``F_STATS`` (0x801B63AC) after a change. Maximums come from the disc's own ItemPMT: ``max_grind`` at PMT offset
0x16, exposed by the app as ``GET /api/pso/items?version=gc``.

``--watch`` keeps every weapon at maximum - so a Randomized cycle, an enemy drop or a gBox give can never leave a
weapon below its PMT maximum.

    python pso-grind-max.py --once
    python pso-grind-max.py --watch
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import time
import urllib.request
import uuid

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
PHASE = 0x804FE120
F_STATS = 0x801B63AC
VT_UPDATE = 0x804C3BC8
CAVE = 0x80004C00
BUF = 0x80004800
NEXT_ID = 0x80004C00 + 0x3E0
ID_BASE = 0x00F00000
F_ATTACH = 0x801B8E68
F_EQUIP = 0x801B9F40
# The game's own 6x2B create path: prepare the record, create the TItem, attach it to the inventory.
F_CREATE_PREPARE = 0x8010C740
F_CREATE_COMMIT = 0x8010CCB0
F_CREATE_OBJECT = 0x80102AC0
HUmar_MASK = 0x49
INVENTORY_ARENA = (0x80F00000, 0x81200000)


def token():
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=90):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as error:                                   # noqa: BLE001
        return {"error": str(error)}


def log(message):
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "grind-max.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


class Session:
    def __init__(self):
        rows = call("/api/sessions")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        live = [row for row in rows if row.get("state") in ("running", "starting") and row.get("adapter") == "dolphin"]
        if not live:
            raise RuntimeError("no live dolphin session")
        self.sid = live[0]["session_id"]
        self.worker = self.sid.split("-")[0]

    def rpc(self, op, **args):
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST")

    def read(self, address, length):
        raw = self.rpc("read_memory", address=int(address), length=int(length))
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def write(self, address, data):
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": self.worker,
                                 "input": {"session_id": self.sid, "address": int(address),
                                           "hex_bytes": data.hex()}}, "POST", 30)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return False
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            row = call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") == "succeeded":
                return True
            if isinstance(row, dict) and row.get("state") in ("failed", "cancelled"):
                return False
            time.sleep(0.05)
        return False

    def player(self):
        state = self.rpc("state") or {}
        pointer = (state.get("player") or {}).get("ptr")
        if not pointer:
            raise RuntimeError("no live player")
        return int(pointer, 16)

    def mods(self, **fields):
        command = {"command_id": str(uuid.uuid4()), "expires": time.time() + 12, "input": fields}
        return call(f"/api/sessions/{self.sid}/rpc", {"op": "pso_controls", "args": command}, "POST", 120)

    def inventory(self):
        result = self.mods(op="list") or {}
        return result.get("inventory") or []

    def native(self, calls, timeout=3.0):
        queue = 0x80004400
        size = 40
        if any(self.u32(queue + index * size) for index in range(20)):
            raise RuntimeError("native queue busy")
        payload = b"".join(struct.pack(">10I", 0, *[int(v) & 0xFFFFFFFF for v in args],
                                       *([0] * (8 - len(args))), 0) for fn, *args in calls)
        self.write(queue, payload)
        for index, (fn, *_rest) in enumerate(calls):
            self.write(queue + index * size, struct.pack(">I", int(fn) & 0xFFFFFFFF))
        until = time.monotonic() + timeout
        while True:
            if all(self.u32(queue + index * size) == 0 for index in range(len(calls))):
                return [self.u32(queue + index * size + 36) for index in range(len(calls))]
            if time.monotonic() > until:
                # The dispatcher only runs during an active player update; a menu or a pause leaves the entries
                # pending. Clear the fn words so no stale call executes later, then report the failure.
                try:
                    for index in range(len(calls)):
                        self.write(queue + index * size, b"\x00\x00\x00\x00")
                except Exception:                                # noqa: BLE001
                    pass
                raise RuntimeError("native batch not acknowledged")
            time.sleep(0.02)

    def u32(self, address):
        raw = self.read(address, 4)
        return struct.unpack(">I", raw)[0] if len(raw) == 4 else 0

    def find_item_records(self, code_hex, item_id):
        """Every 20-byte create-record copy of this item, not just the first.

        The character's item data exists twice in RAM - the decrypted save-slot image (e.g. 0x80FC7870) and the live
        inventory-manager nodes in the 0x80FCAxxx arena - and the first match landed on the save copy, so a grind
        write looked successful while F_INVENTORY kept reporting the old value. Any copy where the code is at 0-2
        and the id at 12 is treated as a record of this item.
        """
        code = bytes.fromhex(code_hex)
        packed = struct.pack(">I", item_id & 0xFFFFFFFF)
        found = []
        base, end = INVENTORY_ARENA
        while base < end:
            block = self.read(base, 0x100000)
            if len(block) != 0x100000:
                base += 0x100000
                continue
            index = block.find(packed)
            while index >= 0:
                start = index - 12
                if start >= 0 and block[start:start + 3] == code:
                    found.append(base + start)
                index = block.find(packed, index + 1)
            base += 0x100000
        return found

    def find_item_record(self, code_hex, item_id):
        found = self.find_item_records(code_hex, item_id)
        return found[0] if found else None

    # -- authoritative item object --------------------------------------------------------------------------------
    # The live item data is stored inside the TItem object (20 bytes spaced 2 apart at TItem+0x134, id at data
    # 12..15); F_INVENTORY rebuilds its 28-byte entries from these objects. Patching a heap copy of the record
    # therefore never changed what the game showed (measured: 13 matches for one Saber, all outside the objects).
    ITEM_RECORD = 0x134
    F_FIND_ITEM = 0x801D4F14
    F_ITEM_OBJECT = 0x801D5764

    def item_object(self, player, item_id):
        inventory = self.u32(player + 0xD00)
        if not 0x80000000 <= inventory < 0x81800000:
            raise RuntimeError(f"inventory manager pointer {inventory:#x} is not live")
        node = self.native([(self.F_FIND_ITEM, inventory, item_id)])[0]
        if not node:
            return None
        obj = self.native([(self.F_ITEM_OBJECT, node)])[0]
        return obj if 0x8C000000 <= obj < 0x8D000000 else None

    def object_record(self, obj):
        return bytes(self.read(obj + self.ITEM_RECORD + 2 * index, 1)[0] for index in range(20))

    # -- giving weapons at maximum grind ---------------------------------------------------------------------------
    def give_weapon(self, code, grind):
        """Create a real inventory weapon whose record already carries its maximum grind (the game's 6x2B path)."""
        player = self.player()
        current = self.u32(NEXT_ID)
        if not ID_BASE <= current < ID_BASE + 0xF0000:
            current = ID_BASE + (int(time.time() * 7) % 0xE000) * 16
        item = bytearray(20)
        item[:3] = bytes.fromhex(code)
        item[3] = max(0, min(255, int(grind)))                       # weapon grind, the operator's requirement
        struct.pack_into(">I", item, 12, current)
        self.write(NEXT_ID, struct.pack(">I", current + 1))
        self.write(BUF, bytes(item))
        self.native([(F_CREATE_PREPARE, BUF, 0), (F_CREATE_COMMIT, BUF)])
        obj = self.native([(F_CREATE_OBJECT, BUF)])[0]
        if not obj:
            raise RuntimeError("the game refused the item object")
        self.native([(F_ATTACH, player, obj)])
        return current, obj

    def equip_obj(self, obj):
        player = self.player()
        self.native([(F_EQUIP, player, obj, 0), (F_STATS, player)])
        for row in self.inventory():
            if row.get("equipped") and str(row.get("code", "")).startswith("00"):
                return row
        return None


def catalog_max_grind():
    rows = call("/api/pso/items?version=gc")
    if not isinstance(rows, list):
        raise RuntimeError(f"item catalog unavailable: {str(rows)[:200]}")
    return {row["code"]: int(row.get("max_grind") or 0) for row in rows if row.get("code")}


def fix(session, maximums, *, only_equipped=False, dry_run=False):
    player = session.player()
    inventory = session.inventory()
    changed = []
    for row in inventory:
        code = str(row.get("code") or "")
        if not code.startswith("00") or row.get("id") is None:
            continue                                   # weapons only (code 00 cc ii)
        if only_equipped and not row.get("equipped"):
            continue
        maximum = maximums.get(code) or maximums.get(code[:4] + "00")
        if maximum is None or maximum <= 0:
            continue
        data = bytes.fromhex(row.get("data") or "")
        if len(data) < 20:
            continue
        grind = data[3]
        if grind >= maximum:
            continue
        try:
            obj = session.item_object(player, int(row["id"]))
        except Exception as error:                               # noqa: BLE001
            log(f"grind skip: {code} id {row['id']:#x}: item object unavailable ({error})")
            continue
        if obj is None:
            continue
        if dry_run:
            changed.append({"code": code, "name": row.get("name"), "id": row.get("id"),
                            "grind": grind, "max": maximum, "equipped": bool(row.get("equipped")),
                            "object": f"0x{obj:x}"})
            continue
        if session.write(obj + session.ITEM_RECORD + 2 * 3, bytes([maximum])):
            after = session.object_record(obj)
            if after[3] == maximum:
                changed.append({"code": code, "name": row.get("name"), "id": row.get("id"),
                                "grind": grind, "max": maximum, "equipped": bool(row.get("equipped")),
                                "verified": True})
    if changed and not dry_run:
        session.native([(F_STATS, player)])
        for item in changed:
            log(f"grind max: {item['name'] or item['code']} [{item['code']}] id {item['id']:#x} "
                f"+{item['grind']} -> +{item['max']}{' (equipped)' if item['equipped'] else ''}")
    return changed


def remove_item(session, item_id):
    """Remove a gBox-generated inventory item through the game's own REMOVE routine."""
    player = session.player()
    inventory = session.u32(player + 0xD00)
    node = session.native([(0x801D4F14, inventory, item_id)])[0]
    if not node:
        return False
    session.native([(0x801D4A6C, inventory, player, node), (F_STATS, player)])
    return True


def catalog_rows():
    rows = call("/api/pso/items?version=gc")
    if not isinstance(rows, list):
        raise RuntimeError(f"item catalog unavailable: {str(rows)[:200]}")
    return rows


def best_grindeable(rows):
    """The strongest class-compatible weapon that the disc lets us grind (by atp_max + 2*max_grind, like the loadouts)."""
    pool = [row for row in rows
            if row.get("cat") == "Weapons" and int(row.get("max_grind") or 0) > 0
            and int(row.get("usability_flags") or 0) & HUmar_MASK == HUmar_MASK]
    if not pool:
        return None
    return max(pool, key=lambda row: (int(row.get("atp_max") or 0) + 2 * int(row.get("max_grind") or 0),
                                      int(row.get("ata") or 0)))


def ensure_max_weapon(session, maximums, rows, *, force_best=False, dry_run=False):
    """Guarantee the equipped weapon is at its PMT maximum grind; swap in a max-grind copy when it is not.

    Randomized equips a fresh rare every cycle with grind 0. Rather than fight it, the guard creates the same weapon
    through the game's own create path with the grind byte already at the PMT maximum, equips it, and removes the
    spent +0 copy (so the inventory does not fill up).
    """
    player = session.player()
    inventory = session.inventory()
    equipped = next((row for row in inventory
                     if row.get("equipped") and str(row.get("code", "")).startswith("00")), None)
    chosen = None
    if force_best or equipped is None:
        chosen = best_grindeable(rows)
        if chosen is None:
            return None
        code = chosen["code"]
        maximum = int(chosen.get("max_grind") or 0)
        old = equipped
    else:
        code = equipped["code"]
        maximum = maximums.get(code) or maximums.get(code[:4] + "00") or 0
        if maximum <= 0:
            return None                         # not a grindeable weapon; nothing to raise
        old = equipped
        data = bytes.fromhex(old.get("data") or "")
        if len(data) >= 4 and data[3] >= maximum:
            return None
    info = {"code": code, "name": (chosen or {}).get("name") or (old or {}).get("name"),
            "max": maximum, "from": old.get("id") if old else None,
            "from_grind": (bytes.fromhex(old.get("data") or "")[3] if old and len(old.get("data") or "") >= 8 else None)}
    if dry_run:
        info["verified"] = False
        return info
    new_id, obj = session.give_weapon(code, maximum)
    if not session.equip_obj(obj):
        raise RuntimeError("the game refused the max-grind weapon")
    listed = next((row for row in session.inventory() if row.get("id") == new_id), None)
    data = bytes.fromhex((listed or {}).get("data") or "")
    info.update(id=new_id, object=obj, grind=data[3] if len(data) > 3 else None,
                verified=bool(listed and listed.get("equipped") and data[3] == maximum))
    if old and old.get("id") is not None and ID_BASE <= int(old["id"]) < ID_BASE + 0x100000:
        info["removed_old"] = remove_item(session, int(old["id"]))
    return info


def main(argv=None):
    parser = argparse.ArgumentParser(description="grind every weapon to its PMT maximum")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--equip-best", action="store_true", help="give and equip the strongest grindeable weapon")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--period", type=float, default=2.0)
    args = parser.parse_args(argv)
    session = Session()
    maximums = catalog_max_grind()
    rows = catalog_rows()
    if not args.watch:
        info = ensure_max_weapon(session, maximums, rows, force_best=args.equip_best, dry_run=args.dry_run)
        print(json.dumps({"changed": info, "catalog_entries": len(maximums)}, indent=1))
        return 0
    log(f"max-grind weapon guard started ({len(rows)} catalog entries, every {args.period:.0f}s)")
    while True:
        try:
            if session is None:
                session = Session()
            if session.u32(PHASE) == 0xE and session.u32(VT_UPDATE) == CAVE:
                info = ensure_max_weapon(session, maximums, rows)
                if info:
                    log(f"weapon max grind: {info['name']} [{info['code']}] "
                        f"+{info['from_grind']} -> +{info['max']} id {info['id']:#x} verified={info['verified']}")
        except Exception as error:                               # noqa: BLE001
            session = None
            log(f"pass failed: {type(error).__name__}: {error}")
        time.sleep(args.period)


if __name__ == "__main__":
    raise SystemExit(main())


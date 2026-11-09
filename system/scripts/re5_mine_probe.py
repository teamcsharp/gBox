"""Read-only probe for RE5 (Switch) mine placement, through the gBox API.

Purpose: prove the operator's mine requirement from the game's own memory rather than from bot counters:
the proximity bomb (0x10A) in the player's inventory (count, quick slot, in hand), the uWp0a units planted
on the ground (pointer + position), the player's position and the Mercenaries score/kills. Each sample is
independent of the bot, so a dropped placement or a mis-identified item shows up honestly.

Usage (from the repo root, with the API reachable and the token in system/gbox-data/api_token):

    python system/scripts/re5_mine_probe.py <session_id> [--api http://10.89.1.246:8765]
        [--worker 4e342e9ebf5948da] [--samples 20] [--pause 5]

Every read is a `read_memory` job (no writes); the module base comes from `re5_mods op=status`. The offsets
mirror gbox/mercs/titles/re5_switch.py (S_PLAYER 0x1CF1C98, P_FIRST 0x30, P_POS 0x60, P_INV 0x30F0, slot
0x38, S_UNIT 0x26A3270, line 11 stride 0x30, next 0x18, uWp0a +0x60). An inventory-owned mine (the stack's
own unit) is excluded by object identity, exactly as the snapshot does.

What a good run looks like: `mine=(0x10a, 5, 5, 1, 0)` early (five bombs, grid 1, not in hand), then a
`NEW_MINE` line a short distance ahead of the player, roughly every 30 s while clearance permits, with
`grounds` growing and later shrinking when a Majini sets a bomb off.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
import urllib.request
from pathlib import Path

S_PLAYER, S_UNIT, S_MAIN = 0x1CF1C98, 0x26A3270, 0x26A1BA8
P_FIRST, P_POS = 0x30, 0x60
GS_KILLS, GS_SCORE, MAIN_GAMESYS = 0x96C, 0x990, 0x584E0
P_INV, INV_SLOT, INV_SLOTS = 0x30F0, 0x38, 24
INV_ID, INV_ROUNDS, INV_GRID, INV_HAND, INV_OBJ = 0x08, 0x0C, 0x1C, 0x20, 0x30
UNIT_LINES, LINE_STRIDE, UNIT_NEXT, MINE_LINE, E_POS = 0x18, 0x30, 0x18, 11, 0x60
MINE_ID = 0x10A


def default_token() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "system" / "gbox-data" / "api_token").read_text().strip()


class Api:
    def __init__(self, base: str, token: str, worker: str):
        self.base, self.token, self.worker = base.rstrip("/"), token, worker

    def call(self, path: str, body: dict | None = None, headers: dict | None = None) -> bytes:
        req = urllib.request.Request(self.base + path, method="POST" if body is not None else "GET")
        req.add_header("Authorization", "Bearer " + self.token)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, data=data, timeout=90) as response:
            return response.read()

    def submit(self, body: dict, tries: int = 90) -> dict:
        job = json.loads(self.call("/api/jobs", body, {"x-gbox-actor": "agent"}))
        if "id" not in job:
            raise SystemExit(f"job submission refused: {str(job)[:300]}")
        for _ in range(tries):
            time.sleep(0.6)
            state = json.loads(self.call(f"/api/jobs/{job['id']}"))
            if state["state"] == "succeeded":
                return state
            if state["state"] not in ("queued", "running"):
                raise SystemExit(f"job {job['id']} {state['state']}: {str(state.get('error'))[:240]}")
        raise SystemExit(f"job {job['id']} did not finish in time")

    def read_mem(self, sid: str, address: int, length: int) -> bytes | None:
        try:
            state = self.submit({"tool": "read_memory", "require_worker": self.worker, "agent_use": True,
                                 "low_priority": True,
                                 "input": {"session_id": sid, "address": address, "length": length}})
        except SystemExit as exc:
            if "arena" in str(exc) or "failed" in str(exc):
                return None
            raise
        out = state["output"]
        sha = (out.get("result") or {}).get("sha256") or out.get("sha256")
        artifacts = out.get("artifacts") or {}
        if isinstance(artifacts, dict) and artifacts:
            first = next(iter(artifacts.values()))
            sha = first.get("sha256", sha) if isinstance(first, dict) else sha
        blob = self.call(f"/api/artifacts/{sha}")
        return blob if len(blob) == length else None


def u64(blob: bytes, offset: int = 0) -> int:
    return struct.unpack_from("<Q", blob, offset)[0]


def dti_class(api: Api, sid: str, vtable: int) -> str | None:
    """The class name of a unit object, through its vtable's getDTI slot (re5_switch.class_name)."""
    try:
        getter = u64(api.read_mem(sid, vtable + 8 * 5, 8))
        w0, w1, w2 = struct.unpack("<III", api.read_mem(sid, getter, 12))
        if (w0 & 0x9F00001F) != 0x90000000 or w2 != 0xD65F03C0:
            return None
        imm = ((w0 >> 29) & 3) | (((w0 >> 5) & 0x7FFFF) << 2)
        if imm & (1 << 20):
            imm -= 1 << 21
        page = (getter & ~0xFFF) + (imm << 12)
        if (w1 & 0xFFC003FF) == 0x91000000:
            dti = page + ((w1 >> 10) & 0xFFF)
        elif (w1 & 0xFFC003FF) == 0xF9400000:
            dti = u64(api.read_mem(sid, page + (((w1 >> 10) & 0xFFF) << 3), 8))
        else:
            return None
        name = api.read_mem(sid, u64(api.read_mem(sid, dti + 0x8, 8)), 40).split(b"\0")[0].decode("ascii")
        return name if name.isidentifier() else None
    except Exception:
        return None


def sample(api: Api, sid: str, base: int, seen: dict) -> None:
    now = time.time()
    pointer = api.read_mem(sid, base + S_PLAYER, 8)
    if pointer is None:
        print(f"t={now:.0f} no player (menu, loading or round over)")
        return
    player = u64(api.read_mem(sid, u64(pointer) + P_FIRST, 8))
    pos_blob = api.read_mem(sid, player + P_POS, 12) if player else None
    pos = struct.unpack("<3f", pos_blob) if pos_blob else None
    inv = api.read_mem(sid, player + P_INV, INV_SLOT * INV_SLOTS) if player else None
    mine, others, owned = None, [], set()
    if inv:
        for slot in range(INV_SLOTS):
            o = INV_SLOT * slot
            item = struct.unpack_from("<I", inv, o + INV_ID)[0]
            if item in (0, 0x100) or item > 0xFFFF:
                continue
            rounds, cap = struct.unpack_from("<ii", inv, o + INV_ROUNDS)
            grid, hand = struct.unpack_from("<ii", inv, o + INV_GRID)
            if item == MINE_ID:
                mine = (hex(item), rounds, cap, grid, hand)
                owned.add(struct.unpack_from("<Q", inv, o + INV_OBJ)[0])
            elif rounds > 0:
                others.append((hex(item), rounds, grid))
    main = api.read_mem(sid, base + S_MAIN, 8)
    kills = score = None
    if main and u64(main):
        gs = u64(api.read_mem(sid, u64(main) + MAIN_GAMESYS, 8))
        if gs:
            kb, sb = api.read_mem(sid, gs + GS_KILLS, 4), api.read_mem(sid, gs + GS_SCORE, 4)
            kills = struct.unpack("<i", kb)[0] if kb else None
            score = struct.unpack("<i", sb)[0] if sb else None
    grounds = []
    su_blob = api.read_mem(sid, base + S_UNIT, 8)
    su = u64(su_blob) if su_blob else 0
    if su:
        head = api.read_mem(sid, su + UNIT_LINES + LINE_STRIDE * MINE_LINE, 8)
        unit, guard = (u64(head) if head else 0), 0
        while unit and guard < 64:
            if dti_class(api, sid, unit) == "uWp0a":
                blob = api.read_mem(sid, unit + E_POS, 12)
                if blob:
                    p = struct.unpack("<3f", blob)
                    if all(math.isfinite(v) for v in p) and unit not in owned:
                        grounds.append((unit, p))
            nxt = api.read_mem(sid, unit + UNIT_NEXT, 8)
            if not nxt:
                break
            unit, guard = u64(nxt), guard + 1
    fresh = [g for g in grounds if g[0] not in seen]
    for unit, p in fresh:
        seen[unit] = (now, p)
    shown = None if pos is None else tuple(round(v, 1) for v in pos)
    print(f"t={now:.0f} pos={shown} mine={mine} others={others} kills={kills} score={score} "
          f"grounds={len(grounds)} fresh={len(fresh)}", flush=True)
    for unit, p in fresh:
        distance = None if pos is None else round(math.dist((pos[0], pos[2]), (p[0], p[2])), 1)
        print(f"  NEW_MINE ptr={unit:#x} pos={tuple(round(v, 1) for v in p)} dist_cm={distance}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session_id")
    parser.add_argument("--api", default="http://10.89.1.246:8765")
    parser.add_argument("--worker", default="4e342e9ebf5948da")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--pause", type=float, default=5.0)
    parser.add_argument("--token-file", default="")
    args = parser.parse_args()

    token = Path(args.token_file).read_text().strip() if args.token_file else default_token()
    api = Api(args.api, token, args.worker)
    status = api.submit({"tool": "re5_mods", "require_worker": args.worker, "agent_use": True,
                         "input": {"session_id": args.session_id, "op": "status"}})
    result = status["output"]["result"]["status"]
    base = int(result["module_base"], 16)
    print(f"MODULE_BASE {base:#x} mines={result.get('mine_settings')} loadout={result.get('mine_loadout')}")
    seen: dict = {}
    for _ in range(args.samples):
        sample(api, args.session_id, base, seen)
        time.sleep(args.pause)
    return 0


if __name__ == "__main__":
    sys.exit(main())

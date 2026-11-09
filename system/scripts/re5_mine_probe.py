"""Read-only probe for RE5 (Switch) mine placement, through the gBox API.

Purpose: prove the operator's mine requirement from the game's own memory rather than from bot counters:
the proximity bomb (0x10A) in the player's inventory (count, quick slot, in hand), the uWp0a units planted
on the ground (pointer + position), the player's position and the Mercenaries score/kills. Each sample is
independent of the bot, so a dropped placement or a mis-identified item shows up honestly.

Usage (from the repo root, with the API reachable and the token in system/gbox-data/api_token):

    python system/scripts/re5_mine_probe.py <session_id> [--api http://10.89.1.246:8765]
        [--worker <id>] [--samples 20] [--pause 5]

The worker defaults to the session id's own prefix (a session is `<worker id>-<launch job>`, and the worker id
changes at every service restart, so a fixed default goes stale).

Two ways to read, both read-only:
  * default: one `re5_mods op=mine_probe` job a sample (gbox/mercs/titles/re5_switch_mods.mine_probe reads the
    same memory on the worker in one go, about a second a sample, with the Majini distances beside it);
  * `--raw`: `read_memory` jobs only, nothing but this file's own offsets between you and the game. A job is
    about a second on the Spark and a sample is ~8 reads plus one per unit on the mine line (41 units live), so
    a raw sample takes most of a minute: use it to cross-check the op, not to time a 30 s cadence.
Keep either short and never leave one running across rounds: a worker with a job in flight is "busy with jobs"
to MercMode's scheduler, which starts no next round while that holds (the probe stops when its session ends
and slows down while no player is up). In raw mode the module base comes from `re5_mods op=status`. The offsets
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
        delay = 0.1
        for _ in range(tries):
            time.sleep(delay)
            delay = min(0.6, delay * 1.5)
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


def u64(blob: bytes | None, offset: int = 0) -> int:
    """The pointer at `offset`, 0 when the read failed (a lost page reads as "nothing there", never as a crash)."""
    return struct.unpack_from("<Q", blob, offset)[0] if blob and len(blob) >= offset + 8 else 0


def ptr_ok(p: int) -> bool:
    return 0x1000000 <= p < (1 << 40)                       # re5_switch.ptr_ok


def dti_class(api: Api, sid: str, vtable: int, names: dict) -> str | None:
    """The class name behind a vtable, through its getDTI slot (re5_switch.class_name), each vtable named once.

    `vtable` is the unit's first word, not the unit: the first version of this probe passed the unit pointer
    itself, read a field of the unit as "getDTI", named nothing, and so could never report a planted mine."""
    if vtable not in names:
        names[vtable] = _dti_class(api, sid, vtable) if ptr_ok(vtable) else None
    return names[vtable]


def _dti_class(api: Api, sid: str, vtable: int) -> str | None:
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


UNIT_HEAD = E_POS + 12                                      # one read a unit: vtable +0, next +0x18, position +0x60


def sample(api: Api, sid: str, base: int, seen: dict, names: dict) -> list:
    """Print one sample; returns the mines first seen in it as [(time, pointer, position, distance_cm)]."""
    now = time.time()
    holder = u64(api.read_mem(sid, base + S_PLAYER, 8))
    player = u64(api.read_mem(sid, holder + P_FIRST, 8)) if ptr_ok(holder) else 0
    if not ptr_ok(player):
        print(f"t={now:.0f} no player (menu, loading or round over)", flush=True)
        return []
    pos_blob = api.read_mem(sid, player + P_POS, 12)
    pos = struct.unpack("<3f", pos_blob) if pos_blob else None
    inv = api.read_mem(sid, player + P_INV, INV_SLOT * INV_SLOTS)
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
    main = u64(api.read_mem(sid, base + S_MAIN, 8))
    kills = score = None
    if ptr_ok(main):
        gs = u64(api.read_mem(sid, main + MAIN_GAMESYS, 8))
        if ptr_ok(gs):
            kb, sb = api.read_mem(sid, gs + GS_KILLS, 4), api.read_mem(sid, gs + GS_SCORE, 4)
            kills = struct.unpack("<i", kb)[0] if kb else None
            score = struct.unpack("<i", sb)[0] if sb else None
    grounds = []
    su = u64(api.read_mem(sid, base + S_UNIT, 8))
    walked = 0
    if ptr_ok(su):
        unit = u64(api.read_mem(sid, su + UNIT_LINES + LINE_STRIDE * MINE_LINE, 8))
        while ptr_ok(unit) and walked < 64:
            head = api.read_mem(sid, unit, UNIT_HEAD)
            if not head:
                break
            if dti_class(api, sid, u64(head), names) == "uWp0a":
                p = struct.unpack_from("<3f", head, E_POS)
                if all(math.isfinite(v) for v in p) and unit not in owned:
                    grounds.append((unit, p))
            unit, walked = u64(head, UNIT_NEXT), walked + 1
    fresh = [g for g in grounds if g[0] not in seen]
    for unit, p in fresh:
        seen[unit] = (now, p)
    shown = None if pos is None else tuple(round(v, 1) for v in pos)
    print(f"t={now:.0f} pos={shown} mine={mine} others={others} kills={kills} score={score} "
          f"line_units={walked} grounds={len(grounds)} fresh={len(fresh)}", flush=True)
    receipts = []
    for unit, p in fresh:
        distance = None if pos is None else round(math.dist((pos[0], pos[2]), (p[0], p[2])), 1)
        print(f"  NEW_MINE ptr={unit:#x} pos={tuple(round(v, 1) for v in p)} dist_cm={distance}", flush=True)
        receipts.append((now, unit, p, distance))
    return receipts


def fast_sample(api: Api, sid: str, seen: dict):
    """One sample in one job (re5_mods op=mine_probe, gbox/mercs/titles/re5_switch_mods.mine_probe): the same memory,
    read on the worker in one go. Returns the new mines [(time, pointer, position, distance_cm)], False with no player
    (menu, loading, round over), None when this worker's bot module has no such op yet."""
    try:
        state = api.submit({"tool": "re5_mods", "require_worker": api.worker, "agent_use": True,
                            "input": {"session_id": sid, "op": "mine_probe"}})
    except SystemExit as exc:
        if "unknown op" in str(exc):
            return None
        raise
    r = (state.get("output") or {}).get("result") or {}
    if r.get("op") != "mine_probe" or "ground_mines" not in r:
        return None
    now = r.get("at") or time.time()
    if not r.get("player"):
        print(f"t={now:.0f} no player (menu, loading or round over)", flush=True)
        return False
    p, mine, foes = r["player"], r.get("mine") or {}, r.get("foes") or {}
    row = (hex(mine["id"]), mine.get("rounds"), mine.get("cap"), mine.get("grid"), int(bool(mine.get("hand")))) \
        if mine else None
    fresh = [g for g in r["ground_mines"] if g["ptr"] not in seen]
    print(f"t={now:.0f} pos={tuple(p['pos'])} hp={p.get('hp')} mine={row} kills={r.get('kills')} "
          f"score={r.get('score')} timer={r.get('timer')} foes={foes.get('alive')} "
          f"nearest_cm={foes.get('nearest_cm')} in4m={foes.get('within_400')} "
          f"grounds={len(r['ground_mines'])} fresh={len(fresh)}", flush=True)
    receipts = []
    for g in fresh:
        seen[g["ptr"]] = (now, g["pos"])
        print(f"  NEW_MINE ptr={g['ptr']:#x} pos={tuple(g['pos'])} dist_cm={g['dist_cm']}", flush=True)
        receipts.append((now, g["ptr"], g["pos"], g["dist_cm"]))
    down = {g["ptr"] for g in r["ground_mines"]}
    for ptr in [k for k in seen if k not in down]:
        print(f"  MINE_GONE ptr={ptr:#x} after_s={round(now - seen[ptr][0], 1)}", flush=True)
        del seen[ptr]                                        # reported once; a reused pointer is a new mine
    return receipts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session_id")
    parser.add_argument("--api", default="http://10.89.1.246:8765")
    parser.add_argument("--worker", default="", help="default: the session id's own worker prefix")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--pause", type=float, default=5.0)
    parser.add_argument("--token-file", default="")
    parser.add_argument("--raw", action="store_true",
                        help="read_memory jobs only (slow: ~50 a sample); default is one re5_mods op=mine_probe job")
    args = parser.parse_args()

    token = Path(args.token_file).read_text().strip() if args.token_file else default_token()
    worker = args.worker or args.session_id.split("-")[0]
    api = Api(args.api, token, worker)
    seen: dict = {}
    names: dict = {}
    receipts: list = []
    base = None
    fast = not args.raw
    for _ in range(args.samples):
        try:
            if fast:
                got = fast_sample(api, args.session_id, seen)
                if got is None:                              # a bot module from before the op: the raw reads still work
                    fast = False
                    print("mine_probe op not on this worker yet: falling back to raw read_memory jobs", flush=True)
                    continue
            else:
                if base is None:
                    status = api.submit({"tool": "re5_mods", "require_worker": worker, "agent_use": True,
                                         "input": {"session_id": args.session_id, "op": "status"}})
                    result = status["output"]["result"]["status"]
                    base = int(result["module_base"], 16)
                    print(f"MODULE_BASE {base:#x} mines={result.get('mine_settings')} "
                          f"loadout={result.get('mine_loadout')}", flush=True)
                got = sample(api, args.session_id, base, seen, names)
        except SystemExit as exc:
            if "SessionGone" in str(exc) or "no longer running" in str(exc):
                print("session ended (the round's title restarted or the game closed): stopping", flush=True)
                break                                        # never keep queueing jobs at a game that is gone
            raise
        receipts += got or []
        # Between rounds (no player) the worker must look idle to MercMode's scheduler: a job in flight there is
        # "busy with jobs", and the next round does not start while that holds.
        time.sleep(args.pause if got is not False else max(args.pause, 8.0))
    gaps = [round(b[0] - a[0], 1) for a, b in zip(receipts, receipts[1:])]
    print(f"SUMMARY new_mines={len(receipts)} gaps_s={gaps}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

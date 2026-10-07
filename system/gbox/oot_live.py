"""Zelda: Ocarina of Time: live views of the running game for gBox's model tools - the actors on screen (which one is
under a screen point), the object and skeleton an actor draws with, its current pose, where Link stands, and the room
that is loaded. Struct offsets from the zeldaret/oot decompilation (include/play_state.h, actor.h, object.h, room.h,
animation.h); RDRAM access through gbox.oot (_rd / _wr: word-swapped ParaLLEl RDRAM).

PlayState (oot.PLAY: the live tools know NTSC 1.2's address only, like gbox.oot):
  +0x00A4 sceneId (s16) | +0x1C24 actorCtx: +0x0C actorLists[12] {s32 length, Actor* head}
  +0x117A4 objectCtx: +0x0C slots[19] {s16 id, void* segment, ...} 0x44 each | +0x11CBC roomCtx: curRoom {s8 num, ...,
  RoomShape* +0x08, void* segment +0x0C} | +0x11D60 viewProjectionMtxF (float[4][4], column-major)
Actor: +0x00 id, +0x02 category, +0x1C params, +0x1E objectSlot, +0x24 world.pos, +0x30 world.rot, +0x38 focus.pos,
  +0x50 scale, +0x124 next, +0x134 draw
"""
from __future__ import annotations

import struct

import numpy as np

from . import oot

ACTOR_CTX, OBJECT_CTX, ROOM_CTX, VP_MTX = 0x1C24, 0x117A4, 0x11CBC, 0x11D60
CATEGORIES = ["switch", "bg", "player", "explosive", "npc", "enemy", "prop", "itemaction", "misc", "boss", "door", "chest"]


def _names():
    from .oot_swap import NAMES
    return NAMES


def u16(ad, a):
    return struct.unpack(">H", oot._rd(ad, a, 2))[0]


def s16(ad, a):
    return struct.unpack(">h", oot._rd(ad, a, 2))[0]


def u32(ad, a):
    return struct.unpack(">I", oot._rd(ad, a, 4))[0]


def f3(ad, a):
    return np.array(struct.unpack(">3f", oot._rd(ad, a, 12)))


def scene(ad) -> int:
    return s16(ad, oot.PLAY + 0xA4)


def object_slots(ad) -> list[dict]:
    base = oot.PLAY + OBJECT_CTX
    n = oot._rd(ad, base + 8, 1)[0]
    raw = oot._rd(ad, base + 0x0C, 0x44 * 19)
    out = []
    for i in range(min(n, 19)):
        oid, seg = struct.unpack_from(">h2xI", raw, 0x44 * i)
        out.append({"slot": i, "id": oid, "segment": seg, "name": _names()["objects"].get(hex(abs(oid)), "")})
    return out


def actors(ad) -> list[dict]:
    """Every live actor: id, name, category, world / focus position, object slot -> object id / name, instance address."""
    slots = {s["slot"]: s for s in object_slots(ad)}
    lists = oot._rd(ad, oot.PLAY + ACTOR_CTX + 0x0C, 8 * 12)
    out = []
    for cat in range(12):
        n, a = struct.unpack_from(">iI", lists, 8 * cat)
        seen = 0
        while a and 0x80000000 <= a < 0x80800000 and seen < 200:
            raw = oot._rd(ad, a, 0x140)
            aid, catg = struct.unpack_from(">hB", raw, 0)
            params, slot = struct.unpack_from(">hb", raw, 0x1C)
            pos = np.array(struct.unpack_from(">3f", raw, 0x24))
            rot = struct.unpack_from(">3h", raw, 0x30)
            focus = np.array(struct.unpack_from(">3f", raw, 0x38))
            nxt, draw = struct.unpack_from(">I", raw, 0x124)[0], struct.unpack_from(">I", raw, 0x134)[0]
            ob = slots.get(slot, {})
            out.append({"addr": a, "id": aid, "name": _names()["actors"].get(hex(aid), hex(aid)), "category": CATEGORIES[cat],
                        "params": params, "pos": pos, "rot": rot, "focus": focus, "slot": slot, "object": ob.get("id"),
                        "object_name": ob.get("name", ""), "object_segment": ob.get("segment"), "drawn": bool(draw)})
            a = nxt
            seen += 1
    return out


def view_proj(ad) -> np.ndarray:
    """play->viewProjectionMtxF as a row-major 4x4 for column vectors (clip = M @ [x, y, z, 1])."""
    v = struct.unpack(">16f", oot._rd(ad, oot.PLAY + VP_MTX, 64))
    return np.array(v).reshape(4, 4).T


def project(M: np.ndarray, p) -> tuple[float, float, float]:
    """World point -> (x, y) fractions of the game picture (0..1, y down) and w (> 0 = in front of the camera)."""
    c = M @ np.r_[np.asarray(p, float), 1.0]
    if c[3] <= 1e-6:
        return float("nan"), float("nan"), float(c[3])
    return float((c[0] / c[3] + 1) / 2), float((1 - c[1] / c[3]) / 2), float(c[3])


def unproject_to_floor(M: np.ndarray, x: float, y: float, floor_y: float) -> np.ndarray | None:
    """The point on the plane y = floor_y seen at picture point (x, y)."""
    inv = np.linalg.inv(M)
    nx, ny = 2 * x - 1, 1 - 2 * y
    a = inv @ np.array([nx, ny, -1.0, 1.0])
    b = inv @ np.array([nx, ny, 1.0, 1.0])
    a, b = a[:3] / a[3], b[:3] / b[3]
    d = b - a
    if abs(d[1]) < 1e-9:
        return None
    t = (floor_y - a[1]) / d[1]
    return a + t * d if t > 0 else None


def pick(ad, x: float, y: float, want=("player", "npc", "enemy", "boss", "prop", "misc"), limit: float = 0.12) -> dict | None:
    """The actor drawn nearest to picture point (x, y): distance to its feet-to-head segment on screen."""
    M = view_proj(ad)
    best = None
    for a in actors(ad):
        if a["category"] not in want or not a["drawn"]:
            continue
        p0, p1 = project(M, a["pos"]), project(M, a["focus"] if np.linalg.norm(a["focus"] - a["pos"]) > 1 else a["pos"] + [0, 40, 0])
        if not (p0[2] > 0 and p1[2] > 0):
            continue
        A, B, P = np.array(p0[:2]), np.array(p1[:2]), np.array([x, y])
        d = B - A
        t = float(np.clip(np.dot(P - A, d) / max(np.dot(d, d), 1e-12), 0, 1))
        dist = float(np.linalg.norm(A + t * d - P))
        if best is None or dist < best[0]:
            best = (dist, a, (p0, p1))
    if best is None or best[0] > limit:
        return None
    dist, a, (p0, p1) = best
    return a | {"screen": [round(p0[0], 3), round(p0[1], 3), round(p1[0], 3), round(p1[1], 3)], "distance": round(dist, 3)}


def player(ad) -> dict:
    a = u32(ad, oot.PLAY + 0x1C44)
    raw = oot._rd(ad, a, 0x140)
    return {"addr": a, "pos": np.array(struct.unpack_from(">3f", raw, 0x24)), "rot": struct.unpack_from(">3h", raw, 0x30),
            "floor": struct.unpack_from(">f", raw, 0x80)[0]}


def skel_anime(ad, actor: dict, size: int = 0x400) -> dict | None:
    """Find the actor's SkelAnime in its instance: {u8 limbCount, mode, dListCount, taper; void** skeleton (segment-6
    limb table); animation; ...; Vec3s* jointTable at +0x20}. -> {at, limbs, skeleton, joint_table, frame}."""
    a = actor["addr"]
    raw = oot._rd(ad, a, size)
    for o in range(0x13C, size - 0x28, 4):               # retail Actor is 0x13C (the decomp's 0x14C has a debug pad)
        cnt, mode, dlc = raw[o], raw[o + 1], raw[o + 2]
        sk = struct.unpack_from(">I", raw, o + 4)[0]
        jt = struct.unpack_from(">I", raw, o + 0x20)[0]
        ok_sk = sk >> 24 == 6 or 0x80000000 <= sk < 0x80800000
        if not 2 <= cnt <= 81 or mode > 5 or not ok_sk or not 0x80000000 <= jt < 0x80800000 or dlc > cnt:
            continue
        if sk >> 24 != 6:                               # SkelAnime_Init* keeps the limb table as a RAM address:
            segs = sorted((s["segment"], s["id"]) for s in object_slots(ad) if s["segment"] and s["segment"] <= sk)
            if not segs:
                continue
            base, _oid = segs[-1]                       # -> offset in the object it was loaded with
            sk = 0x06000000 | (sk - base)
        data = oot._rd(ad, jt, 6 * cnt)
        frame = [struct.unpack_from(">3h", data, 6 * k) for k in range(cnt)]
        return {"at": a + o, "limbs": cnt - 1, "skeleton": sk, "joint_table": jt, "frame": frame, "dlcount": dlc}
    return None


def describe(a: dict) -> str:
    on = f" (object {a['object_name']})" if a.get("object_name") else ""
    return f"{a['name']}{on}, {a['category']}"


# ---------------------------------------------------------------- statues in rooms (gbox.oot_place), live

WATCH: dict[str, dict] = {}                             # session id -> {"items": [...], "thread", "hooks": int}


def write_block(ad, a: int, data: bytes) -> None:
    """A big 4-aligned write: RDRAM is word-swapped, so swap per word and write once."""
    data = data + bytes((-len(data)) % 4)
    sw = b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))
    for o in range(0, len(sw), 0x8000):
        ad.write_memory(a + o, sw[o:o + 0x8000])


def rooms_loaded(ad) -> list[dict]:
    out = []
    for k in range(2):                                  # curRoom, prevRoom (both drawn during a room transition)
        raw = oot._rd(ad, oot.PLAY + ROOM_CTX + 0x14 * k, 0x14)
        num = struct.unpack_from(">b", raw, 0)[0]
        shape, seg = struct.unpack_from(">II", raw, 8)
        if num >= 0 and 0x80000000 <= shape < 0x80800000 and 0x80000000 <= seg < 0x80800000:
            out.append({"num": num, "shape": shape, "segment": seg})
    return out


def _entries(ad, room: dict) -> list[dict]:
    h = oot._rd(ad, room["shape"], 8)
    typ, n = h[0], h[1]
    ent = room["segment"] + (struct.unpack_from(">I", h, 4)[0] & 0xFFFFFF)
    out = []
    if typ == 0:
        for i in range(n):
            out.append({"opa_at": ent + 8 * i})
    elif typ == 1:
        out.append({"opa_at": ent})
    else:
        raw = oot._rd(ad, ent, 16 * n)
        for i in range(n):
            x, y, z, r = struct.unpack_from(">4h", raw, 16 * i)
            out.append({"opa_at": ent + 16 * i + 8, "center": np.array([x, y, z], float), "radius": r,
                        "radius_at": ent + 16 * i + 6})
    return out


def objects_end(ad, obj_table: int) -> tuple[int, int]:
    """-> (end of the last loaded object, objectCtx.spaceEnd). Object sizes from gObjectTable (vromEnd - vromStart)."""
    base = oot.PLAY + OBJECT_CTX
    end = u32(ad, base + 4)
    last = u32(ad, base)
    for s in object_slots(ad):
        if s["id"] and s["segment"]:
            vs, ve = struct.unpack(">II", oot._rd(ad, obj_table + 8 * abs(s["id"]), 8))
            last = max(last, s["segment"] + (ve - vs))
    return last, end


def hook_once(ad, items: list[dict], state: dict) -> int:
    """This scene's statues written at the end of the object space and every loaded room that has statues hooked
    (wrapper: segment 0x0E = the statue's data, call its list, ..., branch to the room's own list). If the game's
    objects reach the data, the hooks are taken out again. -> number of hooks (re)written."""
    from .oot_place import wrapper
    sc = scene(ad)
    mine = [it for it in items if it["scene"] == sc]
    rooms = rooms_loaded(ad)
    if not mine:
        return 0
    sizes = [(len(it["blob"]) // 2 + 15) & ~15 for it in mine]
    total = sum(sizes) + 0x400
    last, end = objects_end(ad, mine[0]["obj_table"])
    base = (end - total) & ~0xF
    hooks = state.setdefault("hooks", {})               # entry address -> (wrapper address, original list)
    if last > base:                                     # no room: never draw over the game's objects
        for opa_at, (w_at, orig) in list(hooks.items()):
            if u32(ad, opa_at) == w_at:
                oot._wr(ad, opa_at, struct.pack(">I", orig))
        hooks.clear()
        state["blocked"] = f"object space full ({(last - (end - total)) // 1024 + 1} KB short)"
        return 0
    state.pop("blocked", None)
    offs, o = {}, base
    for it, sz in zip(mine, sizes):
        offs[it["id"]] = o
        o += sz
    key = (sc, base, tuple(offs))
    first = bytes.fromhex(mine[0]["blob"][:32])
    if state.get("key") != key or oot._rd(ad, offs[mine[0]["id"]], 16) != first:
        for it in mine:
            write_block(ad, offs[it["id"]], bytes.fromhex(it["blob"]))
        state["key"] = key
        hooks.clear()
    wbase = base + sum(sizes)
    done = 0
    for wi, room in enumerate(rooms):
        here = [it for it in mine if it["room"] == room["num"]]
        if not here:
            continue
        ents = _entries(ad, room)
        groups = {}
        for it in here:
            withs = [e for e in ents if "center" in e]
            e = min(withs, key=lambda e: np.linalg.norm(e["center"] - it["pos"]) - e["radius"]) if withs else ents[0]
            groups.setdefault(e["opa_at"], (e, []))[1].append(it)
        for gi, (opa_at, (e, its)) in enumerate(sorted(groups.items())):
            w_at = wbase + 0x100 * (2 * gi + wi)
            cur = u32(ad, opa_at)
            if cur == w_at:
                continue
            calls = b"".join(struct.pack(">IIII", 0xDB060038, offs[it["id"]], 0xDE000000, 0x0E000000 + it["draw"])
                             for it in its)
            write_block(ad, w_at, calls + wrapper([], cur))
            if "radius_at" in e:
                need = max(int(np.linalg.norm(e["center"] - np.array(it["pos"])) + it["radius"] + 10) for it in its)
                if need > e["radius"]:
                    oot._wr(ad, e["radius_at"], struct.pack(">h", min(need, 0x7FFF)))
            oot._wr(ad, opa_at, struct.pack(">I", w_at))
            hooks[opa_at] = (w_at, cur)
            done += 1
    return done


def watch(sid: str, items: list[dict]) -> dict:
    """Keep the statues of this session hooked: re-hook whenever a room with statues is (re)loaded."""
    import threading
    from .tools import SESSIONS
    w = WATCH.setdefault(sid, {"items": [], "hooks": 0, "state": {}})
    w["items"] = items
    w["state"] = {}
    if w.get("thread") and w["thread"].is_alive():
        return w

    def loop():
        import time
        while sid in SESSIONS and WATCH.get(sid) is w:
            try:
                ad = SESSIONS[sid][0]
                if w["items"]:
                    w["hooks"] += hook_once(ad, w["items"], w["state"])
            except Exception as e:                       # noqa: BLE001 - the game resets / loads: try again
                w["error"] = f"{type(e).__name__}: {e}"
            time.sleep(0.5)
    w["thread"] = threading.Thread(target=loop, daemon=True, name=f"oot-statues-{sid}")
    w["thread"].start()
    return w


def where(ad) -> dict:
    p = player(ad)
    age_child = struct.unpack(">I", oot._rd(ad, oot.SAVE + 4, 4))[0] == 1
    return {"scene": scene(ad), "rooms": [r["num"] for r in rooms_loaded(ad)], "player": [round(float(v), 1) for v in p["pos"]],
            "yaw": p["rot"][1] * 360.0 / 65536, "floor": p["floor"], "age": "child" if age_child else "adult"}


# ---------------------------------------------------------------- the session-side tool

from pydantic import BaseModel  # noqa: E402

from .models import Permission as P  # noqa: E402
from .registry import tool  # noqa: E402


class OotModelsIn(BaseModel):
    session_id: str
    op: str = "where"                      # where | pick | actors | skeleton | floor_point | apply | clear | status
    x: float | None = None                 # pick: picture point (fractions)
    y: float | None = None
    actor: str = ""                        # skeleton / find: actor name (En_Sa) or address (0x80...)
    items: list[dict] = []                 # apply: statues (gbox.oot_place.live_items)


class OotModelsOut(BaseModel):
    result: dict


def _clean(a: dict) -> dict:
    return {k: ([round(float(x), 1) for x in v] if isinstance(v, np.ndarray) else v) for k, v in a.items()}


@tool("oot_models", "1.0", OotModelsIn, OotModelsOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      timeout_s=180)
def oot_models(inp: OotModelsIn, ctx):
    """Ocarina of Time (N64 1.2) live side of gBox's model tools (used by `characters`): where Link is, which actor is
    at a picture point (+ its object, skeleton and current pose), and statues drawn into the loaded rooms (kept hooked
    while the session runs)."""
    from .tools import SESSIONS
    ad, _g = SESSIONS[inp.session_id]
    if inp.op == "where":
        return {"result": where(ad)}
    if inp.op == "actors":
        return {"result": {"actors": [_clean(a) for a in actors(ad) if a["drawn"]]}}
    if inp.op == "pick":
        a = pick(ad, inp.x, inp.y)
        if a is None:
            return {"result": {"actor": None, "where": where(ad)}}
        sk = skel_anime(ad, a) if a["category"] != "player" else None
        return {"result": {"actor": _clean(a), "skeleton": sk, "where": where(ad)}}
    if inp.op == "floor_point":
        M = view_proj(ad)
        pl = player(ad)
        p = unproject_to_floor(M, inp.x, inp.y, pl["floor"])
        return {"result": {"point": [round(float(v), 1) for v in p] if p is not None else None}}
    if inp.op == "skeleton":
        cands = [a for a in actors(ad) if a["name"].lower() == inp.actor.lower() or hex(a["addr"]) == inp.actor.lower()]
        if not cands:
            return {"result": {"actor": None}}
        a = cands[0]
        return {"result": {"actor": _clean(a), "skeleton": skel_anime(ad, a), "count": len(cands)}}
    if inp.op == "apply":
        w = watch(inp.session_id, inp.items)
        n = hook_once(ad, inp.items, w["state"])
        return {"result": {"statues": len(inp.items), "hooked_now": n, "where": where(ad), "watching": True}}
    if inp.op == "clear":
        WATCH.pop(inp.session_id, None)
        return {"result": {"cleared": True, "note": "the statues disappear at the next room load"}}
    w = WATCH.get(inp.session_id) or {}
    return {"result": {"statues": len(w.get("items", [])), "hooks": w.get("hooks", 0), "error": w.get("error"),
                       "blocked": (w.get("state") or {}).get("blocked")}}

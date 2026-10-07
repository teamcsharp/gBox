"""Zelda: Ocarina of Time: put any collection model into the world as a static prop ("put a Cloud statue here", "place
Aya next to the Deku Tree"). No collision.

How it is drawn (chosen because it needs no new game code, works the same live and in the ROM, and survives every
actor / object limit): the statue rides the ROOM's own display list. A room's mesh header (RoomShape, room.h) lists
display-list entries that Room_Draw calls with an identity model matrix and Gfx_SetupDL_25; gBox points one entry's
opaque list at a small wrapper: for each statue `G_MTX push (its placement matrix) -> its lists -> G_POPMTX`, then a
branch to the room's original list. The statue's lists are unlit (shading baked into vertex colours from a fixed light,
because no actor lights are set while rooms draw) and restore SetupDL 25's modes at the end. For a cullable room
(type 2) the hooked entry is the one nearest the statue, and its bounding sphere is grown to cover the statue.

  live  (immediately, on the running game): the statue data goes at the END of the object space (objectCtx.spaceEnd
        down; objects are allocated from the start up, so the tail is free in normal scenes) - not the expansion RAM,
        which the GLideN64 HLE plugin can't read display lists from. The data is segment-relative (segment 0x0E, set by
        the wrapper), so it can sit wherever the space ends in each scene. The session's worker keeps a watcher
        (oot_live.watch) that re-writes and re-hooks whenever the scene / room is (re)loaded, and unhooks if the game's
        own objects ever reach the data (then the statue waits for space).
  ROM   (permanent, in every OoT mod gBox builds afterwards): the same data appended to the room file (segment 3
        addresses), the entry pointed at it; the room file grows, so it gets a new VROM range and the scene's room
        list (scene header command 0x04) is updated (oot_writer.Rom.ref_files).
Placements are kept per game in <cache>/oot_places/<game_id>.json: {id, character, scene, room, pos, yaw, height}.
"""
from __future__ import annotations

import json
import struct
import time
from pathlib import Path

import numpy as np

from . import oot_writer as OW
from . import sm64_swap as S

STATUE_HEIGHT = 75.0                                   # world units (adult Link stands about 60)
MAX_TRIS = 1200                                         # ROM (room file) statues: the room buffer grows by ~50 KB
LIVE_TRIS, LIVE_BUDGET = 600, 0xA000                    # live statues share the object space's free tail
SEG = 0x0E000000                                        # live statue data is addressed through segment 0x0E
MAX_SLOTS = 20


def store_path(cfg, gid: str) -> Path:
    p = Path(cfg.cache) / "oot_places" / f"{gid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load(cfg, gid: str) -> list[dict]:
    p = store_path(cfg, gid)
    return json.loads(p.read_text()) if p.exists() else []


def save(cfg, gid: str, items: list[dict]) -> None:
    store_path(cfg, gid).write_text(json.dumps(items, indent=1))


# ---------------------------------------------------------------- the statue model

def statue_parts(model: Path, height: float, props=(), blender: str | None = None, work: Path | None = None,
                 max_tris: int = MAX_TRIS) -> tuple[dict, list, dict]:
    """A collection model in its own pose, feet on y = 0, centred, `height` world units tall (vertices in hundredths:
    the placement matrix scales by 0.01) -> (parts {0: [(material, tri)]}, materials, report)."""
    from .re4gc_enemies import decimate
    rig = S.load_rig(Path(model), {}, props)
    tris = sum(len(p["tris"]) for p in rig["prims"])
    rep = {"source_triangles": tris}
    prims = rig["prims"]
    if tris > max_tris and blender and work:
        work.mkdir(parents=True, exist_ok=True)
        from .melee_models import write_gltf
        flat = []
        for p in prims:
            J = np.zeros((len(p["pos"]), 4), np.int64)
            Wt = np.zeros((len(p["pos"]), 4))
            Wt[:, 0] = 1
            flat.append({**p, "J": J, "W": Wt, "name": f"m{len(flat)}"})
        src = write_gltf(work / "statue.gltf", [{"parent": -1, "world": np.eye(4)}], flat, 1.0, "statue", ["j00"])
        prims = S.read_rigged(decimate(src, work / f"statue_dec{max_tris}.glb", float(max_tris), blender))
        rep["decimated_to"] = sum(len(p["tris"]) for p in prims)
    allp = np.concatenate([p["pos"] for p in prims])
    lo, hi = allp.min(0), allp.max(0)
    k = height * 100 / max(hi[1] - lo[1], 1e-9)
    ctr = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    mats, key_ix, part = [], {}, []
    for p in prims:
        tex = p["tex"]
        key = (id(tex) if tex is not None else None, tuple(p["color"][:3]))
        if key not in key_ix:
            col = np.array(p["color"][:3], float) / 255
            if tex is not None:
                t = S._fill_alpha(np.asarray(tex, np.uint8))
                if (col < 0.999).any():
                    t = t.copy()
                    t[..., :3] = (t[..., :3] * col).astype(np.uint8)
                mats.append({"color": (255, 255, 255), "tex": t})
            else:
                mats.append({"color": tuple(int(v) for v in col * 255), "tex": None})
            key_ix[key] = len(mats) - 1
        mi = key_ix[key]
        P = (p["pos"] - ctr) * k
        for t in p["tris"]:
            part.append((mi, tuple((P[i], p["nrm"][i], tuple(p["uv"][i])) for i in t)))
    rep |= {"triangles": len(part), "height": height, "radius": float(np.linalg.norm((allp - ctr) * k, axis=1).max() / 100)}
    return {0: part}, mats, rep


def placement_matrix(pos, yaw_deg: float) -> np.ndarray:
    a = np.radians(yaw_deg)
    m = np.eye(4)
    m[:3, :3] = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]]) * 0.01
    m[:3, 3] = pos
    return m


def statue_blob(parts: dict, mats: list, base: int, pos, yaw: float, budget: int = 0x30000) -> tuple[bytes, int]:
    """-> (data placed at address `base`, address of the statue's draw list: matrix push, lists, pop, SetupDL 25 back)."""
    from .oot_swap import fit_budget
    uses = [sum(1 for mi, _ in parts[0] if mi == k) for k in range(len(mats))]
    fitted, _rep = fit_budget(parts, mats, uses, budget - 0x200)
    blob, dls = OW.encode(parts, fitted, base, lit=False)
    blob = bytearray(blob)
    m_at = base + len(blob)
    blob += OW.mtx(placement_matrix(pos, yaw))
    draw = base + len(blob)
    blob += b"".join([OW.PIPESYNC, OW.OTHERMODE_25, OW._w(0xDA380000, m_at), OW._w(0xDE000000, dls[0]),
                      OW._w(0xD8380002, 0x40), OW.PIPESYNC, OW._w(0xD9000000, OW.GEO_STD), OW.CC_SETUP_25,
                      OW._w(0xD7000002, 0xFFFFFFFF), OW.OTHERMODE_25, OW.ENDDL])
    return bytes(blob), draw


def wrapper(draws: list[int], original: int) -> bytes:
    out = b"".join(OW._w(0xDE000000, d) for d in draws)
    return out + (OW._w(0xDE010000, original) if original else OW.ENDDL)


# ---------------------------------------------------------------- room meshes

def mesh_entries(room: bytes, shape_off: int) -> tuple[int, list[dict]]:
    """RoomShape at shape_off (room-file offset) -> (type, [{at: offset of the entry, opa, center, radius}])."""
    typ, n = room[shape_off], room[shape_off + 1]
    ent = OW.u32(room, shape_off + 4) & 0xFFFFFF
    out = []
    if typ == 0:
        for i in range(n):
            out.append({"at": ent + 8 * i, "opa": OW.u32(room, ent + 8 * i), "opa_at": ent + 8 * i})
    elif typ == 1:
        out.append({"at": ent, "opa": OW.u32(room, ent), "opa_at": ent})
    else:
        for i in range(n):
            x, y, z, r = struct.unpack_from(">4h", room, ent + 16 * i)
            out.append({"at": ent + 16 * i, "opa": OW.u32(room, ent + 16 * i + 8), "opa_at": ent + 16 * i + 8,
                        "center": np.array([x, y, z], float), "radius": r, "radius_at": ent + 16 * i + 6})
    return typ, out


def pick_entry(entries: list[dict], pos) -> dict:
    with_sphere = [e for e in entries if "center" in e]
    if with_sphere:
        return min(with_sphere, key=lambda e: np.linalg.norm(e["center"] - pos) - e["radius"])
    return next((e for e in entries if e["opa"]), entries[0])


def room_shape_offset(room: bytes) -> int:
    """Room header command 0x0A (mesh) -> RoomShape offset in the room file."""
    o = 0
    while o + 8 <= len(room):
        cmd = room[o]
        if cmd == 0x0A:
            return OW.u32(room, o + 4) & 0xFFFFFF
        if cmd == 0x14:
            break
        o += 8
    raise ValueError("room file without a mesh command")


# ---------------------------------------------------------------- ROM

def scene_table(rom: OW.Rom) -> int:
    """gSceneTable in code (0x14-byte entries whose first words are a DMA VROM pair) -> its offset."""
    code = rom.file(rom.v["code"])
    pairs = {(e[0], e[1]) for e in rom.dma}
    for o in range(0, len(code) - 0x14 * 100, 4):
        if struct.unpack_from(">II", code, o) in pairs and all(
                struct.unpack_from(">II", code, o + 0x14 * k) in pairs for k in range(1, 100)):
            return o
    raise ValueError("gSceneTable not found in code")


def scene_rooms(rom: OW.Rom, scene: int) -> tuple[int, list[int]]:
    """-> (scene file DMA index, [room file DMA index])."""
    code = rom.file(rom.v["code"])
    st = scene_table(rom)
    vs, _ve = struct.unpack_from(">II", code, st + 0x14 * scene)
    si = rom.index_of_vrom(vs)
    sc = rom.file(si)
    o = 0
    while o + 8 <= len(sc):
        if sc[o] == 0x04:
            n, lst = sc[o + 1], OW.u32(sc, o + 4) & 0xFFFFFF
            return si, [rom.index_of_vrom(OW.u32(sc, lst + 8 * k)) for k in range(n)]
        if sc[o] == 0x14:
            break
        o += 8
    raise ValueError(f"scene {scene} has no room list")


def write_rom(cfg, rom: OW.Rom, placements: list[dict], progress=lambda p, m: None) -> list[dict]:
    """Every placement into its room file (segment-3 data appended, the nearest mesh entry hooked)."""
    from . import characters as C
    by_room, out = {}, []
    for pl in placements:
        by_room.setdefault((pl["scene"], pl["room"]), []).append(pl)
    rom.ref_files = set(getattr(rom, "ref_files", ()))
    root = C.library_root(cfg)
    for (scene, room_no), items in by_room.items():
        si, rooms = scene_rooms(rom, scene)
        ri = rooms[room_no]
        room = bytearray(rom.file(ri))
        typ, entries = mesh_entries(bytes(room), room_shape_offset(bytes(room)))
        draws, groups = [], {}
        for pl in items:
            meta = C.get(root, pl["character"])
            progress(82, f"Placing {meta['name']} in scene {scene} room {room_no} (ROM)")
            parts, mats, rep = statue_parts(root / meta["slug"] / meta["model"], pl["height"],
                                            [p["node"] for p in meta.get("props") or []], C._blender(cfg),
                                            Path(cfg.cache) / "characters_build" / meta["slug"] / "statue")
            room.extend(bytes((-len(room)) % 16))
            blob, draw = statue_blob(parts, mats, 0x03000000 + len(room), pl["pos"], pl["yaw"])
            room.extend(blob)
            e = pick_entry(entries, np.array(pl["pos"]))
            groups.setdefault(e["at"], (e, []))[1].append(draw)
            if "radius_at" in e:
                need = int(np.linalg.norm(e["center"] - pl["pos"]) + rep["radius"] + 10)
                if need > e["radius"]:
                    struct.pack_into(">h", room, e["radius_at"], min(need, 0x7FFF))
            out.append({"id": pl["id"], "scene": scene, "room": room_no, "triangles": rep["triangles"], "room_bytes": len(room)})
        for at, (e, ds) in groups.items():
            room.extend(bytes((-len(room)) % 8))
            w = 0x03000000 + len(room)
            room.extend(wrapper(ds, e["opa"]))
            struct.pack_into(">I", room, e["opa_at"], w)
        rom.put(ri, bytes(room))
        rom.ref_files.add(si)
    return out


# ---------------------------------------------------------------- live (RAM) data for the session's watcher

def live_items(cfg, placements: list[dict], obj_table_ram: int) -> list[dict]:
    """Every placement as segment-0x0E-relative data for the watcher: {id, scene, room, pos, blob hex, draw (offset),
    radius, obj_table (gObjectTable's RAM address: object sizes, to see where the loaded objects end)}."""
    from . import characters as C
    root = C.library_root(cfg)
    out = []
    for pl in placements[:MAX_SLOTS]:
        meta = C.get(root, pl["character"])
        parts, mats, rep = statue_parts(root / meta["slug"] / meta["model"], pl["height"],
                                        [p["node"] for p in meta.get("props") or []], C._blender(cfg),
                                        Path(cfg.cache) / "characters_build" / meta["slug"] / "statue", LIVE_TRIS)
        blob, draw = statue_blob(parts, mats, SEG, pl["pos"], pl["yaw"], LIVE_BUDGET)
        out.append({"id": pl["id"], "scene": pl["scene"], "room": pl["room"], "pos": list(map(float, pl["pos"])),
                    "blob": blob.hex(), "draw": draw - SEG, "radius": rep["radius"], "name": meta["name"],
                    "triangles": rep["triangles"], "obj_table": obj_table_ram})
    return out


def new_placement(character: str, scene: int, room: int, pos, yaw: float, height: float) -> dict:
    return {"id": f"p{int(time.time() * 1000) % 10**10}", "character": character, "scene": int(scene), "room": int(room),
            "pos": [round(float(v), 1) for v in pos], "yaw": round(float(yaw), 1), "height": float(height),
            "added": time.time()}


# ---------------------------------------------------------------- characters op=place / unplace

def _apply_live(ctx, rom: OW.Rom, game: dict, sid: str) -> dict:
    from .oot_swap import _api_job
    items = live_items(ctx.config, load(ctx.config, game["game_id"]), rom.v["code_vram"] + rom.obj_table)
    return _api_job(ctx, sid, "apply", items=items)


def place(ctx, meta: dict, game: dict, inp) -> dict:
    """A statue of `meta` in the scene the session is in: at pos (x, y, z world units), at the floor under picture point
    (x, y), next to an actor (near = "Saria", "Deku Tree", En_Sa...), else 80 units in front of the player, facing him.
    Drawn right away (live) and kept in every OoT mod gBox builds from now on (ROM)."""
    from .oot_swap import _api_job, _norm, rom_of, NAMES, NPCS
    if not inp.session_id:
        raise ValueError("place needs the session_id of the running Ocarina of Time (the statue goes where you are)")
    rom, _p = rom_of(ctx.config, game)
    w = _api_job(ctx, inp.session_id, "where")
    me = np.array(w["player"], float)
    yaw = None
    if inp.pos and len(inp.pos) == 3:
        pos, how = np.array(inp.pos, float), "at the given position"
    elif inp.x is not None and inp.y is not None:
        r = _api_job(ctx, inp.session_id, "floor_point", x=inp.x, y=inp.y)
        if not r.get("point"):
            raise LookupError("that picture point isn't on the ground in front of the camera")
        pos, how = np.array(r["point"], float), "at the picture point"
    elif inp.near:
        want = _norm(inp.near)
        alias = {"deku tree": "Bg_Treemouth", "great deku tree": "Bg_Treemouth", "sign": "En_Kanban"}
        actor = alias.get(want) or NPCS.get(want, (None,))[0] or next(
            (v for v in NAMES["actors"].values() if _norm(v) == want or _norm(v).replace(" ", "") == want.replace(" ", "")), None)
        acts = _api_job(ctx, inp.session_id, "actors")["actors"]
        hits = [a for a in acts if actor and a["name"] == actor]
        if not hits:
            raise LookupError(f"no {inp.near!r} in this scene right now (actors here: "
                              f"{', '.join(sorted({a['name'] for a in acts if a['category'] in ('npc', 'bg', 'prop')}))[:400]})")
        a = min(hits, key=lambda a: np.linalg.norm(np.array(a["pos"]) - me))
        ap = np.array(a["pos"], float)
        d = me - ap
        d[1] = 0
        d = d / (np.linalg.norm(d) or 1)
        side = np.array([d[2], 0, -d[0]])
        pos, how = ap + 60 * side + 30 * d, f"next to {a['name']}"
    else:
        f = np.radians(w["yaw"])
        pos, how = me + 80 * np.array([np.sin(f), 0, np.cos(f)]), "in front of you"
    if yaw is None:
        d = me - pos
        yaw = float(np.degrees(np.arctan2(d[0], d[2]))) if np.linalg.norm(d[[0, 2]]) > 1 else w["yaw"] + 180
    if inp.yaw is not None:
        yaw = float(inp.yaw)
    height = STATUE_HEIGHT * (inp.size or 1.0)
    pl = new_placement(meta["slug"], w["scene"], w["rooms"][0] if w["rooms"] else 0, pos, yaw, height)
    items = load(ctx.config, game["game_id"]) + [pl]
    save(ctx.config, game["game_id"], items)
    ctx.progress(50, f"Building the {meta['name']} statue and drawing it into the room")
    live = _apply_live(ctx, rom, game, inp.session_id)
    blocked = (live.get("blocked") or "")
    msg = (f"A {meta['name']} statue ({height:.0f} units tall) stands {how} in scene {w['scene']} room {pl['room']} "
           f"at ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f}). It's drawn into the room now and redrawn whenever you come "
           "back while this session runs; every OoT mod gBox builds from now on has it in the ROM.")
    if not live.get("hooked_now") and not blocked:
        msg += " (Not visible this instant: the room it belongs to isn't the one loaded.)"
    return {"status": "placed", "placement": pl, "live": live, "message": msg,
            "statues_in_game": len(items)}


def unplace(ctx, game: dict, inp) -> dict:
    """Remove statues: of `character` (or all) in the session's current scene."""
    from .oot_swap import _api_job, rom_of
    items = load(ctx.config, game["game_id"])
    scene = _api_job(ctx, inp.session_id, "where")["scene"] if inp.session_id else None
    keep = [p for p in items if not ((scene is None or p["scene"] == scene) and
                                     (not inp.character or inp.character.lower() in (p["character"], p.get("name", "").lower())))]
    save(ctx.config, game["game_id"], keep)
    if inp.session_id:
        rom, _p = rom_of(ctx.config, game)
        _apply_live(ctx, rom, game, inp.session_id)
    return {"status": "removed", "removed": len(items) - len(keep), "left": len(keep),
            "message": f"Removed {len(items) - len(keep)} statue(s); they disappear at the next room load. Mods built "
                       "before still contain them until rebuilt."}

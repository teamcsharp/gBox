"""The pick whip's backend: identify the character under the cursor down to its RAM, and replace it - live in RAM or
through the swap writer + session swap (docs/live-inject.md, docs/live-picker.md).

pick_identify {session_id, x, y, region?}
    -> {entity, game_id, slot, model, ram, evidence, confidence, replaceable: {live, build, reason}, backend, ...}
  1. entity     the game's own view of the point: OoT actors (gbox.oot_live), DOA2 actors (gbox.doa2_context),
                SM64 (Mario), profile games (profile.camera projection: tools.pick_preview / gbox.entity_probe).
  2. draw       capture=true: the frame as draw calls (gbox.scene_capture, Windows + RenderDoc), the draws under the
                point (characters.cut_scene) and their textures found in RAM (pick_ram.find_texture).
  3. RAM        a main-RAM snapshot: learned pointer paths first (instant), else a pointer walk from the entity struct
                with the platform's structure detectors (Ninja node trees, N64 / GX display lists, vertex arrays,
                matrix arrays); learned model signatures (a previous replace) locate the model image itself.
  4. analysis   static roots (profile tables, pointers to the entity from the executable's data) go to Ghidra
                (pick_ghidra: FindRefs + ExplainAddresses on the RAM image) as a background job whose findings are
                merged into the game's learned profile and the knowledge graph (hypothesis edges).
  5. learning   class -> slot / model slug / model pointer offset, kept in the learned profile (gbox.pick_learn).

pick_replace {session_id, pick, character, mode: live|build} -> fit events for the slot (gbox.fit_events)
  live   OoT NPC: characters op=live_use (bounded object swap) | SM64: live_link push (hot swap in RDRAM) | any other
         writer: pick_prepare builds the mod with the game's writer (on the control plane, where the collection is),
         turns the changed files into in-RAM images (gbox.live_inject), the session's worker locates them in RAM,
         writes them paused, verifies, restores on failure. Not possible -> build (fallback=true).
  build  the writer's mod + POST /api/sessions/{sid}/swap (keep the moment); then, because the restored state still
         holds the old model, the same in-RAM images are injected into the new session (refresh_ram).
"""
from __future__ import annotations

import gzip
import json
import re
import struct
import time
from pathlib import Path

from pydantic import BaseModel

from . import fit_events as FE, live_inject as LI, pick_learn as L, pick_ram as R
from .models import Permission as P
from .registry import HOST_OS, tool

LIVE_PLATFORMS = {"gamecube", "wii", "dreamcast", "naomi", "ps2", "psx"}   # disc-file writers (N64: OoT / SM64 paths)
JOB_POLL_S = 1.5


# ---------------------------------------------------------------- control-plane plumbing

def _api(ctx, method: str, path: str, **kw):
    import httpx
    if not getattr(ctx, "server", None):
        raise RuntimeError("no control-plane connection on this worker")
    r = httpx.request(method, f"{ctx.server}{path}", headers=ctx.headers, timeout=kw.pop("timeout", 60), **kw)
    r.raise_for_status()
    return r.json() if "json" in r.headers.get("content-type", "") else r.content


def _start(ctx, tool_name: str, inp: dict, worker: str | None = None) -> dict:
    return _api(ctx, "POST", "/api/jobs", json={"tool": tool_name, "input": inp,
                                                **({"require_worker": worker} if worker else {})})


def _control_plane(ctx, tool_name: str = "") -> str | None:
    """The worker that holds the character collection (the Spark): online, linux, offering tool_name if given."""
    try:
        ws = [w for w in _api(ctx, "GET", "/api/workers") if w.get("online")]
    except Exception:                                        # noqa: BLE001
        return None
    pref = [w for w in ws if w.get("os") == "linux" and (not tool_name or tool_name in (w.get("tools") or []))]
    pref = pref or [w for w in ws if w.get("os") == "linux"]
    return pref[0]["id"] if pref else None


def _collection_here(cfg) -> bool:
    try:
        from .characters import library_root
        return library_root(cfg).is_dir()
    except Exception:                                        # noqa: BLE001
        return False


def relay(ctx, job: dict, limit: float, pct=(5.0, 85.0)) -> dict:
    """Wait for a sub-job and re-emit its fitting events (and progress) on this job, so the operator's Fitting
    pop-up follows the slot whichever node fits it. -> the finished job."""
    seen, last, t0 = {}, None, time.time()
    while True:
        fit = job.get("fitting") or {}
        prog = job.get("progress") or {}
        p = pct[0] + (pct[1] - pct[0]) * float(prog.get("pct") or 0) / 100.0
        for key in fit.get("order", []):
            m = (fit.get("models") or {}).get(key) or {}
            for sname, s in (m.get("stages") or {}).items():
                sig = (s.get("state"), s.get("ts"))
                if seen.get((key, sname)) == sig:
                    continue
                seen[(key, sname)] = sig
                ev = {"model": key, "label": m.get("label") or key, "stage": sname, "state": s.get("state") or "done"}
                for k in ("data", "text"):
                    if s.get(k) is not None:
                        ev[k] = s[k]
                for k in ("snapshot", "preview"):
                    if m.get(k) and m.get(k + "_stage") == sname:
                        ev[k] = m[k]
                ctx.progress(p, f"{ev['label']}: {sname}" + FE.encode(ev))
        if prog.get("msg") and prog.get("msg") != last:
            last = prog["msg"]
            ctx.progress(p, str(last)[:300])
        if job.get("state") not in ("queued", "running") or time.time() - t0 > limit:
            return job
        time.sleep(JOB_POLL_S)
        job = _api(ctx, "GET", f"/api/jobs/{job['id']}")


def _upload(ctx, name: str, data: bytes, media: str = "application/octet-stream") -> str:
    import httpx
    r = httpx.post(f"{ctx.server}/api/artifacts", params={"name": name, "media_type": media}, content=data,
                   headers={**ctx.headers, "Content-Type": "application/octet-stream"}, timeout=300)
    r.raise_for_status()
    return r.json()["sha256"]


class Evidence(list):
    def add(self, step: str, ok, detail: str, source: str = "", **data):
        row = {"step": step, "ok": bool(ok), "detail": detail, "source": source}
        if data:
            row["data"] = json.loads(json.dumps(data, default=_plain))
        self.append(row)
        return row


def _plain(v):
    if hasattr(v, "tolist"):
        return v.tolist()
    if isinstance(v, bytes):
        return v.hex()
    return str(v)


def _hex(v) -> str | None:
    return None if v is None else f"0x{int(v):08X}"


def _int(v) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    try:
        return int(str(v), 16) if str(v).lower().startswith("0x") else int(str(v), 0)
    except ValueError:
        return None


def picture_xy(x: float, y: float, aspect: float) -> tuple[float, float]:
    """A click in the window (0..1) -> the 4:3 game picture centred in it (0..1)."""
    if aspect > 4 / 3:
        w = (4 / 3) / aspect
        x = (x - (1 - w) / 2) / w
    elif aspect < 4 / 3:
        h = aspect / (4 / 3)
        y = (y - (1 - h) / 2) / h
    return x, y


def region_box(region, aspect: float) -> tuple[float, float, float, float] | None:
    """region {x, y, w, h} | {x0, y0, x1, y1} | [x0, y0, x1, y1] (window fractions) -> picture box."""
    if not region:
        return None
    if isinstance(region, dict):
        if {"x0", "y0", "x1", "y1"} <= set(region):
            b = [region[k] for k in ("x0", "y0", "x1", "y1")]
        elif {"x", "y", "w", "h"} <= set(region):
            b = [region["x"], region["y"], region["x"] + region["w"], region["y"] + region["h"]]
        else:
            return None
    else:
        b = list(region)[:4]
        if len(b) != 4:
            return None
    (x0, y0), (x1, y1) = picture_xy(b[0], b[1], aspect), picture_xy(b[2], b[3], aspect)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def backend_of(g: dict) -> str:
    gid = g.get("game_id") or ""
    try:
        from .oot_swap import is_oot
        if is_oot(g):
            return "oot"
    except Exception:                                        # noqa: BLE001
        pass
    for name, mod in (("sm64", "sm64_swap"), ("doa2", "doa2_chars")):
        try:
            import importlib
            if gid in (getattr(importlib.import_module(f"gbox.{mod}"), "GAME_IDS", None) or ()):
                return name
        except Exception:                                    # noqa: BLE001
            pass
    return "profile"


# ---------------------------------------------------------------- 1. the entity under the point

def entity_oot(ad, g, cx, cy, ev: Evidence) -> dict | None:
    from . import oot, oot_live as OL
    a = OL.pick(ad, cx, cy)
    if a is None:
        ev.add("entity", False, "no actor is drawn at the point (feet-to-head segments through "
                                "play->viewProjectionMtxF)", "gbox.oot_live.pick")
        return None
    sk = OL.skel_anime(ad, a) if a["category"] != "player" else None
    try:
        version = oot.layout(ad).get("version")
    except Exception:                                        # noqa: BLE001
        version = None
    pos = [round(float(v), 1) for v in a["pos"]]
    ent = {"class": a["name"], "kind": a["category"], "ptr": _hex(a["addr"]), "actor_id": a["id"], "object": a["object"],
           "object_name": a.get("object_name"), "x": pos[0], "y": pos[1], "z": pos[2], "screen": a.get("screen")}
    ram = {"entity_struct": _hex(a["addr"]), "model": _hex(a.get("object_segment")),
           "model_kind": "oot_object (segment 6 file as loaded)"}
    if sk:
        ram["skel_anime"] = _hex(sk["at"])
        ram["joint_table"] = _hex(sk["joint_table"])
        if sk["skeleton"] >> 24 == 6 and a.get("object_segment"):
            ram["skeleton"] = _hex(a["object_segment"] + (sk["skeleton"] & 0xFFFFFF))
        ram["limbs"] = sk["limbs"]
    ev.add("entity", True, f"{a['name']} ({a['category']}, object {a.get('object_name') or a['object']}) "
                           f"{a['distance']:.3f} from the point", "gbox.oot_live.pick", screen=a.get("screen"))
    if sk:
        ev.add("skeleton", True, f"SkelAnime at {_hex(sk['at'])}: {sk['limbs']} limbs, limb table {ram.get('skeleton')}, "
                                 f"joint table {_hex(sk['joint_table'])}", "gbox.oot_live.skel_anime")
    return {"entity": ent, "ram": ram, "slot": "player" if a["category"] == "player" else a["name"],
            "version": version, "struct_size": 0x140}


def project_hits(ad, g: dict, prof: dict, st: dict, cx: float, cy: float) -> list[tuple]:
    """Every entity projected through the profile's look-at camera (the player too: the pick whip replaces the
    player first of all), nearest on screen first, the player's room preferred. -> [(miss, entity, (sx, sy), depth)]."""
    import math
    from . import tools as T
    cam = prof["camera"]
    end = ">" if g.get("platform") in R.BIG_ENDIAN else "<"
    eye = struct.unpack(end + "3f", ad.read_memory(int(cam["eye"], 16), 12))
    tgt = struct.unpack(end + "3f", ad.read_memory(int(cam["target"], 16), 12))
    lift = float(cam.get("pick_height", 12))
    hits = []
    for e in st.get("entities", []):
        p3 = (e.get("x") or 0.0, (e.get("y") or 0.0) + lift, e.get("z") or 0.0)
        depth = math.dist(eye, p3)
        if depth > float(cam.get("pick_range", 700)):
            continue
        p = T.project_point(eye, tgt, p3, cam.get("fov", 45))
        if p and -0.1 <= p[0] <= 1.1 and -0.1 <= p[1] <= 1.1:
            hits.append((math.hypot(p[0] - cx, p[1] - cy), e, p, depth))
    me = next((h[1] for h in hits if h[1].get("kind") == "player"), {})
    live_kinds = ("enemy", "npc", "player", "boss")
    near = [h for h in hits if h[0] < (0.2 if h[1].get("kind") in live_kinds else 0.1)] or sorted(hits, key=lambda h: h[0])[:1]
    near.sort(key=lambda h: (h[1].get("room") != me.get("room") if me else False, round(h[0], 2), h[3]))
    return near + sorted((h for h in hits if h not in near), key=lambda h: h[0])


def entity_profile(ad, g, sid, x, y, aspect, cx, cy, box, ev: Evidence, ctx) -> dict | None:
    from . import semantic, tools as T
    try:
        st = T._semantic_state(ad, g)
    except Exception as e:                                   # noqa: BLE001
        ev.add("entity", False, f"semantic state unreadable: {e}", "gbox.semantic")
        return None
    prof = next((p for p in semantic.load_profiles() if p.get("id") == st.get("profile")), None)
    if not prof:
        ev.add("entity", False, "no semantic profile for this game (system/profiles): the entity table and camera "
                                "aren't mapped yet", "gbox.semantic")
        return None
    cam = prof.get("camera") or {}
    picked, others, how = None, [], ""
    if cam.get("layout") == "pos_angles_fov":
        from . import entity_probe
        scan = entity_probe.Probe(prof, ad.read_memory).scan(*T.PICK_FRAME, entities=st.get("entities"))
        res = T._pick_from_probe(scan, cx, cy)
        picked, others, how = res.get("picked"), res.get("others") or [], "gbox.entity_probe (gclient camera)"
    elif cam:
        hits = project_hits(ad, g, prof, st, cx, cy)
        how = "profile.camera projection (tools.project_point)"
        if box:                                              # the selection wins over the click point
            hits.sort(key=lambda h: not (box[0] <= h[2][0] <= box[2] and box[1] <= h[2][1] <= box[3]))
        if hits:
            dist, e, p, _depth = hits[0]
            picked = {k: e.get(k) for k in ("class", "kind", "entity_id", "ptr", "x", "y", "z", "hp", "room")} | {
                "screen": [round(p[0], 3), round(p[1], 3)], "miss": round(dist, 3)}
            others = [{"class": h[1].get("class"), "kind": h[1].get("kind"), "miss": round(h[0], 3)} for h in hits[1:4]]
    else:
        ev.add("entity", False, f"profile {prof['id']} has no camera mapping: the point can't be projected", prof["id"])
        return {"entity": None, "profile": prof, "state": st}
    if box and others and picked and picked.get("screen"):
        sx, sy = picked["screen"][:2]
        if not (box[0] <= sx <= box[2] and box[1] <= sy <= box[3]):
            ev.add("region", False, "the nearest entity lies outside the selected region", how)
    if not picked:
        ev.add("entity", False, "nothing projectable near the point", how)
        return {"entity": None, "profile": prof, "state": st}
    ev.add("entity", True, f"{picked.get('class')} ({picked.get('kind')}) at {picked.get('ptr')}", how,
           others=[o.get("class") for o in others[:3]])
    ents = prof.get("entities") or {}
    size = _int(ents.get("struct_size")) or _int(ents.get("stride")) or _int(picked.get("class_size")) or 0x200
    return {"entity": picked, "profile": prof, "state": st, "struct_size": size,
            "model_map": (prof.get("models") or {}).get(picked.get("class"))}


def entity_doa2(ram: R.Ram, g, cx, ev: Evidence) -> dict | None:
    from . import doa2_context as D
    exe = None
    rom = g.get("_rom_path")
    try:
        if rom and str(rom).lower().endswith(".gdi"):
            from .gdrom import GDRom
            exe = GDRom(str(rom)).read("1ST_READ.BIN")
    except Exception as e:                                   # noqa: BLE001
        ev.add("executable", False, f"1ST_READ.BIN unreadable: {e}", "gbox.gdrom")
    if exe is None:
        ev.add("entity", False, "DOA2's actor layout is pinned to the owned executable, which isn't readable on this "
                                "node", "gbox.doa2_context")
        return None
    cands = []
    for i in (0, 1):
        try:
            cands.append(D.inspect_actor(ram.data, exe, i))
        except Exception as e:                               # noqa: BLE001
            ev.add(f"actor {i}", False, str(e), "gbox.doa2_context.inspect_actor")
    if not cands:
        return None
    pick = cands[0] if len(cands) == 1 else cands[0 if cx < 0.5 else 1]
    ev.add("entity", True, f"native actor {pick['actor_index']} ({pick['resource_filenames'].get('geometry')}) of "
                           f"{len(cands)} drawn" + ("; chosen by screen half (DOA2 actor positions are not mapped: "
                                                     "check the side)" if len(cands) > 1 else ""),
           "gbox.doa2_context.inspect_actor", actors=[c["actor_index"] for c in cands])
    geo = (pick["resource_filenames"].get("geometry") or "").upper()
    m = re.match(r"([A-Z]{3})(\d{2})", geo)
    slot = None
    try:
        from . import doa2_chars
        keys = {k for k, _n, _a in doa2_chars.FIGHTERS}
        if m and m.group(1) in keys:
            slot = f"fighter:{m.group(1)}:{m.group(2)}"
    except Exception:                                        # noqa: BLE001
        pass
    chr_at = _int("0x" + pick["chr_address"])
    ent = {"class": geo or f"actor {pick['actor_index']}", "kind": "fighter", "ptr": "0x" + pick["actor_address"].upper(),
           "actor_index": pick["actor_index"], "render_slot": pick["render_slot"], "costume": pick["render_costume"]}
    ram_out = {"entity_struct": ent["ptr"], "model": _hex(chr_at), "model_kind": "NaomiLib CHR (relocated)",
               "model_table": _hex(chr_at + pick["model_table_offset"]),
               "texture_table": _hex(chr_at + pick["texture_table_offset"]), "models": pick["model_count"]}
    return {"entity": ent, "ram": ram_out, "slot": slot, "ambiguous": len(cands) > 1}


def entity_sm64(ram: R.Ram, g, ev: Evidence) -> dict:
    ent = {"class": "Mario", "kind": "player"}
    out = {"entity": ent, "ram": {}, "slot": "player", "guess": True}
    ev.add("entity", True, "Super Mario 64: the swap writer replaces Mario only, so the pick is Mario (objects under "
                           "the point aren't projected yet)", "gbox.sm64_swap")
    rom = g.get("_rom_path")
    try:
        from . import sm64_mario as sm, sm64_swap, sm64_writer as W
        data = sm64_swap.rom_bytes(Path(rom))
        seg4 = sm.Mem(data).seg[0x04][:W.MARIO_END]
    except Exception as e:                                   # noqa: BLE001
        ev.add("model", False, f"Mario's model data couldn't be read from the ROM on this node: {e}", "gbox.sm64_mario")
        return out
    hits = R.find_window(ram, seg4[:512], None, min_score=1.0)
    hit = next((h for h in hits if ram.read(h["addr"], min(len(seg4), 4096)) == seg4[:4096]), None)
    if hit:
        out["ram"] = {"model": _hex(hit["addr"]), "model_kind": "SM64 segment 04 (Mario's geometry + textures)",
                      "model_bytes": len(seg4)}
        ev.add("model", True, f"Mario's segment-04 model data found at {_hex(hit['addr'])} ({len(seg4)} bytes, "
                              "byte-exact)", "gbox.pick_ram.find_window")
    else:
        ev.add("model", False, "Mario's stock model data isn't in RAM (a modded build is running, or the level hasn't "
                               "loaded him)", "gbox.pick_ram.find_window")
    return out


# ---------------------------------------------------------------- 2. the draw under the point (RenderDoc)

def draw_layer(ad, g, sid, cx, cy, ctx, ev: Evidence) -> dict | None:
    """Capture the frame, cut the object at the point, return its draws + textures (RGBA) for the RAM search.
    Leaves the game paused when the capture does (resume_on_leave); the caller snapshots RAM, then resumes."""
    if HOST_OS != "windows":
        ev.add("draw", False, "frame capture runs on the Windows node (RenderDoc)", "gbox.scene_capture")
        return None
    from . import characters as C, scene_capture as SC
    out = Path(ctx.config.runtime) / "pick_capture" / sid
    try:
        s = SC.capture_session(ad, out, 2, 0, 0, None)
    except Exception as e:                                   # noqa: BLE001
        ev.add("draw", False, f"capture failed: {e}", "gbox.scene_capture")
        return None
    res = {"resume": bool(s.get("resume_on_leave")), "summary": {k: s.get(k) for k in ("draws_exported", "textures")}}
    try:
        cut = C.cut_scene(out / "scene.glb", cx, cy)
        res["cut"] = {k: cut[k] for k in ("nodes", "seed", "depth", "size", "hits")}
        res["draws"] = glb_draws(out / "scene.glb", cut["nodes"])
        res["textures"] = glb_textures(out / "scene.glb", cut["nodes"])
        ev.add("draw", True, f"{len(cut['nodes'])} draw(s) at the point (seed node {cut['seed']}, depth {cut['depth']})",
               "characters.cut_scene", hits=cut["hits"][:4])
    except Exception as e:                                   # noqa: BLE001
        ev.add("draw", False, f"no object draw at the point: {e}", "characters.cut_scene")
    return res


def _glb_json(path: Path) -> tuple[dict, bytes]:
    d = Path(path).read_bytes()
    jl = struct.unpack_from("<I", d, 12)[0]
    return json.loads(d[20:20 + jl]), d[20 + jl + 8:]


def glb_draws(path: Path, nodes: list[int]) -> list[dict]:
    """The draw calls (scene_capture node extras) of some nodes: draw index, event id, vertices, triangles, texture."""
    gl, _bin = _glb_json(path)
    out = []
    for ni in nodes:
        ex = (gl["nodes"][ni].get("extras") or {})
        out.append({"node": ni, **{k: ex.get(k) for k in ("draw", "eid", "call", "vertices", "triangles", "texture",
                                                          "texture_size", "texture_format")}})
    return out


def correlate(draws: list[dict], structures: list[dict]) -> list[dict]:
    """Draw calls under the point <-> RAM structures reached from the entity, by exact triangle / vertex counts."""
    out = []
    for d in draws or []:
        for s in structures or []:
            det = s.get("detail") or {}
            if det.get("triangles") and det["triangles"] == d.get("triangles"):
                out.append({"draw": d.get("draw"), "ram": s["at"], "by": f"{det['triangles']} triangles"})
            elif det.get("count") and det["count"] == d.get("vertices"):
                out.append({"draw": d.get("draw"), "ram": s["at"], "by": f"{det['count']} vertices"})
    return out


def glb_textures(path: Path, nodes: list[int], limit: int = 4) -> list[dict]:
    """The base-colour images of some nodes of a .glb: [{node, name, w, h, rgba}]."""
    import io
    from PIL import Image
    gl, bin_ = _glb_json(path)
    out, seen = [], set()
    for ni in nodes:
        nd = gl["nodes"][ni]
        if "mesh" not in nd:
            continue
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            mi = pr.get("material")
            if mi is None:
                continue
            t = ((gl["materials"][mi].get("pbrMetallicRoughness") or {}).get("baseColorTexture") or {}).get("index")
            if t is None:
                continue
            src = gl["textures"][t].get("source")
            if src is None or src in seen:
                continue
            seen.add(src)
            im = gl["images"][src]
            bv = gl["bufferViews"][im["bufferView"]]
            raw = bin_[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
            img = Image.open(io.BytesIO(raw)).convert("RGBA")
            out.append({"node": ni, "name": im.get("name") or f"image{src}", "w": img.width, "h": img.height,
                        "rgba": img.tobytes()})
            if len(out) >= limit:
                return out
    return out


# ---------------------------------------------------------------- 3. RAM

def static_range(ram: R.Ram, g: dict) -> tuple[int, int] | None:
    """Where the executable's code + static data sit (pointers from there are roots worth a Ghidra look)."""
    if ram.platform in ("gamecube", "wii") and ram.contains(0x80000034, 4):
        lo = ram.canon(ram.u32(0x80000030))                  # OSArenaLo: the end of the DOL's sections
        if lo and lo > 0x80003100:
            return 0x80000000, lo
    if ram.platform in ("dreamcast", "naomi"):
        size = g.get("_exe_size")
        return 0x8C010000, 0x8C010000 + int(size or 0x200000)
    return None


def ram_layer(ram: R.Ram, ent_ptr: int | None, size: int, learned_cls: dict, ev: Evidence) -> dict:
    out: dict = {}
    if ent_ptr is None or not ram.contains(ent_ptr, 4):
        return out
    out["entity_struct"] = _hex(ent_ptr)
    out["struct_size"] = _hex(size)
    for key in ("model_ptr", "skeleton_ptr", "display_list_ptr", "vertex_ptr"):
        rule = (learned_cls or {}).get(key)
        if not rule:
            continue
        a = ent_ptr
        ok = True
        for off in rule.get("path", [rule.get("offset")]):
            o = _int(off)
            if o is None or not ram.contains(a + o, 4):
                ok = False
                break
            t = ram.canon(ram.u32(a + o))
            if t is None:
                ok = False
                break
            a = t
        role = key.removesuffix("_ptr")
        got = R.classify(ram, a, [rule["kind"]]) if ok and rule.get("kind") in R.DETECTORS else []
        if got:
            out[{"model": "model", "skeleton": "skeleton", "display_list": "display_list", "vertex": "vertex_buffer"}[role]] = _hex(a)
            out[role + "_detail"] = _brief(got[0])
            ev.add(f"learned {role}", True, f"{role} at {_hex(a)} via learned path {rule.get('path') or rule.get('offset')} "
                                            f"({rule['kind']})", "gbox.pick_learn")
        else:
            ev.add(f"learned {role}", False, f"learned path {rule.get('path') or rule.get('offset')} no longer leads to a "
                                             f"{rule.get('kind')}: walking again", "gbox.pick_learn")
    if all(out.get(k) for k in ("model",)) and learned_cls.get("model_ptr"):
        return out
    found = R.walk(ram, ent_ptr, size, depth=2)
    best: dict[str, dict] = {}
    for f in found:
        for det in f["found"]:
            role = R.ROLES[det["kind"]]
            score = det["score"] - 0.1 * (len(f["path"]) - 1)
            if role not in best or score > best[role]["score"]:
                best[role] = {"score": score, "det": det, "path": f["path"]}
    for role, b in best.items():
        if out.get(role):
            continue
        out[role] = _hex(b["det"]["at"])
        out[role + "_detail"] = _brief(b["det"])
        out[role + "_path"] = [[_hex(s), _hex(o)] for s, o in b["path"]]
    out["structures"] = [{"at": _hex(f["at"]), "kind": f["found"][0]["kind"], "detail": _brief(f["found"][0]),
                          "via": "+".join(_hex(o) for _s, o in f["path"])} for f in found[:12]]
    ev.add("pointer walk", bool(best), f"{len(found)} structure(s) reachable from the entity struct within 2 pointers"
           + (": " + ", ".join(f"{r} {_hex(b['det']['at'])} ({b['det']['kind']})" for r, b in best.items()) if best else ""),
           "gbox.pick_ram.walk")
    out["_best"] = {r: {"kind": b["det"]["kind"], "path": [o for _s, o in b["path"]]} for r, b in best.items()}
    return out


def _brief(det: dict) -> dict:
    keep = ("kind", "nodes", "models", "chunk_models", "depth", "dialect", "commands", "triangles", "format", "count",
            "stride", "layout", "primitive")
    out = {k: det[k] for k in keep if k in det}
    if "span" in det:
        out["span"] = [_hex(det["span"][0]), _hex(det["span"][1])]
    return out


# ---------------------------------------------------------------- 4. slot, model, replaceable

def _words(s) -> set[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(s or ""))
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in {"tobj", "ene", "obj", "the", "en", "a", "of"}}


def slot_for(game: dict, entity: dict | None, model_map, learned: dict, ev: Evidence) -> tuple[str | None, dict | None]:
    """The writer slot a collection character goes into for this entity: learned, player, the profile's model file
    matched to a writer slot, or a name match. -> (slot, the writer's slot row)."""
    if not entity:
        return None, None
    cls = entity.get("class")
    c = (learned.get("classes") or {}).get(str(cls)) or {}
    rows = []
    try:
        from . import char_coverage
        rows = char_coverage.cast_slots(game)
    except Exception as e:                                   # noqa: BLE001
        ev.add("slots", False, f"writer slots unavailable: {e}", "gbox.char_coverage")
    if c.get("slot"):
        return c["slot"], next((r for r in rows if r.get("slot") == c["slot"]), None)
    if entity.get("kind") == "player":
        return "player", next((r for r in rows if r.get("slot") == "player"), None)
    if model_map and len(model_map) >= 2:
        f, entry = model_map[0], model_map[1]
        for r in rows:
            if r.get("file") == f and (r.get("entry") == entry or entry in (r.get("entries") or [])) and not r.get("aggregate"):
                return r["slot"], r
    want = _words(cls) | _words(entity.get("object_name"))
    best, score = None, 0
    for r in rows:
        if r.get("aggregate"):
            continue
        s = len(want & (_words(r.get("name")) | _words(r.get("slot"))))
        if s > score:
            best, score = r, s
    return (best["slot"], best) if best else (None, None)


def model_for(ctx, gid: str, entity: dict | None, slot: str | None, learned: dict) -> tuple[str | None, str]:
    """The collection entry that is this model (its own game's rip), if any. -> (slug, how)."""
    if not entity:
        return None, ""
    c = (learned.get("classes") or {}).get(str(entity.get("class"))) or {}
    if c.get("model"):
        return c["model"], "learned"
    try:
        chars = _api(ctx, "GET", "/api/characters", params={"game_id": gid})
    except Exception:                                        # noqa: BLE001
        return None, ""
    mine = [m for m in chars if (m.get("source") or {}).get("game_id") == gid] or chars
    from .characters import best_match
    for q in (entity.get("class"), (slot or "").split(":")[-1], entity.get("object_name")):
        if q and (m := best_match(mine, str(q).replace("_", " "))):
            return m["slug"], f"collection name match for {q!r}"
    return None, ""


def replaceable(backend: str, game: dict, slot: str | None, row: dict | None, ad, extra: dict, learned: dict) -> dict:
    w = None
    try:
        from . import char_coverage
        w = char_coverage.writer_for(game)
    except Exception:                                        # noqa: BLE001
        pass
    build = bool(w and w.get("routed") and slot)
    why_build = (f"{w['writer']}: {w['replaces']}" if w else "no swap writer for this game yet (char_coverage)")
    if row and row.get("status") == "not_working":
        build, why_build = False, f"the writer marks slot {slot} not working"
    if not slot:
        build, why_build = False, why_build + "; the entity isn't mapped to a writer slot"
    live, why = False, ""
    if backend == "oot":
        if slot == "player":
            why = "Link's live model writer isn't implemented (bounded NPC objects only): build mode"
        elif extra.get("version") != "ntsc-1.2":
            why = f"live OoT swaps need NTSC 1.2 (this is {extra.get('version') or 'unknown'}): build mode"
        else:
            live, why = True, "bounded single-object NPC swap in the loaded object (gbox.oot_hot_swap)"
    elif backend == "sm64":
        if getattr(ad, "name", "") == "retroarch":
            live, why = True, "Mario hot swap: segment 04 + display-list pointers in RDRAM (gbox.live_link)"
        else:
            why = f"SM64 hot swap needs RetroArch ({getattr(ad, 'name', '?')} session): build mode"
    elif backend == "doa2":
        why = ("DOA2 deforms the fighter's CHR geometry in RAM every frame (SUP/APV/ACS) and its writer patches the "
               "executable: no stable image to patch live; build + session swap")
    elif build and game.get("platform") in LIVE_PLATFORMS:
        rep = (learned.get("replace") or {}).get(slot) or {}
        structural = ("executable", "runtime", "larger", "pointer", "no in-ram images", "layout", "changes no")
        if rep.get("live_ok") is False and any(k in str(rep.get("reason") or "").lower() for k in structural):
            why = f"the last live attempt for this slot can't work again until the writer changes: {rep['reason']}"
        else:
            live = True
            why = ("image injection: the writer's re-encoded files are located in RAM at replace time (exact or "
                   "relocated pointers only) and written paused + verified; falls back to build if the model isn't "
                   "found or doesn't fit")
    elif build:
        why = f"no RAM image path for {game.get('platform')}: build mode"
    else:
        why = "no writer: neither live nor build"
    return {"live": bool(live), "build": bool(build), "reason": f"live: {why}; build: {why_build}",
            "live_reason": why, "build_reason": why_build, "writer": (w or {}).get("writer")}


# ---------------------------------------------------------------- identify

class PickIdentifyIn(BaseModel):
    session_id: str
    x: float                                       # click, 0..1 across the game window
    y: float                                       # click, 0..1 down the game window
    region: dict | list | None = None              # the selection {x, y, w, h} | {x0, y0, x1, y1} | [x0, y0, x1, y1]
    window_aspect: float = 4 / 3
    capture: bool = False                          # also capture the frame (RenderDoc): draws + textures in RAM
    deep: bool = True                              # RAM snapshot + pointer walk (False: entity only, fast)
    analyze: str = "auto"                          # auto (Ghidra once per static root) | never | always


class PickIdentifyOut(BaseModel):
    entity: dict | None = None
    game_id: str = ""
    slot: str | None = None
    model: str | None = None
    ram: dict = {}
    evidence: list[dict] = []
    confidence: float = 0.0
    replaceable: dict = {}
    backend: str = ""
    session_id: str = ""
    title: str = ""
    platform: str = ""
    click: list[float] = []
    draws: list[dict] = []                         # capture=true: the draw calls under the point
    slot_guess: bool = False                       # slot assumed (no entity mapping for this game)
    seconds: float = 0.0


def identify(ad, g: dict, inp: PickIdentifyIn, ctx) -> dict:
    t0 = time.time()
    gid, plat = g.get("game_id") or "", g.get("platform") or ""
    cx, cy = picture_xy(inp.x, inp.y, inp.window_aspect)
    box = region_box(inp.region, inp.window_aspect)
    ev = Evidence()
    learned = L.load(ctx, gid) if gid else {}
    backend = backend_of(g)
    out = {"entity": None, "game_id": gid, "slot": None, "model": None, "ram": {}, "evidence": ev, "confidence": 0.0,
           "replaceable": {}, "backend": backend, "session_id": inp.session_id, "title": g.get("title") or "",
           "platform": plat, "click": [round(cx, 4), round(cy, 4)]}
    if box:
        ev.add("region", True, f"selection {tuple(round(v, 3) for v in box)} (picture fractions)", "input")
    conf = 0.0
    info: dict = {}
    if backend == "oot":
        info = entity_oot(ad, g, cx, cy, ev) or {}
    elif backend == "profile":
        info = entity_profile(ad, g, inp.session_id, inp.x, inp.y, inp.window_aspect, cx, cy, box, ev, ctx) or {}
    draw = draw_layer(ad, g, inp.session_id, cx, cy, ctx, ev) if inp.capture else None
    ram = None
    need_ram = inp.deep or backend in ("sm64", "doa2")
    if need_ram:
        try:
            paused = _pause(ad)
            try:
                ram = R.Ram.snapshot(ad, plat)
            finally:
                if paused:
                    try:
                        ad.resume()
                    except Exception:                        # noqa: BLE001
                        pass
            ev.add("ram", True, f"main RAM {_hex(ram.base)}..{_hex(ram.end)} ({len(ram.data) >> 20} MiB"
                                + (", word-swapped RDRAM normalised" if ram.swapped else "") + ")", "gbox.pick_ram.Ram.snapshot")
        except Exception as e:                               # noqa: BLE001
            ev.add("ram", False, f"RAM snapshot failed: {e}", "gbox.pick_ram.Ram.snapshot")
        finally:
            if draw and draw.get("resume"):
                try:
                    ad.resume()
                except Exception:                            # noqa: BLE001
                    pass
    elif draw and draw.get("resume"):
        try:
            ad.resume()
        except Exception:                                    # noqa: BLE001
            pass
    if backend == "sm64" and ram is not None:
        info = entity_sm64(ram, g, ev)
    elif backend == "doa2" and ram is not None:
        info = entity_doa2(ram, g, cx, ev) or {}
    ent = info.get("entity")
    out["entity"] = ent
    out["ram"] = dict(info.get("ram") or {})
    out["slot_guess"] = bool(info.get("guess"))
    if ent:
        conf += 0.45 if not info.get("ambiguous") else 0.25
    cls = str((ent or {}).get("class") or "")
    lcls = (learned.get("classes") or {}).get(cls) or {}
    if ram is not None and ent:
        ptr = _int(ent.get("ptr"))
        if backend in ("profile", "oot") and ptr is not None:
            r = ram_layer(ram, ptr, info.get("struct_size") or 0x200, lcls, ev)
            best = r.pop("_best", {})
            for k, v in r.items():
                out["ram"].setdefault(k, v)
            if r.get("model") or r.get("display_list") or r.get("vertex_buffer"):
                conf += 0.2
            info["best"] = best
    if draw and draw.get("draws"):
        out["draws"] = draw["draws"]
        m = correlate(draw["draws"], out["ram"].get("structures"))
        if m:
            out["ram"]["draw_matches"] = m
            conf += 0.1
        ev.add("draw <-> RAM", bool(m), ", ".join(f"draw {x['draw']} = {x['ram']} ({x['by']})" for x in m[:4]) if m else
               "no RAM structure reached from the entity has a captured draw's exact triangle / vertex count "
               "(transformed or re-indexed by the emulator)", "gbox.pick_tool.correlate")
    if ram is not None and draw and draw.get("textures"):
        tex_hits = []
        for t in draw["textures"]:
            for h in R.find_texture(ram, t["rgba"], t["w"], t["h"]):
                tex_hits.append({"texture": t["name"], "addr": _hex(h["addr"]), "format": h["format"]})
        if tex_hits:
            out["ram"]["textures"] = tex_hits[:6]
            owners = []
            for h in tex_hits[:3]:
                for chain in R.back_chains(ram, _int(h["addr"]), depth=3, limit=4):
                    owners.append([{k: (_hex(v) if isinstance(v, int) else v) for k, v in c.items()} for c in chain])
            out["ram"]["texture_owners"] = owners[:4]
            conf += 0.1
        ev.add("texture in RAM", bool(tex_hits), f"{len(tex_hits)} captured texture block(s) found re-encoded in RAM"
               if tex_hits else "the captured textures weren't found in a lossless console encoding (compressed / in VRAM)",
               "gbox.pick_ram.find_texture")
    slot, row = info.get("slot"), None
    if backend == "profile":
        slot, row = slot_for(g, ent, info.get("model_map"), learned, ev)
    if slot:
        ev.add("slot", True, f"writer slot {slot}", "gbox.char_coverage.cast_slots" if row else backend)
        conf += 0.15
    elif backend == "profile":                               # no entity mapping: the writer's player slot, flagged
        try:
            from . import char_coverage
            w = char_coverage.writer_for(g) or {}
        except Exception:                                    # noqa: BLE001
            w = {}
        if w.get("routed") and "player" in (w.get("slots") or []):
            slot = "player"
            out["slot_guess"] = True
            ev.add("slot", False, "the point isn't mapped to an entity in this game: assuming the writer's player slot "
                                  f"({w.get('writer')}); confirm on screen", "guess")
            conf += 0.05
    out["slot"] = slot
    # learned model signatures (a previous replace of this slot): the model image itself in RAM
    sig = ((learned.get("assets") or {}).get(slot or "") or {}).get("signatures")
    if ram is not None and sig:
        hits = LI.find_signatures(ram, sig)
        if hits:
            out["ram"].setdefault("model", _hex(hits[0]["base"]))
            out["ram"]["model_images"] = [{"name": h["name"], "base": _hex(h["base"]), "bytes": h["size"]} for h in hits[:6]]
            conf += 0.15
        ev.add("model image", bool(hits), f"{len(hits)} learned model image(s) of slot {slot} located in RAM"
               if hits else f"the learned model images of slot {slot} aren't loaded right now", "gbox.live_inject.find_signatures")
    model, how = model_for(ctx, gid, ent, slot, learned)
    out["model"] = model
    if model:
        ev.add("library model", True, f"{model} ({how})", "collection")
        conf += 0.05
    out["replaceable"] = replaceable(backend, g, slot, row, ad, info, learned)
    out["confidence"] = round(min(conf, 1.0), 2)
    # 4. static analysis of the roots that hold this entity / model (background, cached)
    if ram is not None and ent and inp.analyze != "never":
        _ghidra(ctx, ram, g, info, ent, learned, ev, force=inp.analyze == "always")
    # 5. learn
    if gid and ent and cls:
        rec = {"slot": slot, "model": model, "struct_size": _hex(info.get("struct_size")) if info.get("struct_size") else None,
               "seen": int(lcls.get("seen", 0)) + 1, "last": time.time()}
        for role, key in (("model", "model_ptr"), ("skeleton", "skeleton_ptr"), ("display_list", "display_list_ptr"),
                          ("vertex_buffer", "vertex_ptr")):
            b = (info.get("best") or {}).get(role)
            if b and len(b["path"]) <= 2:
                rec[key] = {"path": [_hex(o) for o in b["path"]], "kind": b["kind"]}
        L.record(ctx, gid, {"classes": {cls: {k: v for k, v in rec.items() if v is not None}}})
    out["seconds"] = round(time.time() - t0, 2)
    if gid and slot and inp.deep:                            # a hover (deep=false) never replaces a clicked pick
        sig = ((learned.get("assets") or {}).get(slot) or {}).get("signatures")
        save_pick(ctx, out, inp.session_id, signatures=sig, status="identified")
    return out


PICK_KEEP = ("entity", "game_id", "slot", "model", "ram", "confidence", "replaceable", "backend", "session_id", "title",
             "platform", "click", "slot_guess", "signatures", "replaced", "status")
RAM_DROP = ("structures", "texture_owners")              # walk listings: volatile, rebuilt by the next identify


def compact_pick(pick: dict, **extra) -> dict:
    """A pick result small and stable enough to keep (learned profile picks[slot] / last_pick, session live_pick) and
    hand back to pick_replace unchanged: identity, slot, replaceable, the RAM addresses + learned model signatures a
    live write needs, one-line evidence. Dropped: RAM / image bytes, per-draw lists, walk listings, timings."""
    def small(v, depth=0):
        if isinstance(v, (bytes, bytearray)):
            return None
        if isinstance(v, dict):
            return {k: s for k, x in v.items() if not str(k).startswith("_") and k not in ("rgba", "png", "image")
                    and (s := small(x, depth + 1)) is not None}
        if isinstance(v, (list, tuple)):
            return [s for x in list(v)[:32] if (s := small(x, depth + 1)) is not None]
        if isinstance(v, str):
            return v[:400]
        if hasattr(v, "tolist"):
            return v.tolist()
        return v
    out = {k: small(pick[k]) for k in PICK_KEEP if k in pick and pick[k] is not None}
    out["ram"] = {k: v for k, v in (out.get("ram") or {}).items() if k not in RAM_DROP}
    out["evidence"] = [{k: str(e.get(k))[:200] if k == "detail" else e.get(k) for k in ("step", "ok", "detail", "source")}
                       for e in (pick.get("evidence") or [])[:24] if isinstance(e, dict)]
    out.update({k: small(v) for k, v in extra.items() if v is not None})
    out["saved"] = time.time()
    return out


def save_pick(ctx, pick: dict, session_id: str | None = None, **extra) -> dict | None:
    """Keep a pick for later tools: learned profile picks[slot] + last_pick (replaced whole, not merged) and the
    session's live_pick. Best effort; -> the saved pick."""
    gid, slot = pick.get("game_id"), pick.get("slot")
    if not gid or not slot:
        return None
    c = compact_pick(pick, **extra)
    if session_id:
        c["session_id"] = session_id
    try:
        L.record(ctx, gid, {"picks": {slot: None}, "last_pick": None})       # replace, never merge into an older pick
        L.record(ctx, gid, {"picks": {slot: c}, "last_pick": c})
    except Exception:                                        # noqa: BLE001
        pass
    sid = c.get("session_id")
    if sid and getattr(ctx, "server", None):
        try:
            _api(ctx, "POST", f"/api/sessions/{sid}/live-pick", json=c, timeout=10)
        except Exception:                                    # noqa: BLE001 - an ended session keeps nothing
            pass
    return c


def _pause(ad) -> bool:
    """Pause for a consistent snapshot unless the operator already paused. -> whether we paused."""
    try:
        if (ad.query_runtime() or {}).get("state") == "PAUSED":
            return False
    except Exception:                                        # noqa: BLE001
        pass
    try:
        ad.pause()
        return True
    except Exception:                                        # noqa: BLE001
        return False


def _ghidra(ctx, ram: R.Ram, g: dict, info: dict, ent: dict, learned: dict, ev: Evidence, force: bool = False):
    roots: dict[int, str] = {}
    prof = info.get("profile") or {}
    ents = prof.get("entities") or {}
    for k in ("table", "base_pointer", "base_pointer_alt"):
        if (a := _int(ents.get(k))) is not None:
            roots[a] = f"profile entities.{k}"
    if (a := _int(prof.get("players_table"))) is not None:
        roots[a] = "profile players_table"
    sr = static_range(ram, g)
    ptr = _int(ent.get("ptr"))
    if sr and ptr is not None:
        for chain in R.back_chains(ram, ptr, depth=2, limit=6):
            for link in chain:
                if sr[0] <= link["at"] < sr[1]:
                    roots.setdefault(link["at"], "static word pointing at the entity")
    if not roots:
        ev.add("ghidra", False, "no static root (table / global) leads to this entity: nothing to look up", "gbox.pick_tool")
        return
    known = learned.get("ghidra") or {}
    todo = {a: why for a, why in roots.items() if force or _hex(a) not in known}
    for a in roots:
        if _hex(a) in known and not force:
            k = known[_hex(a)]
            ev.add("ghidra (cached)", True, f"{_hex(a)} ({roots[a]}): " + ", ".join(
                f"{f.get('name')} @ {f.get('entry')}" for f in (k.get("functions") or [])[:4]), "gbox.pick_learn")
    if not todo:
        return
    if not getattr(ctx, "server", None):
        ev.add("ghidra", False, "no control plane: analysis not queued", "gbox.pick_tool")
        return
    try:
        sha = _upload(ctx, f"ram_{g.get('game_id')}.bin.gz", gzip.compress(ram.data, 6))
        j = _start(ctx, "pick_ghidra", {"game_id": g.get("game_id"), "platform": ram.platform, "ram": sha,
                                         "base": ram.base, "roots": [_hex(a) for a in todo],
                                         "labels": {_hex(a): w for a, w in todo.items()}})
        ev.add("ghidra", True, f"queued pick_ghidra job {j.get('id')} for {len(todo)} root(s) "
                               f"({', '.join(_hex(a) for a in list(todo)[:4])}): FindRefs + ExplainAddresses on the RAM "
                               "image; findings land in the learned profile", "pick_ghidra", job=j.get("id"))
        L.record(ctx, g.get("game_id"), {"ghidra": {_hex(a): {"queued": j.get("id"), "why": w, "at": time.time()}
                                                    for a, w in todo.items()}})
    except Exception as e:                                   # noqa: BLE001
        ev.add("ghidra", False, f"analysis not queued: {e}", "pick_ghidra")


@tool("pick_identify", "1.0", PickIdentifyIn, PickIdentifyOut, capabilities=["runtime", "memory", "analysis"],
      timeout_s=300, side_effects=["pauses the game briefly for the RAM snapshot (the operator's pause is kept)",
                                   "capture=true: RenderDoc frame capture", "records findings in the game's learned "
                                   "profile; may queue a pick_ghidra job"])
def pick_identify(inp: PickIdentifyIn, ctx):
    """Pick whip, step 1: what is under this point of the running game, down to RAM. -> entity (the game's own
    record), game_id, slot (the writer slot a collection character can replace), model (collection slug when known),
    ram (entity struct, model / node tree, display list, vertex buffer, skeleton, textures), evidence (every step,
    with its source: profile, oot_live, doa2_context, pointer walk, learned paths, Ghidra), confidence, replaceable
    {live, build, reason}. Runs on the worker hosting the session."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    if inp.analyze not in ("auto", "never", "always"):
        raise ValueError("analyze: auto | never | always")
    return identify(ad, g, inp, ctx)


# ---------------------------------------------------------------- prepare (control plane: the writer + the patch)

def base_image(ctx, game: dict, marker: dict) -> Path:
    from . import characters as C, filemods
    if not marker.get("image"):
        return filemods.base_dir(ctx.config, game["game_id"])
    plat = game.get("platform")
    if plat in ("dreamcast", "naomi"):
        return C._dc_gdi(ctx, game)
    if plat in ("gamecube", "wii"):
        return C._gc_iso(ctx, game)
    return C._rom(ctx, game)


def prepare(ctx, gid: str, character: str, slot: str, x=None, y=None, rebuild: bool = False, patch: bool = True,
            upload: bool = True) -> dict:
    """The game's writer builds the mod for (character, slot) - fitting events on this job - then the changed files
    become in-RAM images (gbox.live_inject) packed as a live patch artifact."""
    from . import characters as C, filemods
    game = C._api(ctx, "GET", f"/api/catalog/{gid}")
    ci = C.CharIn(op="use", character=character, game_id=gid, slot=slot or "player", launch=False, rebuild=rebuild,
                  x=x, y=y)
    res = C.characters_recorded(ci, ctx)["result"]
    mod = res.get("mod")
    out = {"status": res.get("status"), "mod": mod, "writer": {k: res.get(k) for k in ("status", "mod", "replaces",
                                                                                       "message", "notes") if res.get(k)}}
    if not mod or res.get("status") in ("missing", "failed", "not_in_collection", "unsupported_live_swap"):
        out["reason"] = res.get("message") or res.get("error") or f"the writer built no mod ({res.get('status')})"
        out["mod"] = None
        return out
    if not patch:
        return out
    try:
        d = filemods.mod_dir(ctx.config, gid, mod)
        marker = json.loads((d / ".gbox-mod.json").read_text(encoding="utf-8"))
        pairs, _m = LI.mod_files(d, base_image(ctx, game, marker))
        assets, notes = LI.assets_from_files(pairs, game.get("platform") in R.BIG_ENDIAN)
        if not assets:
            raise LI.Unplaceable("the mod changes no model data the game keeps in RAM" + (f" ({'; '.join(notes)})" if notes else ""))
        blob = LI.pack(assets, {"game_id": gid, "mod": mod, "slot": slot, "character": character,
                                "platform": game.get("platform")})
        out |= {"assets": [{"name": a["name"], "orig_bytes": len(a["orig"]), "new_bytes": len(a["new"]),
                            "whole": a["whole"], "note": a.get("note", "")} for a in assets],
                "notes": notes, "signatures": LI.signatures(assets)}
        if upload and getattr(ctx, "server", None):
            out["patch"] = _upload(ctx, "live_patch.json.gz", blob)
        else:
            out["patch_blob"] = blob
    except LI.Unplaceable as e:
        out["live_reason"] = str(e)
    except Exception as e:                                   # noqa: BLE001
        out["live_reason"] = f"the live patch couldn't be made: {type(e).__name__}: {e}"
    return out


class PickPrepareIn(BaseModel):
    game_id: str
    character: str
    slot: str = "player"
    x: float | None = None
    y: float | None = None
    rebuild: bool = False
    patch: bool = True


class PickPrepareOut(BaseModel):
    result: dict


def _collection_check(cfg) -> str | None:
    return None if _collection_here(cfg) else "the character collection lives on the control-plane node"


@tool("pick_prepare", "1.0", PickPrepareIn, PickPrepareOut, capabilities=["mod", "asset"], permissions=[P.EXECUTE],
      timeout_s=14400, check=_collection_check, artifacts=["live_patch.json.gz"],
      side_effects=["builds the writer's mod under cache/mods (characters op=use launch=false)",
                    "uploads the live patch (in-RAM images of the changed model files)"])
def pick_prepare(inp: PickPrepareIn, ctx):
    """pick_replace's control-plane half: the game's swap writer fits + encodes the character for the slot (fit
    events), and the files it changed become a live patch the session's worker injects into RAM."""
    return {"result": prepare(ctx, inp.game_id, inp.character, inp.slot, inp.x, inp.y, inp.rebuild, inp.patch)}


# ---------------------------------------------------------------- replace

class PickReplaceIn(BaseModel):
    session_id: str
    pick: dict                                     # the pick_identify result
    character: str                                 # collection slug (or name)
    mode: str = "live"                             # live | build
    fallback: bool = True                          # live not possible -> build (session swap)
    rebuild: bool = False
    refresh_ram: bool = True                       # build: inject the new model into the swapped session's RAM too
    revert_on_fail: bool = True                    # live: a black / frozen picture after the write restores RAM
    allow_arena: bool = False                      # live: models larger than their footprint may use learned arenas


class PickReplaceOut(BaseModel):
    result: dict


def _character(ctx, q: str) -> dict:
    from .characters import best_match, find
    chars = _api(ctx, "GET", "/api/characters")
    m = next((c for c in chars if c.get("slug") == q), None) or best_match(chars, q) or find(chars, q)
    if not m:
        raise ValueError(f"{q!r} isn't in the collection")
    return m


def _wait(ctx, job: dict, limit: float) -> dict:
    t0 = time.time()
    while job.get("state") in ("queued", "running") and time.time() - t0 < limit:
        time.sleep(JOB_POLL_S)
        job = _api(ctx, "GET", f"/api/jobs/{job['id']}")
    return job


def _sub(ctx, tool_name: str, inp: dict, limit: float, worker: str | None, pct=(5.0, 85.0)) -> dict:
    j = _start(ctx, tool_name, inp, worker)
    return relay(ctx, j, limit, pct)


def get_prepared(ctx, gid, meta, slot, pick, rebuild: bool, patch: bool = True) -> dict:
    x = y = None                                           # writers resolve the slot by name (OoT: the actor name)
    if _collection_here(ctx.config):
        return prepare(ctx, gid, meta["slug"], slot, x, y, rebuild, patch)
    cp = _control_plane(ctx, "pick_prepare")
    if not cp:
        return {"mod": None, "reason": "the control-plane worker (character collection) is offline"}
    j = _sub(ctx, "pick_prepare", {"game_id": gid, "character": meta["slug"], "slot": slot, "x": x, "y": y,
                                   "rebuild": rebuild, "patch": patch}, 14000, cp)
    if j.get("state") != "succeeded":
        return {"mod": None, "reason": f"pick_prepare {j.get('state')}: {j.get('error')}", "job": j.get("id")}
    return ((j.get("output") or {}).get("result") or {}) | {"job": j.get("id")}


def _patch_assets(ctx, prepared: dict) -> list[dict]:
    blob = prepared.get("patch_blob")
    if blob is None and prepared.get("patch"):
        blob = _api(ctx, "GET", f"/api/artifacts/{prepared['patch']}", timeout=300)
    if not blob:
        return []
    assets, _meta = LI.unpack(blob)
    return assets


def inject(ad, g: dict, assets: list[dict], hint: int | None, arenas, ctx, revert_on_fail: bool = True) -> dict:
    """Snapshot -> plan -> paused verified write (+ frame check). -> {ok, plan, apply | reason}."""
    plat = g.get("platform") or ""
    paused = _pause(ad)                                    # snapshot, plan and write in one paused moment
    keep_paused = False
    try:
        ram = R.Ram.snapshot(ad, plat)
        pl = LI.plan(ram, assets, hint, arenas)
        res = {"plan": {k: pl[k] for k in ("assets", "reason")} | {"writes": len(pl["writes"]),
                                                                   "bytes": sum(len(w["data"]) for w in pl["writes"])}}
        if not pl["ok"]:
            return res | {"ok": False, "reason": pl["reason"] or "nothing placeable"}
        try:
            rep = LI.apply(ad, ram, pl["writes"], progress=lambda d, t: ctx.progress(
                88 + 8 * d / max(t, 1), f"Writing the model into RAM ({d}/{t} bytes)"))
        except RuntimeError as e:
            keep_paused = "left paused" in str(e)            # an unverified rollback is never resumed
            raise
    finally:
        if paused and not keep_paused:
            try:
                ad.resume()
            except Exception:                                # noqa: BLE001
                pass
    rep["pause_preserved"] = (LI._state(ad) == "PAUSED") == (not paused) if LI._state(ad) else True
    if paused and callable(getattr(ad, "get_frame", None)):  # the game was running: it must still draw + animate
        time.sleep(0.6)
        try:
            from .live_link import _frames
            fc = _frames(ad, ctx)
        except Exception as e:                               # noqa: BLE001
            fc = {"ok": True, "skipped": str(e)}
        rep["frame_check"] = fc
        if not fc.get("ok") and revert_on_fail:
            rep["reverted"] = LI.revert(ad, ram, pl["writes"])
    res["apply"] = rep
    res["ok"] = bool(rep.get("verified")) and not rep.get("reverted")
    if not res["ok"]:
        res["reason"] = rep.get("error") or ("the frame check failed after the write (black / frozen picture); RAM was "
                                             "restored" if rep.get("reverted") else "not verified")
    return res


def live(ctx, inp: PickReplaceIn, pick: dict, meta: dict, key: str, label: str, ad, g) -> dict:
    backend, slot, sid = pick.get("backend") or "profile", pick.get("slot"), inp.session_id
    gid = pick.get("game_id") or g.get("game_id")
    rp = pick.get("replaceable") or {}
    if backend == "oot":
        if slot == "player":
            return {"ok": False, "method": "oot", "reason": "Link has no live writer (bounded NPC objects only)"}
        x, y = (pick.get("click") or [None, None])[:2]
        args = {"op": "live_use", "character": meta["slug"], "session_id": sid, "game_id": gid, "x": x, "y": y}
        if _collection_here(ctx.config):
            from .characters import CharIn, characters_tool
            r = characters_tool(CharIn(**args), ctx)["result"]
        else:
            j = _sub(ctx, "characters", args, 3600, _control_plane(ctx, "characters"))
            r = (j.get("output") or {}).get("result") or {"status": j.get("state"), "message": j.get("error")}
        return {"ok": r.get("status") == "live_swapped", "method": "oot_hot_swap (characters op=live_use)", "result": r,
                "reason": None if r.get("status") == "live_swapped" else r.get("message")}
    if backend == "sm64":
        args = {"op": "push", "character": meta["slug"], "target": sid, "method": "hotswap",
                "revert_on_fail": inp.revert_on_fail}
        if _collection_here(ctx.config):
            from .live_link import LiveIn, live_link
            r = live_link(LiveIn(**args), ctx)["result"]
        else:
            j = _sub(ctx, "live_link", args, 3600, _control_plane(ctx, "live_link"))
            r = (j.get("output") or {}).get("result") or {"status": j.get("state"), "message": j.get("error")}
        return {"ok": r.get("status") == "live", "method": "live_link hot swap (SM64 RDRAM)", "result": r,
                "reason": None if r.get("status") == "live" else r.get("message")}
    if not rp.get("live"):
        return {"ok": False, "method": "none", "reason": rp.get("reason") or "live replacement isn't available here"}
    prepared = get_prepared(ctx, gid, meta, slot, pick, inp.rebuild, True)
    out = {"ok": False, "method": "live_inject (writer images in RAM)", "prepared": prepared}
    if not prepared.get("mod"):
        return out | {"reason": prepared.get("reason") or "the writer built nothing"}
    assets = _patch_assets(ctx, prepared)
    if not assets:
        return out | {"reason": prepared.get("live_reason") or "no in-RAM images in the build"}
    learned = L.load(ctx, gid)
    arenas = [tuple(_int(v) for v in a) for a in (learned.get("arenas") or [])] if inp.allow_arena else []
    FE.model(key, label, meta["slug"])
    FE.stage("write", "running", {"target": "RAM", "assets": len(assets)}, text="locating the model in RAM")
    ctx.progress(86, "Locating the model in the running game's RAM")
    try:
        r = inject(ad, g, assets, _int((pick.get("ram") or {}).get("model")), arenas, ctx, inp.revert_on_fail)
    except Exception as e:                                   # noqa: BLE001
        r = {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    FE.stage("write", "done" if r.get("ok") else "failed",
             {"target": "RAM", **({"bytes": (r.get("apply") or {}).get("bytes"), "writes": (r.get("apply") or {}).get("writes")}
                                  if r.get("apply") else {}), "reason": r.get("reason")})
    out |= r
    L.record(ctx, gid, {"replace": {slot: {"live_ok": bool(r.get("ok")), "method": out["method"], "mod": prepared["mod"],
                                           "reason": r.get("reason"), "at": time.time()}},
                        **({"assets": {slot: {"signatures": prepared.get("signatures"), "mod": prepared["mod"],
                                              "at": time.time()}}} if prepared.get("signatures") else {})})
    return out


def build(ctx, inp: PickReplaceIn, pick: dict, meta: dict, key: str, label: str, g, prepared: dict | None) -> dict:
    from .tools import SESSIONS
    gid, slot, sid = pick.get("game_id") or g.get("game_id"), pick.get("slot"), inp.session_id
    if not prepared or not prepared.get("mod"):
        prepared = get_prepared(ctx, gid, meta, slot, pick, inp.rebuild, inp.refresh_ram)
    out = {"prepared": {k: v for k, v in prepared.items() if k != "patch_blob"}}
    if not prepared.get("mod"):
        return out | {"ok": False, "reason": prepared.get("reason") or "the writer built no mod"}
    ctx.progress(88, f"Swapping the session to {prepared['mod']} at the same moment")
    try:
        j = _api(ctx, "POST", f"/api/sessions/{sid}/swap", json={"mod": prepared["mod"], "keep_state": True})
    except Exception as e:                                   # noqa: BLE001 - e.g. 409: a replacement is already running
        detail = getattr(getattr(e, "response", None), "text", "") or str(e)
        FE.stage("write", "failed", {"target": "session swap", "error": detail[:160]})
        return out | {"ok": False, "reason": f"the session swap was refused: {detail[:300]}"}
    j = _wait(ctx, j, 1800)
    sw = j.get("output") or {}
    out["swap"] = {"job": j.get("id"), "state": j.get("state"), "error": j.get("error"),
                   **{k: sw.get(k) for k in ("session_id", "state_loaded", "load_verified", "notes")}}
    if j.get("state") != "succeeded":
        FE.stage("write", "failed", {"target": "session swap", "error": j.get("error")})
        return out | {"ok": False, "reason": f"session swap {j.get('state')}: {j.get('error')}"}
    nsid = sw.get("session_id")
    FE.model(key, label, meta["slug"])
    FE.stage("write", "done", {"target": "session swap", "mod": prepared["mod"], "session": nsid})
    out |= {"ok": True, "session_id": nsid}
    if inp.refresh_ram and nsid:
        assets = []
        try:
            assets = _patch_assets(ctx, prepared)
        except Exception as e:                               # noqa: BLE001
            out["ram_refresh"] = {"ok": False, "reason": f"patch unavailable: {e}"}
        if assets and nsid in SESSIONS:
            nad, ng = SESSIONS[nsid]
            time.sleep(2.0)
            try:
                out["ram_refresh"] = inject(nad, ng, assets, None, [], ctx, inp.revert_on_fail)
            except Exception as e:                           # noqa: BLE001
                out["ram_refresh"] = {"ok": False, "reason": f"{type(e).__name__}: {e}"}
        elif assets:
            out["ram_refresh"] = {"ok": False, "reason": "the new session runs on another worker: the model appears "
                                                         "at the next load of that character"}
        elif "ram_refresh" not in out:
            out["ram_refresh"] = {"ok": False, "reason": prepared.get("live_reason") or "no in-RAM images in the build"}
    return out


def replace(inp: PickReplaceIn, ctx) -> dict:
    from .tools import SESSIONS
    if inp.mode not in ("live", "build"):
        raise ValueError("mode: live | build")
    pick = inp.pick or {}
    ad, g = SESSIONS[inp.session_id]
    gid = pick.get("game_id") or g.get("game_id")
    if pick.get("game_id") and g.get("game_id") and pick["game_id"] != g["game_id"]:
        raise ValueError("the pick was made in another game than this session runs")
    slot = pick.get("slot")
    res = {"character": inp.character, "game_id": gid, "slot": slot, "mode": inp.mode, "session_id": inp.session_id}
    if not slot:
        return res | {"status": "not_replaceable", "message": "the pick isn't mapped to a writer slot: "
                                                              + str((pick.get("replaceable") or {}).get("reason") or "")}
    meta = _character(ctx, inp.character)
    key = slot
    label = f"{meta['name']} -> {g.get('title') or gid} ({slot})"
    FE.plan([(key, meta["slug"], label)])
    FE.default_model(key, label, meta["slug"])
    res |= {"character": meta["name"], "slug": meta["slug"]}
    prepared = None
    if inp.mode == "live":
        lv = live(ctx, inp, pick, meta, key, label, ad, g)
        prepared = lv.get("prepared")
        res["live"] = {k: v for k, v in lv.items() if k != "prepared"}
        if lv.get("ok"):
            res |= {"status": "live", "mode_used": "live", "message": f"{meta['name']} replaces {slot} in the "
                    f"running game ({lv.get('method')}); same session, same moment"}
            keep_pick(ctx, pick, res, prepared, lv)
            return res
        if not inp.fallback:
            return res | {"status": "live_failed", "mode_used": "live", "message": f"live replacement not possible: "
                          f"{lv.get('reason')}"}
        res["fell_back"] = True
        res["fallback_reason"] = lv.get("reason")
        ctx.progress(60, f"Live replacement not possible ({str(lv.get('reason'))[:120]}): building + session swap")
    bd = build(ctx, inp, pick, meta, key, label, g, prepared)
    res["build"] = bd
    if not bd.get("ok"):
        return res | {"status": "failed", "mode_used": "build", "message": bd.get("reason")}
    rr = bd.get("ram_refresh") or {}
    res |= {"status": "swapped", "mode_used": "build", "session_id": bd.get("session_id"),
            "message": f"{meta['name']} is in {bd['prepared'].get('mod')}; the session was swapped at the same "
                       "moment" + ("; the loaded model was refreshed in RAM" if rr.get("ok") else
                                   f"; RAM refresh: {rr.get('reason')}" if rr else "")}
    keep_pick(ctx, pick, res, bd.get("prepared") or prepared, rr)
    return res


def keep_pick(ctx, pick: dict, res: dict, prepared: dict | None, applied: dict | None) -> dict | None:
    """After a replace that put the character in (live / swapped): the pick as it now stands, saved for later tools
    (learned picks[slot] / last_pick, the session's live_pick - the new session after a swap). The RAM addresses the
    write used and the writer's model signatures go with it, so a later pick_replace (the Blender round trip) can
    locate the model again."""
    p = dict(pick)
    ram = dict(p.get("ram") or {})
    inst = [{"name": a["name"], "base": i["base"], "bytes": a.get("new_bytes")}
            for a in ((applied or {}).get("plan") or {}).get("assets") or [] for i in a.get("instances") or []]
    if inst:
        ram["model_images"] = inst
        ram.setdefault("model", inst[0]["base"])
    p["ram"] = ram                                          # a swap restores the same state: same addresses
    sig = (prepared or {}).get("signatures")
    replaced = {"character": res.get("character"), "slug": res.get("slug"), "status": res.get("status"),
                "mode_used": res.get("mode_used"), "mod": (prepared or {}).get("mod"), "at": time.time()}
    return save_pick(ctx, p, res.get("session_id"), signatures=sig or pick.get("signatures"), replaced=replaced,
                     status=res.get("status"))


@tool("pick_replace", "1.0", PickReplaceIn, PickReplaceOut, capabilities=["mod", "runtime", "memory"],
      permissions=[P.EXECUTE, P.MEMORY_WRITE], timeout_s=14400,
      side_effects=["live: writes the fitted model into the running game's RAM (paused, verified, restored on "
                    "failure)", "build: builds the writer's mod and swaps the session to it at the same moment",
                    "records the outcome in the game's learned profile"])
def pick_replace(inp: PickReplaceIn, ctx):
    """Pick whip, step 2: put a collection character where pick_identify pointed. mode=live writes the fitted model
    into the running game's RAM (OoT NPCs, SM64 Mario, and every writer whose rebuilt files sit in RAM as loaded);
    mode=build (and live's fallback) builds the writer's mod and swaps the session to it keeping the moment. Emits
    fit events for the slot (Fitting pop-up). Runs on the worker hosting the session."""
    return {"result": replace(inp, ctx)}


# ---------------------------------------------------------------- Ghidra (background, on a node that has it)

class PickGhidraIn(BaseModel):
    game_id: str
    platform: str
    ram: str                                       # artifact sha256 of the gzip'd RAM image
    base: int
    roots: list[str]                               # static addresses (hex) whose code references are wanted
    labels: dict = {}
    explain: bool = True


class PickGhidraOut(BaseModel):
    result: dict


def _ghidra_check(cfg):
    from .tools import _ghidra_check as chk
    return chk(cfg)


def run_ghidra(ctx, inp: PickGhidraIn) -> dict:
    import shutil
    import subprocess
    import tempfile
    from .re_lab_tool import PLATFORM_CPU, analysis_root, ram_to_image
    from .tools import ROOT, _ghidra_env, _ghidra_exe
    blob = _api(ctx, "GET", f"/api/artifacts/{inp.ram}", timeout=600)
    data = gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob
    elf, _info = ram_to_image(inp.platform, data, inp.base)
    proc = PLATFORM_CPU.get(inp.platform, (None, None))[1]
    d = analysis_root(ctx.config) / "re" / inp.game_id
    d.mkdir(parents=True, exist_ok=True)
    name = f"ram_pick_{int(time.time())}.elf"
    (d / name).write_bytes(elf)
    work = Path(tempfile.mkdtemp())
    gh = str(_ghidra_exe(ctx.config))
    scripts = str(ROOT / "adapters" / "ghidra")
    refs_out, ex_out = work / "refs.json", work / "explain.json"
    try:
        ctx.progress(10, f"Ghidra: importing + analysing the RAM image ({len(data) >> 20} MiB)")
        cmd = [gh, str(work), "pick", "-import", str(d / name), "-scriptPath", scripts, "-postScript", "FindRefs.java",
               str(refs_out), *[r.removeprefix("0x").removeprefix("0X") for r in inp.roots]]
        if proc:
            cmd += ["-processor", proc]
        r = subprocess.run(cmd, timeout=3300, capture_output=True, text=True, env=_ghidra_env(ctx.config))
        if r.returncode or not refs_out.exists():
            raise RuntimeError(f"ghidra FindRefs failed ({r.returncode}): {(r.stdout + r.stderr)[-800:]}")
        targets = json.loads(refs_out.read_text())["targets"]
        funcs = {}
        for t in targets:
            for ref in t.get("refs") or []:
                if ref.get("entry"):
                    funcs.setdefault(ref["entry"], {"name": ref.get("function"), "entry": ref["entry"], "roots": set()})
                    funcs[ref["entry"]]["roots"].add(t["addr"])
        explained = []
        if inp.explain and funcs:
            ctx.progress(70, f"Ghidra: decompiling {min(len(funcs), 12)} referencing function(s)")
            cmd = [gh, str(work), "pick", "-process", name, "-noanalysis", "-scriptPath", scripts, "-postScript",
                   "ExplainAddresses.java", str(ex_out), *[e.removeprefix("0x") for e in list(funcs)[:12]]]
            r2 = subprocess.run(cmd, timeout=1800, capture_output=True, text=True, env=_ghidra_env(ctx.config))
            if not r2.returncode and ex_out.exists():
                for a in json.loads(ex_out.read_text()).get("addresses", []):
                    explained.append({"function": a.get("function"), "entry": a.get("entry"),
                                      "callers": (a.get("callers") or [])[:6],
                                      "decompiled": (a.get("decompiled") or "").strip()[:1200]})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    per_root = {}
    for t in targets:
        key = "0x" + t["addr"].upper()
        per_root[key] = {"why": inp.labels.get(key) or inp.labels.get(key.lower()),
                         "refs": [{k: ref.get(k) for k in ("from", "function", "entry", "type")} for ref in (t.get("refs") or [])[:24]],
                         "functions": [{"name": f["name"], "entry": f["entry"]} for f in funcs.values()
                                       if t["addr"] in f["roots"]][:12], "job": ctx.job_id, "at": time.time()}
    result = {"elf": f"re/{inp.game_id}/{name}", "roots": per_root, "explained": explained}
    raw = json.dumps(result, default=list).encode()
    ctx.artifact("pick_ghidra.json", raw, "application/json", game_id=inp.game_id)
    L.record(ctx, inp.game_id, {"ghidra": per_root})
    try:                                                     # hypotheses in the knowledge graph (runtime-promoted later)
        sha = _upload(ctx, "pick_ghidra.json", raw, "application/json")
        for root, v in per_root.items():
            for f in v["functions"][:6]:
                _api(ctx, "POST", "/api/knowledge", json={
                    "game_id": inp.game_id, "src": f"RAM {root} ({v.get('why') or 'static root'})", "rel": "referenced_by",
                    "dst": f"{f['name']} @ 0x{str(f['entry']).upper()}", "confidence": 0.5, "status": "hypothesis",
                    "evidence": [sha], "source": "gbox.pick_tool.pick_ghidra"})
    except Exception:                                        # noqa: BLE001
        pass
    return result


@tool("pick_ghidra", "1.0", PickGhidraIn, PickGhidraOut, capabilities=["analysis", "ghidra"], timeout_s=3600,
      check=_ghidra_check, artifacts=["pick_ghidra.json"],
      side_effects=["writes <data_dir>/analysis/re/<game_id>/ram_pick_*.elf", "records findings in the learned profile "
                    "and hypothesis edges in the knowledge graph"])
def pick_ghidra(inp: PickGhidraIn, ctx):
    """pick_identify's static step: the RAM image as an ELF in Ghidra, the code that references the static roots
    holding a picked entity / model (FindRefs) and those functions decompiled (ExplainAddresses): the loader /
    renderer that owns the model. Findings are cached in the game's learned profile."""
    return {"result": run_ghidra(ctx, inp)}

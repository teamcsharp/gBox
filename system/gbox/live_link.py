"""Blender Live Link, game side: a variant re-sent from Blender appears in the RUNNING game without the operator doing
anything (`live_link op=push`, started by the gBox add-on on Ctrl+S / Push).

push (control-plane node, where the collection lives):
  target      target=<session> | game_id=<game> | neither: the running session (newest) whose current model belongs to
              the character's family (itself, its original, the original's other variants: their built mods'
              names vs the session's live_mod / mod, or the character the pick whip put there) - so a save in
              Blender updates whichever game shows that character now; none -> "stored" (nothing to reload)
  live inject when a worker registers `pick_replace` (gbox.pick_tool, docs/live-inject.md), it runs first on the
              session's worker: mode "live", fallback (build + session swap), with the pick that put the character
              there when one was recorded (the session's live_pick / pick / last_pick, the learned profile's
              picks[slot] / last_pick) else a slot-only pick (slot_pick). status live | swapped = done; a failed
              build there ends the push; not_replaceable / refused -> the rebuild below
  building    the game's swap writer rebuilds the variant's mod (SM64: sm64_<slug>; RE4 GC: re4_<slug>); the previous
              build is kept as <mod>.prev until the new one is live. Every other writer: characters op=use
              rebuild=true launch=false for the slot (generic_push), then the session swap below
  validating  deterministic checks of the built files (no guessing), any blocking failure stops here with the reason:
              skeleton (joint count / order / offsets) unchanged, model-data budget, texture limits, culling radius still
              covers the model, hit boxes independent of the mesh (documented per writer; flags visual-only overhang)
  reloading   SM64 on RetroArch: hot swap = the new model data, geo layout and display-list pointers are written straight
              into the running game's RDRAM (paused for the write): same moment, no relaunch, ~seconds.
              Others: save state -> relaunch with the new mod -> load the state (RE4 GC keeps the model it already loaded
              in RAM until the next area load: the state brings the old one back; walk through a door). Other writers:
              POST /api/sessions/{sid}/swap {mod, keep_state} (session_swap: same PC, same moment).
              Attachments (gbox.attachments) report kept / simplified / dropped for the game's budget.
  live        a frame check (picture not black, game still animating) confirms it; otherwise the previous build is put
              back (RAM and mod files) and the push reports "reverted".
hotswap (runs on the session's worker): applies one prepared patch to the emulator's memory and checks frames.

Hit boxes: SM64 - Mario's collision is fixed in code/behaviour data (bhvMario SET_HITBOX radius 37, height 160; wall/floor/
ceiling radii are constants in mario_step.c): no mesh data is involved, so a model or head-size change is visual only.
RE4 GC - the pl00/08/09/10 model packs gBox rewrites hold bones, vertices, materials and textures only; Leon's collision
and hit detection come from the game code and room data, so a swap/head scale is visual only (not verified in game).
"""
from __future__ import annotations

import base64
import json
import shutil
import struct
import time
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from .models import Permission as P
from .registry import tool

MARIO_HITBOX = {"radius": 37, "height": 160}               # bhvMario SET_HITBOX (code-side, not the mesh)
DEFAULT_CULL = 300                                         # SM64 obj_is_in_view without a culling-radius geo node


# ---------------------------------------------------------------- validation (deterministic)

def _check(name, ok, detail, blocking=True):
    return {"check": name, "ok": bool(ok), "blocking": blocking, "detail": detail}


def _geo_nodes(tree):
    yield tree
    for c in tree.get("children", []):
        yield from _geo_nodes(c)


def sm64_shape(rom: bytes) -> dict:
    """Mario as the ROM draws him (idle pose 197): joints, triangle count, textures, world-space extents (geo scale
    applied) and the culling radius the object uses."""
    from . import sm64_mario as sm
    model = sm.extract(rom, 197)
    tree = sm.geo_tree(sm.Mem(rom), sm.MARIO_GEO)
    scale = 1.0
    cull = None
    for n in _geo_nodes(tree):
        if n.get("cmd") == 0x1D:
            scale *= struct.unpack_from(">I", n["raw"], 4)[0] / 65536.0
        elif n.get("cmd") == 0x20:
            cull = struct.unpack_from(">h", n["raw"], 2)[0]
    pts = []
    for jt in model["joints"]:
        for _key, tri in jt["tris"]:
            for p, _c, _uv in tri:
                pts.append((np.r_[np.asarray(p, float), 1.0] @ jt["world"])[:3])
    pts = np.array(pts) * scale if pts else np.zeros((1, 3))
    pts[:, 1] -= pts[:, 1].min()                           # the object's origin is at his feet
    return {"joints": [(jt["parent"], tuple(int(v) for v in jt["t"])) for jt in model["joints"]],
            "triangles": sum(len(jt["tris"]) for jt in model["joints"]),
            "textures": [{"w": k[3], "h": k[4], "fmt": k[1], "siz": k[2]} for k in model["textures"]],
            "radius": float(np.linalg.norm(pts, axis=1).max()), "height": float(np.ptp(pts[:, 1])),
            "top": float(pts[:, 1].max()), "geo_scale": scale, "cull": cull or DEFAULT_CULL, "cull_node": cull is not None}


def validate_sm64(new_rom: bytes, vanilla_rom: bytes, report: dict) -> list[dict]:
    from . import sm64_writer as W
    a, b = sm64_shape(vanilla_rom), sm64_shape(new_rom)
    out = [_check("skeleton", a["joints"] == b["joints"],
                  f"{len(b['joints'])} joints, order and offsets {'unchanged' if a['joints'] == b['joints'] else 'CHANGED'} "
                  "(Mario's animations index them)"),
           _check("budget", report.get("bytes", 0) <= W.MARIO_END,
                  f"model data {report.get('bytes')} of {W.MARIO_END} bytes (Mario's own segment-04 data)"),
           _check("textures", all(t["w"] * t["h"] <= 2048 for t in b["textures"]),
                  f"{len(b['textures'])} textures, largest {max([t['w'] * t['h'] for t in b['textures']] or [0])} texels "
                  "(TMEM limit 2048 RGBA16 texels)"),
           _check("triangles", b["triangles"] > 0, f"{b['triangles']} triangles drawn (Mario: {a['triangles']})")]
    margin = b["radius"] * 1.25                            # animation poses reach further than the idle pose
    out.append(_check("culling radius", b["radius"] <= b["cull"],
                      f"model reaches {b['radius']:.0f} units from Mario's origin (idle; ~{margin:.0f} in motion), culling radius "
                      f"{b['cull']} ({'geo node' if b['cull_node'] else 'SM64 default, no culling node in his geo layout'}); "
                      f"vanilla Mario {a['radius']:.0f}" + ("" if margin <= b["cull"] else " - close to the limit: may pop at screen edges")))
    over = b["top"] > MARIO_HITBOX["height"] * 1.1
    out.append(_check("hit box", True,
                      f"collision is fixed in code (hitbox r{MARIO_HITBOX['radius']} h{MARIO_HITBOX['height']}, independent of the mesh): "
                      f"visual top {b['top']:.0f} vs hitbox {MARIO_HITBOX['height']}" +
                      (" - the model pokes above the hitbox: visual only, it can clip through low ceilings; gameplay unchanged"
                       if over else ", gameplay unchanged"), blocking=False))
    return out


def validate_re4(cfg, meta: dict, game: dict, build: dict) -> list[dict]:
    from . import filemods, re4gc_models as R
    from .gcdisc import GCDisc
    out = []
    packs = build.get("packs") or {}
    over = {k: v for k, v in packs.items() if v.get("bytes", 0) > v.get("disc_bytes", 0)}
    out.append(_check("budget", packs and not over, ", ".join(f"{Path(k).name} {v.get('bytes')}/{v.get('disc_bytes')} B"
                                                          for k, v in packs.items()) + " (disc-1 file slots)"))
    drs = Path(cfg.cache) / "characters_build" / meta["slug"] / "drs"
    base = next(filemods.base_dir(cfg, game["game_id"]).glob("*.iso"), None)
    try:
        disc = GCDisc(base)
        bad = []
        for name in packs:
            old = R.bin_read(R.ModelPack(disc.read(name)).items[0][1])
            new = R.bin_read(R.ModelPack((drs / Path(name).name).read_bytes()).items[0][1])
            if [b[:2] for b in old.bones] != [b[:2] for b in new.bones]:
                bad.append(Path(name).name)
        disc.f.close()
        out.append(_check("skeleton", not bad, "Leon's bone ids / parents unchanged in every pack" if not bad else f"changed in {bad}"))
    except Exception as e:                                 # noqa: BLE001 - a check that can't run blocks
        out.append(_check("skeleton", False, f"couldn't read the packs back: {type(e).__name__}: {e}"))
    out.append(_check("textures", True, "textures re-encoded <= 128 px CMPR by the writer (swap_packs max_tex)", blocking=False))
    out.append(_check("culling radius", True, "not checked: RE4 GC culls by room / camera, gBox knows no per-model radius",
                      blocking=False))
    out.append(_check("hit box", True, "player collision is code/room data, not in the model packs: visual only "
                      "(not verified in game)", blocking=False))
    return out


# ---------------------------------------------------------------- SM64 hot swap

def _dl_map(old_rom: bytes, new_rom: bytes) -> list[list[int]]:
    """Display-list pointers of Mario's geo layout, old build -> new build (same tree: the writer patches in place)."""
    from . import sm64_mario as sm
    a = [n for n in _geo_nodes(sm.geo_tree(sm.Mem(old_rom), sm.MARIO_GEO)) if "dl" in n]
    b = [n for n in _geo_nodes(sm.geo_tree(sm.Mem(new_rom), sm.MARIO_GEO)) if "dl" in n]
    if len(a) != len(b):
        raise ValueError("geo layouts differ in shape: can't hot swap")
    m = {}
    for x, y in zip(a, b):
        if x["dl"] and x["dl"] != y["dl"] and (x["dl"] not in m or not m[x["dl"]]):
            m[x["dl"]] = y["dl"]
    return [[k, v] for k, v in m.items()]


def sm64_patch(old_rom: bytes, new_rom: bytes) -> dict:
    from . import sm64_mario as sm, sm64_writer as W
    o4, n4 = sm.Mem(old_rom).seg[0x04][:W.MARIO_END], sm.Mem(new_rom).seg[0x04][:W.MARIO_END]
    o17, n17 = old_rom[sm.SEG17[0]:sm.SEG17[1]], new_rom[sm.SEG17[0]:sm.SEG17[1]]
    e = lambda b: base64.b64encode(b).decode()             # noqa: E731
    return {"seg4_old": e(o4), "seg4_new": e(n4), "seg17_old": e(o17), "seg17_new": e(n17), "dl_map": _dl_map(old_rom, new_rom)}


def _swap32(b: bytes) -> bytes:
    return np.frombuffer(b[:len(b) // 4 * 4], ">u4").astype("<u4").tobytes()


def _frames(ad, ctx, n=2, gap=0.8) -> dict:
    from .tools import mean_luma
    fs = []
    for k in range(n):
        if k:
            time.sleep(gap)
        fs.append(ad.get_frame())
    luma = mean_luma(fs[-1])
    for i, f in enumerate(fs):
        ctx.artifact(f"frame{i}.png", f, "image/png", note="live_link frame check")
    from .store import sha256
    alive = len({sha256(f) for f in fs}) > 1
    return {"luma": luma, "animating": alive, "frames": [sha256(f) for f in fs],
            "ok": alive and (luma is None or luma > 3)}


def apply_hotswap(ad, pt: dict, ctx, revert_on_fail=True) -> dict:
    t0 = time.time()
    d = lambda k: base64.b64decode(pt[k])                  # noqa: E731
    o4, n4, o17, n17 = d("seg4_old"), d("seg4_new"), d("seg17_old"), d("seg17_new")
    RAM, SIZE = 0x80000000, 0x800000
    ram = ad.read_memory(RAM, SIZE)
    t_read = time.time() - t0
    order = None
    for name, conv in (("be", lambda b: b), ("le32", _swap32)):
        # Different builds share the first vertices/padding. A prefix match can
        # overwrite a model loaded from a different save state; require the
        # complete previous segment before changing any live memory.
        i4 = ram.find(conv(o4))
        if i4 >= 0 and i4 % 4 == 0:
            order, cv = name, conv
            break
    if order is None:
        if ram.find(n4) >= 0 or ram.find(_swap32(n4)) >= 0:
            return {"ok": True, "already": True, "message": "the new model is already in the game's memory"}
        raise RuntimeError("Mario's current model data isn't in the game's RAM where the previous build put it "
                           "(the session runs a different build): relaunch it with the mod instead")
    i17 = ram.find(cv(o17[:1024]))
    words = np.frombuffer(ram, ">u4" if order == "be" else "<u4")
    skip = [(i4, i4 + len(o4))] + ([(i17, i17 + len(o17))] if i17 >= 0 else [])
    def find(pairs):                                       # (address, old word, new word) outside the swapped blocks
        out = []
        for ov, nv in pairs:
            for w in np.nonzero(words == ov)[0]:
                a = int(w) * 4
                if not any(lo <= a < hi for lo, hi in skip):
                    out.append((a, ov, nv))
        return out
    # Mario's graph nodes (built from the geo layout at area load) hold his display lists as segmented addresses
    # (0x04xxxxxx); only if none is found, KSEG0 pointers into segment 4 are tried
    ptr = find([(o, n) for o, n in pt["dl_map"]])
    how = "segmented"
    if not ptr:
        ptr = find([(0x80000000 | (i4 + (o & 0xFFFFFF)), (0x80000000 | (i4 + (n & 0xFFFFFF))) if n else 0)
                    for o, n in pt["dl_map"] if o >> 24 == 0x04])
        how = "kseg0"
    CH = 512                                               # RetroArch takes <= 674 bytes per WRITE_CORE_MEMORY

    def write(off: int, data: bytes, old: bytes | None = None):
        n = 0
        for k in range(0, len(data), CH):
            chunk = data[k:k + CH]
            if old is not None and old[k:k + CH] == chunk:
                continue
            r = ad.write_memory(RAM + off + k, cv(chunk))
            if r.get("written", len(chunk)) != len(chunk):
                raise RuntimeError(f"emulator wrote {r.get('written')} of {len(chunk)} bytes at {RAM + off + k:#x}")
            n += len(chunk)
        return n

    def word(v: int) -> bytes:
        return cv(struct.pack(">I", v))
    paused = False
    try:
        ad.pause()
        paused = True
    except Exception:                                      # noqa: BLE001 - writes still land, one frame may mix
        pass
    try:
        wrote = write(i4, n4, o4)
        if i17 >= 0:
            wrote += write(i17, n17, o17)
        for a, _ov, nv in ptr:
            ad.write_memory(RAM + a, word(nv))
        back = ad.read_memory(RAM + i4, len(n4))
        verified = cv(n4) == back[:len(n4)]
    finally:
        if paused:
            ad.resume()
    res = {"order": order, "seg4_at": hex(RAM + i4), "seg17_at": hex(RAM + i17) if i17 >= 0 else None, "bytes_written": wrote,
           "pointers": len(ptr), "pointer_kind": how, "pointer_words": len({a for a, _o, _n in ptr}), "verified": verified, "read_s": round(t_read, 1), "swap_s": round(time.time() - t0, 1)}
    time.sleep(0.6)
    fr = _frames(ad, ctx)
    res["frame_check"] = fr
    res["ok"] = verified and fr["ok"]
    if not res["ok"] and revert_on_fail:                   # put the previous model back
        try:
            ad.pause()
        except Exception:                                  # noqa: BLE001
            pass
        write(i4, o4, n4)
        if i17 >= 0:
            write(i17, o17, n17)
        for a, ov, _nv in ptr:
            ad.write_memory(RAM + a, word(ov))
        try:
            ad.resume()
        except Exception:                                  # noqa: BLE001
            pass
        res["reverted"] = True
    return res


# ---------------------------------------------------------------- push

def _upload(ctx, name: str, data: bytes, media_type="application/json") -> str:
    import httpx
    r = httpx.post(f"{ctx.server}/api/artifacts", params={"name": name, "media_type": media_type}, content=data,
                   headers={**ctx.headers, "Content-Type": "application/octet-stream"}, timeout=120)
    r.raise_for_status()
    return r.json()["sha256"]


def _mod_image(cfg, gid: str, mod: str, d: Path | None = None) -> Path | None:
    from . import filemods
    d = d or filemods.mod_dir(cfg, gid, mod)
    try:
        return d / json.loads((d / ".gbox-mod.json").read_text())["image"]
    except (OSError, ValueError, KeyError):
        return None


def family(chars: list[dict], meta: dict) -> list[dict]:
    """The character, its original (variant_of) and every other variant of that original."""
    base = meta.get("variant_of") or meta["slug"]
    return [m for m in chars if m.get("slug") in (meta["slug"], base) or m.get("variant_of") == base]


def live_mods(chars: list[dict], meta: dict) -> dict[str, dict]:
    """mod name -> {game_id, slot, slug} for every swap mod built from the character's family (module doc: a running
    session using one of them is showing this character)."""
    out: dict[str, dict] = {}
    for m in sorted(family(chars, meta), key=lambda m: m.get("slug") != meta["slug"]):   # the character's own first
        for gid, lst in (m.get("targets") or {}).items():
            for t in lst or []:
                for mod in (t.get("mod"), t.get("base_mod")):
                    if mod and mod not in out:
                        out[mod] = {"game_id": gid, "slot": t.get("slot") or "player", "slug": m["slug"]}
    return out


def find_live_session(sessions: list[dict], chars: list[dict], meta: dict) -> tuple[dict | None, dict]:
    """The running session (newest first) whose current model (live_mod / mod, or the character the pick whip put
    there) belongs to this character's family -> (session, {game_id, slot, slug, why}) | (None, {})."""
    mods = live_mods(chars, meta)
    fam = {m["slug"] for m in family(chars, meta)}
    for s in sorted((s for s in sessions if s.get("state") == "running"), key=lambda s: -(s.get("started") or 0)):
        for key in ("live_mod", "mod"):
            if s.get(key) and s[key] in mods:
                return s, mods[s[key]] | {"why": f"session {s['session_id']} runs {s[key]}"}
        live = s.get("live_character") or s.get("character") or ""
        if live and live in fam:
            return s, {"game_id": s.get("game_id"), "slot": s.get("live_slot") or "player", "slug": live,
                       "why": f"session {s['session_id']} shows {live} (picked)"}
    return None, {}


PICK_OK = ("live", "swapped")                              # pick_replace result.status values that mean "it's in"


def recorded_pick(sess: dict, learned: dict, slot: str) -> dict | None:
    """The pick_identify result that put a character into this slot, when one was kept: on the session (the pick
    whip UI's live_pick / pick / last_pick) or in the game's learned profile (picks[slot] / last_pick). Only a pick for
    this game and this slot counts."""
    gid = sess.get("game_id")
    cands = [sess.get(k) for k in ("live_pick", "pick", "last_pick")]
    cands += [((learned.get("picks") or {}).get(slot) if isinstance(learned.get("picks"), dict) else None),
              learned.get("last_pick")]
    for p in cands:
        if isinstance(p, dict) and p.get("slot") == slot and (not p.get("game_id") or p.get("game_id") == gid):
            return p
    return None


def slot_pick(game: dict, sess: dict, slot: str, learned: dict) -> dict:
    """A pick for a known slot without a click: the fields pick_replace reads (slot, game_id, backend, replaceable;
    session / title / platform for the record), worked out the way pick_identify would for that slot
    (pick_tool.backend_of + replaceable). No entity / RAM hints: a live write locates the model by the writer's
    learned image signatures alone, and falls back to build + session swap."""
    from types import SimpleNamespace
    from . import pick_tool as PT
    backend = PT.backend_of(game)
    try:
        rp = PT.replaceable(backend, game, slot, None, SimpleNamespace(name=sess.get("adapter") or ""), {}, learned)
    except Exception as e:                                 # noqa: BLE001 - unknown: let pick_replace build
        rp = {"live": False, "build": True, "reason": f"replaceable unknown ({type(e).__name__}: {e})"}
    return {"game_id": game.get("game_id") or sess.get("game_id"), "slot": slot, "backend": backend,
            "replaceable": rp, "session_id": sess.get("session_id"), "title": game.get("title") or "",
            "platform": game.get("platform") or "", "entity": None, "ram": {}, "click": [], "slot_guess": False,
            "confidence": 1.0, "evidence": [{"step": "slot", "ok": True,
                                             "detail": f"slot {slot} from the running mod (live_link, no click)",
                                             "source": "gbox.live_link"}]}


def pick_replace_live(ctx, sess: dict, meta: dict, slot: str, game: dict | None = None) -> dict:
    """The pick whip's `pick_replace` (gbox.pick_tool, docs/live-inject.md) in mode "live" with fallback (build +
    session swap), when a worker registers it: {ok, tried, ...}. The pick is the one that put the character there
    when it was recorded, else a slot-only pick (slot_pick). Dispatched to the session's worker. Not registered /
    no worker -> {tried: False}; ran but not live / swapped -> {tried: True, ok: False}."""
    from . import characters as C
    try:
        tools = C._api(ctx, "GET", "/api/tools")
    except Exception:                                      # noqa: BLE001 - no tool list: not available
        return {"tried": False}
    t = next((t for t in tools or [] if isinstance(t, dict) and t.get("name") == "pick_replace"), None)
    if not t or not t.get("workers"):
        return {"tried": False}
    sid, gid = sess["session_id"], sess.get("game_id") or (game or {}).get("game_id") or ""
    try:
        learned = C._api(ctx, "GET", f"/api/profiles/{gid}/pick") if gid else {}
    except Exception:                                      # noqa: BLE001 - nothing learned yet
        learned = {}
    learned = learned if isinstance(learned, dict) else {}
    pick = recorded_pick(sess, learned, slot)
    how = "recorded pick"
    if pick is None:
        pick, how = slot_pick(game or {"game_id": gid}, sess, slot, learned), "slot-only pick"
    try:
        j = C._job(ctx, "pick_replace", {"session_id": sid, "pick": pick, "character": meta["slug"], "mode": "live",
                                         "fallback": True, "rebuild": False, "refresh_ram": True,
                                         "revert_on_fail": True, "allow_arena": False}, sid.split("-")[0], 14400)
    except Exception as e:                                 # noqa: BLE001 - refused: the rebuild path here
        return {"tried": True, "ok": False, "pick": how, "error": f"{type(e).__name__}: {e}"}
    r = (j.get("output") or {}).get("result") or {}
    r = r if isinstance(r, dict) else {}
    ok = j.get("state") == "succeeded" and r.get("status") in PICK_OK
    return {"tried": True, "ok": bool(ok), "pick": how, "job": j.get("id"), "state": j.get("state"),
            "error": j.get("error"), "status": r.get("status"), "mode_used": r.get("mode_used"),
            "fell_back": r.get("fell_back"), **({"session_id": r["session_id"]} if r.get("session_id") else {}),
            "result": r}


def generic_push(ctx, meta: dict, game: dict, sess: dict | None, slot: str, stage, t0: float) -> dict:
    """Any game with a swap writer (characters op=use routes to it): rebuild the character's mod for that slot, then
    session_swap it into the running game (same PC, same moment: save state -> relaunch with the mod -> load state)."""
    from . import attachments, characters as C, sm64_swap
    gid = game["game_id"]
    stage("building", 5, f"{meta['name']} -> {game['title']} ({slot})")
    with attachments.ledger() as led:
        try:
            res = C.characters_tool(C.CharIn(op="use", character=meta["slug"], game_id=gid, slot=slot, rebuild=True,
                                             launch=False), ctx)["result"]
        except Exception as e:                             # noqa: BLE001
            return {"status": "blocked", "stage": "building", "message": f"the build failed: {e}"}
    att = attachments.summary(led)
    mod = res.get("mod")
    if not mod:
        st = res.get("status") or "missing"
        return {"status": "missing" if st in ("missing", "overlay", "gap") else "blocked", "stage": "building",
                "build": {k: v for k, v in res.items() if k in ("status", "message", "missing", "notes")},
                "message": res.get("message") or f"no swap writer built a mod for {game['title']} ({slot})"}
    stage("validating", 60, "the writer's own checks")
    checks = [_check("build", True, res.get("message") or res.get("notes") or f"{mod} built")]
    if att:
        checks.append(_check("attachments", not att["dropped"], att["message"], blocking=False))
    out = {"mod": mod, "checks": checks, "writer": "characters op=use",
           "build": {k: v for k, v in res.items() if k in ("mod", "status", "notes", "report", "slot")},
           **({"attachments": att} if att else {})}
    if not sess:
        return out | {"status": "built", "message": f"{mod} built (no running session to update)"}
    sid = sess["session_id"]
    stage("reloading", 70, f"session swap into {sid}")
    try:
        j = C._api(ctx, "POST", f"/api/sessions/{sid}/swap", json={"mod": mod, "keep_state": True})
        j = sm64_swap._wait(ctx, j, 900)
    except Exception as e:                                 # noqa: BLE001
        return out | {"status": "failed", "stage": "reloading", "message": f"session swap refused: {e}"}
    o = j.get("output") or {}
    if j.get("state") != "succeeded" or not o.get("session_id"):
        return out | {"status": "failed", "stage": "reloading",
                      "message": f"session swap {j.get('state')}: {j.get('error')}; the game keeps the previous model"}
    stage("live", 100, "✓")
    return out | {"status": "live", "method": "session_swap", "session_id": o["session_id"], "reload": o,
                  "seconds": round(time.time() - t0, 1),
                  "message": f"live ✓ {meta['name']} is in the running game (rebuilt + swapped at the same moment, "
                             f"{round(time.time() - t0)} s{'; state loaded' if o.get('state_loaded') else ''})"}


def push(ctx, inp) -> dict:
    from . import characters as C, filemods, sm64_swap
    from .models import CatalogEntry
    from .tools import rom_path
    cfg = ctx.config
    root = C.library_root(cfg)
    if not root.is_dir():
        raise ValueError("live_link push runs on the control-plane node (where the collection is)")
    meta = C.get(root, inp.character)
    sess = C._session(ctx, inp.target) if inp.target else None
    if inp.target and (not sess or sess.get("state") != "running"):
        if not inp.auto_target:
            raise ValueError(f"session {inp.target} isn't running")
        sess = None                                        # replaced (a swap / relaunch) or stopped: find it again
    found = {}
    if not sess and not inp.game_id and inp.auto_target:
        # Blender saved a character: is it (its original, or another variant of it) in a running game right now?
        sess, found = find_live_session(C._api(ctx, "GET", "/api/sessions"), C._api(ctx, "GET", "/api/characters"), meta)
        if not sess:
            return {"character": meta["slug"], "status": "stored", "stages": {},
                    "message": f"{meta['name']} saved; no running game shows it or {meta.get('variant_of') or 'its original'} "
                               "(Use in game once: Live then follows that game)"}
    gid = (sess or {}).get("game_id") or inp.game_id
    if not gid:
        raise ValueError("push needs target (a running session) or game_id")
    game = C._api(ctx, "GET", f"/api/catalog/{gid}")
    t0 = time.time()
    slot = inp.slot or found.get("slot") or "player"
    out = {"character": meta["slug"], "game": game["title"], "game_id": gid, "slot": slot, "stages": {},
           **({"session_id": sess["session_id"], "found_by": found.get("why")} if found else {})}

    def stage(name, pct, msg):
        out["stages"][name] = round(time.time() - t0, 1)
        ctx.progress(pct, f"{name}: {msg}")
    if sess and inp.method in ("auto", "live"):           # the live injection tool, when a worker has it
        r = pick_replace_live(ctx, sess, meta, slot, game)
        if r.get("ok"):
            how = "RAM injection" if r.get("status") == "live" else "built + session swap"
            stage("live", 100, f"✓ (pick_replace {r.get('status')})")
            return out | {"status": "live", "method": f"pick_replace {r.get('mode_used') or r.get('status')}", "reload": r,
                          "session_id": r.get("session_id") or sess["session_id"], "seconds": round(time.time() - t0, 1),
                          "message": f"live ✓ {meta['name']} is in the running game ({how}, {round(time.time() - t0)} s)"}
        if r.get("tried") and r.get("status") == "failed" and r.get("mode_used") == "build":
            return out | {"status": "failed", "stage": "reloading", "pick_replace": r,      # its build + swap failed:
                          "message": f"pick_replace build + session swap failed: "         # the same build here would too
                                     f"{(r.get('result') or {}).get('message') or r.get('error')}"}
        if r.get("tried"):
            out["pick_replace"] = r                        # not mapped / refused: this module's rebuild + swap
    if gid in sm64_swap.GAME_IDS and slot == "player":
        writer, mod = "sm64", f"sm64_{meta['slug']}"
    elif gid in C.RE4GC and slot == "player":
        writer, mod = "re4gc", f"re4_{meta['slug']}" + ("_d2" if gid == "e42c9b780c07c437" else "")
    else:
        return out | generic_push(ctx, meta, game, sess, slot, stage, t0)
    d = filemods.mod_dir(cfg, gid, mod)
    prev = d.with_name(mod + ".prev")
    shutil.rmtree(prev, ignore_errors=True)
    if d.exists():
        shutil.copytree(d, prev)

    def restore():
        if prev.exists():
            shutil.rmtree(d, ignore_errors=True)
            prev.rename(d)
        else:
            shutil.rmtree(d, ignore_errors=True)
    stage("building", 5, f"{writer} writer: {meta['name']}")
    try:
        if writer == "sm64":
            b = sm64_swap.build_mod(cfg, meta, game, lambda p, m: ctx.progress(5 + p * 0.5, "building: " + m))
            notes = (f"replaces Mario (all his animations); {b['report']['triangles']} triangles, {b['report']['textures']} textures "
                     f"<= {b['report']['max_texels']} texels; preview targets/sm64_preview.png")
        else:
            b = C.build_re4(ctx, meta, game, lambda p, m: ctx.progress(5 + p * 0.5, "building: " + m))
            notes = "replaces Leon (story + Mercenaries)"
    except Exception as e:                                 # noqa: BLE001
        restore()
        return out | {"status": "blocked", "stage": "building", "message": f"the build failed: {e}"}
    out["build"] = {k: v for k, v in b.items() if k in ("mod", "image", "report", "packs", "props", "how")}
    stage("validating", 60, "skeleton, budget, textures, culling, hit boxes")
    if writer == "sm64":
        new_rom = Path(d / b["image"]).read_bytes()
        vanilla = sm64_swap.rom_bytes(rom_path(CatalogEntry.model_validate(game), cfg))
        checks = validate_sm64(new_rom, vanilla, b["report"])
    else:
        checks = validate_re4(cfg, meta, game, b)
    out["checks"] = checks
    bad = [c for c in checks if c["blocking"] and not c["ok"]]
    if bad:
        restore()
        return out | {"status": "blocked", "stage": "validating",
                      "message": "blocked: " + "; ".join(f"{c['check']}: {c['detail']}" for c in bad)}
    C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
           json={"game_id": gid, "slot": "player", "mod": mod, "nodes": [C.HOST_OS], "notes": notes, "needs_rebuild": False})
    if not sess:
        shutil.rmtree(prev, ignore_errors=True)
        return out | {"status": "built", "mod": mod, "message": f"{mod} built and validated (no running session to update)"}
    sid, wid = sess["session_id"], sess["session_id"].split("-")[0]
    method = inp.method
    if method in ("auto", "live"):
        method = "hotswap" if writer == "sm64" and sess.get("adapter") == "retroarch" else "relaunch"
    stage("reloading", 70, f"{method} into session {sid}")
    if method == "hotswap":
        cur = sess.get("live_mod") or sess.get("mod") or ""
        old_img = (_mod_image(cfg, gid, cur, prev) if cur == mod else _mod_image(cfg, gid, cur)) if cur else None
        old_rom = old_img.read_bytes() if old_img and old_img.exists() else vanilla
        sha = _upload(ctx, "hotswap.json", json.dumps(sm64_patch(old_rom, new_rom)).encode())
        j = C._job(ctx, "live_link", {"op": "hotswap", "session_id": sid, "patch": sha,
                                      "revert_on_fail": inp.revert_on_fail}, wid, 600)
        r = (j.get("output") or {}).get("result") or {}
        out["reload"] = r | {"job": j.get("id"), "state": j.get("state"), "error": j.get("error")}
        if j.get("state") != "succeeded" or not r.get("ok"):
            restore()
            why = j.get("error") or ("the frame check failed (black or frozen picture)" if r.get("frame_check") else r)
            return out | {"status": "reverted" if r.get("reverted") else "failed", "stage": "reloading",
                          "message": f"hot swap didn't go live: {why}; the previous build is back"}
        if cur != mod:                                     # the session's ROM is now a different build: label it
            out["note"] = f"session started with {cur or 'the original game'}; Mario's model is {mod} now (until a reset)"
        C._api(ctx, "POST", f"/api/sessions/{sid}/live-model", json={"mod": mod})
    else:
        r = relaunch(ctx, sess, gid, mod, inp.revert_on_fail)
        out["reload"] = r
        if not r.get("ok"):
            restore()
            return out | {"status": "reverted" if r.get("reverted") else "failed", "stage": "reloading",
                          "message": f"relaunch didn't go live: {r.get('error') or 'frame check failed'}; previous build back"}
        sid = r["session_id"]
    shutil.rmtree(prev, ignore_errors=True)
    stage("live", 100, "✓")
    return out | {"status": "live", "mod": mod, "session_id": sid, "seconds": round(time.time() - t0, 1),
                  "message": f"live ✓ {meta['name']} is in the running game ({method}, {round(time.time() - t0)} s)"
                             + (". RE4 shows the new model after the next area load (the state holds the old one)" if writer == "re4gc" else "")}


def relaunch(ctx, sess: dict, gid: str, mod: str, revert: bool) -> dict:
    """Save state -> launch the new mod on the same node -> load the state -> stop the old session -> frame check."""
    from . import characters as C
    sid, wid = sess["session_id"], sess["session_id"].split("-")[0]
    j = C._job(ctx, "state_transfer", {"session_id": sid, "op": "export"}, wid, 240)
    if j.get("state") != "succeeded":
        return {"ok": False, "error": f"save state: {j.get('error') or j.get('state')}"}
    art = j["output"]["result"]["artifact"]
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": mod, "node": wid, "swap": False}})
    from .sm64_swap import _wait
    lj = _wait(ctx, lj, 600)
    nsid = (lj.get("output") or {}).get("session_id")
    if lj.get("state") != "succeeded" or not nsid:
        return {"ok": False, "error": f"launch: {lj.get('error') or lj.get('state')}"}
    time.sleep(8)
    ij = C._job(ctx, "state_transfer", {"session_id": nsid, "op": "import", "artifact": art}, wid, 240)
    C._job(ctx, "session_op", {"session_id": sid, "op": "stop_game", "args": {}}, wid, 60)
    time.sleep(1.5)
    f1 = C._job(ctx, "get_frame", {"session_id": nsid}, wid, 60)
    time.sleep(0.8)
    f2 = C._job(ctx, "get_frame", {"session_id": nsid}, wid, 60)
    o1, o2 = f1.get("output") or {}, f2.get("output") or {}
    ok = ij.get("state") == "succeeded" and o1.get("sha256") != o2.get("sha256") and (o2.get("mean_luma") or 10) > 3
    res = {"ok": ok, "session_id": nsid, "state_loaded": ij.get("state") == "succeeded",
           "frames": [o1.get("sha256"), o2.get("sha256")], "luma": o2.get("mean_luma")}
    if not ok and revert:                                  # back to the previous build at the same moment
        C._job(ctx, "session_op", {"session_id": nsid, "op": "stop_game", "args": {}}, wid, 60)
        lj = _wait(ctx, C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": sess.get("mod") or "", "swap": False,
                                                                                            "node": wid}}), 600)
        osid = (lj.get("output") or {}).get("session_id")
        if osid:
            time.sleep(8)
            C._job(ctx, "state_transfer", {"session_id": osid, "op": "import", "artifact": art}, wid, 240)
        res |= {"reverted": True, "session_id": osid}
    return res


# ---------------------------------------------------------------- the tool

class LiveIn(BaseModel):
    op: str = "push"                       # push | hotswap | validate
    character: str = ""                    # push / validate: the variant (collection slug)
    target: str = ""                       # push: the running session to update ("" = build + validate only)
    game_id: str = ""                      # push without target: the game to build for
    method: str = "auto"                   # push: auto (pick_replace live if registered; SM64 on RetroArch: hotswap, else
                                           # relaunch / session swap) | live | hotswap | relaunch
    slot: str = ""                         # push: the slot the character fills ("" = the one its running mod was built for)
    auto_target: bool = True               # push without target/game_id: find the running game showing this character
    revert_on_fail: bool = True
    session_id: str = ""                   # hotswap (internal): the session whose memory is patched
    patch: str = ""                        # hotswap (internal): artifact sha of the prepared patch


class LiveOut(BaseModel):
    result: dict


@tool("live_link", "1.0", LiveIn, LiveOut, capabilities=["mod", "runtime", "memory"], permissions=[P.EXECUTE], timeout_s=1800,
      artifacts=["frame0.png", "frame1.png"],
      side_effects=["push: rebuilds the variant's mod (previous build kept until live)", "push: may write the running game's "
                    "memory (SM64 hot swap) or relaunch it from a save state", "push: records the mod in the character's targets"])
def live_link(inp: LiveIn, ctx):
    """Blender Live Link: push character=<variant slug> target=<running session id> = rebuild its mod, validate it
    (skeleton, budget, textures, culling radius, hit boxes), then put it into the running game (SM64: hot swap in RDRAM;
    others: save state -> relaunch -> load state) and confirm with a frame check (reverts on failure). Without target
    or game_id it finds the running game showing the character (or its original / another variant); any game with a
    swap writer is rebuilt for that slot and session-swapped; `pick_replace` mode live is tried first when registered."""
    if inp.op == "push":
        return {"result": push(ctx, inp)}
    if inp.op == "hotswap":
        import httpx
        from .tools import SESSIONS
        ad, _g = SESSIONS[inp.session_id]
        r = httpx.get(f"{ctx.server}/api/artifacts/{inp.patch}", headers=ctx.headers, timeout=120)
        r.raise_for_status()
        return {"result": apply_hotswap(ad, r.json(), ctx, inp.revert_on_fail)}
    raise ValueError("op: push | hotswap")

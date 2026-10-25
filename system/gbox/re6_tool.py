"""`re6`: Resident Evil 6 (Xbox 360, in Xenia on a Windows node) - Mercenaries loadouts, items and character swaps.
Register with:  from . import re6_tool  # noqa: F401

Safety: refuses everything while the game could be in a network session (see online_guard); only this title
(BH6MasterRelease, title 43430819) is touched; the disc image is never written (model swaps are mod folders of hard
links to an extracted copy, launched with launch_game(mod=...)); every live memory change is recorded per session and
undone by op=revert_all.

ops (live ones need session_id of a running RE6 session):
  status                      mode (title / story / mercenaries), online state, character, inventory summary
  inventory                   the case: slot, item id + name, ammo / count
  give item=<name|id> amount  put an item into the case (any item, story-only weapons included)
  set_loadout items=[...]     the case = these items (weapons first; amount = ammo / count); replaces what's there
  auto on=true|false          apply the saved loadout (POST /api/re6/loadout) at the start of every Mercenaries match
  infinite_ammo / infinite_health on=true|false   held live (every gun/ammo stack full / Life = LifeMax); saved per game
  give_now item=<name|id> amount   into the running game's inventory now (Mercenaries or campaign): any item; a gun
                              the stage didn't load gets its resources (uWpNNNN.arc) loaded first
  remove_item slot=N          empty one inventory slot live
  set_slot slot=N item= amount=   change one slot live (another item, or only the count)
  live_inventory              the player's inventory right now (slot, item, count / max)
  unlock_all [on=false]       everything unlocked (save + live), on=false = original save back (= unlock)
  everything_unlocked / boot_to_title on=   the boot profile switches (both on by default)
  auto_qte on=true|false      every QTE prompt succeeds (default on whenever RE6 boots through gBox)
  settings                    the saved RE6 switches (auto_qte, infinite_*, everything_unlocked, boot_to_title)
  revert_all                  undo every live change, stop auto / freezes, delete gBox's RE6 mod folders
  catalog                     the item list (names from the disc)
  capabilities                character writer support and limits (no session needed)
  build_mod character=<library name> [target=leon costume=]   character swap mod (no launch)
  mods                        RE6 mods built on this node
"""
from __future__ import annotations

import json
import copy
import hashlib
import re
import shutil
import struct
import threading
import time
from pathlib import Path

from pydantic import BaseModel

from . import re6
from .models import Permission as P
from .registry import Unsupported, tool

GAME_IDS = {re6.GAME_ID}
TITLE_CHECK = (0x821B07F0, bytes.fromhex("0001000101000000000000010000000000020002020000000000000100000000"))   # item id table


# ------------------------------------------------------------------ mod folders (character swaps)

def _iso(cfg) -> Path:
    """The RE6 disc image on this node: the staged cache copy when there is one, else the library file."""
    from .models import CatalogEntry
    from .tools import rom_path
    import httpx  # noqa: F401
    staged = Path(cfg.cache) / re6.GAME_ID / "Resident Evil 6.iso"
    if staged.is_file():
        return staged
    g = {"game_id": re6.GAME_ID, "title": "Resident Evil 6", "platform": "xbox360", "library": "hyperspin",
         "rel_path": "collections/Microsoft XBOX 360/roms/Resident Evil 6.iso", "launch": {}}
    return rom_path(CatalogEntry.model_validate(g), cfg)


def base(cfg, progress=None) -> Path:
    b = re6.base_dir(cfg)
    if not (b / ".gbox-base-complete").exists():
        last = [0.0]

        def prog(done, total, p):
            if progress and time.time() - last[0] > 1:
                last[0] = time.time()
                progress(5 + 50 * done / total, f"Extracting the RE6 disc for mods: {done / 2**30:.1f} / {total / 2**30:.1f} GB")
        re6.extract(_iso(cfg), b, prog)
    return b


def mod_dir(cfg, name: str) -> Path:
    from . import filemods
    return filemods.mod_dir(cfg, re6.GAME_ID, name)


def build_mod_folder(cfg, name: str, files: dict[str, bytes], meta: dict | None = None) -> dict:
    """Mod = hard links to the extracted disc + the replaced files as real copies. Launch: launch_game(mod=name)
    (filemods.launch_path -> <mod>/default.xex, which Xenia boots as a folder game)."""
    b = base(cfg)
    out = mod_dir(cfg, name)
    if out.exists():
        shutil.rmtree(out)
    norm = {k.replace("\\", "/").lower(): (k, v) for k, v in files.items()}
    n_link = 0
    for f in b.rglob("*"):
        if f.name == ".gbox-base-complete":
            continue
        rel = f.relative_to(b)
        t = out / rel
        if f.is_dir():
            t.mkdir(parents=True, exist_ok=True)
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        hit = norm.pop(rel.as_posix().lower(), None)
        if hit:
            t.write_bytes(hit[1])
        else:
            import os
            os.link(f, t)
            n_link += 1
    for k, v in norm.values():
        t = out / k
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(v)
    info = {"name": name, "game_id": re6.GAME_ID, "image": "default.xex", "files": sorted(files), "built": time.time(),
            **(meta or {})}
    (out / ".gbox-mod.json").write_text(json.dumps(info))
    return {"mod": name, "dir": str(out), "files": len(files), "linked": n_link}


def list_mods(cfg) -> list[dict]:
    d = mod_dir(cfg, "x").parent
    out = []
    for m in sorted(d.glob("*/.gbox-mod.json")) if d.is_dir() else []:
        try:
            out.append(json.loads(m.read_text()))
        except ValueError:
            pass
    return out


def fetch_model(ctx, meta: dict) -> Path:
    """The collection model on this node: the library itself if it's here, else raw bytes from the API into
    cache/characters_mirror (a .gltf comes back as JSON from the API, so it's fetched raw), plus any external
    buffers / images a .gltf references."""
    from . import characters as C
    lib = C.library_root(ctx.config) / meta["slug"] / meta["model"]
    if lib.is_file():
        return lib
    import httpx
    d = Path(ctx.config.cache) / "characters_mirror" / meta["slug"]
    d.mkdir(parents=True, exist_ok=True)

    def get(rel: str) -> Path:
        out = d / rel
        if not out.is_file():
            r = httpx.get(f"{ctx.server}/api/characters/{meta['slug']}/file/{rel}", headers=ctx.headers, timeout=300)
            r.raise_for_status()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(r.content)
        return out
    m = get(meta["model"])
    if m.suffix.lower() == ".gltf":
        gl = json.loads(m.read_text(encoding="utf-8"))
        for x in gl.get("buffers", []) + gl.get("images", []):
            u = x.get("uri", "")
            if u and not u.startswith("data:"):
                get(u)
    return m


def character_capabilities() -> dict:
    """Static writer capabilities, without starting a watcher or inspecting a running game."""
    from . import re6_models as M
    return {"game_id": re6.GAME_ID, "platform": "xbox360", "backend": "xenia", "host_os": "windows",
            "character_replacement": {"build_mod": True, "relaunch": True, "requires_relaunch": True,
                                      "realtime": False, "active_target_detection": False,
                                      "animation_retarget": False, "binding": "rigid geometry on the native skeleton",
                                      "targets": [{"id": k, "name": v["name"], "costumes": list(v["costumes"])}
                                                  for k, v in M.CHARACTERS.items()]},
            "unsupported_platforms": ["pc", "ps3", "ps4"],
            "limitations": ["Requires an extracted Xbox 360 disc and a donor with body roles.",
                            "The selected native character must be chosen in game after launching the mod.",
                            "No writer for the native PC, PS3 or PS4 edition; no realtime body replacement.",
                            "A successful build does not verify its appearance or animations in gameplay."]}


def _character_choice(target: str = "leon", costume: str = "") -> tuple[str, list[str]]:
    from . import re6_models as M
    target = str(target or "leon").strip().casefold()
    if target not in M.CHARACTERS:
        raise ValueError(f"target must be one of {sorted(M.CHARACTERS)}; no active character is inferred")
    available = M.CHARACTERS[target]["costumes"]
    if costume:
        match = next((c for c in available if c.casefold() == costume.strip().casefold()), None)
        if match is None:
            raise ValueError(f"costume for {target} must be one of {available}")
        return target, [match]
    return target, list(available)


def _player_meta(meta: dict, scale: dict | None = None) -> dict:
    from . import retarget_profile as RP
    meta = RP.apply_to_meta(meta, re6.GAME_ID, "player")
    if scale:
        meta = copy.deepcopy(meta)
        rig = meta.setdefault("rig", {})
        rig["scale"] = dict(rig.get("scale") or {}) | scale
    return meta


def _fit_key(meta: dict) -> str:
    """Profile and legacy scale changes must not reuse a mod built with a different fit."""
    from . import retarget_profile as RP
    scale = dict((meta.get("rig") or {}).get("scale") or {})
    profile = scale.pop("profile", None)
    changed = {"profile": RP.digest(profile), "saved_profile": meta.get("retarget_profile_digest", ""), "scale": scale}
    if not any(changed.values()):
        return ""
    return hashlib.sha256(json.dumps(changed, sort_keys=True).encode()).hexdigest()[:12]


def _character_mod_name(meta: dict, target: str, costume: str = "") -> str:
    name = f"re6_{meta['slug']}" + ("" if target == "leon" else f"_{target}")
    if costume:
        name += f"_{costume}"
    fit = _fit_key(meta)
    return name + (f"_fit{fit}" if fit else "")


def build_character(ctx, meta: dict, target: str = "leon", costume: str = "", progress=None,
                    scale: dict | None = None) -> dict:
    """Build replacement geometry for an explicit native target; loading the mod requires a relaunch."""
    from . import characters as C, re6_models as M
    target, costumes = _character_choice(target, costume)
    meta = _player_meta(meta, scale)
    progress = progress or (lambda *a: None)
    roles = (meta.get("rig") or {}).get("roles")
    if not roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles) in the collection: can't fit it to an RE6 skeleton")
    scale = (meta.get("rig") or {}).get("scale")
    progress(5, "RE6 disc copy for mods")
    b = base(ctx.config, progress)
    model = fetch_model(ctx, meta)
    files, report = {}, []
    for k, cos in enumerate(costumes):
        progress(55 + 30 * k / len(costumes), f"Fitting {meta['name']} to {M.CHARACTERS[target]['name']} ({cos})")
        r = M.build_swap(b, model, roles, target, cos, meta["slug"], scale=scale)
        files.update(r.pop("files"))                     # costumes never share arcs
        report.append(r)
    name = _character_mod_name(meta, target, costumes[0] if costume else "")
    progress(88, f"Writing mod {name}")
    res = build_mod_folder(ctx.config, name, files, {"character": meta["slug"], "target": target, "costumes": costumes,
                                                   "fit_key": _fit_key(meta)})
    work = Path(ctx.config.cache) / "characters_build" / meta["slug"]
    work.mkdir(parents=True, exist_ok=True)
    prev = None
    try:                                                   # read the written model back and render it (checked picture)
        r0 = M.build_swap(b, model, roles, target, costumes[0], meta["slug"], work / "re6_preview.gltf", scale=scale)
        C.render_preview(Path(r0["preview_gltf"]), work / "re6_preview.png")
        prev = str(work / "re6_preview.png")
        ctx.artifact("re6_preview.png", (work / "re6_preview.png").read_bytes(), "image/png", character=meta["slug"])
    except Exception as e:                                 # noqa: BLE001 - the preview is a check, not the product
        prev = f"preview failed: {e}"
    return res | {"target": target, "costumes": costumes, "requires_relaunch": True, "realtime": False,
                  "fit_key": _fit_key(meta), "triangles": report[0]["triangles"],
                  "hidden": report[0]["hidden_parts"], "notes": sorted({n for r in report for n in r["notes"]}), "preview": prev}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """Build/relaunch a replacement for an explicit target (default Leon); never infer the active player."""
    from . import characters as C, re6_models as M
    gid = game["game_id"]
    if getattr(inp, "slot", "player") != "player":            # slot=enemies | enemy:<family>
        return use_enemies(ctx, meta, game, inp)
    target, costumes = _character_choice(getattr(inp, "target", ""))
    meta = _player_meta(meta, getattr(inp, "scale", None))
    name = _character_mod_name(meta, target)
    target_name = M.CHARACTERS[target]["name"]
    replaces = f"{target_name} (all {len(costumes)} costumes); choose {target} in game"
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    built = None
    if inp.rebuild or not (mod_dir(ctx.config, name) / ".gbox-mod.json").exists():
        if C.HOST_OS != "windows":                         # the extracted disc + Xenia live on the Windows node
            w = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "windows" and w.get("online")), None)
            if not w:
                return {"status": "failed", "error": "no Windows node online to build the RE6 mod on"}
            j = C._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "rebuild": inp.rebuild,
                                           "launch": inp.launch, "session_id": inp.session_id, "target": target,
                                           "scale": getattr(inp, "scale", {})}, w, 3600)
            return (j.get("output") or {}).get("result") or {"status": j.get("state"), "error": j.get("error")}
        built = build_character(ctx, meta, target, "", ctx.progress, scale=getattr(inp, "scale", None))
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": "player", "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"replaces {target_name} (every costume); head/hands hidden; requires relaunch; "
                              "revert: launch without the mod or re6 op=revert_all"})
    res = {"mod": name, "build": built, "target": target, "costumes": costumes, "replaces": replaces,
           "requires_relaunch": True, "realtime": False}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    if sess and sess.get("game_id") == gid and sess.get("mod") == name:
        return res | {"status": "already running", "message": f"Resident Evil 6 is already running with {meta['name']} "
                      f"(mod {name}). Choose {target_name} in game."}
    ctx.progress(92, f"Launching Resident Evil 6 with {meta['name']} (mod {name})")
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    for _ in range(600):
        j = C._api(ctx, "GET", f"/api/jobs/{lj['id']}")
        if j.get("state") not in ("queued", "running"):
            break
        time.sleep(1)
    ok = j.get("state") == "succeeded"
    return res | {"status": ("built+launched" if built else "launched") if ok else f"launch {j.get('state')}",
                  "launch": {"job": lj.get("id"), "session_id": (j.get("output") or {}).get("session_id"), "error": j.get("error")},
                  "message": (f"Resident Evil 6 is starting with {meta['name']} replacing {target_name} (mod {name}). "
                              f"Choose {target} in game. Revert: launch RE6 without the mod, or re6 op=revert_all."
                              if ok else f"mod {name} ready, launch failed: {j.get('error')}")}


# ------------------------------------------------------------------ live: Mercenaries loadouts (verified in game)
# The Mercenaries start loadouts are a table in the executable's .data (found by reading game memory):
# 16 records of 0x70 bytes at 0x83C6B8F0, one per character / costume:
#   +0  u8 character (0 Leon, 1 Helena, 2 Chris, 3 Piers, 4 Jake, 5 Sherry, 6 Ada, 7 Agent), u8 costume (0x00 default,
#       0x10 EX, 0x02 Ada's Carla), u16 900, u16 900, ...
#   +16 24 entries {u8 type, u8 id, u16 count}: type 1 = weapon / grenade / recovery item id 0-40 (count = loaded ammo,
#       0xFFFF = melee), 2 = ammo (item id - 100), 3 = herb (item id - 200); slots 0-6 = weapons, 7-12 = the fixed
#       grenade / recovery selectors, 13-14 unused, 15-23 = the case (grenade stock, sprays, ammo).
# The game copies a record when a match starts from character select (Continue / Retry reuse the running copy), so
# writing the table = the loadout of every following match until the game is closed. Same format as the save's
# per-character inventories.
MERC_TABLE, MERC_REC, MERC_N = 0x83C6B8F0, 0x70, 16
CHARS = {"leon": 0, "helena": 1, "chris": 2, "piers": 3, "jake": 4, "sherry": 5, "ada": 6, "agent": 7}
FIXED = [(1, 29, None), (1, 32, 0), (1, 19, 0), (1, 20, 0), (1, 21, 0), (1, 22, 0)]       # slots 7-12 (tablets keep count)
MAG = {0: 0xFFFF, 1: 15, 2: 16, 3: 18, 4: 8, 5: 7, 6: 3, 7: 7, 8: 6, 9: 6, 10: 5, 11: 10, 12: 50, 13: 20, 14: 30,
       15: 30, 16: 30, 17: 30, 18: 6, 23: 1, 24: 0xFFFF, 25: 0xFFFF, 26: 0xFFFF, 27: 1, 31: 1, 38: 0xFFFF, 39: 1, 40: 20}
AMMO_OF = {1: 101, 2: 101, 3: 101, 12: 101, 13: 101, 14: 101, 40: 101, 4: 102, 5: 102, 9: 103, 10: 103, 15: 104,
           16: 104, 17: 104, 11: 105, 7: 106, 8: 107, 18: 108, 27: 111, 23: 112, 6: 114}
STOCK = {101: 60, 102: 20, 103: 15, 104: 60, 105: 10, 106: 20, 107: 15, 108: 6, 109: 6, 110: 6, 111: 3, 112: 15,
         113: 6, 114: 12}                                 # ammo stock added with a gun (roughly the game's own stocks)
_STATE: dict = {"auto": {}, "watch": None, "undo": {}}


def _names(cfg) -> dict[int, str]:
    if "names" not in _STATE:
        from . import re6_items
        b = re6.base_dir(cfg)
        msg = re6.Arc(path=b / "nativeXenon" / "arc" / "X360" / "Msg_eng.arc")
        _STATE["names"] = re6_items.parse_gmd(msg.get(msg.find("soft\\message\\mes_item_eng", "242bb29a")))
    return _STATE["names"]


def resolve_item(cfg, q) -> int:
    """'elephant killer' / 'hand cannon' / 8 / '0x8' -> item id."""
    if isinstance(q, int):
        return q
    s = str(q).strip().lower()
    if re.fullmatch(r"(0x[0-9a-f]+|\d+)", s):
        return int(s, 0)
    alias = {"hand cannon": 8, "handcannon": 8, "magnum": 8, "revolver": 8, "desert eagle": 7, "deagle": 7,
             "m500": 8, "rpg": 27, "rocket": 27, "machete": 25, "knife": 24, "grenade": 19, "flashbang": 21,
             "first aid": 32, "spray": 32, "herb": 201, "green herb": 201, "red herb": 202, "bow": 23}
    if s in alias:
        return alias[s]
    names = {k: v.lower() for k, v in _names(cfg).items() if k < 440}
    hit = [k for k, v in names.items() if v == s] or [k for k, v in names.items() if s in v] or \
          [k for k, v in names.items() if all(w in v for w in s.split())]
    if not hit:
        raise ValueError(f"no RE6 item matches {q!r}")
    return sorted(hit)[0]


def _original_table(cfg) -> bytes:
    """The table as shipped (from the decoded executable image): what revert writes back."""
    img = re6.runtime(cfg) / "BH6MasterRelease.bin"
    if not img.is_file():
        img.write_bytes(re6.xex_image((base(cfg) / "default.xex").read_bytes())["image"])
    with open(img, "rb") as f:
        f.seek(MERC_TABLE - 0x82000000)
        return f.read(MERC_REC * MERC_N)


def _entries(rec: bytes) -> list[list[int]]:
    return [list(struct.unpack_from(">BBH", rec, 16 + 4 * i)) for i in range(24)]


def _pack(rec: bytes, ents) -> bytes:
    return rec[:16] + b"".join(struct.pack(">BBH", *e) for e in ents)


def _item_entry(iid: int, amount: int):
    if iid < 100:
        return [1, iid, amount]
    if iid < 200:
        return [2, iid - 100, amount]
    if iid < 300:
        return [3, iid - 200, amount]
    raise ValueError(f"item {iid} can't be carried in Mercenaries (skill points / key items)")


def build_record(rec: bytes, items: list[tuple[int, int]], replace: bool = True) -> bytes:
    """items [(item id, amount)] -> the record: weapons into slots 0-6 (amount = loaded ammo, 0 = full magazine),
    grenades / recovery / ammo / herbs into the case (slots 15-23); with replace the character's own guns and case
    are cleared first. Each gun also gets a case stock of its ammo unless the list has that ammo."""
    ents = _entries(rec)
    empty = [0, 0, 0xFFFF]
    if replace:
        for i in list(range(7)) + list(range(15, 24)):
            ents[i] = list(empty)
    guns = [(i, a) for i, a in items if i < 100 and i not in (19, 20, 21, 22, 29, 32)]
    case = [(i, a) for i, a in items if not (i < 100 and i not in (19, 20, 21, 22, 29, 32))]
    have_ammo = {i for i, _ in case if 100 <= i < 200}
    for gid, _ in guns:
        am = AMMO_OF.get(gid)
        if am and am not in have_ammo:
            case.append((am, STOCK.get(am, 60)))
            have_ammo.add(am)
    free_w = [k for k in range(7) if ents[k][0] == 0]
    for (gid, a) in guns:
        if any(ents[k][0] == 1 and ents[k][1] == gid for k in range(7)):
            continue
        if not free_w:
            raise ValueError("more than 7 weapons: Mercenaries has 7 weapon slots")
        ents[free_w.pop(0)] = _item_entry(gid, a or MAG.get(gid, 10))
    free_c = [k for k in range(15, 24) if ents[k][0] == 0]
    for (iid, a) in case:
        e = _item_entry(iid, a or (STOCK.get(iid, 30) if 100 <= iid < 200 else 3 if iid < 100 else 1))
        same = next((k for k in range(15, 24) if ents[k][:2] == e[:2]), None)
        if same is not None:
            ents[same][2] = min(0xFFFE, ents[same][2] + e[2])
            continue
        if not free_c:
            raise ValueError("the Mercenaries case has 9 slots: too many items")
        ents[free_c.pop(0)] = e
    return _pack(rec, ents)


def _records(ad) -> list[bytes]:
    d = ad.read_memory(MERC_TABLE, MERC_REC * MERC_N)
    return [d[k * MERC_REC:(k + 1) * MERC_REC] for k in range(MERC_N)]


def _targets(recs, character: str) -> list[int]:
    if not character or character == "any":
        return list(range(MERC_N))
    c = CHARS.get(character.lower().split()[0])
    if c is None:
        raise ValueError(f"character must be one of {sorted(CHARS)} or any")
    return [k for k, r in enumerate(recs) if r[0] == c]


def apply_loadout(ad, cfg, items: list[tuple[int, int]], character: str = "", replace: bool = True) -> dict:
    recs = _records(ad)
    if recs[0][2:6] != b"\x03\x84\x03\x84":
        raise RuntimeError("the Mercenaries loadout table isn't where expected (different game build?)")
    done = []
    for k in _targets(recs, character):
        new = build_record(recs[k], items, replace)
        ad.write_memory(MERC_TABLE + k * MERC_REC, new)
        done.append(k)
    return {"records": done, "characters": sorted({_char_name(recs[k][0]) + ("" if recs[k][1] == 0 else " EX")
                                                    for k in done})}


def _char_name(c: int) -> str:
    return next((n for n, i in CHARS.items() if i == c), str(c)).title()


def describe(cfg, rec: bytes) -> dict:
    names = _names(cfg)
    out = []
    for t, i, c in _entries(rec):
        if not t:
            continue
        iid = i if t & 0xF == 1 else 100 + i if t == 2 else 200 + i if t == 3 else None
        out.append({"id": iid, "name": names.get(iid, f"item {iid}"), "count": None if c == 0xFFFF else c})
    return {"character": _char_name(rec[0]), "costume": {0: "default", 0x10: "EX", 2: "Carla"}.get(rec[1], hex(rec[1])),
            "items": [x for x in out if x["count"] != 0 or x["id"] in (29,)]}


# ------------------------------------------------------------------ safety

def online_guard(ad) -> dict:
    """Refuse when the game could be in a network session. This Xenia build has no netplay (no network_mode /
    api_address options; XNet calls are unimplemented), the game itself reports 'not signed in to Xbox LIVE' and
    greys out Duo online; a Xenia build with netplay enabled, or a log with Xbox LIVE session calls, blocks gBox."""
    from .xenia import cvar_known
    exe = (getattr(ad, "info", None) or {}).get("exe")
    netplay = bool(exe) and (cvar_known(exe, "network_mode") or cvar_known(exe, "api_address"))
    if netplay:
        cfgf = Path(exe).with_name("xenia-canary.config.toml")
        txt = cfgf.read_text(errors="replace") if cfgf.is_file() else ""
        m = re.search(r"(?m)^\s*network_mode\s*=\s*(\d+)", txt)
        if not m or m.group(1) != "0":
            raise Unsupported("this Xenia build has netplay enabled: gBox doesn't touch RE6 while it could be online")
    log = getattr(ad, "log_tail", lambda n=0: "")(200000)
    if re.search(r"XSessionCreate\b.*(?:=> 0\b|success)|XamUserGetSigninState.*=> 2", log):
        raise Unsupported("an Xbox LIVE session was started in this game: gBox refuses to modify memory online")
    return {"online": False, "netplay_build": netplay}


def _guard(ctx_or_sid):
    from .tools import SESSIONS
    if ctx_or_sid not in SESSIONS:
        raise ValueError(f"no session {ctx_or_sid} on this node")
    ad, g = SESSIONS[ctx_or_sid]
    if (g.get("game_id") if isinstance(g, dict) else None) not in GAME_IDS:
        raise Unsupported("re6 works on Resident Evil 6 (Xbox 360) sessions")
    if getattr(ad, "name", "") != "xenia":
        raise Unsupported("re6 needs the Xenia session (launched by gBox on the Windows node)")
    if ad.read_memory(*TITLE_CHECK[:1], len(TITLE_CHECK[1])) != TITLE_CHECK[1]:
        raise Unsupported("this isn't the RE6 build gBox mapped (BH6MasterRelease, title 43430819)")
    return ad, g, online_guard(ad)


def mode_of(ad) -> str:
    """From Xenia's own log of file opens: Mercenaries stages are s12xx and load sa/Mercenaries.arc."""
    log = ad.log_tail(400000)
    stages = re.findall(r"ResolvePath\(\\nativeXenon\\data\\detail\\(s\d{4})\)", log)
    merc = log.rfind("Mercenaries.arc")
    last = stages[-1] if stages else None
    if last and last.startswith("s12"):
        return "mercenaries"
    if last:
        return "story"
    return "mercenaries menu" if merc >= 0 else "title / menus"


# ------------------------------------------------------------------ save: intro skip + unlocks (verified in game)
# The save (content/43430819/00000001/savedata.bin/savedata.bin) is plain; u32 at 8 = big-endian word sum of the
# file from offset 12. mTempData.mHistory.mUnlockFlag (named in the game's own property table) is the u32 at 0xBC:
# 0xFFFFFFFF skips the forced prologue and opens Campaign, Extra Content > The Mercenaries and Agent Hunt.
SAVE_REL = Path("content") / "43430819" / "00000001" / "savedata.bin" / "savedata.bin"


def save_path(cfg) -> Path:
    from .xenia import install_dir
    return install_dir(cfg) / SAVE_REL


def save_backup(cfg) -> Path:
    return re6.runtime(cfg) / "save_backup" / "43430819"


def _save_sum(d: bytes) -> int:
    n = (len(d) - 12) // 4
    return sum(struct.unpack_from(f">{n}I", d, 12)) & 0xFFFFFFFF


# "Everything unlocked" = what the game's own unused debug routine 0x824D8800 (this = save manager [0x83CA4F98]) does:
# every campaign / chapter / difficulty record, all skills, Mercenaries stages (u32 at 0x974, 10 bits) and characters +
# costumes (u32 at 0x978, 30 bits; 0x10101 = Leon / Chris / Jake by default), figures / emblems / titles / special
# features. gBox ran it once in the game, let the game write its save, and keeps the result as a template
# (profiles/gamedata/0871eee3b68cdea3-unlock.json): offsets are save-file offsets; the running game keeps the same bytes at
# [0x83CA4F98] + idx * 0x8A04 + 0x30 (idx = u32 at manager+0x24), so the same template applies live.
# Save-file map: 0xBC mUnlockFlag; 0xCC-0x6F8 story/chapter/collection progress; 0x6F8 skill points; 0x700 skills owned
# (97); 0x974 / 0x978 Mercenaries stage / character masks; 0x164C campaign records [7 characters][5 chapters]
# [5 difficulties] x 12 bytes {u32 flags, u32 rank, f32 time}; 0x235C Mercenaries records [solo, duo][10 stages]
# [16 characters] x 12 {u8 played, u8 rank (0 = best), u32 score, u8 kills, combo, costume, partner}; 0x4AF0
# per-character Mercenaries inventories (same 0x70-byte records as the loadout table).
MGR, MGR_STRIDE, MGR_SAVE = 0x83CA4F98, 0x8A04, 0x30
_UNLOCK: dict = {}


def unlock_template() -> dict:
    if not _UNLOCK:
        f = Path(__file__).resolve().parent.parent / "profiles" / "gamedata" / f"{re6.GAME_ID}-unlock.json"
        _UNLOCK.update(json.loads(f.read_text()))
    return _UNLOCK


def apply_unlock(d: bytearray) -> int:
    """Everything unlocked, applied to a save image (file layout from offset 0). Only raises values: what the player
    already has (better ranks / times, Mercenaries scores, skill points) is kept. Returns the number of bytes changed."""
    t = unlock_template()
    before = bytes(d)
    for off, val in t["or32"].items():
        o = int(off, 16)
        struct.pack_into(">I", d, o, struct.unpack_from(">I", d, o)[0] | int(val, 16))
    for off in t["flags8"]:
        o = int(off, 16)
        d[o] = max(d[o], 1)
    for r in t["regions"]:
        o, src, m = int(r["off"], 16), bytes.fromhex(r["hex"]), r["mode"]
        if m == "max8":
            d[o:o + len(src)] = bytes(max(a, b) for a, b in zip(d[o:o + len(src)], src))
        elif m == "max32":
            n = len(src) // 4
            cur, new = struct.unpack_from(f">{n}I", d, o), struct.unpack(f">{n}I", src)
            struct.pack_into(f">{n}I", d, o, *[max(a, b) for a, b in zip(cur, new)])
        elif m == "rec12":                               # campaign record: only where the player has none
            for k in range(0, len(src), 12):
                if not struct.unpack_from(">I", d, o + k)[0]:
                    d[o + k:o + k + 12] = src[k:k + 12]
    return sum(1 for a, b in zip(before, d) if a != b)


def unlock_save(cfg) -> dict:
    """Offline: everything unlocked in Xenia's RE6 save (backup of the original kept once; restore_save = revert)."""
    sp = save_path(cfg)
    if not sp.is_file():
        raise FileNotFoundError("no RE6 save yet: start the game once (it creates the save at the title screen)")
    bk = save_backup(cfg)
    if not bk.exists():
        shutil.copytree(sp.parents[2], bk)                 # content/43430819 as it was
    d = bytearray(sp.read_bytes())
    if struct.unpack_from(">I", d, 8)[0] != _save_sum(d):
        raise ValueError("the save's checksum doesn't match: not touching it")
    before = struct.unpack_from(">I", d, 0xBC)[0]
    n = apply_unlock(d)
    if n:
        struct.pack_into(">I", d, 8, _save_sum(d))
        sp.write_bytes(bytes(d))
    return {"unlock_flag": {"before": hex(before), "after": hex(struct.unpack_from(">I", d, 0xBC)[0])},
            "bytes_changed": n, "already_unlocked": n == 0, "backup": str(bk)}


def _runs(a: bytes, b: bytes, gap: int = 16):
    """[(start, end)] of the differing bytes, runs closer than `gap` merged."""
    out = []
    for i in (i for i in range(len(a)) if a[i] != b[i]):
        if out and i - out[-1][1] < gap:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return out


def unlock_live(ad) -> dict:
    """The same template written into the running game's save data (any screen); the game writes it to the save at its
    next save point (end of a match / chapter, or the menus' own saves)."""
    mgr = _u32(ad, MGR)
    if not mgr:
        raise Unsupported("RE6's save manager isn't up yet (still booting)")
    base = mgr + _u32(ad, mgr + 0x24) * MGR_STRIDE + MGR_SAVE
    cur = ad.read_memory(base, 0x4500)
    d = bytearray(cur)
    n = apply_unlock(d)
    for s, e in _runs(cur, d):
        ad.write_memory(base + s, bytes(d[s:e]))
    # the save I/O object keeps the file image it read at boot (+0xC910, 0x6000 bytes, file layout) and the menus
    # re-read the manager's data from it (seen: title -> main menu): patch that image too, checksum included
    io = _u32(ad, SAVE_IO)
    img = None
    if io and _u32(ad, io + SAVE_IO_BUF) == SAVE_MAGIC:
        cur2 = ad.read_memory(io + SAVE_IO_BUF, 0x6000)
        f = bytearray(cur2)
        img = apply_unlock(f)
        struct.pack_into(">I", f, 8, _save_sum(f))
        for s, e in _runs(cur2, f):
            ad.write_memory(io + SAVE_IO_BUF + s, bytes(f[s:e]))
    return {"bytes_changed": n, "file_image_bytes_changed": img, "stage_mask": hex(_u32(ad, base + 0x974)),
            "character_mask": hex(_u32(ad, base + 0x978))}


def restore_save(cfg) -> bool:
    bk = save_backup(cfg)
    if not bk.exists():
        return False
    dst = save_path(cfg).parents[2]
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(bk, dst)
    return True


# ------------------------------------------------------------------ default boot profile "RE6: Everything unlocked"
# Every RE6 launch through gBox (settings everything_unlocked / boot_to_title, both on by default):
#  * before Xenia starts, the save gets the everything-unlocked template (backup of the original kept; revert_all or
#    unlock_all on=false restores it); the forced prologue is skipped by the save's mUnlockFlag;
#  * right after boot, two 1-word code patches skip the RE6 logo movie that plays after PRESS START (two paths load it):
#    - the first-boot title sequence (0x823AF6A0, state 10) loads "movie\re6logo" through sResource vtable+0x30 (the
#      bctrl at 0x823AF9B0) and, when that returns nothing, goes straight on to the title: the patch makes the call
#      return 0 (li r3, 0);
#    - the opening scene (0x82FD7908) plays movie index 0/1 (bh6logo / re6logo; 2/3 = the title loops) through
#      0x82FD67A0, which already skips any index < 0 or > 3: the patch moves the lower bound to 2 (cmpwi r9, 2), so the
#      logo movies are skipped and the title loops still play.
#    Leaving the movie file out of a mod folder instead does NOT work (the game shows "Disc Read Error"). Like Auto QTE
#    the patches must land before the code is first compiled (gBox writes them as soon as the executable is in memory);
#  * with no real controller connected, gBox then presses START / A through PRESS START and the three notices (Xbox LIVE,
#    loading content, storage) until the title screen (_auto_title).
TITLE_PATCHES = [(0x823AF9B0, 0x4E800421, 0x38600000), (0x82FD67B4, 0x2F090000, 0x2F090002)]


def title_install(ad) -> str:
    res = []
    for a, orig, new in TITLE_PATCHES:
        cur = struct.unpack(">I", ad.read_memory(a, 4))[0]
        if cur == new:
            res.append("already")
        elif cur != orig:
            res.append("unknown code")
        else:
            ad.write_memory(a, struct.pack(">I", new))
            res.append("patched")
    return "patched" if all(r == "patched" for r in res) else "/".join(res)


def pre_launch(ctx, mod: str = "") -> dict:
    """Called by launch_game before Xenia starts RE6: everything unlocked in the save (setting everything_unlocked)."""
    _LIVE["cfg"] = ctx.config
    st = settings(ctx.server, ctx.headers)
    out = {"everything_unlocked": bool(st.get("everything_unlocked", True)), "boot_to_title": bool(st.get("boot_to_title", True))}
    if out["everything_unlocked"]:
        try:
            out["unlock"] = unlock_save(ctx.config)
        except (FileNotFoundError, ValueError) as e:       # first boot: the game creates the save; the next launch unlocks
            out["unlock"] = {"error": str(e)}
    _LIVE["pre"] = out
    return out


# ------------------------------------------------------------------ auto loadout watcher

def _saved_loadout(server, headers) -> dict | None:
    import httpx
    try:
        return httpx.get(f"{server}/api/re6/loadout", params={"game_id": re6.GAME_ID}, headers=headers, timeout=10).json()
    except Exception:                                      # noqa: BLE001
        return None


def _watch(cfg, server, headers):
    """Every few seconds: each running RE6 session whose saved loadout has auto=true gets the table rewritten if it
    differs (a fresh boot, or the game reset it). Matches started from character select then use it."""
    from .tools import SESSIONS
    while True:
        try:
            sids = [s for s, (ad, g) in list(SESSIONS.items()) if isinstance(g, dict) and g.get("game_id") in GAME_IDS]
            want = _saved_loadout(server, headers) if sids else None
            for sid in sids:
                ad = SESSIONS[sid][0]
                if not want or not want.get("auto") or not want.get("items"):
                    continue
                try:
                    _guard(sid)
                    items = [(int(i["id"]), int(i.get("amount") or 0)) for i in want["items"]]
                    before = _records(ad)
                    expect = [build_record(r, items, want.get("replace", True)) for r in before]
                    if expect != before:
                        apply_loadout(ad, cfg, items, "", want.get("replace", True))
                        _STATE["auto"][sid] = time.time()
                except Exception:                          # noqa: BLE001 - game still booting / not mapped yet
                    pass
        except Exception:                                  # noqa: BLE001
            pass
        time.sleep(5)


def ensure_watcher(ctx):
    if _STATE["watch"] and _STATE["watch"].is_alive():
        return
    if not ctx.server:
        return
    _STATE["watch"] = threading.Thread(target=_watch, args=(ctx.config, ctx.server, ctx.headers), daemon=True,
                                       name="re6-auto-loadout")
    _STATE["watch"].start()


# ------------------------------------------------------------------ live player: health, ammo, give now, Auto QTE (verified in game)
# sPlayer (static pointer at 0x83CA52FC): +0x28.. = the player characters (uPlayer; +0x28 = player 1, also in the campaign).
# uPlayer: +0x18 cUnit mDeltaTime, +0x50 position (x, y, z), +0xF20 s16 Life, +0xF22 s16 LifeMax (the game's own
# Life/LifeMax properties), +0x3EE8 current slot, +0x3EF0 the inventory: 24 cItem slots of 0x1C bytes
#   +4 u8 active, +5 u8 slot no, +6 u16 item code (type << 8 | id: 1xx weapon/grenade/recovery, 2xx ammo, 3xx herb),
#   +8 u8 mode, +9 u8 mode max, +0xA u16 mNum[3] (count per mode), +0x10 u16 mMax[3], +0x18 weapon object (uWp*).
# uPlayer::setItem(this, slot (-1 = first free), code, count (-1 = default), mode, weapon) = 0x82B1C1C8: the game's own
# "add an item" (creates the weapon object for guns). gBox calls it on the game thread through a one-shot hook: the player
# object gets a private copy of its vtable whose slot 9 (+0x24, called once per frame) is a small stub in the .text padding
# (0x83C17800); the stub puts the real vtable back, calls the function, then the original slot. Data lives at the end of
# .bss (0x83D6F000..0x83D70000, unused; .text pages are read-only for guest stores, so data can't go there).
# A gun needs its model resident (the Mercenaries stage only loads the chosen loadout's guns): a gun that isn't loaded
# would make the game wait forever for a file that isn't on disk loose, so give_now only does guns the player already
# has a model for; other guns go into the Mercenaries loadout table (next match / Retry).
SPLAYER, LIFE, INV, SLOT_SZ = 0x83CA52FC, 0xF20, 0x3EF0, 0x1C
SETITEM = 0x82B1C1C8
INJ_STUB, INJ_VT, INJ_DATA, INJ_SLOT = 0x83C17800, 0x83D6F000, 0x83D6FC00, 9
GRENADES, RECOVERY = {19, 20, 21, 22}, {29, 32}
# Auto QTE: sActionButton::ButtonUnit::update (0x82446078) checks the unit's prompt by type (press / hold / mash / timing /
# stick...) and joins at 0x8244646C with r28 = success. The patch branches there to a stub (0x83C16400) that forces
# r28 = 1 unless the u32 at 0x83D6FFF0 is non-zero (the runtime off switch) or the prompt is a context action (definition
# id 0x1A-0x1F, 0x2A-0x2C, 0x79). Xenia compiles guest code once, so the patch must land before the first prompt is
# processed: gBox writes it right after the game boots (on_launch); flipping the switch works at any time.
QTE_JOIN, QTE_CAVE, QTE_FLAG = 0x8244646C, 0x83C16400, 0x83D6FFF0
QTE_ORIG = bytes.fromhex("578b063e")
QTE_CODE = [0x3D6083D7, 0x816BFFF0, 0x2C0B0000, 0x40820040, 0x817F000C, 0x280B0000, 0x41820034, 0x816B0030,
            0x280B001A, 0x41800024, 0x280B001F, 0x40810020, 0x280B002A, 0x41800014, 0x280B002C, 0x40810010,
            0x280B0079, 0x41820008, 0x3B800001, 0x578B063E, 0x2B0B0000, 0x4A830020]
_LIVE = {"holds": {}, "qte": {}, "title": {}, "inj": threading.Lock()}


def _u32(ad, a):
    return struct.unpack(">I", ad.read_memory(a, 4))[0]


def players(ad) -> list[int]:
    sp = _u32(ad, SPLAYER)
    if not sp:
        return []
    out = []
    for k in range(4):
        p = _u32(ad, sp + 0x28 + 4 * k)
        if p and 0x40000000 <= p < 0x50000000:
            out.append(p)
    return out


def item_code(iid: int) -> int:
    if iid < 100:
        return 0x100 | iid
    if iid < 200:
        return 0x200 | (iid - 100)
    if iid < 300:
        return 0x300 | (iid - 200)
    raise ValueError(f"item {iid} isn't carried (skill points / key items)")


def code_item(code: int) -> int:
    t, i = code >> 8, code & 0xFF
    return {1: i, 2: 100 + i, 3: 200 + i}.get(t, -1)


def live_inventory(ad, cfg, p) -> list[dict]:
    names = _names(cfg)
    inv = ad.read_memory(p + INV, SLOT_SZ * 24)
    out = []
    for k in range(24):
        s = inv[k * SLOT_SZ:(k + 1) * SLOT_SZ]
        if not s[4]:
            continue
        code = struct.unpack_from(">H", s, 6)[0]
        iid = code_item(code)
        out.append({"slot": k, "id": iid, "name": names.get(iid, hex(code)), "count": struct.unpack_from(">H", s, 0xA)[0],
                    "max": struct.unpack_from(">H", s, 0x10)[0], "weapon_object": bool(struct.unpack_from(">I", s, 0x18)[0])})
    return out


def _inject_stub() -> bytes:
    """The generic one-shot call stub (constant code, so Xenia compiles it once). Data block at INJ_DATA:
    +0 real vtable, +4 original slot function, +8 function to call, +12..+28 r4..r8, +32 result."""
    words = [0x7D8802A6, 0x9181FFF8, 0x9421FF70, 0x90610010, 0x90810014, 0x90A10018, 0x90C1001C, 0x90E10020,
             0x91010024, 0x91210028, 0x9141002C, 0xD8210030, 0xD8410038]
    ha, lo = (INJ_DATA + 0x8000) >> 16, INJ_DATA & 0xFFFF
    lis_addi = [0x3D600000 | ha, 0x396B0000 | lo]                     # lis r11, ha; addi r11, r11, lo
    words += lis_addi + [0x818B0000, 0x91830000,                        # lwz r12,0(r11); stw r12,0(r3)
                         0x818B0008, 0x7D8903A6,                        # lwz r12,8(r11); mtctr r12
                         0x808B000C, 0x80AB0010, 0x80CB0014, 0x80EB0018, 0x810B001C,   # r4..r8
                         0x4E800421]                                     # bctrl
    words += lis_addi + [0x906B0020, 0x818B0004, 0x7D8903A6,            # stw r3,32(r11); lwz r12,4(r11); mtctr r12
                         0x80610010, 0x80810014, 0x80A10018, 0x80C1001C, 0x80E10020, 0x81010024, 0x81210028, 0x8141002C,
                         0xC8210030, 0xC8410038, 0x4E800421,             # restore args, bctrl (the original slot)
                         0x38210090, 0x8181FFF8, 0x7D8803A6, 0x4E800020]  # addi r1; lwz r12,-8(r1); mtlr; blr
    return struct.pack(f">{len(words)}I", *words)


def _s32(v: int) -> int:
    v = int(v) & 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def call_on_player(ad, p, func: int, args=(0, 0, 0, 0, 0), timeout=3.0) -> int:
    """func(player, *args) on the game thread (next frame). Returns its r3 (args may be addresses: packed as s32)."""
    with _LIVE["inj"]:
        vt = _u32(ad, p)
        if vt == INJ_VT:
            raise RuntimeError("a previous gBox call is still pending on this player")
        ents = ad.read_memory(vt, 0x800)
        stub = _inject_stub()
        if ad.read_memory(INJ_STUB, len(stub)) != stub:
            ad.write_memory(INJ_STUB, stub)
        slot_fn = struct.unpack_from(">I", ents, 4 * INJ_SLOT)[0]
        ad.write_memory(INJ_DATA, struct.pack(">IIIiiiiii", vt, slot_fn, func, *[_s32(a) for a in args], -0x7FFF))
        ad.write_memory(INJ_VT, ents[:4 * INJ_SLOT] + struct.pack(">I", INJ_STUB) + ents[4 * INJ_SLOT + 4:])
        ad.write_memory(p, struct.pack(">I", INJ_VT))
        t = time.time()
        while time.time() - t < timeout:
            if _u32(ad, p) == vt:
                # the stub puts the real vtable back *before* the call: wait for the result word (sentinel -0x7FFF)
                while time.time() - t < timeout + 5:
                    r = struct.unpack(">i", ad.read_memory(INJ_DATA + 32, 4))[0]
                    if r != -0x7FFF:
                        return r
                    time.sleep(0.01)
                return r
            time.sleep(0.03)
        ad.write_memory(p, struct.pack(">I", vt))
        raise RuntimeError("the game didn't run the call (paused, in a menu or a cutscene?)")


# Item id -> weapon unit class (uWpNNNN; its resources are nativeXenon/arc/X360/uWpNNNN.arc). Read from the game's own class
# registry (every uWp DTI carries key 7 << 24 | item code << 8 at +0x1C), dumped once from the running game.
WP_CLASS = {1: 1010, 2: 1011, 3: 1012, 4: 1020, 5: 1021, 6: 1022, 7: 1030, 8: 1031, 9: 1040, 10: 1041, 11: 1050, 12: 1060,
            13: 1061, 14: 1062, 15: 1070, 16: 1071, 17: 1072, 18: 1080, 19: 1090, 20: 1092, 21: 1094, 22: 1096, 23: 1100,
            24: 1110, 25: 1111, 26: 1112, 27: 1120, 28: 1150, 29: 1160, 30: 1151, 31: 1161, 32: 1173, 34: 1350, 35: 1352,
            36: 1359, 37: 1357, 38: 1051, 39: 1130, 40: 1063}


def weapon_class(ad, code: int) -> str | None:
    """Item code (0x1nn) -> weapon class name, e.g. 0x108 -> uWp1031."""
    n = WP_CLASS.get(code - 0x100) if code >> 8 == 1 else None
    return f"uWp{n}" if n else None


# Preloading a weapon (the fix for "a gun the stage didn't load froze the game"): the gun's model/motion/effect resources
# are the unit archive arc/X360/uWpNNNN.arc. A Mercenaries stage only loads the archives of the chosen loadout, so setItem
# of another gun creates a weapon whose resources never arrive. gBox first asks the game's resource manager for that
# archive on the game thread - sResource ([0x83D3E9EC]) vtable+0x30 = getResource(this, DTI rArchive (0x83D41424),
# "arc\\X360\\uWpNNNN", 1) - the same call the game uses for its own movies; it loads synchronously (~0.05 s for one gun)
# and returns the archive, which gBox keeps referenced (never released) so the weapon's resources stay resident.
# The trampoline VCALL is constant code in the .text padding: r3 = *[D2+0]; ctr = (*r3)[D2+4]; bctr (r4.. from the stub).
SRESOURCE, RARCHIVE_DTI = 0x83D3E9EC, 0x83D41424
VCALL, VCALL_D, VCALL_PATH = 0x83C17C40, 0x83D6FD00, 0x83D6FD40
VCALL_CODE = [0x3D6083D7, 0x396BFD00, 0x806B0000, 0x80630000, 0x81830000, 0x800B0004, 0x7D8C002E, 0x7D8903A6, 0x4E800420]


def preload_weapon(ad, p, iid: int) -> dict:
    """Load the gun's unit archive through the game's resource manager (game thread). {'class', 'resource'}."""
    cls = weapon_class(ad, 0x100 | iid)
    if not cls:
        raise ValueError(f"item {iid} has no weapon unit class")
    code = struct.pack(f">{len(VCALL_CODE)}I", *VCALL_CODE)
    if ad.read_memory(VCALL, len(code)) != code:
        ad.write_memory(VCALL, code)
    ad.write_memory(VCALL_PATH, ("arc\\X360\\" + cls).encode().ljust(64, b"\0"))
    ad.write_memory(VCALL_D, struct.pack(">II", SRESOURCE, 0x30))
    r = call_on_player(ad, p, VCALL, (RARCHIVE_DTI, VCALL_PATH, 1, 0, 0), timeout=20) & 0xFFFFFFFF
    _LIVE.setdefault("preloaded", {})[cls] = r
    return {"class": cls, "resource": r}


def is_gun(iid: int) -> bool:
    return 0 < iid < 100 and iid not in GRENADES | RECOVERY


def give_now(ad, cfg, iid: int, amount: int = 0, all_players=False, slot: int = -1) -> dict:
    ps = players(ad)
    if not ps:
        raise Unsupported("no player in the game right now (start a match / load the chapter first)")
    code = item_code(iid)
    names = _names(cfg)
    pre, ammo = None, None
    if is_gun(iid):
        inv = ad.read_memory(ps[0] + INV, SLOT_SZ * 24)
        rows = [inv[k * SLOT_SZ:(k + 1) * SLOT_SZ] for k in range(24)]
        held = [r for r in rows if r[4] and r[5] < 7 and code_item(struct.unpack_from(">H", r, 6)[0]) == iid]
        if held and slot < 0:                              # already carried: top the magazine up instead of a 2nd copy
            r = held[0]
            n = amount if amount > 0 else struct.unpack_from(">H", r, 0x10)[0]
            ad.write_memory(_slot_addr(ad, ps[0], r[5]) + 0xA, struct.pack(">H", min(n, 0xFFFE)))
            return {"live": True, "slots": [r[5]], "item": iid, "name": names.get(iid, iid), "preloaded": None,
                    "topped_up": n}
        # a gun the stage didn't load: preload its unit archive first (see preload_weapon), else the game waits forever
        known = {code_item(struct.unpack_from(">H", r, 6)[0]) for r in rows if r[5] < 7}
        if iid not in known and weapon_class(ad, code):
            pre = preload_weapon(ad, ps[0], iid)
            if not pre["resource"]:
                return {"live": False, "reason": f"the game couldn't load {names.get(iid, iid)}'s resources "
                        f"({pre['class']}.arc); it was added to the Mercenaries loadout instead"}
        am = AMMO_OF.get(iid)                              # its ammo too, if the case has none
        if am and not any(r[4] and code_item(struct.unpack_from(">H", r, 6)[0]) == am for r in rows):
            ammo = am
    res = []
    for p in (ps if all_players else ps[:1]):
        r = call_on_player(ad, p, SETITEM, (slot, code, amount if amount > 0 else -1, 0, 0))
        res.append(r)
        if ammo and r >= 0:
            call_on_player(ad, p, SETITEM, (-1, item_code(ammo), STOCK.get(ammo, 30), 0, 0))
    return {"live": True, "slots": res, "item": iid, "name": names.get(iid, iid),
            "preloaded": pre["class"] if pre else None, "ammo_added": names.get(ammo) if ammo else None}


def _slot_addr(ad, p, slot: int) -> int:
    """Address of the cItem whose slot number (+5) is `slot` (the 24 entries aren't always in slot order)."""
    inv = ad.read_memory(p + INV, SLOT_SZ * 24)
    for k in range(24):
        if inv[k * SLOT_SZ + 5] == slot:
            return p + INV + k * SLOT_SZ
    raise ValueError(f"no inventory slot {slot} (0-6 weapons, 7-12 grenade/recovery selectors, 15-23 case)")


def remove_item(ad, cfg, slot: int) -> dict:
    """Empty one slot. Case/ammo/herb/grenade slots go through the game's own setItem (count -2 = clear); a gun slot is
    marked not-owned (active 0, the way the game itself keeps guns it isn't carrying); the gun in hand is refused."""
    ps = players(ad)
    if not ps:
        raise Unsupported("no player in the game right now")
    p = ps[0]
    a = _slot_addr(ad, p, slot)
    s = ad.read_memory(a, SLOT_SZ)
    if not s[4]:
        return {"slot": slot, "removed": None, "message": f"Slot {slot} is already empty."}
    code = struct.unpack_from(">H", s, 6)[0]
    iid = code_item(code)
    nm = _names(cfg).get(iid, hex(code))
    if code >> 8 == 1 and slot < 7:
        if _u32(ad, p + 0x3EE8) == slot:
            raise ValueError(f"{nm} is the gun in the player's hands right now: switch to another weapon first")
        ad.write_memory(a + 4, b"\0")
    else:
        call_on_player(ad, p, SETITEM, (slot, code, -2, 0, 0))
    return {"slot": slot, "removed": {"id": iid, "name": nm}, "message": f"{nm} removed from slot {slot}."}


def set_slot(ad, cfg, slot: int, iid: int | None, amount: int = 0) -> dict:
    """Change one inventory slot live: a different item (gun slots 0-6 take guns, case slots ammo/herbs/grenades/sprays),
    or only the count (amount = loaded rounds / stack size)."""
    ps = players(ad)
    if not ps:
        raise Unsupported("no player in the game right now")
    p = ps[0]
    a = _slot_addr(ad, p, slot)
    s = ad.read_memory(a, SLOT_SZ)
    cur = code_item(struct.unpack_from(">H", s, 6)[0]) if s[4] else None
    names = _names(cfg)
    if iid is not None and iid != cur:
        if is_gun(iid) != (slot < 7):
            raise ValueError("slots 0-6 hold guns, 15-23 the case (ammo, herbs, grenades, sprays)")
        if s[4]:
            remove_item(ad, cfg, slot)
        if is_gun(iid):
            r = give_now(ad, cfg, iid, amount)              # the game picks the gun slot (reuses its own record)
        else:
            r = give_now(ad, cfg, iid, amount, slot=slot)
        got = (r.get("slots") or [slot])[0]
        msg = ((f"{names.get(cur, cur)} in slot {slot} replaced by " if cur is not None else "") + f"{names.get(iid, iid)}"
               + (f" (the game put it in gun slot {got})" if got != slot else f" in slot {got}") + ".")
        return r | {"slot": got, "replaced": names.get(cur) if cur is not None else None,
                    "message": msg if got is not None and got >= 0 else f"The game refused {names.get(iid, iid)}."}
    if not s[4]:
        raise ValueError(f"slot {slot} is empty: give an item")
    n = max(0, min(0xFFFE, int(amount)))
    mode = s[8] if s[8] < 3 else 0
    ad.write_memory(a + 0xA + 2 * mode, struct.pack(">H", n))
    return {"slot": slot, "id": cur, "name": names.get(cur, cur), "count": n,
            "message": f"{names.get(cur, cur)} in slot {slot}: {n}."}


def _hold_loop(sid: str, kind: str, stop: threading.Event):
    from .tools import SESSIONS
    while not stop.is_set():
        try:
            ad = SESSIONS[sid][0]
            for p in players(ad):
                if kind == "health":
                    life, mx = struct.unpack(">hh", ad.read_memory(p + LIFE, 4))
                    if 0 < mx < 30000 and life != mx:
                        ad.write_memory(p + LIFE, struct.pack(">h", mx))
                else:
                    inv = bytearray(ad.read_memory(p + INV, SLOT_SZ * 24))
                    for k in range(24):
                        s = inv[k * SLOT_SZ:(k + 1) * SLOT_SZ]
                        if not s[4]:
                            continue
                        code = struct.unpack_from(">H", s, 6)[0]
                        t, i = code >> 8, code & 0xFF
                        if t == 3 or (t == 1 and i in RECOVERY):
                            continue
                        num = list(struct.unpack_from(">3H", s, 0xA)); mx = list(struct.unpack_from(">3H", s, 0x10))
                        if t == 1 and i in GRENADES and not any(num):
                            continue                          # don't hand out grenades the player doesn't carry
                        new = [m if 0 < m < 0xFFFF else n for n, m in zip(num, mx)]
                        if new != num:
                            ad.write_memory(p + INV + k * SLOT_SZ + 0xA, struct.pack(">3H", *new))
        except KeyError:
            return
        except Exception:                                  # noqa: BLE001 - loading screens: no player for a moment
            pass
        stop.wait(0.05)


def set_hold(sid: str, kind: str, on: bool):
    key = (sid, kind)
    old = _LIVE["holds"].pop(key, None)
    if old:
        old.set()
    if on:
        ev = threading.Event()
        _LIVE["holds"][key] = ev
        threading.Thread(target=_hold_loop, args=(sid, kind, ev), daemon=True, name=f"re6-{kind}").start()


def qte_install(ad) -> str:
    """Write the Auto QTE stub + branch (once per boot). 'patched' / 'already' / 'late' (the function had run already)."""
    cur = ad.read_memory(QTE_JOIN, 4)
    if cur != QTE_ORIG:
        return "already"
    ad.write_memory(QTE_CAVE, struct.pack(f">{len(QTE_CODE)}I", *QTE_CODE))
    ad.write_memory(QTE_JOIN, struct.pack(">I", (18 << 26) | ((QTE_CAVE - QTE_JOIN) & 0x3FFFFFC)))
    return "patched"


def qte_set(ad, on: bool):
    ad.write_memory(QTE_FLAG, struct.pack(">I", 0 if on else 1))


SETTING_DEFAULTS = {"auto_qte": True, "infinite_health": False, "infinite_ammo": False, "everything_unlocked": True,
                    "boot_to_title": True}


def _local_settings_file() -> Path | None:
    cfg = _LIVE.get("cfg")
    return re6.runtime(cfg) / "settings_local.json" if cfg is not None else None


def settings(server, headers) -> dict:
    """The saved RE6 switches: control plane (GET /api/re6/settings) over a node-local copy (switches the control plane
    doesn't know yet, e.g. before it was restarted with a newer gBox) over the defaults."""
    import httpx
    local = {}
    f = _local_settings_file()
    try:
        if f and f.is_file():
            local = json.loads(f.read_text())
    except (OSError, ValueError):
        pass
    try:
        srv = httpx.get(f"{server}/api/re6/settings", headers=headers, timeout=10).json()
    except Exception:                                      # noqa: BLE001
        srv = {}
    return SETTING_DEFAULTS | local | {k: v for k, v in srv.items() if k in SETTING_DEFAULTS or k == "game_id"}


def _boot_patch(sid: str, server, headers):
    """Right after RE6 starts: wait for the executable image, then (before the code first runs) the logo-movie skip and
    Auto QTE, then the saved switches."""
    from .tools import SESSIONS
    st = settings(server, headers)
    t = time.time()
    while time.time() - t < 300 and sid in SESSIONS:
        ad = SESSIONS[sid][0]
        try:
            if ad.read_memory(TITLE_CHECK[0], len(TITLE_CHECK[1])) == TITLE_CHECK[1]:
                if st.get("boot_to_title", True):
                    _LIVE["title"][sid] = title_install(ad)
                    threading.Thread(target=_auto_title, args=(sid,), daemon=True, name="re6-title").start()
                _LIVE["qte"][sid] = qte_install(ad)
                qte_set(ad, bool(st.get("auto_qte", True)))
                set_hold(sid, "health", bool(st.get("infinite_health")))
                set_hold(sid, "ammo", bool(st.get("infinite_ammo")))
                return
        except Exception:                                  # noqa: BLE001 - guest memory not mapped yet
            pass
        time.sleep(0.05)


SAVE_IO, SAVE_IO_BUF, SAVE_MAGIC = 0x83CA53F8, 0xC910, 0x12071800


def _save_loaded(ad) -> bool:
    """The save I/O object ([0x83CA53F8], built by 0x824A7A10) has a 0x6000-byte file buffer at +0xC910, zeroed at boot;
    it holds the file (magic 0x12071800 first) once the save was read (or created on a first boot)."""
    io = _u32(ad, SAVE_IO)
    return bool(io) and _u32(ad, io + SAVE_IO_BUF) == SAVE_MAGIC


def _auto_title(sid: str):
    """Press through PRESS START and the three notices (Xbox LIVE / loading content / storage) to the title screen.
    PRESS START takes only START and the notices only A, so until the save is read gBox alternates the two; after it,
    a few more A (the storage notice; A does nothing on the title screen itself), then stops. Only with no real
    controller (the keyboard pad is then player 1); with a pad connected the player presses START, since the game binds
    to the controller that pressed it. With the 2023 Xenia (physical-keyboard driver) a key only goes out while Xenia /
    the gBox window docking it is the active window (never into another app). (Xenia's log is written in bursts, so it
    can't tell when the title is up; the save I/O buffer in memory tells when the save was read.)"""
    from .tools import SESSIONS
    from .xenia import _xinput_connected
    if sid not in SESSIONS:
        return
    ad = SESSIONS[sid][0]
    if _xinput_connected() or not hasattr(ad, "press"):
        _LIVE["title"][sid] = f"{_LIVE['title'].get(sid)}; auto-press skipped (a controller is connected: press START)"
        return
    t = time.time()
    try:
        time.sleep(4)
        k, after = 0, 0
        while time.time() - t < 120 and sid in SESSIONS:
            loaded = _save_loaded(ad)
            if loaded:
                after += 1
                if after > 4:
                    _LIVE["title"][sid] = f"title screen after {time.time() - t:.0f} s"
                    return
            try:
                ad.press("start" if not loaded and k % 2 else "a")
            except RuntimeError:                           # Xenia not the active window right now (old driver): wait
                pass
            k += 1
            time.sleep(1.6 if loaded else 1.2)
        _LIVE["title"][sid] = f"{_LIVE['title'].get(sid)}; the save wasn't read within 120 s"
    except Exception as e:                                 # noqa: BLE001 - window closed
        _LIVE["title"][sid] = f"auto-press stopped: {e}"


def on_launch(sid: str, ctx):
    """Called by launch_game when an RE6 session starts on this node."""
    _LIVE["cfg"] = ctx.config
    threading.Thread(target=_boot_patch, args=(sid, ctx.server, ctx.headers), daemon=True, name="re6-boot").start()
    ensure_watcher(ctx)


# ------------------------------------------------------------------ the tool

class Re6In(BaseModel):
    op: str = "status"          # status | inventory | give | give_now | live_inventory | remove_item | set_slot | set_loadout
                                # (= loadout_set) | auto | unlock_all (= unlock) | everything_unlocked | boot_to_title |
                                # revert_all | catalog | capabilities | build_mod | mods | infinite_ammo | infinite_health | auto_qte | settings
    session_id: str = ""
    slot: int = -1              # remove_item / set_slot: inventory slot number (0-6 guns, 7-12 selectors, 15-23 case)
    item: str = ""              # give: name ('elephant killer', 'hand cannon') or id
    amount: int = 0             # give: ammo / count (0 = a full magazine / sensible stack)
    items: list = []            # set_loadout / auto: names, ids or {id, amount}
    character: str = ""         # give / set_loadout: leon | helena | chris | piers | jake | sherry | ada | agent | any
    replace: bool = True        # set_loadout: clear the character's own guns and case first
    on: bool = True             # auto / infinite_*
    now: bool = True            # set_loadout: write the table now (also when auto)
    target: str = "leon"        # build_mod: the RE6 character to replace
    costume: str = ""           # build_mod: one costume (default: all of them)
    scale: dict = {}            # build_mod: optional fit overrides, including a retarget profile
    enemies: dict = {}          # replace_enemies: {family: collection character} (families: op=enemy_families)
    random: bool = False        # replace_enemies: every family gets a different collection character
    player: str = ""            # replace_enemies: also play as this collection character (Leon's slot)
    launch: bool = True         # replace_enemies: launch RE6 with the mod (replaces the running RE6)
    seed: int | None = None


class Re6Out(BaseModel):
    result: dict


def _items_arg(cfg, items) -> list[tuple[int, int]]:
    out = []
    for it in items:
        if isinstance(it, dict):
            out.append((resolve_item(cfg, it.get("id", it.get("name"))), int(it.get("amount") or 0)))
        else:
            out.append((resolve_item(cfg, it), 0))
    return out


@tool("re6", "1.0", Re6In, Re6Out, capabilities=["runtime", "memory", "mod"], permissions=[P.MEMORY_WRITE], timeout_s=1800,
      artifacts=["re6_preview.png"],
      side_effects=["writes the Mercenaries loadout table in the running game (restored by revert_all)",
                    "live: holds Life / ammo counts, calls the game's own setItem on the game thread (give_now), Auto QTE "
                    "code patch at boot with a runtime off switch (revert_all switches it off)",
                    "unlock_all / boot profile: edits the RE6 save in Xenia's content folder before every launch (backup kept, "
                    "restored by unlock_all on=false / revert_all); logo-movie skip code patch at boot; presses START/A to "
                    "the title when no controller is connected",
                    "build_mod: writes a mod folder under cache/mods (hard links + replaced arcs)"])
def re6_tool(inp: Re6In, ctx):
    """Resident Evil 6 (Xbox 360 in Xenia): Mercenaries loadouts (any item incl. story-only weapons), unlocks,
    character swap mods, revert. Offline only (refuses if the game could be online)."""
    cfg = ctx.config
    op = inp.op
    if op == "capabilities":
        return {"result": character_capabilities()}
    ensure_watcher(ctx)
    if op == "catalog":
        names = _names(cfg)
        return {"result": {"items": [{"id": k, "name": v} for k, v in sorted(names.items()) if k < 440]}}
    if op == "mods":
        return {"result": {"mods": list_mods(cfg)}}
    if op == "enemy_families":
        from . import re6_models as M
        return {"result": {"families": [{"family": f, "label": v[0], "arcs": v[1]} for f, v in M.ENEMIES.items()]}}
    if op == "replace_enemies":
        from . import re6_models as M
        enemies = dict(inp.enemies)
        if inp.random:
            enemies = random_mix(ctx, list(enemies) or list(M.ENEMIES), inp.seed)
        if not enemies:
            raise ValueError("replace_enemies needs enemies={family: character} or random=true")
        r = build_combined(ctx, enemies, inp.player, ctx.progress)
        if inp.launch:
            r |= _launch_mod(ctx, re6.GAME_ID, r["mod"], inp)
        who = ", ".join(f"{e['label']} = {e['character']}" for e in r["enemies"])
        return {"result": r | {"message": f"Built {r['mod']}: {who}" + (f"; you play as {r['player']}" if r["player"] else "")
                               + (". RE6 is starting with it." if inp.launch else ". Launch RE6 with mod " + r["mod"] + ".")}}
    if op == "build_mod":
        if not inp.character:
            raise ValueError("build_mod needs character=<collection name>")
        from . import characters as C
        chars = C._api(ctx, "GET", "/api/characters")
        meta = C.best_match(chars, inp.character) or C.find(chars, inp.character)
        if not meta:
            raise ValueError(f"{inp.character!r} isn't in the collection")
        return {"result": build_character(ctx, meta, inp.target, inp.costume, ctx.progress, scale=inp.scale)}
    if op == "loadout_set":
        op = "set_loadout"
    if op == "weapon_classes":
        names = _names(cfg)
        return {"result": {"weapons": [{"id": i, "name": names.get(i), "class": f"uWp{c}"} for i, c in sorted(WP_CLASS.items())]}}
    if op in ("unlock", "unlock_all", "everything_unlocked"):
        return {"result": unlock_all(ctx, inp.on, setting=op == "everything_unlocked", session_id=inp.session_id)}
    if op == "boot_to_title":
        _save_setting(ctx, "boot_to_title", inp.on)
        return {"result": {"boot_to_title": inp.on, "message": ("From the next RE6 start: the RE6 logo movie is skipped and "
                           "gBox presses through PRESS START and the notices to the title screen (only with no real "
                           "controller connected)." if inp.on else "From the next RE6 start the game boots normally "
                           "(logo movie, PRESS START).") + " The running game isn't changed."}}
    if op == "revert_all":
        return {"result": revert_all(ctx, inp.session_id)}
    if op == "settings":
        _LIVE["cfg"] = cfg
        return {"result": settings(ctx.server, ctx.headers)}
    ad, g, guard = _guard(inp.session_id)
    if op == "status":
        recs = _records(ad)
        orig = _original_table(cfg)
        return {"result": {"mode": mode_of(ad), "online": guard["online"], "title": "Resident Evil 6 (X360)",
                           "loadout_table_modified": b"".join(recs) != orig,
                           "auto_loadout": bool(_STATE["auto"].get(inp.session_id)),
                           "mod": (g.get("_rom_path") or "").replace("\\", "/").split("/mods/")[-1].split("/")[1]
                           if "/mods/" in (g.get("_rom_path") or "").replace("\\", "/") else None,
                           "leon": describe(cfg, recs[0])}}
    if op == "inventory":
        recs = _records(ad)
        rows = [describe(cfg, r) for r in recs]
        if inp.character:
            rows = [r for r in rows if r["character"].lower() == inp.character.lower()]
        return {"result": {"mode": mode_of(ad), "loadouts": rows,
                           "note": "Mercenaries start loadouts per character/costume (what a match from character select gives)"}}
    if op in ("give", "set_loadout", "auto"):
        _STATE["undo"].setdefault(inp.session_id, b"".join(_records(ad)))
        if op == "give":
            iid = resolve_item(cfg, inp.item)
            r = apply_loadout(ad, cfg, [(iid, inp.amount)], inp.character, replace=False)
            nm = _names(cfg).get(iid, iid)
            return {"result": r | {"item": iid, "name": nm, "message": f"{nm} added to the Mercenaries loadout of "
                                   f"{', '.join(r['characters'])}: it's in the case at the start of the next match "
                                   "(pick the character from character select; Continue/Retry keep the running loadout)."}}
        items = _items_arg(cfg, inp.items)
        if op == "auto" and inp.on and items:
            import httpx
            httpx.post(f"{ctx.server}/api/re6/loadout", headers=ctx.headers, timeout=10,
                       json={"game_id": re6.GAME_ID, "items": [{"id": i, "amount": a} for i, a in items], "auto": True,
                             "replace": inp.replace})
        if op == "auto" and not inp.on:
            import httpx
            cur = _saved_loadout(ctx.server, ctx.headers) or {}
            httpx.post(f"{ctx.server}/api/re6/loadout", headers=ctx.headers, timeout=10,
                       json={"game_id": re6.GAME_ID, "items": cur.get("items", []), "auto": False})
            return {"result": {"auto": False, "message": "Saved loadout no longer applied automatically (the current "
                               "table stays until revert_all or a restart)."}}
        if not items and op == "auto":
            items = [(int(i["id"]), int(i.get("amount") or 0)) for i in (_saved_loadout(ctx.server, ctx.headers) or {}).get("items", [])]
        r = apply_loadout(ad, cfg, items, inp.character, inp.replace) if items else {"records": []}
        if op == "auto":
            _STATE["auto"][inp.session_id] = time.time()
        names = _names(cfg)
        return {"result": r | {"items": [{"id": i, "name": names.get(i), "amount": a} for i, a in items],
                               "auto": op == "auto",
                               "message": f"Mercenaries loadout set ({len(items)} items) for "
                                          f"{', '.join(r.get('characters', [])) or 'nobody'}; it's used from the next match "
                                          "started from character select" + (", and re-applied whenever RE6 runs (saved for "
                                          "this game)." if op == "auto" else ".")}}
    if op in ("infinite_ammo", "infinite_health", "auto_qte"):
        key = {"infinite_ammo": "infinite_ammo", "infinite_health": "infinite_health", "auto_qte": "auto_qte"}[op]
        _save_setting(ctx, key, inp.on)
        if op == "auto_qte":
            st = qte_install(ad)
            qte_set(ad, inp.on)
            late = st == "patched" and _LIVE["qte"].get(inp.session_id) is None
            return {"result": {"auto_qte": inp.on, "patch": st, "message": ("Auto QTE on: every button / mash / timing prompt "
                               "succeeds by itself." if inp.on else "Auto QTE off: prompts need your input again.") +
                               (" It was installed after the game had already shown a prompt, so it takes effect from the "
                                "next RE6 start (gBox installs it at boot from now on)." if late and inp.on else "")}}
        set_hold(inp.session_id, "health" if op == "infinite_health" else "ammo", inp.on)
        what = "Infinite health" if op == "infinite_health" else "Infinite ammo"
        return {"result": {op: inp.on, "message": f"{what} {'on' if inp.on else 'off'} (held by gBox while RE6 runs; saved for "
                           "this game, so it comes back on at the next start)." + (" Guns, ammo stacks and carried grenades "
                           "stay full; first-aid sprays and herbs are left alone." if op == "infinite_ammo" and inp.on else "")}}
    if op == "remove_item":
        if inp.slot < 0:
            raise ValueError("remove_item needs slot=<inventory slot> (see live_inventory)")
        return {"result": remove_item(ad, cfg, inp.slot)}
    if op == "set_slot":
        if inp.slot < 0:
            raise ValueError("set_slot needs slot=<inventory slot> and item= and/or amount=")
        iid = resolve_item(cfg, inp.item) if str(inp.item).strip() else None
        return {"result": set_slot(ad, cfg, inp.slot, iid, inp.amount)}
    if op == "live_inventory":
        ps = players(ad)
        if not ps:
            return {"result": {"inventory": [], "message": "No player right now (menu / loading)."}}
        return {"result": {"mode": mode_of(ad), "inventory": live_inventory(ad, cfg, ps[0]),
                           "life": list(struct.unpack(">hh", ad.read_memory(ps[0] + LIFE, 4)))}}
    if op == "give_now":
        iid = resolve_item(cfg, inp.item)
        r = give_now(ad, cfg, iid, inp.amount)
        if not r["live"]:
            _STATE["undo"].setdefault(inp.session_id, b"".join(_records(ad)))
            apply_loadout(ad, cfg, [(iid, inp.amount)], inp.character, replace=False)
            return {"result": r | {"message": r["reason"] + ": pick the character again (or Retry) and it's in the case."}}
        if r.get("topped_up"):
            return {"result": r | {"message": f"{r['name']} is already carried: magazine set to {r['topped_up']}."}}
        return {"result": r | {"message": (f"{r['name']} is in your inventory now" + (f" (its resources {r['preloaded']}"
                               ".arc loaded first)" if r.get("preloaded") else "") + (f", with {r['ammo_added']}"
                               if r.get("ammo_added") else "") + ".") if min(r["slots"]) >= 0 else
                               f"The game refused {r['name']} (no free slot of that kind)."}}
    raise ValueError("op: status | inventory | live_inventory | give | give_now | remove_item | set_slot | set_loadout | "
                     "loadout_set | auto | unlock_all | everything_unlocked | boot_to_title | revert_all | catalog | "
                     "weapon_classes | build_mod | mods | infinite_ammo | infinite_health | auto_qte | settings")


def unlock_all(ctx, on: bool = True, setting: bool = False, session_id: str = "") -> dict:
    """Everything unlocked (on) / the original save back (off). Offline in the save file; also live in every running RE6
    session on this node (the game then saves it itself). setting=True also stores the boot default."""
    from .tools import SESSIONS
    cfg = ctx.config
    if setting:
        _save_setting(ctx, "everything_unlocked", on)
    running = [(s, a) for s, (a, g) in list(SESSIONS.items()) if isinstance(g, dict) and g.get("game_id") in GAME_IDS]
    if not on:
        if running:
            return {"everything_unlocked": False, "restored": False, "message": "RE6 is running: close it, then "
                    "unlock_all on=false (or revert_all) puts the original save back (the running game would write its "
                    "own copy over it)." + (" Saved: the next starts keep the original save." if setting else "")}
        ok = restore_save(cfg)
        return {"everything_unlocked": False, "restored": ok, "message": ("Original RE6 save restored from gBox's backup."
                if ok else "No backup: gBox never changed this save.") + (" Saved: RE6 starts with the save as it is."
                if setting else "")}
    out = {"everything_unlocked": True}
    try:
        out["save"] = unlock_save(cfg)
    except (FileNotFoundError, ValueError) as e:
        out["save"] = {"error": str(e)}
    live = {}
    for sid, ad in running:
        try:
            _guard(sid)
            live[sid] = unlock_live(ad)
        except Exception as e:                             # noqa: BLE001 - still booting / not mapped
            live[sid] = {"error": str(e)}
    out["live"] = live
    out["message"] = ("Everything unlocked: all campaigns, chapters and difficulties (Amateur-Professional), Agent Hunt, "
                      "The Mercenaries with all 3 stages on this disc and all 9 characters with their EX costumes, every "
                      "skill, figures / emblems / titles / special features." + (" Live in the running game too "
                      "(menus update when re-entered; the game saves it at its next save point)." if running else
                      " Launch RE6 to use it.") + (" Saved as the boot default." if setting else ""))
    out["not_on_this_disc"] = ("No Hope difficulty, Mercenaries No Mercy and the DLC stages / retro costumes are later "
                               "title-update / DLC / PC content, not in this Xbox 360 build (BH6MasterRelease Jul 2012)")
    return out


def _save_setting(ctx, key: str, val: bool):
    import httpx
    _LIVE["cfg"] = ctx.config
    f = _local_settings_file()
    try:                                                   # node-local copy (see settings())
        cur = json.loads(f.read_text()) if f.is_file() else {}
        cur[key] = bool(val)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cur))
    except (OSError, ValueError):
        pass
    try:
        httpx.post(f"{ctx.server}/api/re6/settings", headers=ctx.headers, timeout=10, json={key: bool(val)})
    except Exception:                                      # noqa: BLE001 - the live change still happens
        pass


def revert_all(ctx, session_id: str = "") -> dict:
    """Everything gBox did to RE6, undone: loadout table back to the shipped one in every running RE6 session,
    auto-apply off, save restored from the backup, gBox's RE6 mod folders deleted (unless one is running)."""
    from .tools import SESSIONS
    cfg, out = ctx.config, {"tables": [], "save_restored": False, "mods_removed": [], "mods_kept": []}
    orig = _original_table(cfg)
    running_mods = set()
    for sid, (ad, g) in list(SESSIONS.items()):
        if not (isinstance(g, dict) and g.get("game_id") in GAME_IDS):
            continue
        rp = (g.get("_rom_path") or "").replace("\\", "/")
        if "/mods/" in rp:
            running_mods.add(rp.split("/mods/")[1].split("/")[1])
        try:
            ad.write_memory(MERC_TABLE, orig)
            out["tables"].append(sid)
        except Exception as e:                             # noqa: BLE001
            out["tables"].append(f"{sid}: {e}")
    _STATE["auto"].clear()
    _STATE["undo"].clear()
    for (hs, kind) in list(_LIVE["holds"]):
        set_hold(hs, kind, False)
    for sid, (ad, g) in list(SESSIONS.items()):
        if isinstance(g, dict) and g.get("game_id") in GAME_IDS:
            try:
                qte_set(ad, False)
            except Exception:                              # noqa: BLE001
                pass
    try:
        import httpx
        for k in ("everything_unlocked", "boot_to_title"):
            _save_setting(ctx, k, False)
        httpx.post(f"{ctx.server}/api/re6/settings", headers=ctx.headers, timeout=10,
                   json={"auto_qte": False, "infinite_health": False, "infinite_ammo": False})
    except Exception:                                      # noqa: BLE001
        pass
    try:
        import httpx
        cur = _saved_loadout(ctx.server, ctx.headers) or {}
        httpx.post(f"{ctx.server}/api/re6/loadout", headers=ctx.headers, timeout=10,
                   json={"game_id": re6.GAME_ID, "items": cur.get("items", []), "auto": False})
    except Exception:                                      # noqa: BLE001
        pass
    if not any(isinstance(g, dict) and g.get("game_id") in GAME_IDS for _, g in SESSIONS.values()):
        out["save_restored"] = restore_save(cfg)
    else:
        out["save_note"] = "RE6 is running: the save backup is restored by revert_all once the game is closed"
    for m in list_mods(cfg):
        if m["name"] in running_mods:
            out["mods_kept"].append(m["name"])
            continue
        shutil.rmtree(mod_dir(cfg, m["name"]), ignore_errors=True)
        out["mods_removed"].append(m["name"])
    out["message"] = ("RE6 is back to the original: Mercenaries loadouts restored, auto-apply off"
                      + (", save restored from the backup" if out["save_restored"] else "")
                      + (f", mods removed: {', '.join(out['mods_removed'])}" if out["mods_removed"] else "")
                      + ". The disc image was never changed; launching RE6 without a mod is the untouched game.")
    return out


# ------------------------------------------------------------------ enemies / combined mods

def _meta(ctx, q):
    from . import characters as C
    chars = C._api(ctx, "GET", "/api/characters")
    m = C.best_match(chars, q) or C.find(chars, q)
    if not m:
        raise ValueError(f"{q!r} isn't in the collection")
    if not (m.get("rig") or {}).get("roles"):
        raise ValueError(f"{m['name']} has no body roles in the collection: can't fit it to RE6 skeletons")
    return m


def random_mix(ctx, families: list[str], seed: int | None = None) -> dict[str, str]:
    """Each enemy family gets a different collection character with body roles (RE6's own excluded)."""
    import random
    from . import characters as C
    pool = [m["slug"] for m in C._api(ctx, "GET", "/api/characters")
            if (m.get("rig") or {}).get("roles") and m.get("kind", "character") == "character"
            and (m.get("source") or {}).get("game_id") not in GAME_IDS and not m.get("variant_of")]
    rnd = random.Random(seed)
    rnd.shuffle(pool)
    return {f: pool[k % len(pool)] for k, f in enumerate(families)} if pool else {}


def build_combined(ctx, enemies: dict[str, str], player: str = "", progress=None) -> dict:
    """One mod folder: optional player swap (Leon, every costume) + enemy families -> collection characters."""
    from . import re6_models as M, retarget_profile as RP
    progress = progress or (lambda *a: None)
    b = base(ctx.config, progress)
    files, report = {}, {"enemies": [], "player": None}
    if player:
        pm = _player_meta(_meta(ctx, player))
        model = fetch_model(ctx, pm)
        for k, cos in enumerate(M.CHARACTERS["leon"]["costumes"]):
            progress(20 + 10 * k / 5, f"Leon ({cos}) -> {pm['name']}")
            r = M.build_swap(b, model, pm["rig"]["roles"], "leon", cos, pm["slug"], scale=pm["rig"].get("scale"))
            files.update(r.pop("files"))
        report["player"] = pm["slug"]
    for n, (fam, who) in enumerate(enemies.items()):
        em = _meta(ctx, who)
        profiles = RP.stored(em, re6.GAME_ID)
        slot = f"enemy:{fam}" if f"enemy:{fam}" in profiles or fam in profiles else "enemies"
        em = RP.apply_to_meta(em, re6.GAME_ID, slot)
        progress(35 + 40 * n / max(1, len(enemies)), f"{M.ENEMIES[fam][0]} -> {em['name']}")
        r = M.build_enemy_swap(b, fam, fetch_model(ctx, em), em["rig"]["roles"], em["slug"], scale=em["rig"].get("scale"))
        # a family built earlier in this mod may share arcs: merge entry by entry
        for rel, data in r.pop("files").items():
            if rel in files:
                cur, add = re6.Arc(files[rel]), re6.Arc(data)
                base_arc = M._arc(b, Path(rel).stem)
                olds = {(e["name"].lower(), e["ext"]): e["_raw"] for e in base_arc.entries}
                for e in add.entries:
                    if olds.get((e["name"].lower(), e["ext"])) != e["_raw"]:
                        cur.put(e["name"], e["type"], add.get(e))
                files[rel] = cur.build()
            else:
                files[rel] = data
        report["enemies"].append({"family": fam, "label": M.ENEMIES[fam][0], "character": em["slug"],
                                  "models": [x["model"] for x in r["models"]], "textures": r["textures"]})
    progress(80, "Writing the change into every arc that carries the same resources")
    files = M.propagate(b, files)
    tag = "_".join([f"p{report['player']}"] * bool(player) + [f"{f.split('_')[-1]}{w}" for f, w in enemies.items()])
    import hashlib
    name = "re6_" + (tag if len(tag) <= 40 else hashlib.sha1(tag.encode()).hexdigest()[:10])
    progress(90, f"Mod folder {name}")
    res = build_mod_folder(ctx.config, name, files, {"player": report["player"], "enemies": enemies})
    return res | report


def use_enemies(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use slot=enemies (every family) or slot=enemy:<family>: build + launch."""
    from . import re6_models as M
    fams = list(M.ENEMIES) if inp.slot == "enemies" else [inp.slot.split(":", 1)[1]]
    bad = [f for f in fams if f not in M.ENEMIES]
    if bad:
        return {"status": "failed", "error": f"unknown enemy family {bad}; have {sorted(M.ENEMIES)}"}
    r = build_combined(ctx, {f: meta["slug"] for f in fams}, "", ctx.progress)
    return r | {"status": "built", **_launch_mod(ctx, game["game_id"], r["mod"], inp)}


def _launch_mod(ctx, gid, name, inp) -> dict:
    if not getattr(inp, "launch", True):
        return {}
    from . import characters as C
    sess = C._session(ctx, inp.session_id) if getattr(inp, "session_id", "") else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    for _ in range(600):
        j = C._api(ctx, "GET", f"/api/jobs/{lj['id']}")
        if j.get("state") not in ("queued", "running"):
            break
        time.sleep(1)
    return {"launch": {"job": lj.get("id"), "state": j.get("state"), "session_id": (j.get("output") or {}).get("session_id"),
                       "error": j.get("error")}}

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
  give_now item=<name|id> amount   into the running game's inventory now (Mercenaries or campaign): ammo, herbs,
                              grenades, sprays, and guns whose model the stage has loaded; other guns -> loadout table
  live_inventory              the player's inventory right now (slot, item, count / max)
  auto_qte on=true|false      every QTE prompt succeeds (default on whenever RE6 boots through gBox)
  settings                    the saved RE6 switches (auto_qte, infinite_health, infinite_ammo)
  revert_all                  undo every live change, stop auto / freezes, delete gBox's RE6 mod folders
  catalog                     the item list (names from the disc)
  build_mod character=<library name> [target=leon costume=]   character swap mod (no launch)
  mods                        RE6 mods built on this node
"""
from __future__ import annotations

import json
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


def build_character(ctx, meta: dict, target: str = "leon", costume: str = "", progress=None) -> dict:
    """Library character -> RE6 swap mod re6_<slug>[_<target>]: every costume of `target` (or one) becomes it."""
    from . import characters as C, re6_models as M
    progress = progress or (lambda *a: None)
    roles = (meta.get("rig") or {}).get("roles")
    if not roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles) in the collection: can't fit it to an RE6 skeleton")
    if target not in M.CHARACTERS:
        raise ValueError(f"target must be one of {sorted(M.CHARACTERS)}")
    progress(5, "RE6 disc copy for mods")
    b = base(ctx.config, progress)
    model = fetch_model(ctx, meta)
    costumes = [costume] if costume else M.CHARACTERS[target]["costumes"]
    files, report = {}, []
    for k, cos in enumerate(costumes):
        progress(55 + 30 * k / len(costumes), f"Fitting {meta['name']} to {M.CHARACTERS[target]['name']} ({cos})")
        r = M.build_swap(b, model, roles, target, cos, meta["slug"])
        files.update(r.pop("files"))                     # costumes never share arcs
        report.append(r)
    name = f"re6_{meta['slug']}" + ("" if target == "leon" else f"_{target}")
    progress(88, f"Writing mod {name}")
    res = build_mod_folder(ctx.config, name, files, {"character": meta["slug"], "target": target, "costumes": costumes})
    work = Path(ctx.config.cache) / "characters_build" / meta["slug"]
    work.mkdir(parents=True, exist_ok=True)
    prev = None
    try:                                                   # read the written model back and render it (checked picture)
        r0 = M.build_swap(b, model, roles, target, costumes[0], meta["slug"], work / "re6_preview.gltf")
        C.render_preview(Path(r0["preview_gltf"]), work / "re6_preview.png")
        prev = str(work / "re6_preview.png")
        ctx.artifact("re6_preview.png", (work / "re6_preview.png").read_bytes(), "image/png", character=meta["slug"])
    except Exception as e:                                 # noqa: BLE001 - the preview is a check, not the product
        prev = f"preview failed: {e}"
    return res | {"target": target, "costumes": costumes, "triangles": report[0]["triangles"],
                  "hidden": report[0]["hidden_parts"], "notes": sorted({n for r in report for n in r["notes"]}), "preview": prev}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for RE6: build re6_<slug> (replaces Leon in every costume: story + Mercenaries) if missing,
    record it in the character's targets, launch it on the requesting session's node (or this one)."""
    from . import characters as C
    gid = game["game_id"]
    if getattr(inp, "slot", "player") != "player":            # slot=enemies | enemy:<family>
        return use_enemies(ctx, meta, game, inp)
    target = "leon"
    name = f"re6_{meta['slug']}"
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    built = None
    if inp.rebuild or not (mod_dir(ctx.config, name) / ".gbox-mod.json").exists():
        if C.HOST_OS != "windows":                         # the extracted disc + Xenia live on the Windows node
            w = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "windows" and w.get("online")), None)
            if not w:
                return {"status": "failed", "error": "no Windows node online to build the RE6 mod on"}
            j = C._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "rebuild": inp.rebuild,
                                           "launch": inp.launch, "session_id": inp.session_id}, w, 3600)
            return (j.get("output") or {}).get("result") or {"status": j.get("state"), "error": j.get("error")}
        built = build_character(ctx, meta, target, "", ctx.progress)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": "player", "mod": name, "nodes": [C.HOST_OS],
                     "notes": "replaces Leon (every costume, story + Mercenaries); head/hands hidden; revert: launch "
                              "without the mod or re6 op=revert_all"})
    res = {"mod": name, "build": built, "replaces": "Leon (all 5 costumes); pick Leon in Mercenaries"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    if sess and sess.get("game_id") == gid and sess.get("mod") == name:
        return res | {"status": "already running", "message": f"Resident Evil 6 is already running with {meta['name']} "
                      f"(mod {name}). In Mercenaries pick Leon."}
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
                  "message": (f"Resident Evil 6 is starting with {meta['name']} in Leon's place (mod {name}). Choose Leon "
                              "in Mercenaries (or any Leon chapter). Revert: launch RE6 without the mod, or re6 op=revert_all."
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


def unlock_save(cfg) -> dict:
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
    struct.pack_into(">I", d, 0xBC, 0xFFFFFFFF)
    struct.pack_into(">I", d, 8, _save_sum(d))
    sp.write_bytes(bytes(d))
    return {"unlock_flag": {"before": hex(before), "after": "0xffffffff"}, "backup": str(bk)}


def restore_save(cfg) -> bool:
    bk = save_backup(cfg)
    if not bk.exists():
        return False
    dst = save_path(cfg).parents[2]
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(bk, dst)
    return True


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
_LIVE = {"holds": {}, "qte": {}, "inj": threading.Lock()}


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
    pre = None
    if is_gun(iid):
        # a gun the stage didn't load: preload its unit archive first (see preload_weapon), else the game waits forever
        have = {code_item(struct.unpack_from(">H", ad.read_memory(ps[0] + INV + SLOT_SZ * k, 8), 6)[0]) for k in range(7)}
        if iid not in have and weapon_class(ad, code):
            pre = preload_weapon(ad, ps[0], iid)
            if not pre["resource"]:
                return {"live": False, "reason": f"the game couldn't load {names.get(iid, iid)}'s resources "
                        f"({pre['class']}.arc); it was added to the Mercenaries loadout instead"}
    res = []
    for p in (ps if all_players else ps[:1]):
        r = call_on_player(ad, p, SETITEM, (slot, code, amount if amount > 0 else -1, 0, 0))
        res.append(r)
    return {"live": True, "slots": res, "item": iid, "name": names.get(iid, iid),
            "preloaded": pre["class"] if pre else None}


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
        return r | {"slot": slot, "replaced": names.get(cur) if cur is not None else None,
                    "message": f"Slot {slot}: {names.get(iid, iid)}" + (f" (was {names.get(cur, cur)})" if cur is not None else "")}
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


def settings(server, headers) -> dict:
    import httpx
    try:
        return httpx.get(f"{server}/api/re6/settings", headers=headers, timeout=10).json()
    except Exception:                                      # noqa: BLE001
        return {"auto_qte": True}


def _boot_patch(sid: str, server, headers):
    """Right after RE6 starts: wait for the executable image, install Auto QTE before the first prompt, apply settings."""
    from .tools import SESSIONS
    t = time.time()
    while time.time() - t < 300 and sid in SESSIONS:
        ad = SESSIONS[sid][0]
        try:
            if ad.read_memory(TITLE_CHECK[0], len(TITLE_CHECK[1])) == TITLE_CHECK[1]:
                st = settings(server, headers)
                _LIVE["qte"][sid] = qte_install(ad)
                qte_set(ad, bool(st.get("auto_qte", True)))
                set_hold(sid, "health", bool(st.get("infinite_health")))
                set_hold(sid, "ammo", bool(st.get("infinite_ammo")))
                return
        except Exception:                                  # noqa: BLE001 - guest memory not mapped yet
            pass
        time.sleep(0.2)


def on_launch(sid: str, ctx):
    """Called by launch_game when an RE6 session starts on this node."""
    threading.Thread(target=_boot_patch, args=(sid, ctx.server, ctx.headers), daemon=True, name="re6-boot").start()
    ensure_watcher(ctx)


# ------------------------------------------------------------------ the tool

class Re6In(BaseModel):
    op: str = "status"          # status | inventory | give | give_now | live_inventory | set_loadout | auto | unlock |
                                # revert_all | catalog | build_mod | mods | infinite_ammo | infinite_health | auto_qte | settings
    session_id: str = ""
    item: str = ""              # give: name ('elephant killer', 'hand cannon') or id
    amount: int = 0             # give: ammo / count (0 = a full magazine / sensible stack)
    items: list = []            # set_loadout / auto: names, ids or {id, amount}
    character: str = ""         # give / set_loadout: leon | helena | chris | piers | jake | sherry | ada | agent | any
    replace: bool = True        # set_loadout: clear the character's own guns and case first
    on: bool = True             # auto / infinite_*
    now: bool = True            # set_loadout: write the table now (also when auto)
    target: str = "leon"        # build_mod: the RE6 character to replace
    costume: str = ""           # build_mod: one costume (default: all of them)
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
                    "unlock: edits the RE6 save in Xenia's content folder (backup kept, restored by revert_all)",
                    "build_mod: writes a mod folder under cache/mods (hard links + replaced arcs)"])
def re6_tool(inp: Re6In, ctx):
    """Resident Evil 6 (Xbox 360 in Xenia): Mercenaries loadouts (any item incl. story-only weapons), unlocks,
    character swap mods, revert. Offline only (refuses if the game could be online)."""
    cfg = ctx.config
    ensure_watcher(ctx)
    op = inp.op
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
        return {"result": build_character(ctx, meta, inp.target, inp.costume, ctx.progress)}
    if op == "unlock":
        from .tools import SESSIONS
        running = [s for s, (a, g) in SESSIONS.items() if isinstance(g, dict) and g.get("game_id") in GAME_IDS]
        r = unlock_save(cfg)
        return {"result": r | {"message": "Intro skipped and The Mercenaries unlocked in the save (Play Game > Extra Content > "
                               "The Mercenaries)." + (" RE6 is running: restart it to load the edited save (the game "
                               "would otherwise write its own copy back)." if running else " Launch RE6 to use it."),
                               "restart_needed": bool(running), "no_mercy": "not in the Xbox 360 version (it was a PC-only "
                               "mode); the 360 build has no No Mercy mode, files or menu entry"}}
    if op == "revert_all":
        return {"result": revert_all(ctx, inp.session_id)}
    if op == "settings":
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
        return {"result": r | {"message": f"{r['name']} is in your inventory now." if min(r["slots"]) >= 0 else
                               f"The game refused {r['name']} (no free slot of that kind)."}}
    raise ValueError("op: status | inventory | live_inventory | give | give_now | set_loadout | auto | unlock | revert_all | "
                     "catalog | build_mod | mods | infinite_ammo | infinite_health | auto_qte | settings")


def _save_setting(ctx, key: str, val: bool):
    import httpx
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
    from . import re6_models as M
    progress = progress or (lambda *a: None)
    b = base(ctx.config, progress)
    files, report = {}, {"enemies": [], "player": None}
    if player:
        pm = _meta(ctx, player)
        model = fetch_model(ctx, pm)
        for k, cos in enumerate(M.CHARACTERS["leon"]["costumes"]):
            progress(20 + 10 * k / 5, f"Leon ({cos}) -> {pm['name']}")
            r = M.build_swap(b, model, pm["rig"]["roles"], "leon", cos, pm["slug"])
            files.update(r.pop("files"))
        report["player"] = pm["slug"]
    for n, (fam, who) in enumerate(enemies.items()):
        em = _meta(ctx, who)
        progress(35 + 40 * n / max(1, len(enemies)), f"{M.ENEMIES[fam][0]} -> {em['name']}")
        r = M.build_enemy_swap(b, fam, fetch_model(ctx, em), em["rig"]["roles"], em["slug"])
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

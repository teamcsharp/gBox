"""Builds view (top bar "Builds"): every custom / modified build in one list, what each one changed, and the build jobs
that are queued or running.

GET   /api/builds                               every build: the Spark's central collection (the built-mods index) plus
                                                each PC's own builds (its heartbeat's local_builds; staged copies map to
                                                the build they mirror), newest first; ?q= &game_id= &kind= filters
PATCH /api/builds/{game_id}/{name}              {display_name}: the operator's own name for a build ("" clears it)
GET   /api/builds/{game_id}/{name}/details      modifications, characters inserted (slot <- donor, with the models for the
                                                360 viewers), codes / cheats / hacks, compile changes, build recipe, jobs
                                                and receipts, verification + launch history
GET   /api/builds/scheduled                     queued / claimed / running build jobs (+ the last finished ones)
GET   /api/builds/scheduled/{job_id}            investigate: log tail, receipt + artifacts, fitting events, result
POST  /api/builds/scheduled/{job_id}/edit       {input}: a queued build job with edited input (cancel + resubmit, same
                                                OS / PC / parent request / agent flag)

Requests read the built-mods index (memory), the store and the workers' heartbeats; never the mod folders (details
stat only the files a build's marker names). Display names live in the store (gbox.built_mods.NAME_KIND), never in
the folder name or the marker (the marker is part of the build's pinned manifest: changing it would make every PC
stage the whole build again); gbox.built_mods joins them so the Mods page, Special builds and notifications show them.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import Body, Depends, HTTPException

from . import built_mods as BM

KINDS = {"cast": "cast swap", "character": "character swap", "file": "file mod", "cheats": "cheats",
         "romhack": "ROM hack", "compile": "decomp / compile", "showcase": "showcase", "test": "test"}
PRIMARY = ("showcase", "cast", "character", "compile", "romhack", "cheats", "file", "test")
CODE_KEYS = {"codes": "code", "cheats": "cheat", "cheat_codes": "cheat", "unlocks": "unlock", "patches": "patch",
             "code_patches": "code_patch", "memory_patches": "patch", "ram_writes": "ram_write", "memory_writes":
             "ram_write", "pokes": "ram_write", "hacks": "hack", "changeset": "changeset", "changes_applied": "changeset"}
COMPILE_KEYS = ("compiler", "compiler_flags", "flags", "toolchain", "defines", "source_patches", "decomp", "recomp",
                "recompiled", "target", "makefile", "build_flags")
LIVE_TOOLS = {"cheats": "cheat", "re_mods": "code_patch", "write_memory": "ram_write", "poke": "ram_write",
              "freeze_memory": "ram_write", "game_link": "ram_write", "mgs_vr": "unlock", "re6": "hack",
              "re5": "hack", "gta_live": "hack", "stage_warp": "hack", "script_patch": "patch"}
MAX_STAT = 64                    # details stat at most this many named files of one build
NAME_MAX = 120
FINISHED = ("succeeded", "failed", "invalid", "rejected")
RECENT_S = 6 * 3600
EDIT_LOCKED = ("op",)            # an edit never turns one kind of job into another


# ------------------------------------------------------------------------------------------------- kinds

def _list(v) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, dict):
        return [{"name": k, "value": x} for k, x in v.items()]
    return list(v) if isinstance(v, (list, tuple)) else [v]


def compile_of(meta: dict) -> dict:
    """Decomp / recompile facts: the marker's `compile` record, else the compile keys a writer recorded."""
    c = meta.get("compile")
    out = dict(c) if isinstance(c, dict) else {}
    for k in COMPILE_KEYS:
        if k in meta and k not in out and meta[k] not in (None, "", [], {}):
            out[k] = meta[k]
    return out


def card_codes(card: dict | None) -> list[dict]:
    """The codes / cheats / hacks a mod card applies with its build (every call besides @launch)."""
    rows = []
    for c in (card or {}).get("calls") or []:
        tool, inp = str(c.get("tool") or ""), c.get("input") or {}
        if tool in ("@launch", "") or tool == "characters":
            continue
        op = str(inp.get("op") or "")
        typ = LIVE_TOOLS.get(tool) or ("changeset" if tool.endswith("_mods") else "live")
        if tool == "mgs_vr" and "unlock" not in op:
            typ = "hack"
        row = {"type": typ, "tool": tool, "label": f"{tool} {op}".strip(), "source": "mod card"}
        if inp.get("codes"):
            row["codes"] = [str(x) for x in _list(inp["codes"])][:64]
        for k in ("address", "value", "size", "patch", "desc", "name", "item", "on"):
            if inp.get(k) not in (None, "", []):
                row[k] = inp[k] if isinstance(inp[k], (int, float, bool)) else str(inp[k])[:200]
        rows.append(row)
    return rows


def marker_codes(meta: dict) -> list[dict]:
    rows = []
    for k, typ in CODE_KEYS.items():
        v = meta.get(k)
        if k == "patches" and isinstance(v, dict) and not v:
            continue
        for x in _list(v):
            if isinstance(x, dict):
                row = {"type": x.get("type") or typ, **{kk: (vv if isinstance(vv, (int, float, bool)) else str(vv)[:300])
                                                         for kk, vv in x.items() if kk != "type"}}
            else:
                row = {"type": typ, "label": str(x)[:300]}
            rows.append(row | {"source": "marker"})
    return rows[:200]


def kinds_of(item: dict, meta: dict, card: dict | None = None) -> list[str]:
    """Every kind a build is (the filter matches any), the primary one first."""
    ks = set()
    if isinstance(meta.get("showcase"), dict) or str(item.get("name", "")).startswith("showcase_") or item.get("showcase"):
        ks.add("showcase")
    if item.get("cast") or isinstance(meta.get("cast"), list):
        ks.add("cast")
    elif item.get("changes") or meta.get("character"):
        ks.add("character")
    if compile_of(meta):
        ks.add("compile")
    fc = meta.get("file_changes") if isinstance(meta.get("file_changes"), list) else []
    if any(isinstance(r, dict) and (r.get("change") == "patched" or r.get("patches")) for r in fc) or meta.get("rom_hack"):
        ks.add("romhack")
    if marker_codes(meta) or card_codes(card):
        ks.add("cheats")
    if meta.get("test") is True or item.get("tickets") or re.match(r"(test|tmp|confirm)[_-]", str(item.get("name", ""))):
        ks.add("test")
    if not ks - {"test"}:
        ks.add("file")
    explicit = meta.get("kind") if meta.get("kind") in KINDS else None
    if explicit:
        ks.add(explicit)
    return sorted(ks, key=lambda k: (k != explicit, PRIMARY.index(k)))


# ------------------------------------------------------------------------------------------------- the list

def local_index(workers: list[dict]) -> dict:
    """"game_id/name" -> [{node, os, online, staged, built}] from each PC's heartbeat (a staged copy counts for the
    build it mirrors, never as its own build)."""
    out: dict[str, list[dict]] = {}
    for w in workers:
        if w.get("os") == "linux":
            continue                              # the Spark's own builds are the index itself
        for r in w.get("local_builds") or []:
            if not isinstance(r, dict) or not BM._safe_component(r.get("game_id")) or not isinstance(r.get("name"), str):
                continue
            base = r.get("staged_of") or r["name"].split(BM.STAGED_SEP)[0]
            if not BM._safe_component(base):
                continue
            key = f"{r['game_id']}/{base}"
            have = out.setdefault(key, [])
            if any(x["node"] == w.get("name") for x in have):
                continue
            have.append({"node": w.get("name") or "", "os": w.get("os") or "", "online": bool(w.get("online")),
                         "staged": base != r["name"], "built": r.get("built")})
    return out


def _image(item: dict) -> str:
    for group in ("shots", "images", "donor_previews"):
        for x in item.get(group) or []:
            if x.get("url"):
                return x["url"]
    return ""


def build_row(item: dict, meta: dict, card: dict | None, pcs: list[dict], here: list[dict]) -> dict:
    from . import special_builds as SB
    kinds = kinds_of(item, meta, card)
    where = [{"where": "spark", "label": "Spark collection"}]
    where += [{"where": "pc", "node": h["node"], "online": h["online"],
               "label": f"{h['node']} ({'staged copy' if h['staged'] else 'local copy'})"} for h in here]
    changes = item.get("changes") or []
    summary = ("; ".join(f"{c.get('donor') or '?'} → {c.get('slot') or '?'}" for c in changes)[:240] if changes
               else f"built by {item.get('writer') or '?'}")
    recipe, recorded = SB.recipe_for(meta, item["game_id"])
    return {"key": item["key"], "name": item["name"], "game_id": item["game_id"], "game_title": item.get("title") or "",
            "platform": item.get("platform") or "", "label": item.get("mod_title") or item["name"],
            "display_name": item.get("display_name") or "", "original_title": item.get("original_title") or item["name"],
            "kind": kinds[0], "kinds": kinds, "writer": item.get("writer") or "", "built": item.get("built") or 0,
            "size": item.get("size"), "own_size": item.get("own_size"), "verified": bool(item.get("verified")),
            "image": _image(item), "summary": summary, "changes": changes, "slots": len(changes),
            "where": where, "local_only": False, "tickets": item.get("tickets") or [], "last_launch": item.get("last_launch"),
            "card_id": item.get("card_id") or "", "state_slot": item.get("state_slot"),
            "launch_options": SB.launch_options(item, pcs), "has_recipe": bool(recipe), "recipe_recorded": recorded,
            "job_id": meta.get("job_id") or ""}


def local_only_row(key: str, here: list[dict], names: dict, titles: dict) -> dict:
    """A build only a PC has (not in the Spark's collection yet: it uploads when that PC's worker starts)."""
    from . import special_builds as SB
    gid, name = key.split("/", 1)
    pcs = [{"name": h["node"], "os": h["os"]} for h in here if h["online"] and not h["staged"]]
    opts = [o for o in SB.launch_options({"game_id": gid, "name": name}, pcs) if o["id"].startswith("pc:")]
    built = max((h.get("built") or 0) for h in here)
    return {"key": key, "name": name, "game_id": gid, "game_title": titles.get(gid) or gid, "platform": "",
            "label": names.get(key) or name, "display_name": names.get(key) or "", "original_title": name,
            "kind": "file", "kinds": ["file"], "writer": name.split("_", 1)[0] if "_" in name else "", "built": built,
            "size": None, "own_size": None, "verified": False, "image": "",
            "summary": "only on " + ", ".join(h["node"] for h in here) + " (not in the Spark collection yet)",
            "changes": [], "slots": 0, "local_only": True, "tickets": [], "last_launch": None, "card_id": "",
            "state_slot": None, "launch_options": opts, "has_recipe": False, "recipe_recorded": False, "job_id": "",
            "where": [{"where": "pc", "node": h["node"], "online": h["online"], "label": f"{h['node']} (local only)"}
                      for h in here]}


def facets(rows: list[dict]) -> dict:
    games, kinds = {}, {}
    for r in rows:
        g = games.setdefault(r["game_id"], {"game_id": r["game_id"], "title": r["game_title"] or r["game_id"], "count": 0})
        g["count"] += 1
        for k in r["kinds"]:
            kinds[k] = kinds.get(k, 0) + 1
    return {"games": sorted(games.values(), key=lambda g: g["title"].lower()),
            "kinds": [{"kind": k, "label": KINDS[k], "count": kinds[k]} for k in PRIMARY if k in kinds]}


def select(rows: list[dict], q: str = "", game_id: str = "", kind: str = "") -> list[dict]:
    words = [w for w in str(q or "").lower().split() if w]

    def hay(r):
        return " ".join([r["name"], r["label"], r["original_title"], r["game_id"], r["game_title"], r["writer"],
                         " ".join(KINDS[k] for k in r["kinds"]), *(f"{c.get('donor')} {c.get('slot')}" for c in r["changes"]),
                         *(f"#{t.get('number')}" for t in r["tickets"])]).lower()
    return [r for r in rows if (not game_id or r["game_id"] == game_id) and (not kind or kind in r["kinds"])
            and all(w in hay(r) for w in words)]


def listing(items: list[dict], records: list[dict], cards: dict, workers: list[dict], names: dict,
            titles: dict | None = None) -> list[dict]:
    """Every build, newest first: the index's builds with where they live, then builds only a PC has."""
    metas = {f"{r['game_id']}/{r['name']}": r.get("meta") or {} for r in records}
    pcs = sorted(({"name": w.get("name"), "os": w.get("os")} for w in workers if w.get("online") and w.get("name")),
                 key=lambda w: str(w["name"]).lower())
    here = local_index(workers)
    rows = [build_row(it, metas.get(it["key"]) or {}, cards.get(it.get("card_id") or ""), pcs, here.get(it["key"], []))
            for it in items]
    known = {r["key"] for r in rows}
    titles = dict(titles or {})
    for r in rows:
        titles.setdefault(r["game_id"], r["game_title"])
    rows += [local_only_row(k, v, names, titles) for k, v in here.items() if k not in known]
    rows.sort(key=lambda r: -(r["built"] or 0))
    return rows


# ------------------------------------------------------------------------------------------------- details

_FILE_NOTE = re.compile(r"^@image:\s*(.*?)\s*(?:\((gbox\.[a-z0-9_]+)\))?$")


def modifications(meta: dict, folder: Path | None, stat=True) -> dict:
    """The changed files: the marker's file_changes (sizes + what each change is), else derived from `files` /
    `image` (sizes stat'ed by name, at most MAX_STAT; base sizes were not recorded for older builds)."""
    rows, derived = [], False
    if isinstance(meta.get("file_changes"), list):
        rows = [dict(r) for r in meta["file_changes"] if isinstance(r, dict) and r.get("path")]
    else:
        derived = True
        for f in _list(meta.get("files")):
            if isinstance(f, dict):
                rows.append({"path": str(f.get("path") or f.get("name") or "?"), "change": f.get("change") or "replaced",
                             **{k: f[k] for k in ("size", "what") if k in f}})
                continue
            s = str(f)
            m = _FILE_NOTE.match(s)
            if m:
                rows.append({"path": str(meta.get("image") or "@image"), "change": "image",
                             "what": m[1] + (f" ({m[2]})" if m[2] else "")})
            elif s.endswith(" (new)"):
                rows.append({"path": s[:-6], "change": "new"})
            elif s == "@image":
                rows.append({"path": str(meta.get("image") or "@image"), "change": "patched", "what": "byte patches on the image"})
            else:
                rows.append({"path": s, "change": "replaced or patched"})
    image = meta.get("image")
    if isinstance(image, str) and image and not any(r["path"] == image for r in rows):
        rows.insert(0, {"path": image, "change": "image", "what": "the built image the launch boots"})
    if stat and folder is not None:
        for r in rows[:MAX_STAT]:
            if r.get("size") is None and BM._safe_component(str(r["path"]).split("/")[0]) and ".." not in str(r["path"]):
                try:
                    st = os.lstat(folder / r["path"])
                    r["size"] = st.st_size
                except (OSError, ValueError):
                    pass
    return {"files": rows, "derived": derived,
            **({"note": "derived from the marker's file list: what each change was and the base sizes were not "
                        "recorded for this build"} if derived and rows else {})}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def original_for(slot: str, slot_name: str, game_chars: list[dict]) -> dict | None:
    """The target game's own character a slot holds, from the collection (extracted from that game): by name."""
    tok = _norm((slot_name or slot).split(":")[-1])
    raw = _norm(slot.split(":")[-1])
    if not tok and not raw:
        return None
    for m in game_chars:
        names = {_norm(m.get("name")), _norm(m.get("slug")), *(_norm(a) for a in m.get("aliases") or [])}
        if tok in names or raw in names or any(n and (n.endswith(tok) or n.endswith(raw)) and len(min(tok, raw, key=len)) >= 3
                                                for n in names):
            return m
        if slot == "player" and (m.get("native_player") or "player" in {str(a).lower() for a in m.get("aliases") or []}):
            return m
    return None


def _char_view(m: dict | None, root: Path | None) -> dict | None:
    if not m:
        return None
    model = m.get("model") or ""
    return {"slug": m["slug"], "name": m.get("name") or m["slug"], "source": (m.get("source") or {}).get("game_title") or "",
            "preview_url": f"/api/characters/{m['slug']}/preview",
            "model_url": f"/api/characters/{m['slug']}/file/{model}" if str(model).lower().endswith((".glb", ".gltf")) else ""}


_TARGETS: dict = {}


def fitted_file(root: Path | None, slug: str, game_keys: list[str], slot_key: str = "") -> str:
    """A donor's model as fitted to this game (the writers keep it under <slug>/targets/, named for the game: the
    build's writer prefix (sm64_mario.gltf) or the game id), the one naming the slot first; '' when none is for this
    game (a fitted model of another game is never shown as this one)."""
    if root is None:
        return ""
    d = Path(root) / slug / "targets"
    try:
        mt = d.stat().st_mtime_ns
    except OSError:
        return ""
    hit = _TARGETS.get(str(d))
    if not hit or hit[0] != mt:
        try:
            names = sorted(e.name for e in os.scandir(d) if e.is_file() and e.name.lower().endswith((".glb", ".gltf")))
        except OSError:
            names = []
        hit = _TARGETS[str(d)] = (mt, names)
    keys = [k.lower() for k in game_keys if k and len(k) >= 2]
    mine = [n for n in hit[1] if any(n.lower().startswith(k) or k in n.lower() for k in keys)]
    slot_key = slot_key.lower()
    pick = next((n for n in mine if len(slot_key) >= 3 and slot_key in _norm(n)), mine[0] if mine else "")
    return f"targets/{pick}" if pick else ""


def characters(meta: dict, item: dict, gid: str, lib: dict, root: Path | None, fitting: dict | None, job_id: str,
               fit_exists) -> list[dict]:
    """slot <- donor rows with what the 360 viewers show: the donor as fitted (who they are) and the original
    character the slot held (who they're replacing)."""
    names = {}
    for r in (meta.get("slots") or []) + (meta.get("cast") or []):
        if isinstance(r, dict) and r.get("slot"):
            names.setdefault(str(r["slot"]), {k: r.get(k) for k in ("slot_name", "donor_name", "source") if r.get(k)})
    game_chars = [m for m in lib.get("all") or [] if (m.get("source") or {}).get("game_id") == gid]
    rows = []
    for c in BM.changes_of(meta) or item.get("changes") or []:
        slot = str(c.get("slot") or "")
        slugs = [s.strip() for s in str(c.get("donor") or "").split(",") if s.strip()]
        slug = slugs[0] if slugs else ""
        donor = lib["get"](slug) if slug else None
        n = names.get(slot, {})
        slot_name = n.get("slot_name") or slot
        view = _char_view(donor, root) or ({"slug": slug, "name": n.get("donor_name") or slug, "source": "",
                                            "preview_url": f"/api/characters/{slug}/preview", "model_url": "",
                                            "missing": True} if slug else None)
        fitted, fitted_from = "", ""
        if donor:
            rel = fitted_file(root, slug, [gid, item["name"].split("_")[0]], _norm(slot_name))
            if rel:
                fitted, fitted_from = f"/api/characters/{slug}/file/{rel}", "fitted model kept in the collection"
        snap = ((fitting or {}).get("models") or {}).get(slot) or {}
        if not fitted and snap.get("snapshot") and fit_exists(snap["snapshot"]):
            fitted, fitted_from = snap["snapshot"], f"fitting snapshot of job {job_id} ({snap.get('snapshot_stage') or 'write'})"
        if view and not fitted and view.get("model_url"):
            fitted, fitted_from = view["model_url"], "collection model (not fitted to this game)"
        orig = original_for(slot, slot_name, game_chars) if lib.get("all") is not None else None
        rows.append({"slot": slot, "slot_name": slot_name, "status": c.get("status") or "",
                     **({"reason": str(c["reason"])[:300]} if c.get("reason") else {}),
                     "donors": slugs, "donor": view, "donor_source": n.get("source") or (view or {}).get("source") or "",
                     "fitted_url": fitted, "fitted_from": fitted_from, "original": _char_view(orig, root),
                     **({} if orig else {"original_note": ("the collection is still loading" if lib.get("all") is None else
                                                           f"no character of this game named like {slot_name!r} in the "
                                                           "collection (extract the game's cast to see it)")})})
    return rows


def _jobs_for(store, gid: str, name: str, known: str = "", limit: int = 8) -> list[dict]:
    """The jobs whose result names this build (one indexed-free SQL pass over the job rows, on request only)."""
    out, seen = [], set()
    rows = []
    try:
        with store.lock:
            rows = store.db.execute(
                "SELECT body FROM docs WHERE kind='job' AND (id=? OR json_extract(body,'$.output.result.mod')=? OR "
                "json_extract(body,'$.input.name')=? OR json_extract(body,'$.input.mod_name')=?) ORDER BY rowid DESC "
                "LIMIT ?", (known or "-", name, name, name, limit * 3)).fetchall()
    except Exception:                                            # noqa: BLE001
        rows = []
    for (body,) in rows:
        try:
            j = json.loads(body)
        except ValueError:
            continue
        inp = j.get("input") or {}
        gids = {inp.get("game_id"), inp.get("target_game"), ((j.get("output") or {}).get("result") or {}).get("game_id")}
        if j["id"] != known and gid not in gids and not (isinstance(inp.get("game"), dict) and inp["game"].get("game_id") == gid):
            continue
        if j["id"] in seen:
            continue
        seen.add(j["id"])
        out.append({k: j.get(k) for k in ("id", "tool", "state", "created", "started", "finished", "receipt_id", "error",
                                         "worker_id")} | {"op": inp.get("op") or ""})
    return out[:limit]


def launches(store, gid: str, name: str, limit: int = 10) -> list[dict]:
    rows = [s for s in BM._fields(store, "session", ("session_id", "game_id", "mod", "collection_mod", "started", "ended",
                                                        "state", "exit"))
            if s.get("game_id") == gid and name in (s.get("mod"), s.get("collection_mod"))]
    rows.sort(key=lambda s: -(s.get("started") or 0))
    out = []
    for s in rows[:limit]:
        ex = s.get("exit")
        out.append({"session_id": s.get("session_id"), "node": str(s.get("session_id") or "").split("-")[0],
                    "started": s.get("started"), "ended": s.get("ended"), "state": s.get("state"),
                    **({"exit": (ex if isinstance(ex, str) else json.dumps(ex, default=str))[:300]} if ex else {})})
    return out


def details(store, config, item: dict, meta: dict, card: dict | None, lib: dict, workers: list[dict]) -> dict:
    from . import special_builds as SB
    gid, name = item["game_id"], item["name"]
    folder = BM.mods_root(config) / gid / name
    recipe, recorded = SB.recipe_for(meta, gid)
    job_id = str(meta.get("job_id") or "")
    job = store.get("job", job_id) if job_id else None
    fit_root = Path(config.cache) / "fitting-jobs"

    def fit_exists(url: str) -> bool:
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]{1,64})/fitting/files/([A-Za-z0-9_.-]{1,96})", str(url))
        return bool(m) and (fit_root / m[1] / m[2]).is_file()
    codes = marker_codes(meta) + card_codes(card)
    comp = compile_of(meta)
    jobs = _jobs_for(store, gid, name, job_id)
    receipts = []
    for j in jobs[:4]:
        r = store.get("receipt", j["receipt_id"]) if j.get("receipt_id") else None
        if r:
            receipts.append({"id": r["id"], "job_id": r["job_id"], "tool": r.get("tool"), "validation_ok": r.get("validation_ok"),
                             "problems": (r.get("validation_problems") or [])[:6], "finished": r.get("finished"),
                             "artifacts": [{"sha256": a["sha256"], "name": a.get("name"), "size": a.get("size"),
                                            "media_type": a.get("media_type"), "url": f"/api/artifacts/{a['sha256']}"}
                                           for a in (r.get("artifacts") or [])[:12]]})
    hist = launches(store, gid, name)
    verified = bool(item.get("verified"))
    return {
        "key": item["key"], "name": name, "game_id": gid, "label": item.get("mod_title") or name,
        "display_name": item.get("display_name") or "", "original_title": item.get("original_title") or name,
        "kinds": kinds_of(item, meta, card), "writer": item.get("writer") or "", "built": item.get("built"),
        "built_on": meta.get("built_on") or None, "folder": str(folder),
        "size": item.get("size"), "own_size": item.get("own_size"), "files_count": item.get("files"),
        "modifications": modifications(meta, folder),
        "characters": characters(meta, item, gid, lib, lib.get("root"), (job or {}).get("fitting"), job_id, fit_exists),
        "cast": {"source": meta.get("cast_source") or "", "mapping": meta.get("cast_mapping") or "",
                 "seed": meta.get("cast_seed") or ""} if isinstance(meta.get("cast"), list) else None,
        "codes": codes,
        "codes_note": "" if codes else "no cheat codes, memory patches, unlocks or RAM writes recorded for this build",
        "compile": comp or None,
        "compile_note": "" if comp else "not a decomp / recompile build (no compiler, flags or source patches recorded)",
        "recipe": recipe, "recipe_recorded": recorded,
        "recipe_note": "" if recipe else "the marker records no character or cast plan to build it from",
        "build_call": meta.get("build_call") if isinstance(meta.get("build_call"), dict) else None,
        "job_id": job_id, "jobs": jobs, "receipts": receipts, "tickets": item.get("tickets") or [],
        "card_id": item.get("card_id") or "",
        "verification": {"verified": verified, "last_launch": item.get("last_launch"), "launches": hist,
                         "text": "verified in game" if verified else
                                 ("unverified in game until launched" if not hist else
                                  f"launched {len(hist)} time{'s' if len(hist) != 1 else ''}; not marked verified yet")},
        "where": [], "marker_keys": sorted(meta)[:80],
    }


def library(config) -> dict:
    """The character collection for details: get(slug) reads one meta.json; `all` only when the list cache is warm
    (never a cold 645-folder HDD read inside a request)."""
    try:
        from . import characters as K
        root = K.library_root(config)
    except Exception:                                            # noqa: BLE001
        return {"root": None, "all": [], "get": lambda s: None}
    cache = getattr(K, "_LIST_CACHE", {}).get(str(root))
    every = K.list_all(root) if cache is not None or not Path(root).is_dir() or _small_library(root) else None
    by = {m["slug"]: m for m in every or [] if m.get("slug")}

    def get(slug):
        if slug in by:
            return by[slug]
        if not BM._safe_component(slug):
            return None
        try:
            return K.get(root, slug)
        except (KeyError, OSError, ValueError):
            return None
    return {"root": root, "all": every, "get": get}


def _small_library(root) -> bool:
    try:
        return sum(1 for _ in zip(range(60), os.scandir(root))) < 60      # a test / fresh library: read it now
    except OSError:
        return True


# ------------------------------------------------------------------------------------------------- scheduled

def job_category(tool: str, inp: dict) -> str | None:
    """The build kind of a job, or None when it is not a build (launches, live changes, plans)."""
    op = str(inp.get("op") or "")
    if tool == "characters":
        if inp.get("plan_only"):
            return None
        if op == "cast_swap":
            return "showcase" if inp.get("showcase") or str(inp.get("mod_name") or "").startswith("showcase_") else "cast"
        if op in ("use", "match"):
            return "character"
        if op == "collect":
            return "collect"
        return None
    if tool == "file_mod":
        return "file" if op == "build" else None
    if tool == "rom_export":
        return "romhack" if op in ("", "export") else None
    if tool == "n64recomp":
        return "compile" if op == "run" else None
    if tool == "um_mod":
        return "file" if op == "stage" else None
    if tool.endswith("_mods") and op in ("build", "export"):
        return "file"
    return None


def job_label(tool: str, inp: dict, titles) -> str:
    op = str(inp.get("op") or "")
    g = titles(inp.get("target_game") or inp.get("game_id") or "")
    if tool == "characters" and op == "cast_swap":
        return f"Cast swap: {g or '?'} as {inp.get('source') or '?'}" + (" (rebuild)" if inp.get("rebuild") else "")
    if tool == "characters" and op == "use":
        return f"Character swap: {inp.get('character') or '?'} → {g or '?'} {inp.get('slot') or 'player'}" + \
            (" (rebuild)" if inp.get("rebuild") else "")
    if tool == "characters" and op == "match":
        pairs = inp.get("pairs") or []
        return f"Character swap: {len(pairs)} pair{'s' if len(pairs) != 1 else ''} → {g or '?'}"
    if tool == "characters" and op == "collect":
        return f"Collect characters: {g or '?'}"
    if tool == "file_mod":
        return f"File mod: {inp.get('name') or '?'} ({g or '?'})"
    if tool == "rom_export":
        return f"ROM export: {inp.get('name') or inp.get('mod_id') or '?'}"
    if tool == "n64recomp":
        return f"Recompile: {inp.get('name') or Path(str(inp.get('rom_path') or '?')).name}"
    return f"{tool} {op}".strip()


def fitting_summary(f: dict | None) -> dict | None:
    if not isinstance(f, dict) or not f.get("models"):
        return None
    ms = [f["models"][k] for k in f.get("order") or [] if k in f["models"]]
    return {"models": len(ms), "done": sum(1 for m in ms if m.get("state") == "done"),
            "failed": sum(1 for m in ms if m.get("state") == "failed"), "current": f.get("current") or "",
            "kind": f.get("kind") or "fit"}


def stage_rows(f: dict | None) -> list[dict]:
    """The fitting record folded per stage over every model (the flowchart's work nodes): {name, state, done, total}."""
    from .fit_events import COLLECT_STAGES, STAGES
    if not isinstance(f, dict) or not f.get("models"):
        return []
    ms = [f["models"][k] for k in f.get("order") or [] if k in f["models"]]
    if not ms:
        return []
    out = []
    for name in (COLLECT_STAGES if f.get("kind") == "collect" else STAGES):
        states = [((m.get("stages") or {}).get(name) or {}).get("state") for m in ms]
        seen = [s for s in states if s]
        if not seen:
            continue
        done = sum(s in ("done", "skipped") for s in states)
        state = ("failed" if "failed" in seen else "done" if done == len(ms) else
                 "skipped" if all(s == "skipped" for s in seen) and len(seen) == len(ms) else "running")
        out.append({"name": name, "state": state, "done": done, "total": len(ms)})
    return out


def step_rows(log: list | None, n: int = 6) -> list[str]:
    """The last distinct progress messages (a build without fitting events), numbers and percentages folded."""
    out = []
    for m in log or []:
        t = re.sub(r"\s+", " ", re.sub(r"\d+(\.\d+)?\s*(%|/\s*\d+|MB|GB|KB)?", "#", str(m))).strip()[:70]
        if not t:
            continue
        if out and out[-1][0] == t:
            out[-1] = (t, str(m)[:70])                   # the same step, newer numbers
        else:
            out.append((t, str(m)[:70]))
    return [o[1] for o in out[-n:]]


def job_row(j: dict, names: dict, titles, now: float) -> dict | None:
    inp = j.get("input") or {}
    cat = job_category(j.get("tool") or "", inp)
    if cat is None:
        return None
    state = j.get("state") or ""
    prog = j.get("progress") or None
    phase = state
    if state == "running":
        phase = "claimed" if not prog else "running"
    if state == "failed" and "cancelled" in str(j.get("error") or ""):
        phase = "cancelled"
    eta = None
    if state == "running" and prog and j.get("started"):
        pct = float(prog.get("pct") or 0)
        if 2 <= pct < 100:
            eta = round((now - j["started"]) * (100 - pct) / pct)
    wid = j.get("worker_id") or ""
    return {"id": j["id"], "tool": j.get("tool"), "op": inp.get("op") or "", "category": cat,
            "category_label": KINDS.get(cat, cat), "label": job_label(j.get("tool") or "", inp, titles),
            "state": state, "phase": phase, "worker_id": wid, "worker": names.get(wid) or wid,
            "require_os": j.get("require_os"), "require_worker": j.get("require_worker"),
            "created": j.get("created"), "started": j.get("started"), "finished": j.get("finished"),
            "progress": prog, "eta_s": eta, "editable": state == "queued", "cancel_requested": bool(j.get("cancel")),
            "input": _bounded(inp), "fitting": fitting_summary(j.get("fitting")), "error": j.get("error"),
            "stages": stage_rows(j.get("fitting")), "steps": step_rows(j.get("progress_log")),
            "edited_from": j.get("edited_from") or "", "receipt_id": j.get("receipt_id") or "",
            "game_id": inp.get("target_game") or inp.get("game_id") or "",
            "mod": ((j.get("output") or {}).get("result") or {}).get("mod") if isinstance(j.get("output"), dict) else None}


def _bounded(inp: dict) -> dict:
    from . import build_record
    return build_record._small(inp)


def scheduled(store, workers: list[dict], titles, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    names = {w["id"]: w.get("name") for w in workers if w.get("id")}
    live = store.jobs(states=("queued", "running"), limit=400, reverse=True)
    active = [r for r in (job_row(j, names, titles, now) for j in live) if r]
    order = {"running": 0, "claimed": 1, "queued": 2}
    active.sort(key=lambda r: (order.get(r["phase"], 3), r["created"] or 0))
    done = store.jobs(states=FINISHED, limit=150, reverse=True)
    recent = [r for r in (job_row(j, names, titles, now) for j in done if (j.get("finished") or 0) > now - RECENT_S) if r]
    recent.sort(key=lambda r: -(r["finished"] or 0))
    return {"jobs": active, "recent": recent[:12], "queued": sum(r["state"] == "queued" for r in active),
            "running": sum(r["state"] == "running" for r in active), "at": now}


def investigate(store, jid: str, workers: list[dict], titles) -> dict:
    j = store.get("job", jid)
    if not j:
        raise KeyError(jid)
    names = {w["id"]: w.get("name") for w in workers if w.get("id")}
    row = job_row(j, names, titles, time.time()) or {"id": jid, "tool": j.get("tool"), "state": j.get("state")}
    log = ""
    if j.get("log_sha"):
        data = store.read_artifact(j["log_sha"])
        log = data.decode("utf-8", "replace")[-8000:] if data else ""
    receipt = store.get("receipt", j["receipt_id"]) if j.get("receipt_id") else None
    res = ((j.get("output") or {}).get("result") or {}) if isinstance(j.get("output"), dict) else {}
    result = {k: res.get(k) for k in ("status", "mod", "message", "game_id") if res.get(k) is not None} if isinstance(res, dict) else {}
    if isinstance(res, dict) and isinstance(res.get("report"), list):
        result["report"] = [{k: r.get(k) for k in ("slot", "slot_name", "character", "donor", "status", "reason")
                             if r.get(k) is not None} for r in res["report"][:80] if isinstance(r, dict)]
    return row | {
        "log_tail": log, "progress_log": (j.get("progress_log") or [])[-50:],
        "receipt": ({"id": receipt["id"], "validation_ok": receipt.get("validation_ok"),
                     "problems": (receipt.get("validation_problems") or [])[:10], "finished": receipt.get("finished"),
                     "tool_version": receipt.get("tool_version")} if receipt else None),
        "artifacts": [{"sha256": a["sha256"], "name": a.get("name"), "size": a.get("size"), "media_type": a.get("media_type"),
                       "url": f"/api/artifacts/{a['sha256']}"} for a in ((receipt or {}).get("artifacts") or [])[:24]],
        "fitting_events": j.get("fitting") or None, "result": result,
        "result_state": j.get("result_state"),
    }


def edit(store, jid: str, edits: dict, submit, actor: str) -> dict:
    """A queued build job, edited: the old one is cancelled once the new one (same tool, edited input, same OS / PC /
    parent request / agent flag) is accepted; one store lock so no worker claims the old one in between."""
    if not isinstance(edits, dict) or not edits:
        raise ValueError("input: the edited fields ({slots, assignments, source, mod_name, ...})")
    with store.lock:
        j = store.get("job", jid)
        if not j:
            raise KeyError(jid)
        if j.get("state") != "queued":
            raise PermissionError(f"job {jid} is {j.get('state')}: only a queued job can be edited (cancel it instead)")
        old = j.get("input") or {}
        if job_category(j.get("tool") or "", old) is None:
            raise ValueError(f"job {jid} is not a build job")
        for k in EDIT_LOCKED:
            if k in edits and edits[k] != old.get(k):
                raise ValueError(f"{k} can't be edited (cancel and start a different build)")
        new_input = {k: v for k, v in (old | edits).items() if v is not None}
        new = submit({"tool": j["tool"], "input": new_input, "require_os": j.get("require_os"),
                      "require_worker": j.get("require_worker"), "parent_request_id": j.get("parent_request_id"),
                      "agent_use": bool(j.get("agent_use"))}, actor)
        new = new.model_dump(mode="json") if hasattr(new, "model_dump") else dict(new)
        if new.get("state") == "rejected":
            raise ValueError(f"the edited job was rejected: {new.get('error')}")
        doc = store.get("job", new["id"]) or new
        store.put("job", new["id"], doc | {"edited_from": jid})
        j.update(state="failed", finished=time.time(), error=f"cancelled by the operator: edited, replaced by job {new['id']}",
                 replaced_by=new["id"])
        store.put("job", jid, j)
    store.audit(actor, "job.edit", jid, {"replaced_by": new["id"], "fields": sorted(edits)})
    return {"cancelled": jid, "job": doc | {"edited_from": jid}}


# ------------------------------------------------------------------------------------------------- routes

def clean_name(v) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError("display_name: a string")
    v = re.sub(r"[\x00-\x1f\x7f]+", " ", v).strip()
    if len(v) > NAME_MAX:
        raise ValueError(f"display_name: at most {NAME_MAX} characters")
    return v


def routes(app, store, config, auth, *, submit, workers):
    """submit({tool, input, require_os, require_worker, parent_request_id, agent_use}, actor) -> job (the server's own
    POST /api/jobs); workers() -> [worker + online]."""
    cache = {"titles": {}, "lock": threading.Lock()}

    def gallery(fresh: bool = False):
        index = getattr(app.state, "built_mods", None)
        if index is None:
            return [], [], {}
        index.start()
        if fresh:
            index.ask()
        cur = getattr(app.state, "built_mods_current", None)
        data = cur(fresh) if cur else BM.gallery(store, config, index.records(), register=False)
        return data["items"], index.records(), index.status()

    def titles(gid: str) -> str:
        if not gid:
            return ""
        t = cache["titles"].get(gid)
        if t is None:
            try:
                c = store.catalog_get(gid)
            except Exception:                                    # noqa: BLE001
                c = None
            t = cache["titles"][gid] = (c or {}).get("title") or gid
        return t

    def cards() -> dict:
        return {c.get("id"): c for c in store.all("mod") if c.get("id")}

    def find(game_id: str, name: str):
        items, records, _ = gallery()
        key = f"{game_id}/{name}"
        item = next((m for m in items if m["key"] == key), None)
        meta = next((r.get("meta") or {} for r in records if f"{r['game_id']}/{r['name']}" == key), {})
        return key, item, meta

    @app.get("/api/builds")
    def builds_list(q: str = "", game_id: str = "", kind: str = "", fresh: bool = False, actor=Depends(auth)):
        """Every custom build, newest first: the Spark's collection + each PC's own builds (deduped), with kinds,
        where it lives and its launch options."""
        items, records, status = gallery(fresh)
        ws = workers()
        rows = listing(items, records, cards(), ws, BM.display_names(store),
                       {it["game_id"]: it.get("title") or "" for it in items})
        picked = select(rows, q, game_id, kind)
        return {"items": picked, "total": len(picked), "all": len(rows), **facets(rows),
                "kinds_all": [{"kind": k, "label": v} for k, v in KINDS.items()],
                "pcs": [{"name": w.get("name"), "os": w.get("os")} for w in ws if w.get("online") and w.get("name")],
                **status}

    @app.patch("/api/builds/{game_id}/{name}")
    def builds_rename(game_id: str, name: str, body: dict = Body(default={}), actor=Depends(auth)):
        """{display_name}: the operator's name for a build, shown wherever builds are listed ("" restores the
        writer's title). The folder and its marker are never renamed."""
        if not (BM._safe_component(game_id) and BM._safe_component(name)):
            raise HTTPException(422, "bad build")
        try:
            v = clean_name(body.get("display_name"))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        key, item, _meta = find(game_id, name)
        if item is None and key not in local_index(workers()):
            raise HTTPException(404, f"no build {key}")
        if v:
            store.put(BM.NAME_KIND, key, {"key": key, "display_name": v, "by": actor, "ts": time.time()})
        else:
            store.delete(BM.NAME_KIND, key)
        store.audit(actor, "build.rename", key, {"display_name": v})
        inv = getattr(app.state, "built_mods_invalidate", None)
        if inv:
            inv()
        return {"key": key, "display_name": v, "label": v or ((item or {}).get("original_title") or name)}

    @app.get("/api/builds/scheduled")
    def builds_scheduled(actor=Depends(auth)):
        """Queued / claimed / running build jobs (state, worker, progress, ETA) and the last finished ones."""
        return scheduled(store, workers(), titles)

    @app.get("/api/builds/scheduled/{jid}")
    def builds_job(jid: str, actor=Depends(auth)):
        """Investigate one build job: log tail, receipt + artifacts, fitting events, result."""
        try:
            return investigate(store, jid, workers(), titles)
        except KeyError:
            raise HTTPException(404, "no such job") from None

    @app.post("/api/builds/scheduled/{jid}/edit")
    def builds_job_edit(jid: str, body: dict = Body(default={}), actor=Depends(auth)):
        """Edit a queued build job's input (cancel + resubmit with the same OS / PC / parent request / agent flag)."""
        try:
            return edit(store, jid, body.get("input") or {}, submit, actor)
        except KeyError:
            raise HTTPException(404, "no such job") from None
        except PermissionError as e:
            raise HTTPException(409, str(e)) from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except HTTPException as e:                                # the resubmit's own validation (input invalid)
            raise HTTPException(e.status_code, f"edited input refused: {e.detail}") from None

    @app.get("/api/builds/{game_id}/{name}/details")
    def builds_details(game_id: str, name: str, actor=Depends(auth)):
        """Everything one build changed: files, characters (with the 360 viewer models), codes, compile changes,
        recipe, jobs / receipts and verification."""
        if not (BM._safe_component(game_id) and BM._safe_component(name)):
            raise HTTPException(422, "bad build")
        key, item, meta = find(game_id, name)
        ws = workers()
        here = local_index(ws).get(key, [])
        if item is None:
            if not here:
                raise HTTPException(404, f"no build {key}")
            row = local_only_row(key, here, BM.display_names(store), {})
            return {"key": key, "name": name, "game_id": game_id, "label": row["label"], "local_only": True,
                    "where": row["where"], "kinds": row["kinds"],
                    "note": "this build is only on " + ", ".join(h["node"] for h in here) + "; its details arrive with "
                            "its marker when that PC's worker uploads it to the Spark collection (at worker start)"}
        card = store.get("mod", item["card_id"]) if item.get("card_id") else None
        out = details(store, config, item, meta, card, library(config), ws)
        out["where"] = build_row(item, meta, card, [], here)["where"]
        return out

    return builds_list, builds_rename, builds_details, builds_scheduled

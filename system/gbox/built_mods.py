"""Built mods gallery: every mod folder a writer built in the configured cache, joined with its mod card.

Writers build launchable mods straight into <cache>/mods/<game_id>/<mod>/ with a .gbox-mod.json marker (cast swaps,
PSO enemies, Crazy Taxi, JGR, Def Jam, PE2, Clay Fighter, SmackDown 2, MGS VR, DOA2 rosters, Vice City, ...). Many are
never saved as a mod card (/api/mods), so the operator could not see or launch them. This module

  * scans the control plane's own cache (config.cache, never a hardcoded path) for built folders,
  * normalizes each writer's marker into one shape: writer, donor -> slot rows (the per-slot report for cast swaps),
    built time, size, verified flag, last launch result, preview images, ticket numbers,
  * joins the mod cards (thumbnail, in-game shots, saved moment) and the donors' collection previews,
  * registers a mod card for any built folder that lacks one (idempotent), so every build launches the usual way
    (@launch mod=<name>).

GET /api/mods/built                                     the gallery (filters + pagination)
GET /api/mods/built/{game_id}/{mod}/image/{name}        a preview picture from the mod folder (path-checked)
"""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

MARKER = ".gbox-mod.json"
STAGED_MARK = ".gbox-staged-of"            # a local staging copy of a collection mod (filemods.STAGED_MARK)
STAGED_SEP = "~"                           # <mod>~<build>: a rebuilt mod staged beside a copy a running game holds open
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
PREVIEW_DIRS = ("preview", "previews")     # subfolders some writers put their pictures in
MAX_IMAGES = 24
TTL = 20.0                                 # seconds a scan answer is reused (the views poll it)
VERIFIED_KEYS = ("verified", "verified_in_game", "gameplay_verified")
TICKET_KEYS = ("requests", "request", "tickets", "ticket", "request_number")


# ------------------------------------------------------------------------------------------------- folder scan

def mods_root(config) -> Path:
    return Path(config.cache) / "mods"


def _safe_component(value) -> bool:
    return isinstance(value, str) and bool(value) and value not in (".", "..") and not any(c in value for c in "/\\:\0")


def _images(folder: Path) -> list[str]:
    """Preview pictures in the mod folder (top level + preview/ previews/), never the game's own asset tree."""
    found = []
    for sub in ("", *PREVIEW_DIRS):
        d = folder / sub if sub else folder
        if not d.is_dir() or d.is_symlink():
            continue
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except OSError:
            continue
        for e in entries:
            if Path(e.name).suffix.lower() in IMAGE_TYPES and e.is_file(follow_symlinks=False):
                found.append(f"{sub}/{e.name}" if sub else e.name)
    # pictures named like a preview first (frames_preview.png, preview.png, atlas.png ...)
    found.sort(key=lambda n: (0 if re.search(r"preview|thumb|shot|frame", n, re.I) else 1, n.lower()))
    return found[:MAX_IMAGES]


def _size(folder: Path) -> tuple[int, int, int]:
    """(bytes, own bytes, files): own bytes leave out hard links to the shared base copy (filemods' folder games)."""
    total = own = count = 0
    stack = [folder]
    while stack:
        d = stack.pop()
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    stack.append(Path(e.path))
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    total += st.st_size
                    count += 1
                    if st.st_nlink <= 1:
                        own += st.st_size
            except OSError:
                continue
    return total, own, count


_FOLDER_CACHE: dict = {}
_FOLDER_LOCK = threading.Lock()


def read_folder(folder: Path) -> dict | None:
    """One built mod folder -> its raw facts (marker, images, size), cached until the marker changes."""
    marker = folder / MARKER
    try:
        st = marker.stat()
    except OSError:
        return None
    if (folder / STAGED_MARK).exists() or STAGED_SEP in folder.name:
        return None
    key = (str(folder), st.st_mtime_ns, st.st_size)
    with _FOLDER_LOCK:
        hit = _FOLDER_CACHE.get(str(folder))
    if hit and hit[0] == key:
        return hit[1]
    try:
        meta = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    size, own, files = _size(folder)
    rec = {"name": folder.name, "game_id": folder.parent.name, "meta": meta, "images": _images(folder),
           "size": size, "own_size": own, "files": files, "marker_mtime": st.st_mtime}
    with _FOLDER_LOCK:
        _FOLDER_CACHE[str(folder)] = (key, rec)
    return rec


def scan(root: Path) -> list[dict]:
    """Every built mod under <cache>/mods/<game_id>/<mod>/ (a .gbox-mod.json marker; staging copies left out)."""
    out = []
    root = Path(root)
    if not root.is_dir():
        return out
    for gdir in sorted(root.iterdir()):
        if not gdir.is_dir() or gdir.is_symlink() or not _safe_component(gdir.name):
            continue
        try:
            mods = sorted(gdir.iterdir())
        except OSError:
            continue
        for mdir in mods:
            if mdir.is_dir() and not mdir.is_symlink() and _safe_component(mdir.name):
                rec = read_folder(mdir)
                if rec:
                    out.append(rec)
    return out


# ------------------------------------------------------------------------------------------------- normalizing

def writer_of(meta: dict, name: str) -> str:
    """Which writer built it: the marker's own `writer`, else the (gbox.<module>) its file notes name, else the
    mod name's prefix."""
    w = meta.get("writer")
    if isinstance(w, str) and w.strip():
        m = re.match(r"gbox\.([a-z0-9_]+)", w.strip())
        return m[1] if m else w.strip().split()[0]
    for f in meta.get("files") or []:
        m = re.search(r"\(gbox\.([a-z0-9_]+)", str(f))
        if m:
            return m[1]
    if meta.get("cast"):
        return "cast_swap"
    if "_" in name:
        return name.split("_", 1)[0]
    return "file mod" if meta.get("files") else "unknown"


def _as_list(v) -> list:
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def changes_of(meta: dict) -> list[dict]:
    """donor -> slot rows from whichever shape the writer recorded (cast plan rows keep their status / reason)."""
    rows = []
    if isinstance(meta.get("cast"), list):                       # cast_swap: the per-slot report
        for r in meta["cast"]:
            if isinstance(r, dict):
                rows.append({"donor": r.get("character") or r.get("donor") or "", "slot": str(r.get("slot") or ""),
                             "status": r.get("status") or "", **({"reason": str(r["reason"])} if r.get("reason") else {})})
        return rows
    if isinstance(meta.get("roster"), list):                     # doa2 roster: [{fighter, character}]
        for r in meta["roster"]:
            if isinstance(r, dict):
                rows.append({"donor": r.get("character") or "", "slot": str(r.get("fighter") or r.get("slot") or "")})
        if rows:
            return rows
    donors = _as_list(meta.get("characters")) or _as_list(meta.get("character"))
    slots = _as_list(meta.get("replaces"))
    if not slots:
        enemies = meta.get("enemies")
        if isinstance(enemies, dict):                            # pso_enemy cast: {enemy: donor}
            return [{"donor": str(d), "slot": f"enemy:{k}"} for k, d in enemies.items()]
        slots = ([meta["slot"]] if meta.get("slot") else
                 [f"enemy:{e}" for e in enemies] if isinstance(enemies, list) else
                 [o if isinstance(o, str) else (o.get("name") or o.get("slot") or "") for o in _as_list(meta.get("outfits"))]
                 if meta.get("outfits") else [])
    if not donors and not slots:
        return rows
    if len(donors) == len(slots):
        return [{"donor": str(d), "slot": str(s)} for d, s in zip(donors, slots)]
    if len(donors) == 1:
        return [{"donor": str(donors[0]), "slot": ", ".join(str(s) for s in slots) or "player"}]
    return [{"donor": ", ".join(str(d) for d in donors), "slot": ", ".join(str(s) for s in slots)}]


def verified_of(meta: dict, card: dict | None) -> bool:
    if card and card.get("verified"):
        return True
    return any(meta.get(k) is True for k in VERIFIED_KEYS)


def tickets_of(meta: dict, card: dict | None) -> list[int]:
    out = set()
    for v in [*(card or {}).get("requests", [])] + [x for k in TICKET_KEYS for x in _as_list(meta.get(k))]:
        try:
            n = int(str(v).lstrip("#"))
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.add(n)
    return sorted(out)


def card_mod(card: dict) -> str:
    """The file mod a card boots (its @launch call), if any."""
    for c in card.get("calls") or []:
        if c.get("tool") == "@launch" and (c.get("input") or {}).get("mod"):
            return c["input"]["mod"]
    return ""


def card_index(cards: list[dict]) -> dict:
    idx = {}
    for c in sorted(cards, key=lambda c: c.get("ts") or 0):     # newest card wins
        mod = card_mod(c)
        if mod:
            idx[(c.get("game_id") or "", mod)] = c
    return idx


def launch_index(sessions: list[dict], jobs: list[dict]) -> dict:
    """(game_id, mod) -> the newest launch result: a session (running / ended + its exit) or a failed launch job."""
    out = {}
    for s in sessions:
        mod = s.get("collection_mod") or s.get("mod")
        if not mod:
            continue
        k = (s.get("game_id") or "", mod)
        t = s.get("started") or 0
        if k not in out or t > out[k]["ts"]:
            ex = s.get("exit")
            out[k] = {"ts": t, "state": s.get("state") or "", "session_id": s.get("session_id"),
                      "ended": s.get("ended"), "adapter": s.get("adapter"),
                      **({"exit": ex if isinstance(ex, str) else json.dumps(ex, default=str)[:300]} if ex else {})}
    for j in jobs:
        if j.get("tool") != "launch_game" or j.get("state") not in ("failed", "cancelled"):
            continue
        inp = j.get("input") or {}
        mod = inp.get("mod")
        gid = (inp.get("game") or {}).get("game_id") if isinstance(inp.get("game"), dict) else ""
        if not mod or not gid:
            continue
        k, t = (gid, mod), j.get("finished") or j.get("updated") or j.get("created") or 0
        if k not in out or t > out[k]["ts"]:
            out[k] = {"ts": t, "state": j["state"], "job_id": j.get("id"), "error": str(j.get("error") or "")[:400]}
    return out


def donor_previews(changes: list[dict], library: Path | None) -> list[dict]:
    out, seen = [], set()
    if not library:
        return out
    for r in changes:
        for slug in str(r.get("donor") or "").split(","):
            slug = slug.strip()
            if not slug or slug in seen or not _safe_component(slug):
                continue
            seen.add(slug)
            if (Path(library) / slug / "preview.png").is_file():
                out.append({"slug": slug, "url": f"/api/characters/{slug}/preview"})
    return out


def entry(rec: dict, card: dict | None, launch: dict | None, catalog: dict | None, requests: dict, library) -> dict:
    meta, gid, name = rec["meta"], rec["game_id"], rec["name"]
    changes = changes_of(meta)
    built = meta.get("built")
    built = float(built) if isinstance(built, (int, float)) else rec.get("marker_mtime") or 0
    base = f"/api/mods/built/{gid}/{name}/image/"
    shots = [s for s in [*(card or {}).get("shots", [])] if s]
    if card and card.get("thumb") and card["thumb"] not in shots:
        shots.insert(0, card["thumb"])
    tickets = tickets_of(meta, card)
    return {
        "key": f"{gid}/{name}", "name": name, "game_id": gid,
        "title": (catalog or {}).get("title") or (card or {}).get("game_title") or meta.get("game_title") or gid,
        "platform": (catalog or {}).get("platform") or "",
        "mod_title": meta.get("title") or (card or {}).get("title") or name,
        "writer": writer_of(meta, name), "changes": changes, "cast": isinstance(meta.get("cast"), list),
        "report": meta.get("cast") if isinstance(meta.get("cast"), list) else None,
        "cast_source": meta.get("cast_source") or "",
        "built": built, "size": rec["size"], "own_size": rec["own_size"], "files": rec["files"],
        "image": meta.get("image") or "",
        "verified": verified_of(meta, card), "last_launch": launch,
        "images": [{"name": n, "url": base + n} for n in rec["images"]],
        "donor_previews": donor_previews(changes, library),
        "shots": [{"sha256": s, "url": f"/api/artifacts/{s}"} for s in shots],
        "card_id": (card or {}).get("id") or "", "state_slot": (card or {}).get("state_slot"),
        "video": (card or {}).get("video") or "",
        "tickets": [{"number": n, **({k: requests[n].get(k) for k in ("id", "title", "status")} if n in requests else {})}
                    for n in tickets],
    }


def card_for(rec: dict, existing: dict, catalog: dict | None) -> tuple[str, dict]:
    """A mod card that launches this built folder (the shape POST /api/mods saves)."""
    meta, gid, name = rec["meta"], rec["game_id"], rec["name"]
    changes = changes_of(meta)
    title = str(meta.get("title") or name)[:120]
    mid = hashlib.sha1(f"{gid}:{title.lower()}".encode()).hexdigest()[:12]
    other = existing.get(mid)
    if other and card_mod(other) != name:                         # same title, another mod: keep both cards
        title = f"{title} [{name}]"
        mid = hashlib.sha1(f"{gid}:{title.lower()}".encode()).hexdigest()[:12]
    what = "; ".join(f"{r['donor'] or '?'} -> {r['slot'] or '?'}" for r in changes)[:500]
    built = meta.get("built") if isinstance(meta.get("built"), (int, float)) else rec.get("marker_mtime") or time.time()
    return mid, {"id": mid, "title": title, "calls": [{"tool": "@launch", "input": {"mod": name}}], "game_id": gid,
                 "game_title": (catalog or {}).get("title") or "",
                 "desc": f"Built by {writer_of(meta, name)}" + (f": {what}" if what else "") + " (registered from the built mod folder)",
                 "verified": verified_of(meta, None), "requests": tickets_of(meta, None),
                 "by": "mods-gallery", "auto_registered": True, "ts": float(built)}


def register_missing(store, records: list[dict]) -> list[str]:
    """Save a mod card for every built folder no card launches yet; returns the new card ids (idempotent)."""
    made = []
    with store.lock:
        cards = store.all("mod")
        have = card_index(cards)
        by_id = {c.get("id"): c for c in cards}
        for rec in records:
            if (rec["game_id"], rec["name"]) in have:
                continue
            mid, doc = card_for(rec, by_id, store.catalog_get(rec["game_id"]))
            if mid in by_id and card_mod(by_id[mid]) == rec["name"]:
                continue
            store.put("mod", mid, doc)
            by_id[mid] = doc
            have[(rec["game_id"], rec["name"])] = doc
            made.append(mid)
    for mid in made:
        store.audit("mods-gallery", "mod.register", mid, {"from": "built folder"})
    return made


def gallery(store, config, *, register: bool = True) -> dict:
    """The whole gallery, newest build first."""
    root = mods_root(config)
    records = scan(root)
    made = register_missing(store, records) if register and records else []
    cards = card_index(store.all("mod"))
    launches = launch_index(store.all("session"), store.all("job"))
    requests = {}
    for r in store.all("request"):
        if isinstance(r.get("number"), int):
            requests[r["number"]] = r
    try:
        from . import characters
        library = characters.library_root(config)
    except Exception:                                            # noqa: BLE001 - previews are a convenience
        library = None
    catalogs: dict = {}
    items = []
    for rec in records:
        gid = rec["game_id"]
        if gid not in catalogs:
            catalogs[gid] = store.catalog_get(gid)
        items.append(entry(rec, cards.get((gid, rec["name"])), launches.get((gid, rec["name"])), catalogs[gid],
                           requests, library))
    items.sort(key=lambda m: -(m["built"] or 0))
    return {"items": items, "registered": made, "cache_dir": str(root)}


def select(items: list[dict], game_id: str = "", writer: str = "", q: str = "") -> list[dict]:
    words = [w for w in q.lower().split() if w]

    def hay(m):
        return " ".join([m["name"], m["game_id"], m["title"], m["mod_title"], m["writer"],
                         *(f"{r.get('donor')} {r.get('slot')}" for r in m["changes"]),
                         *(f"#{t['number']}" for t in m["tickets"])]).lower()
    return [m for m in items if (not game_id or m["game_id"] == game_id) and (not writer or m["writer"] == writer)
            and all(w in hay(m) for w in words)]


def facets(items: list[dict]) -> dict:
    games, writers = {}, {}
    for m in items:
        g = games.setdefault(m["game_id"], {"game_id": m["game_id"], "title": m["title"], "count": 0})
        g["count"] += 1
        writers[m["writer"]] = writers.get(m["writer"], 0) + 1
    return {"games": sorted(games.values(), key=lambda g: g["title"].lower()),
            "writers": [{"writer": w, "count": n} for w, n in sorted(writers.items())]}


# ------------------------------------------------------------------------------------------------- routes

def image_path(config, game_id: str, mod: str, name: str) -> Path:
    """The preview picture a gallery card links to, or ValueError (outside the folder, not a picture, staged copy)."""
    if not (_safe_component(game_id) and _safe_component(mod)) or STAGED_SEP in mod:
        raise ValueError("bad mod")
    root = mods_root(config).resolve()
    folder = (root / game_id / mod)
    if not folder.resolve().is_relative_to(root / game_id) or not (folder / MARKER).is_file() or (folder / STAGED_MARK).exists():
        raise ValueError("no such built mod")
    parts = name.split("/") if isinstance(name, str) else []
    if not parts or len(parts) > 2 or any(not _safe_component(p) for p in parts) or (len(parts) == 2 and parts[0] not in PREVIEW_DIRS):
        raise ValueError("bad picture name")
    f = folder.joinpath(*parts)
    if f.suffix.lower() not in IMAGE_TYPES or f.is_symlink() or not f.resolve().is_relative_to(folder.resolve()) or not f.is_file():
        raise ValueError("no such picture")
    return f


def routes(app, store, config, auth):
    cache = {"at": 0.0, "data": None}
    lock = threading.Lock()

    def current(fresh: bool = False) -> dict:
        with lock:
            if fresh or cache["data"] is None or time.time() - cache["at"] > TTL:
                cache["data"], cache["at"] = gallery(store, config), time.time()
            return cache["data"]

    app.state.built_mods_invalidate = lambda: cache.update(at=0.0)

    @app.get("/api/mods/built")
    def built_list(game_id: str = "", writer: str = "", q: str = "", offset: int = 0, limit: int = 0,
                   fresh: bool = False, actor=Depends(auth)):
        """Every built mod folder in this node's cache, newest first, joined with its mod card (filters + pages)."""
        data = current(fresh)
        items = data["items"]
        picked = select(items, game_id, writer, q)
        offset = max(0, offset)
        page = picked[offset:offset + limit] if limit > 0 else picked[offset:]
        return {"total": len(picked), "all": len(items), "offset": offset, "limit": limit, "items": page,
                **facets(items), "registered": data["registered"], "cache_dir": data["cache_dir"]}

    @app.get("/api/mods/built/{game_id}/{mod}/image/{name:path}")
    def built_image(game_id: str, mod: str, name: str, actor=Depends(auth)):
        try:
            f = image_path(config, game_id, mod, name)
        except (ValueError, OSError):
            raise HTTPException(404, "no such picture") from None
        return FileResponse(f, media_type=IMAGE_TYPES[f.suffix.lower()], headers={"cache-control": "max-age=300"})

    @app.on_event("startup")
    async def _register_built():
        # cards for builds nobody saved, without waiting for the first gallery visit
        def run():
            try:
                current(True)
            except Exception:                                    # noqa: BLE001 - the view retries on demand
                pass
        threading.Thread(target=run, name="built-mods-register", daemon=True).start()

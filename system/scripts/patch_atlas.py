#!/usr/bin/env python3
"""gBox's patch atlas: the platform database of game patching (docs/patch-atlas/README.md).

For every game gBox has modded: how each replaceable file / asset is identified, how gBox replaced it, and how it can
be swapped or hooked live during gameplay (insert / replace / live replace / pick whip). One JSON file holds it all,
system/gbox/patch_atlas.json; the Markdown pages under docs/patch-atlas/ are rendered from it.

Each game in the atlas has two halves:
  curated    the research: identification, file layout, asset classes, live hooks, gaps, sources. People and agents
             write it (`curate`); the generator never changes it.
  generated  the facts the generator recomputes: the builds in the Spark's patch library and the live Switch build
             folders (`scan`), the RAM maps / cheat codes / item tables / picker profiles in the repo, and which cited
             source files exist.

Stdlib only, so the same file runs on the Spark as the scanner.

  # on the Spark (read-only): summarise the patch library and the live Switch builds into one small JSON
  python3 patch_atlas.py scan --library ~/gBox/system/gbox-data/patch-library \\
      --switch ~/gBox_alt/gbox-cache/mods --db ~/gBox/system/gbox-data/gbox.sqlite3 --atlas patch_atlas.json \\
      --out /tmp/patch_atlas_scan.json

  # in the repo (system/): merge a scan, refresh the repo facts, render the pages
  python scripts/patch_atlas.py build --scan patch_atlas_scan.json
  python scripts/patch_atlas.py build                 # no new scan: repo facts + pages only
  python scripts/patch_atlas.py curate --from knowledge.json     # {"games": {slug: GAME}} -> curated halves
  python scripts/patch_atlas.py check                 # exit 1 when the JSON or a page is stale
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import socket
import sqlite3
import sys
import time
from pathlib import Path

FORMAT = "gbox-patch-atlas/1"
SCAN_FORMAT = "gbox-patch-scan/1"
REPO = Path(__file__).resolve().parents[1]                 # system/
ATLAS = REPO / "gbox" / "patch_atlas.json"
DOCS = REPO / "docs" / "patch-atlas"
PLATFORM_DIR = {"psx": "ps1"}
PLATFORM_ORDER = ["switch", "gamecube", "wii", "ps2", "psx", "ps3", "dreamcast", "n64", "xbox", "xbox360", "nes", "3ds"]
PLATFORM_NAMES = {"switch": "Nintendo Switch", "gamecube": "GameCube", "wii": "Wii", "ps2": "PlayStation 2",
                  "psx": "PlayStation", "ps3": "PlayStation 3", "dreamcast": "Dreamcast", "n64": "Nintendo 64",
                  "xbox": "Xbox", "xbox360": "Xbox 360", "nes": "NES", "3ds": "Nintendo 3DS"}
CURATED_KEYS = ("title", "platform", "game_ids", "emulator", "identification", "layout", "assets", "live", "gaps",
                "sources")
WRITER_GLOBS = ("*_swap.py", "*_writer.py", "*_cast.py", "*_mods.py", "*_mod.py")
BUILD_FILES_KEPT = 8            # per build row in the atlas JSON
BUILD_ROWS_RENDERED = 80        # per page
SIDE_SUFFIX = ".sha256.json"


# ------------------------------------------------------------------------------------------------ small helpers ----

def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def dump_json(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def slugify(title: str, platform: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "game").lower()).strip("-")[:40].strip("-") or "game"
    return f"{base}-{platform or 'other'}"


def platform_dir(platform: str) -> str:
    return PLATFORM_DIR.get(platform, platform or "other")


def day(ts) -> str | None:
    """A build's timestamp as YYYY-MM-DD (UTC): float epochs and ISO strings both appear in manifests."""
    if isinstance(ts, (int, float)) and ts > 0:
        return time.strftime("%Y-%m-%d", time.gmtime(ts))
    if isinstance(ts, str) and re.match(r"\d{4}-\d\d-\d\d", ts):
        return ts[:10]
    return None


def strs(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    return []


def short(s, n=160) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def sidecar_name(folder: str) -> str:
    """'.sm64_ryo.sha256.json' / '.pe_mario.sha256.json.cold' -> the build it hashed ('sm64_ryo', 'pe_mario')."""
    n = folder[:-5] if folder.endswith(".cold") else folder
    n = n[1:] if n.startswith(".") else n
    return n[:-len(SIDE_SUFFIX)] if n.endswith(SIDE_SUFFIX) else n


def build_name(folder: str) -> str:
    return folder[:-5] if folder.endswith(".cold") else folder


# -------------------------------------------------------------------------------------- manifest normalisation ----

def verified(man: dict):
    """True / False / None from the several flags writers use (verified_in_game, gameplay_verified, verified)."""
    for key in ("verified_in_game", "gameplay_verified", "verified"):
        v = man.get(key)
        if isinstance(v, bool):
            return v
    v = man.get("verification")
    if isinstance(v, dict):
        for key in ("in_game", "gameplay", "verified"):
            if isinstance(v.get(key), bool):
                return v[key]
    return None


RECIPE_ARGS = ("op", "slot", "character", "source", "seed", "assign", "mapping", "target_game", "kind")


def recipe(man: dict) -> dict | None:
    rec = man.get("recipe") or man.get("build_call")
    if not isinstance(rec, dict):
        return None
    inp = rec.get("input") if isinstance(rec.get("input"), dict) else {}
    args = {k: inp[k] for k in RECIPE_ARGS if isinstance(inp.get(k), (str, int, float, bool)) and k != "op"}
    out = {"tool": rec.get("tool")}
    if inp.get("op"):
        out["op"] = inp["op"]
    if args:
        out["args"] = args
    if isinstance(rec.get("plan"), dict):
        out["plan_keys"] = len(rec["plan"])
    return out


def files_of(man: dict) -> list[str]:
    out = strs(man.get("files"))
    for fc in man.get("file_changes") or []:
        if isinstance(fc, dict) and isinstance(fc.get("path"), str):
            out.append(fc["path"])
    ch = man.get("changes")
    if isinstance(ch, dict):
        out += [k for k in ch if isinstance(k, str)]
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def slots_of(man: dict) -> list[list[str]]:
    """[[slot, donor], ...] from slots / costumes / changes / character+target."""
    out = []
    for row in man.get("slots") or []:
        if isinstance(row, dict) and (row.get("slot") or row.get("donor")):
            out.append([str(row.get("slot") or ""), str(row.get("donor") or "")])
    for row in man.get("costumes") or []:
        if isinstance(row, dict) and row.get("donor"):
            out.append([str(row.get("costume") or ""), str(row["donor"])])
    ch = man.get("changes")
    if isinstance(ch, list):
        for row in ch:
            if isinstance(row, dict) and row.get("donor"):
                out.append([str(row.get("slot") or ""), str(row["donor"])])
    if not out and isinstance(man.get("character"), str) and man.get("character"):
        target = man.get("target") or man.get("slot") or "player"
        for donor in man["character"].split(","):
            if donor.strip():
                out.append([str(target), donor.strip()])
    return out


def build_note(man: dict) -> str | None:
    for key in ("note", "desc", "notes", "what"):
        if isinstance(man.get(key), str) and man[key].strip():
            return short(man[key], 200)
    hist = [h for h in man.get("history") or [] if isinstance(h, dict) and h.get("note")]
    return short(hist[-1]["note"], 200) if hist else None


def build_row(folder: str, man: dict | None, arc: dict | None, source: str) -> dict:
    """One build, compact: what it changed, who wrote it, how to rebuild it, whether it was seen in game."""
    man, arc = man or {}, arc or {}
    files = files_of(man)
    slots = slots_of(man)
    donors = []
    for _slot, d in slots:
        if d and d not in donors:
            donors.append(d)
    for d in strs(man.get("characters")):
        if d not in donors:
            donors.append(d)
    lfs = man.get("layeredfs") if isinstance(man.get("layeredfs"), dict) else {}
    tier = arc.get("tier") or ("cold" if folder.endswith(".cold") else ("live" if source == "switch" else "hot"))
    row = {"name": build_name(folder), "source": source, "tier": tier,
           "writer": man.get("writer") or None,   # (archive.json's "writer" falls back to the kind: not a writer)
           "kind": man.get("kind") or None,
           "recipe": recipe(man), "built": day(man.get("built") or man.get("built_at") or man.get("created")),
           "image": man.get("image") or arc.get("image") or None, "files_count": len(files),
           "files": files[:BUILD_FILES_KEPT], "slots_count": len(slots), "donors": donors[:8],
           "replaces": strs(man.get("replaces"))[:8], "verified": verified(man), "note": build_note(man)}
    if lfs:
        row["title_id"] = lfs.get("title_id")
        row["edits"] = len(man.get("history") or [])
        if man.get("hot_swaps"):
            row["hot_swaps"] = man["hot_swaps"]
    if arc:
        row["payload_files"] = len(arc.get("payload") or [])
        row["not_kept"] = len(arc.get("not_kept") or [])
        row["size"] = arc.get("size")
    if not man:
        row["note"] = "no .gbox-mod.json" + (f"; {short('; '.join(strs(arc.get('notes'))), 120)}" if arc.get("notes") else "")
    return {k: v for k, v in row.items() if v not in (None, [], {})}


# ------------------------------------------------------------------------------------------------------- scan ----

def scan_library(lib: Path) -> dict:
    """The patch library: <game_id>/<build>/{archive.json, .gbox-mod.json, payload/, meta/}. Folders named
    .<build>.sha256.json(.cold) are a deleted build's hash sidecar: recorded by name only."""
    folders = {}
    for gid in sorted(os.listdir(lib)) if lib.is_dir() else []:
        gp = lib / gid
        if not gp.is_dir():
            continue
        f = folders.setdefault(gid, {"source": "library", "title": None, "platform": None, "builds": [],
                                     "sidecars": []})
        for b in sorted(os.listdir(gp)):
            bp = gp / b
            if not bp.is_dir():
                continue
            arc = load_json(bp / "archive.json", {}) or {}
            man = load_json(bp / ".gbox-mod.json")
            f["title"] = f["title"] or arc.get("title") if arc.get("title") != "?" else f["title"]
            f["platform"] = f["platform"] or (arc.get("platform") if arc.get("platform") != "?" else None)
            lone = any("lone file" in n for n in strs(arc.get("notes")))
            if man is None and (lone or b.lstrip(".").replace(".cold", "").endswith(SIDE_SUFFIX)):
                f["sidecars"].append(sidecar_name(b))
                continue
            f["builds"].append(build_row(b, man if isinstance(man, dict) else None, arc, "library"))
        names = {r["name"] for r in f["builds"]}
        f["sidecars"] = sorted({s for s in f["sidecars"] if s not in names})
    return folders


def scan_switch(sw: Path) -> dict:
    """The live Switch builds: <game_id>/<build>/.gbox-mod.json, LayeredFS overlays (only the changed RomFS / ExeFS
    files)."""
    folders = {}
    for gid in sorted(os.listdir(sw)) if sw.is_dir() else []:
        gp = sw / gid
        if not gp.is_dir():
            continue
        f = folders.setdefault(gid, {"source": "switch", "title": None, "platform": "switch", "builds": [],
                                     "sidecars": []})
        for b in sorted(os.listdir(gp)):
            man = load_json(gp / b / ".gbox-mod.json")
            if not isinstance(man, dict):
                continue
            f["title"] = f["title"] or man.get("game_title")
            row = build_row(b, man, None, "switch")
            f["builds"].append(row)
            if row.get("title_id"):
                f["title_id"] = row["title_id"]
    return folders


def catalog_rows(db: Path, ids) -> dict:
    """{game_id: identification} from the catalog (read-only): title, platform, serial, file name, format, size."""
    out = {}
    if not db or not Path(db).is_file():
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for gid in sorted(set(ids)):
            r = con.execute("SELECT title, platform, system, body FROM catalog WHERE game_id=?", (gid,)).fetchone()
            if not r:
                continue
            try:
                body = json.loads(r[3] or "{}")
            except ValueError:
                body = {}
            rel = body.get("rel_path") or ""
            out[gid] = {k: v for k, v in {
                "title": r[0], "platform": r[1] or r[2], "region": body.get("region"), "serial": body.get("serial"),
                "file": rel.replace("\\", "/").rsplit("/", 1)[-1] or None, "format": body.get("format"),
                "size": body.get("size"), "library": body.get("library"),
                "hashes": body.get("hashes") if isinstance(body.get("hashes"), dict) and body.get("hashes") else None,
            }.items() if v not in (None, "", {})}
    finally:
        con.close()
    return out


def scan(library: Path | None, switch: Path | None, db: Path | None = None, atlas: Path | None = None,
         now: float | None = None) -> dict:
    folders = {}
    if library:
        folders.update(scan_library(Path(library)))
    if switch:
        for gid, f in scan_switch(Path(switch)).items():
            if gid in folders:
                folders[gid]["builds"] += f["builds"]
            else:
                folders[gid] = f
    ids = set(folders)
    a = load_json(atlas, {}) if atlas else {}
    for g in (a.get("games") or {}).values():          # an atlas, or a curate input ({games: {slug: GAME}})
        ids.update(strs((g.get("curated") or g).get("game_ids")))
    notes = []
    if library and not (Path(library) / "index.json").exists():
        notes.append("the library has no index.json: this scan is its index")
    return {"format": SCAN_FORMAT, "scanned_at": day(now or time.time()), "host": socket.gethostname(),
            "roots": {"library": str(library) if library else None, "switch": str(switch) if switch else None},
            "notes": notes, "folders": folders,
            "catalog": catalog_rows(Path(db), ids) if db else {}}


# ----------------------------------------------------------------------------------------------- repo facts ----

def _ram_maps(repo: Path) -> list[tuple[str, dict]]:
    files = sorted((repo / "profiles" / "gamedata").glob("*-ram.json")) + sorted((repo / "docs").glob("*-ram-map-*.json"))
    out = []
    for p in files:
        d = load_json(p)
        if isinstance(d, dict) and str(d.get("format", "")).startswith("gbox-ram-map"):
            out.append((p.relative_to(repo).as_posix(), d))
    return out


def _field_at(f: dict) -> str:
    if f.get("address"):
        return str(f["address"])
    p = f.get("pointer")
    if isinstance(p, list):
        return " -> ".join(str(x) for x in p)
    if isinstance(p, dict):
        base = p.get("base") or p.get("address") or ""
        offs = p.get("offsets") or p.get("chain") or []
        return " -> ".join([str(base)] + [str(o) for o in offs]) if offs else str(base)
    return str(p or "")


def ram_map_summary(rel: str, d: dict) -> dict:
    fields = []
    for name, f in (d.get("fields") or {}).items():
        if isinstance(f, dict):
            fields.append({"name": name, "at": _field_at(f), "type": f.get("type"),
                           "what": short(f.get("description"), 140), "source": f.get("source")})
    notes = d.get("notes")
    return {"file": rel, "id": d.get("id"), "title": d.get("title"), "platform": d.get("platform"),
            "endian": d.get("endian"), "groups": d.get("groups") or {}, "fields": fields,
            "notes": [short(n, 300) for n in (notes if isinstance(notes, list) else [notes] if notes else [])][:6]}


def _pick_profiles(repo: Path) -> list[tuple[str, dict]]:
    out = []
    for p in sorted((repo / "profiles").glob("*.json")):
        d = load_json(p)
        if isinstance(d, dict) and isinstance(d.get("match"), dict):
            out.append((p.relative_to(repo).as_posix(), d))
    return out


def _cited_paths(text: str) -> list[str]:
    return re.findall(r"(?:system/)?((?:gbox|docs|profiles|scripts|tests|clients|integrations)/[\w./\-]+\.(?:py|md|json|js))",
                      text or "")


def repo_facts(repo: Path, cur: dict, maps, profiles, caps, titles=()) -> dict:
    ids = set(strs(cur.get("game_ids")))
    ident = cur.get("identification") or {}
    tid = str(ident.get("title_id") or "").upper()
    disc = {str(ident.get(k) or "").upper() for k in ("disc_id", "serial") if ident.get(k)}
    names = [str(t).lower() for t in (cur.get("title"), *titles) if t]
    out = {"ram_maps": [], "codes": [], "items": [], "unlock": [], "pick_profiles": [], "capabilities": {},
           "missing_sources": []}
    for rel, d in maps:
        m = d.get("match") or {}
        if ids & set(strs(m.get("game_ids"))) or (tid and str(m.get("title_id") or "").upper() == tid) \
                or (disc and str(m.get("disc_id") or "").upper() in disc):
            out["ram_maps"].append(ram_map_summary(rel, d))
    for gid in sorted(ids):
        for kind in ("codes", "items", "unlock"):
            p = repo / "profiles" / "gamedata" / f"{gid}-{kind}.json"
            d = load_json(p)
            if d is None:
                continue
            row = {"file": p.relative_to(repo).as_posix()}
            if kind == "codes" and isinstance(d, dict):
                row |= {"codes": len(d.get("codes") or []), "verified": d.get("verified"),
                        "scope": strs(d.get("scope"))[:6]}
            elif kind == "items" and isinstance(d, dict):
                row["items"] = len(d.get("items") or [])
            out[kind].append(row)
        if gid in caps:
            out["capabilities"][gid] = {k: (v.get("result") if isinstance(v, dict) else v) for k, v in caps[gid].items()}
    for rel, d in profiles:
        m = d["match"]
        hit = d.get("game_id") in ids
        tc = str(m.get("title_contains") or "").lower()
        if not hit and tc and m.get("platform") == cur.get("platform") and any(tc in n for n in names):
            hit = True
        if not hit and disc & {str(s).upper() for s in strs(m.get("serial"))}:
            hit = True
        if hit:
            out["pick_profiles"].append({"file": rel, "id": d.get("id"), "title": d.get("title"),
                                         "camera": bool(d.get("camera")), "entities": bool(d.get("entities"))})
    cited = set()
    for a in cur.get("assets") or []:
        cited.update(_cited_paths(json.dumps(a)))
    for s in strs(cur.get("sources")):
        cited.update(_cited_paths(s))
    for rel in sorted(cited):
        if not (repo / rel).exists():
            out["missing_sources"].append(rel)
    return {k: v for k, v in out.items() if v}


def library_summary(folders: dict, ids: list[str], scanned_at) -> dict:
    rows, sidecars = [], []
    for gid in ids:
        f = folders.get(gid)
        if not f:
            continue
        for r in f["builds"]:
            rows.append({"folder": gid, **r})
        sidecars += f.get("sidecars") or []
    rows.sort(key=lambda r: (r.get("built") or "", r["name"]))
    files, donors = collections.Counter(), collections.Counter()
    for r in rows:
        files.update(r.get("files") or [])
        donors.update(r.get("donors") or [])
    ver = collections.Counter("yes" if r.get("verified") is True else "no" if r.get("verified") is False else "unknown"
                              for r in rows)
    count = lambda key: dict(collections.Counter(str(key(r)) for r in rows).most_common())  # noqa: E731
    return {"scanned_at": scanned_at, "folders": [g for g in ids if g in folders], "builds": len(rows),
            "by_source": count(lambda r: r["source"]), "by_writer": count(lambda r: r.get("writer")),
            "by_kind": count(lambda r: r.get("kind")),
            "by_tool": count(lambda r: "/".join(x for x in ((r.get("recipe") or {}).get("tool"),
                                                         (r.get("recipe") or {}).get("op")) if x) or None),
            "verified": dict(ver), "files_touched": [list(x) for x in files.most_common(40)],
            "donors": [list(x) for x in donors.most_common(25)], "sidecar_only": sorted(set(sidecars)), "rows": rows}


def status_of(cur: dict, lib: dict) -> dict:
    live = cur.get("live") or {}
    hooks = live.get("ram_hooks") or []
    assets = cur.get("assets") or []
    av = collections.Counter(str(a.get("verified_in_game")) for a in assets)
    replace = "proven" if av.get("yes") else "partial" if av.get("partial") else "untested" if assets else "none"
    return {"replace": replace, "live_file_swap": (live.get("file_swap") or {}).get("status") or "none",
            "ram_writes_proven": sum(1 for h in hooks if h.get("status") == "proven_write"),
            "ram_reads_proven": sum(1 for h in hooks if h.get("status") == "proven_read"),
            "pickwhip": (live.get("pickwhip") or {}).get("status") or "none",
            "assets_verified": av.get("yes", 0), "assets": len(assets),
            "builds": lib.get("builds", 0), "builds_verified": (lib.get("verified") or {}).get("yes", 0)}


def unpaged_writers(repo: Path, games: dict) -> list[str]:
    text = json.dumps([g.get("curated") for g in games.values()])
    out = []
    for pat in WRITER_GLOBS:
        for p in sorted((repo / "gbox").glob(pat)) + sorted((repo / "gbox" / "mercs" / "titles").glob(pat)):
            rel = p.relative_to(repo).as_posix()
            if p.stem not in text and rel not in out:
                out.append(rel)
    return sorted(out)


# ---------------------------------------------------------------------------------------------------- build ----

def skeleton() -> dict:
    return {"format": FORMAT, "about": "gBox patch atlas: see docs/patch-atlas/README.md", "scan": {}, "platforms": {},
            "games": {}, "unpaged_writers": []}


def assign(folders: dict, games: dict) -> dict[str, str]:
    """folder id -> slug: by catalog id, then by Switch title id, else a new stub entry."""
    by_id, by_tid = {}, {}
    for slug, g in games.items():
        cur = g.get("curated") or {}
        for gid in strs(cur.get("game_ids")):
            by_id[gid] = slug
        tid = str((cur.get("identification") or {}).get("title_id") or "").upper()
        if tid:
            by_tid[tid] = slug
    out = {}
    for gid, f in folders.items():
        slug = by_id.get(gid) or by_tid.get(gid.upper()) or by_tid.get(str(f.get("title_id") or "").upper())
        if not slug:
            slug = slugify(f.get("title") or gid, f.get("platform") or "other")
            if slug not in games:
                games[slug] = {"curated": {"title": f.get("title") or gid, "platform": f.get("platform") or "other",
                                           "game_ids": [gid], "stub": True,
                                           "gaps": ["no curated research yet: research the game and run "
                                                    "`patch_atlas.py curate`"]}}
            else:
                games[slug]["curated"].setdefault("game_ids", []).append(gid)
        out[gid] = slug
    return out


def build(atlas: dict, scan_doc: dict | None, repo: Path = REPO) -> dict:
    atlas = json.loads(json.dumps(atlas)) if atlas else skeleton()
    for k, v in skeleton().items():
        atlas.setdefault(k, v)
    games = atlas["games"]
    if scan_doc:
        if scan_doc.get("format") != SCAN_FORMAT:
            raise ValueError(f"not a {SCAN_FORMAT} scan")
        folders = scan_doc.get("folders") or {}
        where = assign(folders, games)
        atlas["scan"] = {"scanned_at": scan_doc.get("scanned_at"), "host": scan_doc.get("host"),
                         "roots": scan_doc.get("roots"), "notes": scan_doc.get("notes") or [],
                         "folders": len(folders), "builds": sum(len(f["builds"]) for f in folders.values())}
        for slug, g in games.items():
            ids = [gid for gid, s in where.items() if s == slug]
            gen = g.setdefault("generated", {})
            gen["library"] = library_summary(folders, ids, scan_doc.get("scanned_at")) if ids else {}
            cat = {gid: row for gid, row in (scan_doc.get("catalog") or {}).items()
                   if gid in set(strs(g["curated"].get("game_ids"))) | set(ids)}
            gen["catalog"] = cat
    maps, profiles = _ram_maps(repo), _pick_profiles(repo)
    caps = (load_json(repo / "profiles" / "gamedata" / "game-capabilities.json", {}) or {}).get("games") or {}
    for slug, g in games.items():
        cur = g.setdefault("curated", {})
        gen = g.setdefault("generated", {})
        gen.setdefault("library", {})
        gen.setdefault("catalog", {})
        gen["repo"] = repo_facts(repo, cur, maps, profiles, caps,
                                 [c.get("title") for c in (gen.get("catalog") or {}).values()])
        g["status"] = status_of(cur, gen["library"])
        g["page"] = f"{platform_dir(cur.get('platform') or 'other')}/{slug}.md"
    order = {p: i for i, p in enumerate(PLATFORM_ORDER)}
    atlas["games"] = {s: {"curated": g["curated"], "status": g["status"], "page": g["page"], "generated": g["generated"]}
                      for s, g in sorted(games.items(),
                                         key=lambda kv: (order.get(kv[1]["curated"].get("platform"), 99), kv[0]))}
    atlas["unpaged_writers"] = unpaged_writers(repo, atlas["games"])
    return atlas


def curate(atlas: dict, doc: dict, *, require: bool = True) -> list[str]:
    """Set the curated half of each game in doc {"games": {slug: GAME}} (and doc["platforms"] when present)."""
    atlas = atlas if atlas else skeleton()
    done = []
    for slug, g in (doc.get("games") or {}).items():
        missing = [k for k in CURATED_KEYS if k not in g]
        if require and missing:
            raise ValueError(f"{slug}: missing {', '.join(missing)}")
        entry = atlas["games"].setdefault(slug, {})
        entry["curated"] = g
        done.append(slug)
    for name, p in (doc.get("platforms") or {}).items():
        atlas["platforms"][name] = p
        done.append(f"platform:{name}")
    return done


# --------------------------------------------------------------------------------------------------- render ----

def cell(v, n=None) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v)
    s = " ".join(str(v).split()).replace("|", "\\|")
    return short(s, n) if n else s


def table(head: list[str], rows: list[list]) -> list[str]:
    if not rows:
        return []
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return out + [""]


STATUS_WORDS = {"proven": "proven live", "static_only": "static only", "none": "none", "works": "works",
                "partial": "partial", "untested": "untested"}


def status_line(st: dict) -> str:
    return (f"replace: **{st['replace']}** · live file swap: **{STATUS_WORDS.get(st['live_file_swap'], st['live_file_swap'])}**"
            f" · RAM writes proven: **{st['ram_writes_proven']}** (reads {st['ram_reads_proven']})"
            f" · pick whip: **{st['pickwhip']}** · builds scanned: **{st['builds']}** (manifest-verified "
            f"{st['builds_verified']})")


def render_page(slug: str, g: dict, atlas: dict) -> str:
    cur, gen, st = g["curated"], g["generated"], g["status"]
    plat = cur.get("platform") or "other"
    L = [f"# {cur.get('title') or slug} ({PLATFORM_NAMES.get(plat, plat)})", "",
         "<!-- Generated by scripts/patch_atlas.py from system/gbox/patch_atlas.json. Do not edit by hand: change the "
         "curated entry (`patch_atlas.py curate`) or rescan the library, then `patch_atlas.py build`. -->", "",
         f"Atlas key `{slug}` · [atlas index](../README.md) · [{PLATFORM_NAMES.get(plat, plat)} mechanisms]"
         f"(../README.md#{plat})", "", status_line(st), ""]
    if cur.get("stub"):
        L += ["> **Stub:** builds exist in the patch library but nobody has researched this game for the atlas yet.", ""]
    if cur.get("emulator"):
        L += [f"**Runs on:** {cell(cur['emulator'])}", ""]
    # identification
    L += ["## Identification", ""]
    ident = cur.get("identification") or {}
    rows = [[k, ident.get(k)] for k in ("title_id", "disc_id", "serial") if ident.get(k)]
    for k, v in (ident.get("hashes") or {}).items():
        rows.append([f"hash: {k}", v])
    L += table(["what", "value"], rows)
    cat = gen.get("catalog") or {}
    ids = strs(cur.get("game_ids"))
    crow = []
    for gid in ids:
        c = cat.get(gid) or {}
        crow.append([f"`{gid}`", c.get("title"), c.get("file"), c.get("format"), c.get("size"), c.get("serial"),
                     c.get("region")])
    L += ["Catalog ids (a gBox `game_id` is the first 16 hex of the file's sha1 when the library is hashed, else of "
          "sha1(`<library>:<rel_path>`); see the README):", ""]
    L += table(["game_id", "catalog title", "file", "format", "bytes", "serial", "region"], crow)
    if ident.get("notes"):
        L += [cell(ident["notes"]), ""]
    # layout
    if cur.get("layout"):
        L += ["## File layout", ""]
        L += table(["container", "format", "reader", "notes"],
                   [[f"`{x.get('container')}`" if x.get("container") else "", x.get("format"), x.get("reader"),
                     x.get("notes")] for x in cur["layout"]])
    # assets
    if cur.get("assets"):
        L += ["## Replaceable assets", ""]
        L += table(["class", "where", "how gBox found it", "writer", "method", "in game", "evidence / notes"],
                   [[a.get("class"), a.get("where"), a.get("how_found"), a.get("writer"), a.get("method"),
                     a.get("verified_in_game"), " ".join(x for x in (cell(a.get("evidence")), cell(a.get("notes"))) if x)]
                    for a in cur["assets"]])
    # live
    live = cur.get("live") or {}
    if live:
        L += ["## Live replacement", ""]
        fs = live.get("file_swap") or {}
        if fs:
            L += [f"**Live file swap: {STATUS_WORDS.get(fs.get('status'), fs.get('status'))}.** {cell(fs.get('how'))}", ""]
        pw = live.get("pickwhip") or {}
        if pw:
            L += [f"**Pick whip: {pw.get('status')}.** {cell(pw.get('how'))}", ""]
        if live.get("live_controls"):
            L += [f"**Live controls:** {cell(live['live_controls'])}", ""]
        if live.get("ram_hooks"):
            L += ["### RAM / runtime hooks (curated)", ""]
            L += table(["hook", "address", "what", "status", "source"],
                       [[h.get("name"), f"`{h.get('address')}`" if h.get("address") else "", h.get("what"),
                         h.get("status"), h.get("source")] for h in live["ram_hooks"]])
    repo = gen.get("repo") or {}
    for m in repo.get("ram_maps") or []:
        L += [f"### RAM map `{m['file']}` ({m.get('id')}, {m.get('endian')}-endian)", ""]
        if m.get("groups"):
            L += ["Groups: " + "; ".join(f"`{k}` {cell(v, 90)}" for k, v in m["groups"].items()), ""]
        fields = m.get("fields") or []
        if fields:
            L += table(["field", "at", "type", "what", "source"],
                       [[f"`{f['name']}`", f"`{f['at']}`" if f.get("at") else "", f.get("type"), f.get("what"),
                         f.get("source")] for f in fields[:120]])
            if len(fields) > 120:
                L += [f"... and {len(fields) - 120} more fields in the map.", ""]
        else:
            L += ["The map holds no absolute fields (an ASLR title: the driver resolves module base + offset); its notes:", ""]
            L += [f"- {cell(n)}" for n in m.get("notes") or []] + [""]
    extra = []
    for row in repo.get("codes") or []:
        extra.append(f"- cheat codes `{row['file']}`: {row.get('codes')} codes, verified {row.get('verified')}, "
                     f"scope {cell(row.get('scope'))}")
    for row in repo.get("items") or []:
        extra.append(f"- item table `{row['file']}`: {row.get('items')} items")
    for row in repo.get("unlock") or []:
        extra.append(f"- unlock map `{row['file']}`")
    for row in repo.get("pick_profiles") or []:
        extra.append(f"- picker profile `{row['file']}` ({row.get('id')}): camera {row.get('camera')}, "
                     f"entities {row.get('entities')}")
    for gid, c in (repo.get("capabilities") or {}).items():
        extra.append(f"- capabilities (`profiles/gamedata/game-capabilities.json`, {gid}): "
                     + ", ".join(f"{k} {v}" for k, v in c.items()))
    if extra:
        L += ["### Other repo data for this game", ""] + extra + [""]
    # builds
    lib = gen.get("library") or {}
    if lib.get("builds") or lib.get("sidecar_only"):
        L += ["## Builds in the patch library", "",
              f"Scanned {lib.get('scanned_at')} from {', '.join('`' + f + '`' for f in lib.get('folders') or [])}: "
              f"{lib.get('builds', 0)} builds. Their manifests mark {(lib.get('verified') or {}).get('yes', 0)} "
              f"verified in game, {(lib.get('verified') or {}).get('no', 0)} not verified and "
              f"{(lib.get('verified') or {}).get('unknown', 0)} unrecorded (writers rarely update the flag after a "
              "check: the assets table above has the in-game evidence).", ""]
        for label, key in (("Writers", "by_writer"), ("Recipes (tool/op)", "by_tool")):
            known = {k: v for k, v in (lib.get(key) or {}).items() if k != "None"}
            if known:
                rest = sum((lib.get(key) or {}).values()) - sum(known.values())
                L += [f"{label}: " + ", ".join(f"`{k}` x{v}" for k, v in known.items())
                      + (f" (unrecorded x{rest})" if rest else ""), ""]
        if lib.get("files_touched"):
            L += ["Files replaced (by how many builds): " + ", ".join(f"`{f}` x{n}" for f, n in lib["files_touched"]), ""]
        if lib.get("donors"):
            L += ["Donors used: " + ", ".join(f"{d} x{n}" for d, n in lib["donors"]), ""]
        rows = lib.get("rows") or []
        L += table(["build", "built", "source", "writer", "recipe", "files", "donors / slots", "manifest verified", "note"],
                   [[f"`{r['name']}`", r.get("built"), f"{r['source']}/{r.get('tier')}", r.get("writer") or r.get("kind"),
                     "/".join(str(x) for x in ((r.get("recipe") or {}).get("tool"), (r.get("recipe") or {}).get("op")) if x),
                     f"{r.get('files_count', 0)}: " + cell(r.get("files"), 120) if r.get("files_count") else "",
                     cell(r.get("donors"), 90) + (f" ({r['slots_count']} slots)" if r.get("slots_count") else ""),
                     {True: "yes", False: "no"}.get(r.get("verified"), ""), cell(r.get("note"), 140)]  # manifest flag
                    for r in rows[-BUILD_ROWS_RENDERED:]])
        if len(rows) > BUILD_ROWS_RENDERED:
            L += [f"(The {BUILD_ROWS_RENDERED} newest of {len(rows)}; every build is in `system/gbox/patch_atlas.json`.)", ""]
        if lib.get("sidecar_only"):
            L += ["Earlier builds known only by their hash sidecar (folder gone): "
                  + ", ".join(f"`{s}`" for s in lib["sidecar_only"]), ""]
    # gaps + sources
    if cur.get("gaps"):
        L += ["## Gaps before a live swap / pick whip", ""] + [f"- {cell(x)}" for x in cur["gaps"]] + [""]
    if cur.get("sources") or repo.get("missing_sources"):
        L += ["## Sources", ""] + [f"- `{s}`" for s in strs(cur.get("sources"))] + [""]
        if repo.get("missing_sources"):
            L += ["Cited but not in this checkout: " + ", ".join(f"`{s}`" for s in repo["missing_sources"]), ""]
    return "\n".join(L).rstrip() + "\n"


def replace_block(text: str, name: str, body: str) -> str:
    begin, end = f"<!-- atlas:{name}:begin -->", f"<!-- atlas:{name}:end -->"
    block = f"{begin}\n{body.rstrip()}\n{end}"
    if begin in text and end in text:
        i, j = text.index(begin), text.index(end) + len(end)
        return text[:i] + block + text[j:]
    return text.rstrip() + "\n\n" + block + "\n"


def render_platforms(atlas: dict) -> str:
    L = []
    games = atlas["games"]
    plats = [p for p in PLATFORM_ORDER if p in atlas["platforms"]] + \
            sorted(p for p in atlas["platforms"] if p not in PLATFORM_ORDER)
    for p in plats:
        d = atlas["platforms"][p]
        mine = [s for s, g in games.items() if g["curated"].get("platform") == p]
        L += [f'<a id="{p}"></a>', f"### {d.get('name') or PLATFORM_NAMES.get(p, p)}", ""]
        if d.get("emulators"):
            L += [f"**Emulators:** {cell(d['emulators'])}", ""]
        if d.get("files"):
            L += [f"**How files get in:** {cell(d['files'])}", ""]
        if d.get("ram"):
            L += [f"**RAM access:** {cell(d['ram'])}", ""]
        if d.get("mechanisms"):
            L += table(["verb", "mechanism", "status", "how", "code / evidence"],
                       [[m.get("verb"), m.get("name"), m.get("status"), m.get("how"), m.get("code")]
                        for m in d["mechanisms"]])
        for r in d.get("rules") or []:
            L += [f"> **Rule:** {cell(r)}", ""]
        if mine:
            L += ["Games: " + ", ".join(f"[{games[s]['curated'].get('title')}]({games[s]['page']})" for s in mine), ""]
    return "\n".join(L)


def render_games(atlas: dict) -> str:
    rows = []
    for slug, g in atlas["games"].items():
        st, cur = g["status"], g["curated"]
        rows.append([f"[{cell(cur.get('title'))}]({g['page']})", PLATFORM_NAMES.get(cur.get("platform"), cur.get("platform")),
                     ", ".join(f"`{x}`" for x in strs(cur.get("game_ids"))[:4]), st["replace"],
                     STATUS_WORDS.get(st["live_file_swap"], st["live_file_swap"]), st["ram_writes_proven"], st["pickwhip"],
                     f"{st['builds']} ({st['builds_verified']})"])
    return "\n".join(table(["game", "platform", "catalog ids", "replace", "live file swap", "RAM writes proven",
                            "pick whip", "builds (manifest-verified)"], rows))


def render_gaps(atlas: dict) -> str:
    L = []
    for slug, g in atlas["games"].items():
        cur = g["curated"]
        gaps = strs(cur.get("gaps"))
        if not gaps:
            continue
        L += [f"- **[{cell(cur.get('title'))}]({g['page']})** ({PLATFORM_NAMES.get(cur.get('platform'), cur.get('platform'))}):"]
        L += [f"  - {cell(x)}" for x in gaps[:3]]
        if len(gaps) > 3:
            L += [f"  - ... {len(gaps) - 3} more on the page"]
    return "\n".join(L)


def render_unpaged(atlas: dict) -> str:
    w = atlas.get("unpaged_writers") or []
    if not w:
        return "Every writer module is cited by an atlas page."
    return (f"{len(w)} writer modules (`{'`, `'.join(WRITER_GLOBS)}`) are not cited by any atlas page yet - games gBox "
            "can mod whose builds were never archived to the library, or helpers. Research them next:\n\n"
            + ", ".join(f"`{x}`" for x in w))


README_TEMPLATE = """# gBox patch atlas

<!-- atlas:platforms:begin -->
<!-- atlas:platforms:end -->

<!-- atlas:games:begin -->
<!-- atlas:games:end -->

<!-- atlas:gaps:begin -->
<!-- atlas:gaps:end -->

<!-- atlas:unpaged:begin -->
<!-- atlas:unpaged:end -->
"""


def render_all(atlas: dict, docs: Path) -> dict[Path, str]:
    """{path: text} of every page and the README (its generated blocks only; the rest of it is hand-written)."""
    out = {}
    for slug, g in atlas["games"].items():
        out[docs / g["page"]] = render_page(slug, g, atlas)
    readme = docs / "README.md"
    text = readme.read_text(encoding="utf-8") if readme.exists() else README_TEMPLATE
    for name, body in (("platforms", render_platforms(atlas)), ("games", render_games(atlas)),
                       ("gaps", render_gaps(atlas)), ("unpaged", render_unpaged(atlas))):
        text = replace_block(text, name, body)
    out[readme] = text
    return out


def write_outputs(atlas: dict, atlas_path: Path, docs: Path) -> list[Path]:
    changed = []
    files = {atlas_path: dump_json(atlas)} | render_all(atlas, docs)
    for p, text in files.items():
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old != text:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            changed.append(p)
    return changed


def stale(atlas_path: Path, docs: Path, repo: Path = REPO) -> list[Path]:
    """The files `build` would change (no new scan): a stale page or a JSON whose repo facts moved."""
    atlas = load_json(atlas_path)
    if not atlas:
        return [atlas_path]
    new = build(atlas, None, repo)
    files = {atlas_path: dump_json(new)} | render_all(new, docs)
    return [p for p, t in files.items() if not p.exists() or p.read_text(encoding="utf-8") != t]


# ------------------------------------------------------------------------------------------------------ cli ----

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="summarise the patch library + live Switch builds (run on the Spark, read-only)")
    s.add_argument("--library", type=Path)
    s.add_argument("--switch", type=Path)
    s.add_argument("--db", type=Path, help="gbox.sqlite3, opened read-only, for catalog identification")
    s.add_argument("--atlas", type=Path, help="an atlas JSON whose curated game ids also get catalog rows")
    s.add_argument("--out", type=Path)
    b = sub.add_parser("build", help="merge a scan, refresh repo facts, render the pages")
    b.add_argument("--scan", type=Path)
    b.add_argument("--atlas", type=Path, default=ATLAS)
    b.add_argument("--docs", type=Path, default=DOCS)
    c = sub.add_parser("curate", help="set curated entries from {games: {slug: GAME}, platforms: {...}}")
    c.add_argument("--from", dest="src", type=Path, required=True, action="append")
    c.add_argument("--atlas", type=Path, default=ATLAS)
    c.add_argument("--docs", type=Path, default=DOCS)
    k = sub.add_parser("check", help="exit 1 when the atlas JSON or a page is stale")
    k.add_argument("--atlas", type=Path, default=ATLAS)
    k.add_argument("--docs", type=Path, default=DOCS)
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        if not a.library and not a.switch:
            ap.error("scan needs --library and/or --switch")
        doc = scan(a.library, a.switch, a.db, a.atlas)
        text = dump_json(doc)
        if a.out:
            a.out.write_text(text, encoding="utf-8")
            print(f"{a.out}: {len(doc['folders'])} folders, {sum(len(f['builds']) for f in doc['folders'].values())} builds")
        else:
            sys.stdout.write(text)
        return 0
    if a.cmd == "build":
        atlas = build(load_json(a.atlas) or skeleton(), load_json(a.scan) if a.scan else None)
        for p in write_outputs(atlas, a.atlas, a.docs):
            print("wrote", p)
        return 0
    if a.cmd == "curate":
        atlas = load_json(a.atlas) or skeleton()
        for src in a.src:
            print("curated:", ", ".join(curate(atlas, load_json(src) or {})))
        atlas = build(atlas, None)
        for p in write_outputs(atlas, a.atlas, a.docs):
            print("wrote", p)
        return 0
    if a.cmd == "check":
        bad = stale(a.atlas, a.docs)
        for p in bad:
            print("stale:", p)
        return 1 if bad else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

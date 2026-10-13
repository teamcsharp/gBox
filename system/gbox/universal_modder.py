"""universal-modder as gBox worker tools (#825): typed, audited jobs the chat agent, Hermes and MCP clients can call.

Upstream: https://github.com/rehan-remade/universal-modder (MIT), vendored at a pinned commit in gbox/vendor/universal_modder
(what was taken, what was changed, what was left out: that package's docstring and docs/universal_modder.md).

Tools (each result says what it changed and how to undo it, under "changed" / "undo"):
  um_scan          fingerprint a PC game folder / a live session's game folder: engine + version, .NET or native,
                   anti-cheat, installed mod loaders, mod folders, save folders, ranked modding routes + the engine
                   playbook; op=list lists the Steam / Epic / Xbox installs on that worker. Read-only.
  um_kb            the universal-modder field notes (how games were actually modded: versions, routes, gotchas) and its
                   engine playbooks + safety rules. Search is offline (vendored index); notes are fetched on demand from
                   the pinned commit and cached.
  um_backup        snapshot / list / diff / restore / delete save folders (zip + sha1 manifest in gBox's cache). Restore
                   is a dry run unless confirm=true, takes a pre-restore snapshot first and refuses game install folders.
  um_publish_check lint a mod folder before sharing: game files copied verbatim, leaked keys, decompiled code, user paths.
  um_sprite        2D sprite ops (cutout, fit, pixelate, palette, sheet, slice, frames, team_mask, seamless, previews) on
                   a file, an artifact or the live session's frame; results are artifacts, optionally staged into a mod.
  um_mod           stage files into a gBox mod folder (cache/mods/<game_id>/<name> + .gbox-mod.json + README), list, remove.
  um_comfy         images from a local ComfyUI server (status, default text-to-image graph, any API-format workflow).
  um_render3d      a GLB (file, artifact or collection character) rendered by headless Blender into sprite frames from a
                   game camera (aoe2, iso8, trueiso, topdown, side, turntable) + one sheet per animation.

Nothing here writes into a game install: mods go to gBox's mod folders, snapshots and renders to gBox's cache.

Register with:  from . import universal_modder  # noqa: F401   (tools._load_tool_modules does it)
"""
import hashlib
import io
import json
import os
import re
import shutil
import time
from pathlib import Path

from pydantic import BaseModel

from .models import Permission as P
from .registry import Ctx, Unsupported, tool
from .vendor import universal_modder as UM
from .vendor.universal_modder import backup as um_backup
from .vendor.universal_modder import comfy as um_comfy
from .vendor.universal_modder import common as um_common
from .vendor.universal_modder import kb as um_kb
from .vendor.universal_modder import publish as um_publish
from .vendor.universal_modder import render3d as um_render3d
from .vendor.universal_modder import scan as um_scan
from .vendor.universal_modder import sprite as um_sprite

VENDOR = Path(UM.__file__).resolve().parent
PLAYBOOKS = VENDOR / "playbooks"
INDEX = VENDOR / "knowledge_index.json"
RAW = f"https://raw.githubusercontent.com/rehan-remade/universal-modder/{UM.COMMIT}/knowledge/"
SOURCE = {"upstream": UM.UPSTREAM, "commit": UM.COMMIT, "license": UM.LICENSE}
MARK_KIND = "universal_modder"              # .gbox-mod.json "kind" of the mods um_mod / um_sprite stage
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
NOTE_RE = re.compile(r"^(?:games|techniques)/[a-z0-9][a-z0-9._/-]*\.md$")
MAX_PIXELS = 4096 * 4096                    # any sprite input
MAX_LOOP_PIXELS = 2048 * 2048               # ops that walk pixels in Python (cutout, outline, preview)
TEXT_LIMIT = 12000                          # characters of a note / playbook returned to the LLM


def home(cfg) -> Path:
    """gBox's universal-modder state on this worker: <cache>/universal_modder (backups, notes, renders, trash)."""
    d = Path(cfg.cache) / "universal_modder"
    d.mkdir(parents=True, exist_ok=True)
    um_common.HOME = d
    return d


def _name(value: str, what: str = "name") -> str:
    if not NAME_RE.match(value or ""):
        raise ValueError(f"{what} must be 1-64 letters, digits, '.', '_' or '-' (got {value!r})")
    return value


def _api(ctx: Ctx, path: str, timeout: float = 120):
    import httpx
    if not ctx.server:
        raise Unsupported("this needs the gBox control plane (artifact / catalog / collection fetch); run it as a gBox job")
    r = httpx.get(f"{ctx.server}{path}", headers=ctx.headers, timeout=timeout)
    r.raise_for_status()
    return r


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------------------------------------ where the game lives

def install_root(target: Path) -> Path:
    """The game folder an executable belongs to: steamapps/common/<game>, the project above an Unreal Binaries/ folder,
    else the exe's own folder."""
    parts = target.parts
    low = [p.lower() for p in parts]
    for i in range(len(low) - 2, 0, -1):
        if low[i] == "common" and low[i - 1] == "steamapps" and i + 1 < len(parts):
            return Path(*parts[:i + 2])
    if "binaries" in low:
        i = low.index("binaries")
        return Path(*parts[:max(1, i - 1)])
    return target.parent


def game_folder(ctx: Ctx, session_id: str = "", game_id: str = "", path: str = "") -> tuple[Path | None, str, str]:
    """(folder, title, why-not) for a path, a live session or a catalog game. ROM / disc images have no folder to scan."""
    if path:
        return Path(path), "", ""
    if session_id:
        from .tools import SESSIONS
        if session_id not in SESSIONS:
            raise ValueError(f"no live session {session_id!r} on this worker")
        _, g = SESSIONS[session_id]
        rom, title = g.get("_rom_path") or "", g.get("title") or ""
    elif game_id:
        from .models import CatalogEntry
        from .tools import rom_path
        g = _api(ctx, f"/api/catalog/{game_id}", 60).json()
        rom, title = str(rom_path(CatalogEntry.model_validate(g), ctx.config)), g.get("title") or ""
    else:
        raise ValueError("give path, session_id or game_id (or name for an installed Steam / Epic / Xbox game)")
    if not rom:
        return None, title, "the session has no game path"
    p = Path(rom)
    if p.is_dir():
        return p, title, ""
    if p.name.upper() == "EBOOT.BIN":                  # PS3 disc folder: PS3_GAME/USRDIR/EBOOT.BIN -> disc root
        from .filemods import game_root
        return game_root(p), title, ""
    if p.suffix.lower() == ".exe":
        return install_root(p), title, ""
    return None, title, (f"{p.name} is a ROM / disc image, not an installed game folder: universal-modder fingerprints PC "
                         "installs and extracted game folders. For this game use gBox's own tools (re_executable, "
                         "analyze_binary, the game's tool, cheats, mod).")


def _playbook_text(name: str) -> str:
    name = name if name.endswith(".md") else f"{name}.md"
    p = PLAYBOOKS / ("safety.md" if name == "safety.md" else f"engines/{name}")
    if not p.resolve().is_relative_to(PLAYBOOKS) or not p.is_file():
        raise ValueError(f"no playbook {name!r}; playbooks: {', '.join(sorted(x.name for x in (PLAYBOOKS / 'engines').glob('*.md')))}")
    return p.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------------------- um_scan

class ScanIn(BaseModel):
    op: str = "scan"            # scan | list
    session_id: str = ""        # a live session: its game's folder (PC exe -> install folder; PS3 disc folder)
    game_id: str = ""           # a catalog game: its folder on this worker
    path: str = ""              # any game folder on this worker
    name: str = ""              # an installed Steam / Epic / Xbox game, fuzzy ("terraria")
    playbook: bool = True       # include the engine playbook text (first route's)


class ScanOut(BaseModel):
    result: dict


@tool("um_scan", "1.0", ScanIn, ScanOut, capabilities=["analysis", "mod"], permissions=[P.READ], timeout_s=300)
def um_scan_tool(inp: ScanIn, ctx: Ctx):
    """Fingerprint a PC game install (universal-modder scan): engine + version, .NET or native exes, anti-cheat, installed
    mod loaders, mod folders, save folders, ranked modding routes and the engine playbook to read. op=list: the Steam / Epic
    / Xbox installs on this worker. Give session_id (the live game), game_id, path or name. Read-only: changes nothing."""
    home(ctx.config)
    if inp.op == "list":
        games = sorted(um_scan.all_games(), key=lambda g: (g.get("name") or "").lower())
        return {"result": {"op": "list", "games": games, "count": len(games), "changed": [], "source": SOURCE}}
    if inp.op != "scan":
        raise ValueError(f"unknown op {inp.op!r} (scan | list)")
    title = ""
    if inp.name and not (inp.path or inp.session_id or inp.game_id):
        query = inp.name
    else:
        folder, title, why = game_folder(ctx, inp.session_id, inp.game_id, inp.path)
        if folder is None:
            return {"result": {"op": "scan", "scanned": False, "title": title, "note": why, "changed": []}}
        if not folder.is_dir():
            raise ValueError(f"not a folder on this worker: {folder}")
        query = str(folder)
    ctx.progress(10, f"scanning {query}")
    report = um_scan.scan(query, name=title or None)
    out = {"op": "scan", "scanned": True, **report, "changed": [], "undo": "nothing to undo (read-only)", "source": SOURCE}
    out["playbook"] = report["playbook"].rsplit("/", 1)[-1]       # name for um_kb op=playbook
    if inp.playbook:
        out["playbook_text"] = _playbook_text(out["playbook"])[:TEXT_LIMIT]
    out["next"] = ["um_kb op=search query=<game or engine> for prior field notes",
                   "um_backup op=create path=<a saves folder above> before changing saves",
                   "stage new files with um_mod (never into the install); lint them with um_publish_check"]
    if report.get("anti_cheat") or any("online" in w for w in report.get("warnings", [])):
        out["next"].insert(0, "STOP for online play: read um_kb op=safety; offline / single-player only, never bypass anti-cheat")
    return {"result": out}


# --------------------------------------------------------------------------------------------------------------- um_kb

def _index() -> list[dict]:
    return json.loads(INDEX.read_text(encoding="utf-8"))


def _notes_dir(cfg) -> Path:
    return home(cfg) / "kb" / UM.COMMIT[:12]


def fetch_note(cfg, rel: str) -> str:
    """One field note: the cached copy, else the pinned commit on GitHub (cached for next time)."""
    if not NOTE_RE.match(rel) or ".." in rel or rel not in {e["path"] for e in _index()}:
        raise ValueError(f"{rel!r} is not a note in the universal-modder index (um_kb op=search lists them)")
    p = _notes_dir(cfg) / rel
    if p.is_file():
        return p.read_text(encoding="utf-8")
    import httpx
    r = httpx.get(RAW + rel, timeout=60, follow_redirects=True, headers={"user-agent": "gBox universal-modder"})
    r.raise_for_status()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(r.text, encoding="utf-8", newline="\n")
    return r.text


def search_index(query: str, game: str = "", engine: str = "", route: str = "", limit: int = 8) -> list[dict]:
    """Rank the vendored index's notes (title, game, engine, route, tags, tools) with upstream's term rules."""
    groups = um_kb._groups([query]) if query.strip() else []
    terms = list({t.pattern: t for g in groups for t in g}.values())
    out = []
    for e in _index():
        if game and um_kb.slug(game) not in um_kb.slug(str(e.get("game", ""))) + " " + " ".join(um_kb.slug(x) for x in um_kb.strs(e.get("games_also"))):
            continue
        if engine and str(e.get("engine", "")).lower() != engine.lower():
            continue
        if route and str(e.get("route", "")).lower() != route.lower():
            continue
        fields = {5: str(e.get("title", "")).lower(),
                  4: " ".join([str(e.get("game", ""))] + um_kb.strs(e.get("games_also"))).lower(),
                  3: " ".join(str(x) for x in [e.get("engine", ""), e.get("route", ""), e.get("platform", ""),
                                               *um_kb.strs(e.get("tags")), *um_kb.strs(e.get("tools"))]).lower()}
        text = "\n".join(fields.values())
        if groups and not any(g[0].search(text) or (len(g) > 1 and all(t.search(text) for t in g[1:])) for g in groups):
            continue
        score = sum(w for t in terms for w, f in fields.items() if t.search(f))
        out.append({"score": score, **{k: e.get(k) for k in ("path", "title", "game", "engine", "route", "status", "platform", "date")}})
    out.sort(key=lambda r: -r["score"])
    return out[:max(1, min(limit, 50))]


class KbIn(BaseModel):
    op: str = "search"          # search | show | playbook | safety | engines
    query: str = ""             # search words; "quoted phrase" = the phrase or all of its words
    game: str = ""
    engine: str = ""            # scan engine key (unity-mono, unreal, ...): search filter / playbook pick
    route: str = ""             # data | asset-only | loader-api | managed-patch | native-hook | reimplementation | ...
    path: str = ""              # show: a note path from search (games/<game>/<note>.md)
    playbook: str = ""          # playbook: unity | unreal | native | retro-decomp | ... (or the engine key)
    limit: int = 8


class KbOut(BaseModel):
    result: dict


@tool("um_kb", "1.0", KbIn, KbOut, capabilities=["knowledge", "mod"], permissions=[P.READ, P.NETWORK], timeout_s=120)
def um_kb_tool(inp: KbIn, ctx: Ctx):
    """universal-modder's knowledge base: field notes on how ~200 games were actually modded (versions, route, how it was
    verified, gotchas) and its engine playbooks. op=search query/game/engine/route -> ranked notes (offline index, plus full
    text of notes fetched before); show path -> the note (fetched from the pinned upstream commit, then cached);
    playbook playbook|engine -> the engine playbook; safety -> the safety rules; engines -> engine keys and default routes.
    Only reads (show caches the note under gBox's cache)."""
    op = inp.op
    if op == "search":
        hits = search_index(inp.query, inp.game, inp.engine, inp.route, inp.limit)
        cached = _notes_dir(ctx.config)
        if cached.is_dir() and inp.query.strip():          # full text of the notes already fetched
            have = {h["path"] for h in hits}
            for h in um_kb.search(cached, [inp.query], inp.game or None, inp.engine or None, inp.route or None, inp.limit):
                if h["path"] not in have:
                    hits.append({**h, "full_text": True})
        return {"result": {"op": op, "hits": hits[:max(1, min(inp.limit, 50))], "notes": len(_index()), "changed": [],
                           "next": "um_kb op=show path=<hit path> for the whole note", "source": SOURCE}}
    if op == "show":
        text = fetch_note(ctx.config, inp.path)
        meta = next((e for e in _index() if e["path"] == inp.path), {})
        return {"result": {"op": op, "path": inp.path, "meta": meta, "text": text[:TEXT_LIMIT], "truncated": len(text) > TEXT_LIMIT,
                           "changed": [f"cached {inp.path} under {_notes_dir(ctx.config)}"],
                           "undo": "delete the cached copy (harmless to keep)", "source": SOURCE}}
    if op in ("playbook", "safety"):
        name = "safety" if op == "safety" else (inp.playbook or (um_scan.ENGINES[inp.engine][1] if inp.engine in um_scan.ENGINES else inp.engine))
        if not name:
            raise ValueError("give playbook=<name> or engine=<scan engine key>")
        text = _playbook_text(name)
        return {"result": {"op": op, "playbook": name, "text": text[:TEXT_LIMIT], "truncated": len(text) > TEXT_LIMIT, "changed": []}}
    if op == "engines":
        return {"result": {"op": op, "changed": [], "engines": {k: {"label": v[0], "playbook": v[1], "route": v[2]}
                                                                for k, v in um_scan.ENGINES.items()}}}
    raise ValueError(f"unknown op {op!r} (search | show | playbook | safety | engines)")


# ----------------------------------------------------------------------------------------------------------- um_backup

def _protected_roots(ctx: Ctx, extra: list[Path] = ()) -> list[Path]:
    """Folders restore must never write into: every Steam / Epic / Xbox install on this worker, plus the given ones."""
    roots = [Path(g["path"]) for g in um_scan.all_games() if g.get("path")] + list(extra)
    return [r.resolve() for r in roots if str(r)]


def _inside(p: Path, roots: list[Path]) -> Path | None:
    p = p.resolve()
    return next((r for r in roots if p == r or p.is_relative_to(r)), None)


class BackupIn(BaseModel):
    op: str = "list"            # create | list | diff | restore | delete
    path: str = ""              # create: the folder to snapshot (a saves / config folder from um_scan)
    name: str = ""              # snapshot set (default: the folder's name)
    note: str = ""
    snapshot: str = ""          # a snapshot file name in the set (default: the latest)
    to: str = ""                # restore / diff: another target folder (default: where it was taken from)
    clean: bool = False         # restore: also delete files created after the snapshot
    confirm: bool = False       # restore: false = dry run (what would change), true = do it
    session_id: str = ""        # restore refuses that session's game folder too


class BackupOut(BaseModel):
    result: dict


def _snapshot_path(name: str, snapshot: str) -> Path | None:
    if not snapshot:
        return None
    if Path(snapshot).name != snapshot or not snapshot.endswith(".zip"):
        raise ValueError("snapshot is a file name from op=list (e.g. 20261012-101500.zip)")
    p = um_common.data_dir() / "backups" / name / snapshot
    if not p.is_file():
        raise ValueError(f"no snapshot {snapshot} in set {name}")
    return p


@tool("um_backup", "1.0", BackupIn, BackupOut, capabilities=["saves", "mod"], permissions=[P.READ, P.STAGE, P.FILE_MUTATION],
      side_effects=["create/delete: snapshot zips under <cache>/universal_modder/backups",
                    "restore (confirm=true): rewrites the target saves folder after a pre-restore snapshot"], timeout_s=1800)
def um_backup_tool(inp: BackupIn, ctx: Ctx):
    """Snapshot save / config folders before touching them (universal-modder backup): zip + sha1 manifest in gBox's cache.
    op=create path [name note] | list [name] | diff name [to snapshot] (added / removed / changed since) | restore name
    [snapshot to clean] (dry run unless confirm=true; takes '<name>-pre-restore' first, so a restore can be undone;
    refuses game install folders) | delete name snapshot. Close the game before restoring its saves."""
    root = home(ctx.config) / "backups"
    op = inp.op
    if op == "create":
        if not inp.path:
            raise ValueError("create needs path (the folder to snapshot)")
        src = Path(inp.path)
        if _inside(src, [root.resolve()]):
            raise ValueError("that folder is gBox's own backup store")
        name = _name(inp.name or src.name.replace(" ", "-").lower())
        out = um_backup.create(str(src), name, inp.note)
        m = um_backup._manifest(out)
        return {"result": {"op": op, "name": name, "snapshot": out.name, "files": len(m["files"]),
                           "bytes": sum(f["size"] for f in m["files"].values()), "source_folder": str(src),
                           "changed": [f"added {out}"], "undo": f"um_backup op=delete name={name} snapshot={out.name}"}}
    if op == "list":
        names = [_name(inp.name)] if inp.name else sorted(p.name for p in root.glob("*") if p.is_dir()) if root.exists() else []
        sets = []
        for n in names:
            for zp in um_backup.snapshots(n):
                m = um_backup._manifest(zp)
                sets.append({"name": n, "snapshot": zp.name, "files": len(m["files"]), "source": m["source"],
                             "created": m.get("created"), "note": m.get("note", "")})
        return {"result": {"op": op, "snapshots": sets, "store": str(root), "changed": []}}
    name = _name(inp.name, "name (the snapshot set)")
    if op == "diff":
        if not um_backup.snapshots(name):
            raise ValueError(f"no snapshots for {name}")
        d = um_backup.diff(name, inp.to or None, str(_snapshot_path(name, inp.snapshot) or "") or None)
        d["modified"] = d.pop("changed")               # "changed" is what this op changed (nothing)
        return {"result": {"op": op, **d, "changed": []}}
    if op == "delete":
        zp = _snapshot_path(name, inp.snapshot)
        if not zp:
            raise ValueError("delete needs snapshot (a file name from op=list)")
        zp.unlink()
        return {"result": {"op": op, "deleted": zp.name, "changed": [f"deleted {zp}"],
                           "undo": "none: a deleted snapshot is gone (take a new one with op=create)"}}
    if op == "restore":
        zp = _snapshot_path(name, inp.snapshot) or (um_backup.snapshots(name) or [None])[-1]
        if not zp:
            raise ValueError(f"no snapshots for {name}")
        m = um_backup._manifest(zp)
        target = Path(um_common.to_posix(inp.to or m["source"]))
        for rel in m["files"]:                        # a snapshot only ever puts files back inside its target
            if not (target / rel).resolve().is_relative_to(target.resolve()):
                raise ValueError(f"snapshot {zp.name} has a path outside its folder: {rel!r}")
        extra = []
        if inp.session_id:
            folder, _, _ = game_folder(ctx, session_id=inp.session_id)
            extra = [folder] if folder else []
        if hit := _inside(target, _protected_roots(ctx, extra)):
            raise ValueError(f"{target} is inside the game install {hit}: universal-modder restores save folders only, "
                             "never game installs (stage mods with um_mod instead)")
        d = um_backup.diff(name, str(target), str(zp))
        plan = {"snapshot": zp.name, "target": str(target), "overwrite": d["changed"], "recreate": d["removed"],
                "delete" if inp.clean else "keep": d["added"]}
        if not inp.confirm:
            return {"result": {"op": op, "dry_run": True, **plan, "changed": [],
                               "next": "close the game, then op=restore confirm=true (a pre-restore snapshot is taken first)"}}
        um_backup.restore(name, str(target), str(zp), inp.clean, yes=True)
        pre = (um_backup.snapshots(name + "-pre-restore") or [None])[-1]
        return {"result": {"op": op, "dry_run": False, **plan, "restored": len(m["files"]),
                           "changed": [f"wrote {len(m['files'])} files into {target}"] + (
                               [f"deleted {len(d['added'])} files created after the snapshot"] if inp.clean else []) + (
                               [f"added {pre}"] if pre else []),
                           "undo": (f"um_backup op=restore name={name}-pre-restore snapshot={pre.name} confirm=true clean=true"
                                    if pre else "the target did not exist before: delete it")}}
    raise ValueError(f"unknown op {op!r} (create | list | diff | restore | delete)")


# ---------------------------------------------------------------------------------------------------- um_publish_check

class PublishIn(BaseModel):
    path: str = ""              # the mod folder to lint
    mod: str = ""               # or a gBox mod (cache/mods/<game_id>/<mod>) with game_id
    game_id: str = ""
    game_path: str = ""         # the game install to compare against (catches game files copied verbatim)
    session_id: str = ""        # or the live session's game folder


class PublishOut(BaseModel):
    result: dict


@tool("um_publish_check", "1.0", PublishIn, PublishOut, capabilities=["mod"], permissions=[P.READ], timeout_s=900)
def um_publish_check_tool(inp: PublishIn, ctx: Ctx):
    """Lint a mod folder before sharing it (universal-modder publish check). FAIL: files byte-identical to the game install,
    leaked API keys (fal, Anthropic, OpenAI, GitHub, AWS, private keys), .env files. WARN: decompiler fingerprints, big engine
    archives, absolute user paths, no README / credits. Give path, or mod + game_id; game_path / session_id / game_id adds
    the game-file check. Read-only; a lint, not legal advice."""
    if inp.mod:
        from .filemods import mod_dir
        if not inp.game_id:
            raise ValueError("mod needs game_id")
        folder = mod_dir(ctx.config, inp.game_id, inp.mod)
    elif inp.path:
        folder = Path(inp.path)
    else:
        raise ValueError("give path (a mod folder) or mod + game_id")
    game = inp.game_path
    if not game and (inp.session_id or inp.game_id):
        g, _, _ = game_folder(ctx, inp.session_id, inp.game_id if not inp.session_id else "")
        game = str(g) if g else ""
    r = um_publish.lint(str(folder), game or None)
    return {"result": {**r, "mod_folder": str(folder), "compared_with": game or None, "changed": [],
                       "note": "FAIL blocks sharing; fix WARNs or explain them in the README"}}


# ------------------------------------------------------------------------------------------------------------- um_mod

def _marker(d: Path) -> dict | None:
    try:
        return json.loads((d / ".gbox-mod.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _readme(game_id: str, name: str, install_into: str, note: str) -> str:
    return (f"# {name}\n\nStaged by gBox (universal-modder tools) for game {game_id}.\n\n"
            + (f"{note}\n\n" if note else "")
            + "## Install\n"
            + (f"Copy the files (except .gbox-mod.json and this README) into `{install_into}` inside the game folder, or "
               "point the game's mod loader at this folder.\n" if install_into else
               "Copy the files into the game's mod / loader folder (um_scan lists it).\n")
            + "\n## Undo\nDelete what you copied; gBox's copy goes with `um_mod op=remove`.\n\n"
            + f"## Credits\nTools: universal-modder ({UM.UPSTREAM}, MIT).\n")


def stage_files(ctx: Ctx, game_id: str, name: str, files: dict[str, bytes], install_into: str = "", note: str = "",
                overwrite: bool = False) -> dict:
    """Write files (relative path -> bytes) into gBox's mod folder for this game, with .gbox-mod.json and a README. Never
    touches another tool's mod; existing files are only replaced with overwrite=true."""
    from .filemods import mod_dir
    d = mod_dir(ctx.config, _name(game_id, "game_id"), _name(name, "mod name"))
    meta = _marker(d)
    if d.exists() and any(d.iterdir()) and (not meta or meta.get("kind") != MARK_KIND):
        raise ValueError(f"mod folder {name!r} belongs to another gBox mod; pick another name")
    meta = meta or {"name": name, "game_id": game_id, "kind": MARK_KIND, "launchable": False, "files": [],
                    "created": time.time(), "source": SOURCE}
    written, replaced = [], []
    for rel, data in files.items():
        rp = Path(rel.replace("\\", "/"))
        if rp.is_absolute() or ".." in rp.parts or rp.name in (".gbox-mod.json", "") or ":" in rel:
            raise ValueError(f"bad file path in the mod: {rel!r}")
        t = d / rp
        if t.exists() and not overwrite:
            raise ValueError(f"{rp.as_posix()} is already in mod {name}; pass overwrite=true to replace it")
        (replaced if t.exists() else written).append(rp.as_posix())
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(data)
    if not (d / "README.md").exists():
        (d / "README.md").write_text(_readme(game_id, name, install_into, note), encoding="utf-8", newline="\n")
        written.append("README.md")
    meta["files"] = sorted(set(meta.get("files", [])) | set(written) | set(replaced))
    if install_into:
        meta["install_into"] = install_into
    meta["built"] = time.time()
    (d / ".gbox-mod.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return {"mod": name, "game_id": game_id, "dir": str(d), "written": written, "replaced": replaced,
            "changed": [f"wrote {x} in {d}" for x in written + replaced],
            "undo": f"um_mod op=remove game_id={game_id} name={name} (moves the folder to gBox's trash)"}


class ModFile(BaseModel):
    dest: str                   # path inside the mod (e.g. Content/Items/Missile.png)
    path: str = ""              # a file on this worker
    artifact: str = ""          # or a gBox artifact sha256 (um_sprite / um_comfy / um_render3d outputs)


class ModIn(BaseModel):
    op: str = "list"            # stage | list | remove
    game_id: str = ""
    name: str = ""
    files: list[ModFile] = []
    install_into: str = ""      # where these files belong inside the game folder (documentation for the operator)
    note: str = ""
    overwrite: bool = False


class ModOut(BaseModel):
    result: dict


def _bytes_of(ctx: Ctx, path: str = "", artifact: str = "") -> bytes:
    if artifact:
        if not re.fullmatch(r"[0-9a-f]{64}", artifact):
            raise ValueError("artifact is a sha256 (64 hex characters)")
        return _api(ctx, f"/api/artifacts/{artifact}").content
    if path:
        p = Path(path)
        if not p.is_file():
            raise ValueError(f"no such file on this worker: {p}")
        return p.read_bytes()
    raise ValueError("give path or artifact")


@tool("um_mod", "1.0", ModIn, ModOut, capabilities=["mod"], permissions=[P.STAGE], timeout_s=600,
      side_effects=["stage: writes files + .gbox-mod.json + README.md into <cache>/mods/<game_id>/<name>",
                    "remove: moves that folder to <cache>/universal_modder/trash"])
def um_mod_tool(inp: ModIn, ctx: Ctx):
    """gBox mod folders for universal-modder work: op=stage game_id name files=[{dest, path|artifact}] [install_into note
    overwrite] writes them into cache/mods/<game_id>/<name> with .gbox-mod.json and a README (install steps, undo, credits);
    nothing is copied into the game install. op=list [game_id]; op=remove game_id name (moves the folder to gBox's trash:
    undo by moving it back). Lint with um_publish_check mod=<name> game_id=<id> before sharing."""
    op = inp.op
    mods = Path(ctx.config.cache) / "mods"
    if op == "list":
        out = []
        for m in sorted(mods.glob(f"{_name(inp.game_id, 'game_id') if inp.game_id else '*'}/*/.gbox-mod.json")):
            meta = _marker(m.parent) or {}
            if meta.get("kind") == MARK_KIND:
                out.append({"game_id": m.parent.parent.name, "name": m.parent.name, "files": meta.get("files", []),
                            "install_into": meta.get("install_into", ""), "dir": str(m.parent)})
        return {"result": {"op": op, "mods": out, "changed": []}}
    if op == "stage":
        if not inp.files:
            raise ValueError("stage needs files=[{dest, path | artifact}]")
        data = {f.dest: _bytes_of(ctx, f.path, f.artifact) for f in inp.files}
        return {"result": {"op": op, **stage_files(ctx, inp.game_id, inp.name, data, inp.install_into, inp.note, inp.overwrite)}}
    if op == "remove":
        from .filemods import mod_dir
        d = mod_dir(ctx.config, _name(inp.game_id, "game_id"), _name(inp.name, "mod name"))
        meta = _marker(d)
        if not meta or meta.get("kind") != MARK_KIND:
            raise ValueError(f"{inp.name!r} is not a universal-modder mod of {inp.game_id} (other mods are removed elsewhere)")
        trash = home(ctx.config) / "trash" / inp.game_id / f"{inp.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        trash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d), str(trash))
        return {"result": {"op": op, "removed": str(d), "trash": str(trash), "changed": [f"moved {d} to {trash}"],
                           "undo": f"move {trash} back to {d}"}}
    raise ValueError(f"unknown op {op!r} (stage | list | remove)")


# ---------------------------------------------------------------------------------------------------------- um_sprite

SPRITE_OPS = ("info", "cutout", "fit", "pixelate", "palette", "sheet", "slice", "frames", "team_mask", "seamless",
              "tile_preview", "preview")


class SpriteIn(BaseModel):
    op: str = "info"            # info | cutout | fit | pixelate | palette | sheet | slice | frames | team_mask | seamless | tile_preview | preview
    path: str = ""              # source image on this worker
    artifact: str = ""          # or a gBox artifact sha256 (a get_frame / sprite_capture / um_comfy output)
    session_id: str = ""        # or the live session's current frame
    crop: list[int] = []        # [x, y, w, h] of the source first (e.g. the sprite on the live frame)
    inputs: list[str] = []      # sheet: frames (artifact sha256s or worker paths), in order
    size: str = ""              # fit / pixelate: "64x26" or "32"
    anchor: str = "center"      # fit: center | bottom | top
    smooth: bool = False        # fit: Lanczos instead of nearest neighbour
    colors: int = 16            # pixelate: palette size (0 = keep colours)
    outline: str = ""           # pixelate: 1px outline colour, "#RRGGBB"
    tol: int = 28               # cutout: colour distance to the background
    grey: int | None = None     # cutout: also clear light unsaturated pixels (a soft shadow) at min channel >= grey
    holes: bool = False         # cutout: also clear enclosed background-coloured areas
    keep_top: float = 1.0       # cutout: keep only the top fraction (drop a shadow underneath)
    ref: str = ""               # palette: reference sprite / sheet (artifact sha256 or worker path)
    max_colors: int = 64        # palette
    cols: int = 0               # sheet: columns (0 = one row)
    pad: int = 0                # sheet / slice: gap between frames
    vertical: bool = False      # sheet: one column (Terraria-style strip)
    frame: str = ""             # slice: "32x32"
    n: int = 3                  # frames: how many
    kind: str = "bob"           # frames: bob | squash | wobble | flash
    hue: str = "blue"           # team_mask: blue | red | green | magenta
    blend: float = 0.25         # seamless
    scale: int = 4              # preview
    tiles: int = 3              # tile_preview
    name: str = "sprite"        # output file stem
    mod: str = ""               # also stage the outputs into this gBox mod (with game_id)
    game_id: str = ""
    dest: str = ""              # folder inside the mod for the outputs (e.g. Content/Items)


class SpriteOut(BaseModel):
    result: dict


def _image(data: bytes, crop: list[int] = (), limit: int = MAX_PIXELS):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    if im.width * im.height > MAX_PIXELS:
        raise ValueError(f"image is {im.width}x{im.height}; the limit is {MAX_PIXELS} pixels")
    im = im.convert("RGBA")
    if crop:
        if len(crop) != 4 or crop[2] <= 0 or crop[3] <= 0:
            raise ValueError("crop is [x, y, w, h]")
        x, y, w, h = crop
        im = im.crop((x, y, x + w, y + h))
    if im.width * im.height > limit:
        raise ValueError(f"{im.width}x{im.height} is too big for this op (limit {limit} pixels): crop or fit it first")
    return im


def _png(im) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _source(ctx: Ctx, inp) -> bytes:
    if inp.session_id:
        from .tools import SESSIONS
        if inp.session_id not in SESSIONS:
            raise ValueError(f"no live session {inp.session_id!r} on this worker")
        return SESSIONS[inp.session_id][0].get_frame()
    return _bytes_of(ctx, inp.path, inp.artifact)


def _ref(ctx: Ctx, ref: str) -> bytes:
    return _bytes_of(ctx, artifact=ref) if re.fullmatch(r"[0-9a-f]{64}", ref) else _bytes_of(ctx, path=ref)


@tool("um_sprite", "1.0", SpriteIn, SpriteOut, capabilities=["assets", "mod"], permissions=[P.READ, P.STAGE], timeout_s=300,
      artifacts=["<name>.png (+ frames / mask / previews)"],
      side_effects=["with mod + game_id: writes the outputs into that gBox mod folder (um_mod)"])
def um_sprite_tool(inp: SpriteIn, ctx: Ctx):
    """2D sprite tools (universal-modder sprite) on a worker file, an artifact or the live session's frame (crop=[x,y,w,h]):
    info; cutout (flat background -> transparent, border flood fill); fit size (trim + nearest-neighbour into a frame);
    pixelate size colors outline; palette ref (snap to a game's colours); sheet inputs cols|vertical; slice frame; frames n
    kind (bob/squash/wobble/flash idle); team_mask hue (player-colour mask); seamless; tile_preview; preview scale. Outputs
    are PNG artifacts (result.outputs has their sha256); mod + game_id [+ dest] also stages them into that gBox mod."""
    op = inp.op
    if op not in SPRITE_OPS:
        raise ValueError(f"unknown op {op!r} ({' | '.join(SPRITE_OPS)})")
    stem = _name(inp.name, "name")
    outs: list[tuple[str, object]] = []
    extra: dict = {}
    if op == "sheet":
        if not inp.inputs:
            raise ValueError("sheet needs inputs (frames, in order)")
        frames = [_image(_ref(ctx, x)) for x in inp.inputs]
        outs.append((f"{stem}.png", um_sprite.sheet(frames, inp.cols or None, inp.pad, inp.vertical)))
        extra["frames"] = len(frames)
    else:
        loop_ops = {"cutout", "pixelate", "preview"}
        im = _image(_source(ctx, inp), inp.crop, MAX_LOOP_PIXELS if op in loop_ops else MAX_PIXELS)
        if op == "info":
            info = um_sprite.info(im)
            return {"result": {"op": op, "info": {k: (list(v) if isinstance(v, tuple) else v) for k, v in info.items()},
                               "changed": []}}
        if op == "cutout":
            outs.append((f"{stem}.png", um_sprite.cutout(im, inp.tol, None, inp.grey, holes=inp.holes, keep_top=inp.keep_top)))
        elif op in ("fit", "pixelate"):
            if not inp.size:
                raise ValueError(f"{op} needs size, e.g. 64x26")
            w, h = um_common.parse_size(inp.size)
            if not (0 < w <= 4096 and 0 < h <= 4096):
                raise ValueError("size must be within 1..4096")
            if op == "fit":
                outs.append((f"{stem}.png", um_sprite.fit(im, w, h, inp.anchor, inp.smooth)))
            else:
                outline = None
                if inp.outline:
                    s = inp.outline.lstrip("#")
                    outline = tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
                outs.append((f"{stem}.png", um_sprite.pixelate(im, w, h, inp.colors or None, outline)))
        elif op == "palette":
            if not inp.ref:
                raise ValueError("palette needs ref (a reference sprite / sheet)")
            pal = um_sprite.palette_from(_image(_ref(ctx, inp.ref)), inp.max_colors)
            outs.append((f"{stem}.png", um_sprite.snap_palette(im, pal)))
            extra["palette"] = len(pal)
        elif op == "slice":
            if not inp.frame:
                raise ValueError("slice needs frame, e.g. 32x32")
            fw, fh = um_common.parse_size(inp.frame)
            frames = um_sprite.slice_sheet(im, fw, fh, inp.pad)
            if len(frames) > 256:
                raise ValueError(f"{len(frames)} frames; the limit is 256")
            outs += [(f"{stem}_{i:03d}.png", f) for i, f in enumerate(frames)]
        elif op == "frames":
            outs += [(f"{stem}_{i:03d}.png", f) for i, f in enumerate(um_sprite.simple_frames(im, max(1, min(inp.n, 32)), inp.kind))]
        elif op == "team_mask":
            sprite_im, mask = um_sprite.team_mask(im, inp.hue)
            outs += [(f"{stem}.png", sprite_im), (f"{stem}_mask.png", mask)]
        elif op == "seamless":
            outs.append((f"{stem}.png", um_sprite.seamless(im, inp.blend)))
        elif op == "tile_preview":
            outs.append((f"{stem}_tiles.png", um_sprite.tile_preview(im, max(2, min(inp.tiles, 6)))))
        elif op == "preview":
            scale = max(1, min(inp.scale, 2048 // max(im.width, im.height, 1) or 1))
            outs.append((f"{stem}_preview.png", um_sprite.preview(im, scale)))
    files, listed = {}, []
    for fname, out_im in outs:
        data = _png(out_im)
        ctx.artifact(fname, data, "image/png", tool="um_sprite", op=op)
        files[fname] = data
        listed.append({"name": fname, "sha256": _sha(data), "size": list(out_im.size)})
    res = {"op": op, "outputs": listed, **extra, "changed": [f"artifact {x['name']}" for x in listed],
           "undo": "nothing to undo (new artifacts only)"}
    if inp.mod:
        dest = inp.dest.strip("/\\")
        staged = stage_files(ctx, inp.game_id, inp.mod, {(f"{dest}/{k}" if dest else k): v for k, v in files.items()},
                             overwrite=True)
        res["staged"] = staged
        res["changed"] += staged["changed"]
        res["undo"] = staged["undo"]
    return {"result": res}


# ----------------------------------------------------------------------------------------------------------- um_comfy

class ComfyIn(BaseModel):
    op: str = "status"          # status | image | run
    url: str = ""               # ComfyUI address (default: $COMFYUI_URL or http://127.0.0.1:8188 on this worker)
    prompt: str = ""            # image
    negative: str = ""
    checkpoint: str = ""        # default: the first one the server lists
    size: str = ""              # "512x512" (default 1024x1024 for SDXL-looking checkpoints, else 512x512)
    steps: int = 25
    cfg: float = 7.0
    seed: int | None = None
    n: int = 1
    sprite: bool = False        # a single sprite on a plain background, then cut out (um_sprite cutout)
    workflow: dict = {}         # run: an API-format workflow (ComfyUI: Export (API))
    workflow_path: str = ""     # or that file on this worker
    set: list[str] = []         # run: NODE.INPUT=value | NODE.INPUT:=json overrides
    name: str = ""
    timeout_s: int = 900


class ComfyOut(BaseModel):
    result: dict


SPRITE_STYLE = ("a single game sprite, the whole subject in frame and centered, clean readable silhouette, "
                "no text, no watermark, no ground shadow, no background scenery")   # upstream um/fal.py


def comfy_url(url: str = "") -> str:
    base = um_comfy.base_url(url or None)
    if not re.match(r"^https?://[^/\s]+$", base):
        raise ValueError(f"ComfyUI url must be http(s)://host[:port], got {base!r}")
    return base


@tool("um_comfy", "1.0", ComfyIn, ComfyOut, capabilities=["assets"], permissions=[P.NETWORK], timeout_s=1900,
      artifacts=["<name>.png ..."], side_effects=["queues work on the ComfyUI server; outputs saved under <cache>/universal_modder/comfy"])
def um_comfy_tool(inp: ComfyIn, ctx: Ctx):
    """Images from a local ComfyUI server (universal-modder comfy; no API key, the operator's own GPU). op=status (version,
    devices, checkpoints); image prompt [checkpoint size steps cfg seed n sprite] runs ComfyUI's default text-to-image graph
    (sprite=true: plain background, then cut out); run workflow|workflow_path [set=['6.text=a blue potion', '3.seed:=42']]
    runs any API-format workflow. Outputs are PNG artifacts + files under gBox's cache, with a manifest line each."""
    base = comfy_url(inp.url)
    if inp.op == "status":
        return {"result": {"op": "status", **um_comfy.status(base), "changed": []}}
    out_dir = home(ctx.config) / "comfy"
    timeout = max(30, min(inp.timeout_s, 1800))
    if inp.op == "run":
        if inp.workflow:
            wf = inp.workflow.get("prompt", inp.workflow) if isinstance(inp.workflow.get("prompt"), dict) else inp.workflow
            if "nodes" in wf and "links" in wf:
                raise ValueError("that is a UI workflow: save it in ComfyUI with Export (API)")
        elif inp.workflow_path:
            wf = um_comfy.load_workflow(inp.workflow_path)
        else:
            raise ValueError("run needs workflow (API format) or workflow_path")
        wf = um_comfy.apply_set(wf, inp.set)
        name = _name(inp.name or "workflow", "name")
        files = um_comfy.generate(base, wf, out_dir, name, timeout, dict(set=inp.set))
        record = {"workflow_nodes": len(wf)}
    elif inp.op == "image":
        if not inp.prompt:
            raise ValueError("image needs prompt")
        ckpt = inp.checkpoint or next(iter(um_comfy.checkpoints(base)), "")
        if not ckpt:
            raise ValueError("ComfyUI lists no checkpoints: put one in ComfyUI/models/checkpoints, or use op=run")
        w, h = um_common.parse_size(inp.size) if inp.size else ((1024, 1024) if re.search(r"xl|1024", ckpt, re.I) else (512, 512))
        if not (64 <= w <= 2048 and 64 <= h <= 2048):
            raise ValueError("size must be within 64..2048")
        prompt = f"{inp.prompt}. {SPRITE_STYLE}, on a plain flat white background" if inp.sprite else inp.prompt
        seed = inp.seed if inp.seed is not None else int.from_bytes(os.urandom(4), "big")
        wf = um_comfy.txt2img(prompt, ckpt, inp.negative or um_comfy.NEGATIVE, w, h, max(1, min(inp.steps, 150)), inp.cfg, seed,
                              n=max(1, min(inp.n, 8)))
        name = _name(inp.name or ("_".join(re.sub(r"[^a-z0-9 ]", "", inp.prompt.lower()).split()[:5]) or "image"), "name")
        files = um_comfy.generate(base, wf, out_dir, name, timeout, dict(prompt=prompt, checkpoint=ckpt, seed=seed))
        record = {"checkpoint": ckpt, "seed": seed, "size": [w, h]}
        if inp.sprite:
            cut = []
            for f in files:
                p = Path(f).with_name(Path(f).stem + "_cut.png")
                um_sprite.cutout(um_sprite.load(f)).save(p)
                cut.append(str(p))
            files += cut
    else:
        raise ValueError(f"unknown op {inp.op!r} (status | image | run)")
    listed = []
    for f in files:
        data = Path(f).read_bytes()
        ctx.artifact(Path(f).name, data, "image/png" if f.lower().endswith(".png") else "application/octet-stream",
                     tool="um_comfy", op=inp.op)
        listed.append({"name": Path(f).name, "sha256": _sha(data), "file": f})
    return {"result": {"op": inp.op, "outputs": listed, **record, "changed": [f"wrote {f}" for f in files],
                       "undo": f"delete those files (and the line in {out_dir / 'comfy_manifest.jsonl'})"}}


# ------------------------------------------------------------------------------------------------------- um_render3d

class Render3dIn(BaseModel):
    path: str = ""              # a .glb on this worker
    artifact: str = ""          # or a glb artifact sha256 (scene_capture)
    character: str = ""         # or a collection character slug
    preset: str = "side"        # aoe2 | iso8 | trueiso | topdown | side | turntable
    canvas: str = "128"         # frame size: "N" or "WxH"
    length: float = 100         # the model's longest horizontal side (or height with measure=height) in px
    measure: str = "length"     # length | height
    forward_yaw: float = 0      # degrees to turn the model so its front faces +X (east)
    anims: str = "idle:1"       # name:frames:motion,...  motions: bob walk lunge die wreck spin still
    shadows: bool = False       # also a shadow-only pass (_s.png)
    samples: int = 32
    engine: str = "eevee"       # eevee (fast) | cycles
    elevation: float | None = None
    headings: int | None = None
    name: str = ""              # output folder name (default: the source's)
    mod: str = ""               # also stage the sheets into this gBox mod (with game_id, dest)
    game_id: str = ""
    dest: str = ""


class Render3dOut(BaseModel):
    result: dict


MAX_RENDER_IMAGES = 512


@tool("um_render3d", "1.0", Render3dIn, Render3dOut, capabilities=["assets", "mod"], permissions=[P.EXECUTE, P.STAGE],
      timeout_s=3600, artifacts=["<anim>_sheet.png per animation"],
      side_effects=["runs headless Blender; frames under <cache>/universal_modder/render3d/<name>"])
def um_render3d_tool(inp: Render3dIn, ctx: Ctx):
    """Render a 3D model into sprite frames from a game's camera with headless Blender (universal-modder render3d): the
    collection character (character=slug), a glb artifact or a worker path. preset aoe2 (16 headings, 30 deg) | iso8 |
    trueiso | topdown | side (facing right + left, standing on the frame bottom) | turntable; canvas, length px, anims
    'idle:4:bob,walk:8:walk,attack:6:lunge,death:8:die', shadows. Frames: <anim>_<heading>_<frame>.png under gBox's cache;
    each animation's sheet (rows = headings) is an artifact, and with mod + game_id it is staged into that mod."""
    if inp.preset not in um_render3d.PRESETS:
        raise ValueError(f"preset is one of {', '.join(um_render3d.PRESETS)}")
    if inp.engine not in ("eevee", "cycles"):
        raise ValueError("engine is eevee or cycles")
    from .blender_copy import find_blender
    blender = find_blender()
    if inp.character:
        src_bytes, stem = _api(ctx, f"/api/characters/{inp.character}/model", 300).content, inp.character
    elif inp.artifact:
        src_bytes, stem = _bytes_of(ctx, artifact=inp.artifact), inp.artifact[:12]
    elif inp.path:
        src_bytes, stem = None, Path(inp.path).stem
    else:
        raise ValueError("give character, artifact or path (a .glb)")
    name = _name(inp.name or re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:64], "name")
    work = home(ctx.config) / "render3d" / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    glb = Path(inp.path) if inp.path else work / "source.glb"
    if src_bytes is not None:
        glb.write_bytes(src_bytes)
    if not glb.is_file():
        raise ValueError(f"no such model on this worker: {glb}")
    ctx.progress(10, f"rendering {name} with Blender ({inp.preset})")
    frames_dir = work / "frames"
    um_render3d.render(str(glb), str(frames_dir), inp.preset, inp.canvas, inp.length, inp.forward_yaw, inp.anims, inp.shadows,
                       max(1, min(inp.samples, 256)), inp.engine, inp.elevation, min(inp.headings, 64) if inp.headings else None,
                       measure=inp.measure, blender=blender, timeout=3300, max_images=MAX_RENDER_IMAGES)
    from PIL import Image
    pngs = sorted(frames_dir.glob("*.png"))
    sheets, files = [], {}
    for anim in um_render3d.parse_anims(inp.anims):
        mine = [p for p in pngs if p.name.startswith(f"{anim}_") and not p.stem.endswith("_s")]
        if not mine:
            continue
        rows: dict[str, list] = {}
        for p in mine:                                 # <anim>_<heading>_<frame>.png: one row per heading
            rows.setdefault(p.stem.rsplit("_", 2)[-2], []).append(Image.open(p).convert("RGBA"))
        per_row = max(len(r) for r in rows.values())
        sheet = um_sprite.sheet([f for k in sorted(rows) for f in rows[k]], cols=per_row)
        data = _png(sheet)
        fname = f"{name}_{anim}_sheet.png"
        ctx.artifact(fname, data, "image/png", tool="um_render3d", preset=inp.preset, anim=anim)
        files[fname] = data
        sheets.append({"name": fname, "sha256": _sha(data), "headings": len(rows), "frames_per_heading": per_row,
                       "frame_size": list(rows[sorted(rows)[0]][0].size)})
    res = {"preset": inp.preset, "frames": len(pngs), "frames_dir": str(frames_dir), "sheets": sheets, "blender": blender,
           "changed": [f"wrote {len(pngs)} frames under {work}"], "undo": f"delete {work}"}
    if inp.mod and files:
        dest = inp.dest.strip("/\\")
        staged = stage_files(ctx, inp.game_id, inp.mod, {(f"{dest}/{k}" if dest else k): v for k, v in files.items()},
                             overwrite=True)
        res["staged"] = staged
        res["changed"] += staged["changed"]
        res["undo"] += "; " + staged["undo"]
    return {"result": res}

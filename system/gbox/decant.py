"""Decant: package this gBox as a zip someone without gBox can unzip on their own Windows PC and install as a standalone
gBox (control plane, worker and local LLM on one machine), plus the consumer side the installer runs on their PC.

Producer (the operator's PC, File > Decant... in the desktop app):
  python -m gbox.decant plan --server URL [--cheatdb-ssh HOST:DIR]        manifest JSON on stdout (nothing written)
  python -m gbox.decant pack --server URL --out gBox-decant.zip [...]     writes the zip (manifest inside and on stdout)
  The API token comes from $GBOX_TOKEN and is never written anywhere.

What goes in: gBox's code and clients, the installer entry ("Install gBox.cmd"), a standalone default config, the mod
recipes (mod cards), swap recipes (characters: which character from which game into which game, bone maps), the cheat DB,
game profiles/gamedata, docs. What never goes in (gBox policy, docs/model_swaps.md: assets extracted from the operator's
games are for local use only, never redistributed): ROMs / disc images / built mod images, extracted models and
textures, BIOS, save states, recordings, API tokens or secrets, chat history / inbox / audit / store DB, and the
operator's paths, host names and IPs (scrubbed from every text file, then verified). The recipient's installer rebuilds
what it can from THEIR games (consumer side below); mods whose source game they don't own show as unavailable.

Consumer (the recipient's PC, run by the setup wizard inside the installed venv):
  python -m gbox.decant match   --config gbox.toml      scan the configured ROM folders, match the recipes' games
  python -m gbox.decant rebuild --config gbox.toml      (control plane running) scan, cheat DB, characters, swaps, mod cards
Stdlib only on the producer side; the consumer side uses gBox itself.
"""
from __future__ import annotations

import argparse
import fnmatch
import io
import json
import lzma
import os
import platform
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # system/
RECIPES = "decant"                                         # system/decant/ in the package: recipes + cheat DB
THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"   # the visualizer's only dependency (MIT)

# ---------------------------------------------------------------- what is included / left out

INCLUDE_DIRS = ["gbox", "clients", "adapters", "scripts", "docs", "profiles", "schemas", "assets", "tests", "fixtures", "projects"]
INCLUDE_FILES = ["README.md", "ARCHITECTURE.md", "ROADMAP.md", "SECURITY.md", "LICENSES-THIRD-PARTY.md", "gBox Plan.md",
                 "pyproject.toml", "Dockerfile", "docker-compose.yml", ".dockerignore"]
# (glob on the path relative to system/, reason) -- first match wins; checked before the extension rules
EXCLUDE = [
    ("gbox-data/*", "runtime state: store DB, audit ledger, chat history, inbox, API token, artifacts, runtimes"),
    ("gbox.toml", "the operator's deployment config (network shares, IPs, host paths); replaced by a standalone default"),
    ("gbox.local-*.toml", "per-machine settings of the operator's PCs"),
    ("*/__pycache__/*", "build output"), ("*.pyc", "build output"), ("*.egg-info/*", "build output"),
    (".venv*", "the operator's Python environment"), ("*/node_modules/*", "dependencies (the installer downloads its own)"),
    (".pytest_cache/*", "build output"), ("projects/*/target/*", "build output"),
    ("docs/prompt_history.md", "the operator's chat history"),
    ("scripts/agent_ledger.py", "the operator's inbox tool (talks to the operator's control plane)"),
    ("scripts/inbox_backfill.py", "the operator's inbox tool"),
    ("scripts/prompt_history.py", "the operator's chat-history tool"),
    ("scripts/chat_review.py", "the operator's chat-history tool"),
    ("clients/desktop/gbox-desktop*", "the operator's desktop settings"),
]
EXT_REASONS = {
    "a ROM / disc image (never redistributed)": {".iso", ".gcm", ".gcz", ".rvz", ".wbfs", ".wia", ".cso", ".chd", ".gdi", ".cdi",
        ".cue", ".img", ".z64", ".n64", ".v64", ".nes", ".fds", ".sfc", ".smc", ".gb", ".gbc", ".gba", ".nds", ".3ds", ".xci",
        ".nsp", ".pbp", ".xex", ".pkg", ".7z", ".rar", ".dol", ".rel", ".afs", ".drs", ".bin"},
    "an extracted model / texture (local use only)": {".glb", ".gltf", ".obj", ".fbx", ".blend", ".blend1", ".dae", ".pvr",
        ".pvm", ".xvm", ".gvm", ".tex", ".dds", ".tga", ".nj", ".njm", ".zobj"},
    "a save state / memory card": {".state", ".sav", ".srm", ".gci", ".vmu", ".vms", ".mcr", ".mcd", ".ps2", ".raw", ".st0"},
    "a recording": {".mp4", ".webm", ".mkv", ".avi", ".mov", ".wav", ".ogg", ".mp3"},
    "a secret": {".pem", ".key", ".pfx", ".p12", ".cred"},
}
SECRET_NAMES = {"api_token", ".env", "id_rsa", "id_ed25519", "settings.json"}
BIOS_NAME = re.compile(r"(^|[_\-\s])(bios|scph\d+|dc_boot|dc_flash|ipl|kick\d*|syscard\d*)([_\-.\s]|$)", re.I)
IMAGE_OK = ("assets/", "clients/")                         # UI art; any other picture could be a game capture
TEXT_EXT = {".py", ".js", ".mjs", ".html", ".css", ".md", ".txt", ".json", ".toml", ".ps1", ".sh", ".cmd", ".bat", ".java",
            ".rs", ".yml", ".yaml", ".svg", ".lock", ".cfg", ".ini", ".xml", ""}
MAX_FILE = 4 << 20                                         # anything bigger in the code tree is data, not code

LEFT_OUT = [                                                # what the collection holds that never goes in, and why
    {"what": "ROMs, ISOs, disc images", "why": "copyrighted games: the recipient points the installer at their own copies"},
    {"what": "built disc/ROM mod images (gbox-cache/mods)", "why": "they contain the operator's game data; rebuilt from recipes "
     "on the recipient's PC from their own copies"},
    {"what": "extracted models and textures (the character collection's files, environments, previews)",
     "why": "extracted from the operator's games, local use only (docs/model_swaps.md); re-extracted from the recipient's copies"},
    {"what": "BIOS files", "why": "copyrighted firmware: the recipient supplies their own"},
    {"what": "save states, memory cards, recordings, screenshots, mod thumbnails", "why": "contain game data / the operator's sessions"},
    {"what": "API tokens and secrets", "why": "a new token is minted on the recipient's PC on first start"},
    {"what": "chat history, requests inbox, audit ledger, store DB, knowledge base", "why": "the operator's private records"},
    {"what": "the operator's paths, host names and IPs", "why": "scrubbed from every text file and verified absent"},
]


# ---------------------------------------------------------------- operator identity -> scrub rules

def _api(server: str, token: str, path: str, timeout: float = 30):
    req = urllib.request.Request(server.rstrip("/") + path, headers={"authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def scrub_rules(src: Path, server: str = "", workers: list[str] | None = None) -> list[tuple[re.Pattern, str]]:
    """Regex -> replacement, built from what identifies the operator: their config's paths and hosts, user names,
    this PC's name, worker names, the control plane's address, and any private IPv4 address."""
    import tomllib
    cfg = {}
    try:
        cfg = tomllib.loads((src / "gbox.toml").read_text(encoding="utf-8"))
    except Exception:
        pass
    blob = json.dumps(cfg)
    users = set(re.findall(r"/home/([A-Za-z0-9_.-]+)", blob)) | set(re.findall(r"[\\/]Users[\\/]+([A-Za-z0-9_.-]+)", blob))
    for v in (os.environ.get("USERNAME"), os.environ.get("USER")):
        if v:
            users.add(v)
    users -= {"you", "gbox", "Public", "Default", "me", "user"}
    hosts = {h for h in [platform.node(), *(workers or [])] if h and len(h) > 2 and h.lower() not in ("localhost", "windows", "linux")}
    rules: list[tuple[str, str]] = []
    # library paths / mounts / per-OS dirs of the operator's deployment -> neutral placeholders
    for lib in cfg.get("libraries", []):
        for p in [*(lib.get("paths") or {}).values(), lib.get("mount"), lib.get("mount_root")]:
            if p and not p.startswith("/mnt/gbox"):
                rules.append((re.escape(p), f"//nas/{lib.get('id', 'roms')}"))
                parts = [x for x in re.split(r"[\\/]+", p) if x]
                if p.startswith(("//", "\\\\")) and len(parts) > 1:      # the NAS share's own name, wherever docs mention it
                    rules.append((rf"(?<![\w-]){re.escape(parts[1])}(?![\w-])", f"{lib.get('id', 'roms')}-share"))
    for p in (cfg.get("retroarch_bios") or {}).values():
        rules.append((re.escape(p), "C:/gBox/bios"))
    for key in ("cache_dirs", "runtime_dirs"):                 # D:/gBox/cache -> its "D:/gBox" root, any slash style
        for p in (cfg.get(key) or {}).values():
            parts = [x for x in re.split(r"[\\/]+", p) if x]
            if parts and re.fullmatch(r"[A-Za-z]:", parts[0]) and len(parts) > 1:
                rules.append((re.escape(parts[0]) + r"[\\/]+" + re.escape(parts[1]) + r"\b", "C:/gBox"))
    for u in sorted(users, key=len, reverse=True):
        rules += [(rf"/home/{re.escape(u)}\b", "/home/gbox"), (rf"([\\/]+Users[\\/]+){re.escape(u)}\b", r"\g<1>you")]
        if re.search(r"[_\d]", u) or len(u) >= 7:            # distinctive enough to replace as a bare word too
            rules.append((rf"\b{re.escape(u)}\b", "gbox"))
    for h in sorted(hosts, key=len, reverse=True):
        rules.append((rf"\b{re.escape(h)}\b", "gbox-node"))
    if server:
        host = urllib.parse.urlparse(server).hostname
        if host and host not in ("127.0.0.1", "localhost"):
            rules.append((re.escape(host), "127.0.0.1"))
    # every private IPv4 literal (LAN addresses of the operator's NAS / Spark / PCs)
    rules.append((r"(?<![\d.])(?:10\.(?:\d{1,3})|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?(?![\d.])", "127.0.0.1"))
    return [(re.compile(p), r) for p, r in rules]


def scrub_text(s: str, rules) -> tuple[str, int]:
    n = 0
    for rx, rep in rules:
        s, k = rx.subn(rep, s)
        n += k
    return s, n


def residue(s: str, rules) -> list[str]:
    """Identity strings still present after scrubbing (must be empty)."""
    out = []
    for rx, _ in rules:
        for m in rx.finditer(s):
            if m.group(0) not in ("127.0.0.1",):
                out.append(m.group(0))
    return out


# ---------------------------------------------------------------- code tree

def _rule(rel: str) -> str | None:
    """Why a file is left out (None = included)."""
    for pat, why in EXCLUDE:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch("x/" + rel, pat):
            return why
    name = rel.rsplit("/", 1)[-1]
    ext = os.path.splitext(name)[1].lower()
    if name.lower() in SECRET_NAMES:
        return "a secret / settings file"
    for why, exts in EXT_REASONS.items():
        if ext in exts:
            return why
    if BIOS_NAME.search(os.path.splitext(name)[0]) and ext not in (".py", ".js", ".md", ".json", ".html"):
        return "a BIOS file"
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp") and not rel.startswith(IMAGE_OK):
        return "a picture outside the UI art folders (could be a game capture)"
    return None


def walk_code(src: Path):
    """(included [(rel, path)], excluded [(rel, reason)])."""
    inc, exc = [], []
    files = [src / f for f in INCLUDE_FILES if (src / f).is_file()]
    for d in INCLUDE_DIRS:
        for dirpath, dirnames, names in os.walk(src / d):
            dirnames[:] = [x for x in dirnames if x not in ("__pycache__", "node_modules", ".pytest_cache", "target", ".git")]
            files += [Path(dirpath, n) for n in names]
    for f in files:
        rel = f.relative_to(src).as_posix()
        why = _rule(rel)
        if not why and f.stat().st_size > MAX_FILE:
            why = f"larger than {MAX_FILE >> 20} MB (data, not code)"
        (exc if why else inc).append((rel, why) if why else (rel, f))
    for top in sorted(os.listdir(src)):                     # top-level things not packaged at all, for the manifest
        if top not in INCLUDE_DIRS and top not in INCLUDE_FILES and not top.startswith("."):
            why = _rule(top) or _rule(top + "/x") or ("the operator's runtime data" if top == "gbox-data" else "not part of the package")
            exc.append((top + ("/" if (src / top).is_dir() else ""), why))
    return inc, exc


# ---------------------------------------------------------------- recipes from the control plane

CARD_KEEP = ("id", "title", "game_id", "game_title", "desc", "verified", "calls")
CHAR_KEEP = ("slug", "name", "aliases", "kind", "source", "extraction_tool", "notes", "native_player", "targets", "licence")


def _gids_in(obj) -> set[str]:
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "game_id" and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{16}", v):
                out.add(v)
            out |= _gids_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _gids_in(v)
    return out


def fetch_recipes(server: str, token: str, log=lambda m: None) -> dict:
    log("reading mod cards (/api/mods)")
    cards = _api(server, token, "/api/mods")
    log(f"{len(cards)} mod cards; reading the character collection (/api/characters)")
    chars = _api(server, token, "/api/characters")
    try:
        envs = _api(server, token, "/api/environments")
    except Exception:
        envs = []
    try:
        workers = [w.get("name") for w in _api(server, token, "/api/workers")]
    except Exception:
        workers = []
    out_cards, out_chars, built = [], [], {}
    for c in cards:
        out_cards.append({k: c[k] for k in CARD_KEEP if k in c})
        for call in c.get("calls", []):
            i = call.get("input") or {}
            if call.get("tool") == "@launch" and i.get("mod"):
                built.setdefault((i.get("game_id") or c["game_id"], i["mod"]), {"cards": []})["cards"].append(c["title"])
    for m in chars:
        r = {k: m[k] for k in CHAR_KEEP if k in m}
        rig = m.get("rig") or {}
        r["rig"] = {k: rig[k] for k in ("skinned", "joints", "roles", "roles_from") if k in rig}
        r["source"] = {k: v for k, v in (m.get("source") or {}).items() if k in ("game_title", "game_id", "platform", "files")}
        out_chars.append(r)
        for gid, ts in (m.get("targets") or {}).items():
            for t in ts:
                if t.get("mod"):
                    built.setdefault((gid, t["mod"]), {"cards": []}).update(character=m["slug"], slot=t.get("slot", "player"))
    builtmods = []
    for (gid, name), info in sorted(built.items()):
        files = []
        try:
            files = [f if isinstance(f, str) else f.get("path") or f.get("name") for f in
                     _api(server, token, f"/api/modfiles/{gid}/{urllib.parse.quote(name)}").get("files", [])]
        except Exception:
            pass
        builtmods.append({"game_id": gid, "name": name, "character": info.get("character"), "slot": info.get("slot"),
                          "cards": info["cards"], "replaces": [f for f in files if f and not f.startswith(".gbox")][:40],
                          "rebuild": ("characters op=use (swap writer)" if info.get("character") else "replay the mod card's tool calls")})
    gids = _gids_in(out_cards) | _gids_in(out_chars) | {g for m in out_chars for g in (m.get("targets") or {})}
    log(f"{len(out_chars)} characters, {len(builtmods)} built mods; fingerprinting {len(gids)} games")
    games = {}
    for gid in sorted(gids):
        try:
            g = _api(server, token, f"/api/catalog/{gid}")
        except Exception:
            continue
        if not g:
            continue
        rel = g.get("rel_path") or ""
        games[gid] = {"title": g.get("title"), "platform": g.get("platform"), "region": g.get("region"), "serial": g.get("serial"),
                      "format": g.get("format"), "size": g.get("size"), "file": rel.rsplit("/", 1)[-1] or None,
                      "hashes": g.get("hashes") or {}}
    for m in out_chars:                                     # titles of the games the recipes need, even when not in the catalog
        s = m["source"]
        if s.get("game_id") and s["game_id"] not in games:
            games[s["game_id"]] = {"title": s.get("game_title"), "platform": s.get("platform")}
    for c in out_cards:
        if c["game_id"] not in games:
            games[c["game_id"]] = {"title": c.get("game_title")}
    return {"cards": out_cards, "characters": out_chars, "builtmods": builtmods, "games": games,
            "environments": len(envs), "workers": [w for w in workers if w]}


# ---------------------------------------------------------------- cheat DB

def cheatdb_tarball(src_dir: Path | None, ssh: str = "", log=lambda m: None) -> bytes | None:
    """libretro-database cheats (CC BY-SA 4.0) + Gecko codes as one .tar.xz (27k small files zip badly).
    ssh = "host:dir" streams it from the control-plane node (fast); else walks src_dir (slow over SMB)."""
    cache = Path(os.environ.get("TEMP", "/tmp")) / "gbox-decant-cheatdb.tar.xz"
    if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        log(f"cheat DB: reusing {cache.name} built {time.ctime(cache.stat().st_mtime)}")
        return cache.read_bytes()
    parts = ["libretro-database/cht", "libretro-database/LICENSE", "libretro-database/README.md", "gecko"]
    data = None
    if ssh:
        host, _, d = ssh.partition(":")
        log(f"cheat DB: streaming from {host} over SSH")
        try:
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", host,
                                f"cd {d} && tar cf - --ignore-failed-read {' '.join(parts)} 2>/dev/null | xz -6 -T0"],
                               capture_output=True, timeout=900)
            if r.returncode == 0 and len(r.stdout) > 1000:
                data = r.stdout
        except Exception as e:
            log(f"cheat DB over SSH failed: {e}")
    if data is None and src_dir and src_dir.is_dir():
        log(f"cheat DB: packing {src_dir} (slow over a network share)")
        bio = io.BytesIO()
        with tarfile.open(fileobj=bio, mode="w:xz", preset=6) as tf:
            for p in parts:
                if (src_dir / p).exists():
                    tf.add(src_dir / p, arcname=p)
        data = bio.getvalue()
    if data:
        try:
            cache.write_bytes(data)
        except OSError:
            pass
    return data


# ---------------------------------------------------------------- package files

STANDALONE_TOML = """\
# gBox standalone (decanted): control plane, worker and local LLM on this PC.
# The setup wizard writes this PC's choices (ROM folders, port, folders, models) to gbox.local-<host>.toml next to this file.
data_dir = "gbox-data"            # store, artifacts, api_token (created on first start), runtimes
api_host = "127.0.0.1"            # this PC only; token auth is always on
api_port = 8765
cache_limit_gb = 50
stage_min_mb = 32
granted_permissions = ["read", "execute", "stage", "network", "install", "memory_write"]
examine_ready = false

[agent]
llm_url = "http://127.0.0.1:11434/v1"
model = "gpt-oss:20b"             # tools / chat (sized to the GPU by the wizard)
vision_model = "qwen2.5vl:7b"     # looks at the game picture
searx_url = "http://127.0.0.1:8081"
tts_engine = "xtts"
voice_library = ""
"""

INSTALL_CMD = r"""@echo off
rem gBox setup: gets Python if this PC has none (uv, from astral.sh's GitHub releases), then opens the setup wizard.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0system\scripts\standalone.ps1" install %*
if errorlevel 1 pause
"""

START_CMD = r"""@echo off
rem Start gBox on this PC: the desktop app (or the browser UI) on the local control plane.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0system\scripts\standalone.ps1" start %*
if errorlevel 1 pause
"""

README_FIRST = """gBox (decanted standalone package)
===================================

1. Unzip this folder anywhere (a fast local disk; about 20 GB free is comfortable once emulators and models are in).
2. Double-click "Install gBox.cmd". It gets Python if needed and opens the setup wizard in your browser.
3. Follow the flow chart: check the PC, pick the install folder, install, point at YOUR ROM folders, emulators,
   toolkits, the local LLM, rebuild mods from recipes, start gBox. Every node can be clicked to revisit or redo it.
4. Afterwards, start gBox with "Start gBox.cmd".

Nothing in this package comes from anyone's games: no ROMs, no BIOS, no extracted models or textures, no saves.
The mods and character swaps are recipes; the installer rebuilds them from your own copies of the games.
Mods for games you don't have are listed as unavailable. See MANIFEST.md for exactly what is (and is not) inside.
Everything gBox downloads comes from the projects' official sources (RetroArch / libretro buildbot, Ghidra, Adoptium,
RenderDoc, Ollama, Electron, uv), each after you agree to it. No network? Each step accepts files you already have.
"""


def manifest_md(m: dict) -> str:
    L = [f"# gBox decant manifest", "", f"Built {m['built']} from gBox {m['version']} ({m['files_included']} files, "
         f"{m['bytes_included'] / 1e6:.1f} MB uncompressed).", "",
         "Policy: assets extracted from games are for local use only, never redistributed (docs/model_swaps.md). "
         "This package holds code and recipes; the installer rebuilds what it can from the recipient's own games.", "",
         "## Included", ""]
    for i in m["included"]:
        L.append(f"- **{i['what']}**: {i['detail']}")
    L += ["", "## Left out (and why)", ""]
    for i in m["left_out"]:
        L.append(f"- **{i['what']}**: {i['why']}")
    if m.get("excluded_files"):
        L += ["", "### Files in the source tree that were not packaged", ""]
        for e in m["excluded_files"][:300]:
            L.append(f"- `{e['path']}`: {e['why']}")
    L += ["", "## Scrubbed", "", f"{m['scrub']['replacements']} replacements of the operator's paths, host names and IPs in "
          f"{len(m['scrub']['files'])} files; verified: {m['scrub']['verified']}.", ""]
    L += ["## Recipes", "", "| Mod card | Game |", "|---|---|"]
    for c in m["recipes"]["cards"]:
        L.append(f"| {c['title']} | {c.get('game_title') or c['game_id']} |")
    L += ["", "| Character | Source game | Swaps into |", "|---|---|---|"]
    for c in m["recipes"]["characters"]:
        L.append(f"| {c['name']} | {c['source']} | {', '.join(c['targets']) or '-'} |")
    return "\n".join(L) + "\n"


def build(src: Path, server: str, token: str, out: Path | None, cheat_ssh: str = "", cheat_dir: Path | None = None,
          log=lambda m: None) -> dict:
    """plan (out=None) or write the zip. Returns the manifest."""
    t0 = time.time()
    rec = fetch_recipes(server, token, log) if server and token else {"cards": [], "characters": [], "builtmods": [],
                                                                       "games": {}, "environments": 0, "workers": []}
    rules = scrub_rules(src, server, rec["workers"])
    log("walking the code tree")
    inc, exc = walk_code(src)
    included_bytes, scrubbed, leaks, payload = 0, [], [], []
    for rel, path in inc:
        data = path.read_bytes()
        ext = os.path.splitext(rel)[1].lower()
        if ext in TEXT_EXT:
            try:
                txt = data.decode("utf-8")
            except UnicodeDecodeError:
                txt = None
            if txt is not None:
                txt2, n = scrub_text(txt, rules)
                if n:
                    scrubbed.append({"file": rel, "replacements": n})
                if token and token in txt2:
                    raise SystemExit(f"refusing: the API token appears in {rel}")
                if r := residue(txt2, rules):
                    leaks.append({"file": rel, "found": sorted(set(r))[:5]})
                data = txt2.encode("utf-8")
        elif token and token.encode() in data:
            raise SystemExit(f"refusing: the API token appears in {rel}")
        payload.append((rel, data))
        included_bytes += len(data)
    # recipes (scrubbed the same way: game titles stay, paths and hosts go)
    def jd(o):
        s, _ = scrub_text(json.dumps(o, indent=1, ensure_ascii=False), rules)
        if token and token in s:
            raise SystemExit("refusing: the API token appears in the recipes")
        return s.encode("utf-8")
    recipes = {f"{RECIPES}/mod_cards.json": jd(rec["cards"]), f"{RECIPES}/characters.json": jd(rec["characters"]),
               f"{RECIPES}/built_mods.json": jd(rec["builtmods"]), f"{RECIPES}/games.json": jd(rec["games"])}
    bonemaps = sorted(r for r, _ in inc if re.match(r"scripts/retarget_.*\.json$", r))
    gamedata = sorted(r for r, _ in inc if r.startswith("profiles/"))
    docs = sorted(r for r, _ in inc if r.startswith("docs/") or r.endswith(".md") and "/" not in r)
    cheat = None
    if out is not None:
        cheat = cheatdb_tarball(cheat_dir, cheat_ssh, log)
    three = None
    if out is not None:
        try:
            log("visualizer: fetching three.js r160 (MIT) so the installer's background works offline")
            with urllib.request.urlopen(THREE_URL, timeout=60) as r:
                three = r.read()
        except Exception as e:
            log(f"three.js not fetched ({e}): the installer falls back to the CDN / a plain background")
    owned_titles = {g: (v.get("title") or g) for g, v in rec["games"].items()}
    m = {
        "format": "gbox-decant/1", "built": time.strftime("%Y-%m-%d %H:%M"), "version": _version(src),
        "files_included": len(payload), "bytes_included": included_bytes,
        "included": [
            {"what": "gBox code and clients", "detail": f"{sum(1 for r, _ in payload if r.startswith(('gbox/', 'clients/', 'adapters/')))} "
             "files: control plane, worker, tools, extractors, mod writers, desktop app, web UI, setup wizard, Blender bridge, Ghidra scripts"},
            {"what": "one-click installer", "detail": "Install gBox.cmd (Python via uv if needed, then the setup wizard), Start gBox.cmd"},
            {"what": "standalone default config", "detail": "system/gbox.toml: control plane on 127.0.0.1, local worker, local Ollama"},
            {"what": "mod recipes", "detail": f"{len(rec['cards'])} mod cards (tool-call recipes) for {len({c['game_id'] for c in rec['cards']})} games"},
            {"what": "swap recipes", "detail": f"{len(rec['characters'])} characters (source game, extractor, rig roles, target games), "
             f"{len(rec['builtmods'])} built-mod recipes, {len(bonemaps)} bone maps (scripts/retarget_*.json)"},
            {"what": "game fingerprints", "detail": f"{len(rec['games'])} games the recipes need (title, platform, size, file name): "
             "matched against the recipient's own ROM folders"},
            {"what": "cheat DB", "detail": ("libretro-database cheats (CC BY-SA 4.0) + Gecko codes, system/decant/cheatdb.tar.xz "
                                             f"({len(cheat) / 1e6:.1f} MB)") if cheat else
             ("libretro-database cheats (CC BY-SA 4.0) + Gecko codes (packed when the zip is written)" if out is None else
              "not packed (no SSH / share access to the cheat DB): the installer downloads libretro's cheats when online")},
            {"what": "profiles / gamedata", "detail": f"{len(gamedata)} files (game profiles, parts lists)"},
            {"what": "docs", "detail": f"{len(docs)} files"},
            {"what": "visualizer library", "detail": "three.js r160 (MIT) for the installer background" if three or out is None else
             "not bundled (offline installs show a plain background)"},
        ],
        "left_out": LEFT_OUT + [{"what": f"captured environments ({rec['environments']})", "why": "whole scenes captured from the "
                                 "operator's sessions: no recipe can rebuild them without a live capture"}] if rec["environments"] else LEFT_OUT,
        "excluded_files": [{"path": r, "why": w} for r, w in sorted(exc)],
        "scrub": {"replacements": sum(s["replacements"] for s in scrubbed), "files": scrubbed, "verified": not leaks, "leaks": leaks},
        "recipes": {
            "cards": [{"title": c["title"], "game_id": c["game_id"], "game_title": c.get("game_title")} for c in rec["cards"]],
            "characters": [{"name": c["name"], "slug": c["slug"], "source": (c.get("source") or {}).get("game_title"),
                            "targets": sorted({owned_titles.get(g, g) for g in (c.get("targets") or {})})} for c in rec["characters"]],
            "built_mods": [{"game": owned_titles.get(b["game_id"], b["game_id"]), "name": b["name"], "rebuild": b["rebuild"]}
                           for b in rec["builtmods"]],
            "bone_maps": bonemaps,
        },
        "seconds": round(time.time() - t0, 1),
    }
    if leaks:
        m["error"] = "operator identity strings remain after scrubbing: " + ", ".join(f"{x['file']} {x['found']}" for x in leaks[:10])
    if out is None:
        return m
    if leaks:
        raise SystemExit(m["error"])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    top = "gBox/"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def put(name, data):
            z.writestr(zipfile.ZipInfo(top + name, time.localtime()[:6]), data, zipfile.ZIP_DEFLATED)
        for rel, data in payload:
            put("system/" + rel, data)
        put("system/gbox.toml", STANDALONE_TOML)
        for rel, data in recipes.items():
            put("system/" + rel, data)
        if cheat:
            put(f"system/{RECIPES}/cheatdb.tar.xz", cheat)
        if three:
            put("system/clients/web/viz/vendor/three.module.js", three)
        put("Install gBox.cmd", INSTALL_CMD.replace("\n", "\r\n"))
        put("Start gBox.cmd", START_CMD.replace("\n", "\r\n"))
        put("README-FIRST.txt", README_FIRST.replace("\n", "\r\n"))
        put("MANIFEST.json", json.dumps(m, indent=1))
        put("MANIFEST.md", manifest_md(m))
    tmp.replace(out)
    m["zip"] = str(out)
    m["zip_bytes"] = out.stat().st_size
    log(f"wrote {out} ({m['zip_bytes'] / 1e6:.1f} MB)")
    return m


def _version(src: Path) -> str:
    try:
        return re.search(r'^version\s*=\s*"([^"]+)"', (src / "pyproject.toml").read_text(), re.M).group(1)
    except Exception:
        return "?"


# ================================================================ consumer side (the recipient's PC)

def _norm(t: str | None) -> str:
    t = (t or "").lower()
    t = re.sub(r"\.(iso|gcm|gcz|rvz|wbfs|cso|chd|gdi|cdi|cue|bin|z64|n64|v64|nes|sfc|smc|gba|gbc|gb|nds|pbp|zip|7z)$", "", t)
    return " ".join(re.sub(r"[^a-z0-9()]+", " ", t).split())


def _loose(t: str | None) -> str:
    t = _norm(t)
    disc = " ".join(re.findall(r"\(disc \d+\)", t))
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"^the |, the\b| the\b", " ", t)
    return " ".join((t + " " + disc).split())


def _plat_ok(a: str | None, b: str | None) -> bool:
    if not a or not b or a == b or "unknown" in (a, b):
        return True
    fam = lambda p: {"gamecube_wii": "gamecube", "wii": "gamecube", "gc": "gamecube", "psx": "psx", "ps1": "psx"}.get(p, p)
    return fam(a) == fam(b)


def match_games(recipe_games: dict, entries: list[dict]) -> dict:
    """recipe game_id -> {local entry, score, how}. Content hash > same size+title > same title > loose title."""
    out = {}
    by_norm, by_loose = {}, {}
    for e in entries:
        for t in {e.get("title"), (e.get("rel_path") or "").rsplit("/", 1)[-1]} - {None, ""}:
            by_norm.setdefault(_norm(t), []).append(e)
            by_loose.setdefault(_loose(t), []).append(e)
    for gid, g in recipe_games.items():
        best = None
        sha = (g.get("hashes") or {}).get("sha1")
        for e in entries:
            if sha and (e.get("hashes") or {}).get("sha1") == sha:
                best = (100, e, "content hash")
                break
        if not best:
            for e in by_norm.get(_norm(g.get("title")), []) + by_norm.get(_norm(g.get("file")), []):
                if _plat_ok(g.get("platform"), e.get("platform")):
                    s = (90, e, "same title and size") if g.get("size") and e.get("size") == g.get("size") else (80, e, "same title")
                    best = max(best or s, s, key=lambda x: x[0])
        if not best:
            for e in by_loose.get(_loose(g.get("title")), []):
                if _plat_ok(g.get("platform"), e.get("platform")):
                    best = (60, e, "title (region / revision may differ)")
                    break
        if best:
            out[gid] = {"local_id": best[1]["game_id"], "title": best[1].get("title"), "path": (best[1].get("source_paths") or [""])[0],
                        "score": best[0], "how": best[2]}
    return out


def _load_cfg(config: str):
    sys.path.insert(0, str(ROOT))
    from gbox import config as C
    return C.load(config)


def _recipes() -> dict:
    d = ROOT / RECIPES
    rd = lambda n, dflt: json.loads((d / n).read_text(encoding="utf-8")) if (d / n).exists() else dflt
    return {"cards": rd("mod_cards.json", []), "characters": rd("characters.json", []), "builtmods": rd("built_mods.json", []),
            "games": rd("games.json", {})}


def cmd_match(config: str) -> dict:
    """Scan this PC's ROM folders (the libraries in the config) and match the recipes' games. Writes
    <data_dir>/game_ids.json (local id -> recipe id: scan_library gives matching copies the recipes' ids) and
    <data_dir>/decant-match.json (the report the wizard shows)."""
    cfg = _load_cfg(config)
    from gbox import catalog
    entries, problems, per = [], [], {}
    for lib in cfg.libraries:
        root = lib.root()
        if not root or not Path(root).exists():
            problems.append(f"{lib.id}: folder not reachable: {root}")
            continue
        t = time.time()
        if lib.kind == "attract":
            e, p, _ = catalog.scan_attract(root, lib.id, {})
        else:
            e, p = catalog.scan([root], {}, {}, lib_id=lib.id, do_hash=False)
        entries += [x.model_dump() for x in e]
        problems += p
        per[lib.id] = {"games": len(e), "seconds": round(time.time() - t, 1), "path": str(root)}
        print(json.dumps({"progress": f"{lib.id}: {len(e)} games in {root}"}), flush=True)
    R = _recipes()
    hits = match_games(R["games"], entries)
    ids, aliases = {}, {}
    for gid, h in sorted(hits.items(), key=lambda kv: -kv[1]["score"]):   # one copy can answer several recipe ids (the
        if h["local_id"] in ids:                                            # operator had it in two libraries): the
            aliases[gid] = ids[h["local_id"]]                               # first is its id here, the rest alias it
        else:
            ids[h["local_id"]] = gid
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "game_ids.json").write_text(json.dumps(ids, indent=1))
    platforms = {}
    for e in entries:
        platforms[e.get("platform") or "unknown"] = platforms.get(e.get("platform") or "unknown", 0) + 1
    owned = set(hits)
    cards = [{"title": c["title"], "game": c.get("game_title"), "available": c["game_id"] in owned} for c in R["cards"]]
    chars = [{"name": c["name"], "source": c["source"].get("game_title"), "available": c["source"].get("game_id") in owned,
              "targets": [{"game": R["games"].get(g, {}).get("title") or g, "available": g in owned and c["source"].get("game_id") in owned}
                          for g in (c.get("targets") or {})]} for c in R["characters"]]
    rep = {"scanned": len(entries), "libraries": per, "platforms": platforms, "problems": problems[:50],
           "games_needed": len(R["games"]), "games_owned": len(owned),
           "owned": [{"game_id": g, "recipe_title": R["games"][g].get("title"), **h} for g, h in hits.items()],
           "missing": [g.get("title") or gid for gid, g in R["games"].items() if gid not in owned],
           "cards": cards, "characters": chars, "aliases": aliases, "at": time.time()}
    (cfg.data_dir / "decant-match.json").write_text(json.dumps(rep, indent=1))
    return rep


class _Api:
    def __init__(self, server, token):
        self.server, self.token = server.rstrip("/"), token

    def __call__(self, method, path, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.server + path, data=data, method=method,
                                     headers={"authorization": "Bearer " + self.token, "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")

    def job(self, tool, inp, limit=3600, progress=None):
        j = self("POST", "/api/jobs", {"tool": tool, "input": inp})
        t0 = time.time()
        while j.get("state") in ("queued", "running") and time.time() - t0 < limit:
            time.sleep(1.5)
            j = self("GET", f"/api/jobs/{j['id']}")
            if progress and j.get("progress"):
                progress(j["progress"])
        return j


def _say(**kw):
    print(json.dumps(kw, default=str), flush=True)


def cmd_rebuild(config: str, server: str = "", only: str = "") -> dict:
    """With this PC's control plane running: catalog scan (matching copies get the recipes' ids), cheat DB, the character
    collection (each game's own extractor), swap mods (each game's swap writer), then the mod cards. Never launches a game."""
    cfg = _load_cfg(config)
    server = server or f"http://127.0.0.1:{cfg.api_port}"
    api = _Api(server, cfg.token())
    R = _recipes()
    rep = {"steps": [], "cards": [], "characters": [], "swaps": [], "at": time.time()}
    step = lambda name, status, detail="": (rep["steps"].append({"step": name, "status": status, "detail": detail}),
                                            _say(step=name, status=status, detail=detail))
    # cheat DB
    tb = ROOT / RECIPES / "cheatdb.tar.xz"
    dest = cfg.data_dir / "cheatdb"
    if (not only or only == "cheats") and tb.exists() and not (dest / "libretro-database" / "cht").is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tb, "r:xz") as tf:
            tf.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else tf.extractall(dest)
        step("cheat DB", "ok", f"unpacked into {dest}")
    elif (dest / "libretro-database" / "cht").is_dir():
        step("cheat DB", "ok", "already in place")
    else:
        step("cheat DB", "skipped", "not in this package")
    if only == "cheats":
        return rep
    # catalog
    if not only or only == "scan":
        step("catalog scan", "running", "scanning your ROM folders")
        j = api.job("scan_library", {"include_steam": False}, 7200, lambda p: _say(progress=p))
        step("catalog scan", "ok" if j.get("state") == "succeeded" else "failed",
             f"{(j.get('output') or {}).get('count', '?')} games" if j.get("state") == "succeeded" else j.get("error") or j.get("state"))
    match = json.loads((cfg.data_dir / "decant-match.json").read_text()) if (cfg.data_dir / "decant-match.json").exists() else {}
    owned = {o["game_id"] for o in match.get("owned", [])}  # recipe ids of the games this PC has (the scan gave them these ids)
    alias = match.get("aliases") or {}                       # recipe id -> the id this PC's copy got (same game, two ids)
    canon = lambda o: ({k: canon(v) for k, v in o.items()} | ({"game_id": alias.get(o["game_id"], o["game_id"])} if isinstance(o.get("game_id"), str) else {})
                       if isinstance(o, dict) else [canon(v) for v in o] if isinstance(o, list) else o)
    (Path(cfg.cache) / "characters").mkdir(parents=True, exist_ok=True)   # the collection lives on this (control-plane) PC
    sys.path.insert(0, str(ROOT))
    try:
        from gbox import characters as K
        dedicated = K.DEDICATED
    except Exception as e:                                   # noqa: BLE001
        dedicated, _ = [], step("extractors", "failed", f"{type(e).__name__}: {e}")
    games = R["games"]
    # characters: each game's own extractor (no live capture: those need a session and are listed as manual)
    if not only or only == "characters":
        for c in R["characters"]:
            src = c["source"].get("game_id")
            g = games.get(src, {})
            row = {"name": c["name"], "source": g.get("title") or c["source"].get("game_title")}
            if src not in owned:
                rep["characters"].append(row | {"status": "unavailable", "why": "you don't have the source game"})
                continue
            ext = next((n for n, test, *_ in dedicated if test((g.get("title") or "").lower(), g.get("platform") or c["source"].get("platform") or "")), None)
            if not ext:
                rep["characters"].append(row | {"status": "manual", "why": f"extracted from a live frame capture ({c.get('extraction_tool')}): "
                                                "open the game in gBox and ask for it"})
                continue
            _say(progress={"msg": f"extracting {c['name']} from {row['source']} ({ext})"})
            j = api.job("characters", {"op": "extract", "character": c["name"], "game_id": alias.get(src, src)}, 3600)
            res = ((j.get("output") or {}).get("result") or {})
            rep["characters"].append(row | {"status": res.get("status") or j.get("state"), "why": j.get("error") or res.get("message", "")})
            _say(character=rep["characters"][-1])
        # swaps: build each target the recipe had, for target games this PC has (never launched)
        for c in R["characters"]:
            for tgid, ts in (c.get("targets") or {}).items():
                for t in ts:
                    row = {"character": c["name"], "game": games.get(tgid, {}).get("title") or tgid, "mod": t.get("mod"), "slot": t.get("slot")}
                    if tgid not in owned or c["source"].get("game_id") not in owned:
                        rep["swaps"].append(row | {"status": "unavailable", "why": "you don't have " + ("the target game" if tgid not in owned else "the character's game")})
                        continue
                    if t.get("slot", "player") != "player":
                        rep["swaps"].append(row | {"status": "manual", "why": "enemy swaps are built by hand (re4gc_enemies)"})
                        continue
                    _say(progress={"msg": f"building {t.get('mod')}: {c['name']} into {row['game']}"})
                    j = api.job("characters", {"op": "use", "character": c["slug"], "game_id": alias.get(tgid, tgid), "launch": False, "rebuild": True}, 3600)
                    res = ((j.get("output") or {}).get("result") or {})
                    rep["swaps"].append(row | {"status": res.get("status") or j.get("state"), "why": j.get("error") or res.get("message", "")})
                    _say(swap=rep["swaps"][-1])
    # mod cards for the games this PC has
    if not only or only == "cards":
        for c in R["cards"]:
            need = {c["game_id"]} | _gids_in(c.get("calls", []))
            row = {"title": c["title"], "game": c.get("game_title")}
            if not need <= owned:
                rep["cards"].append(row | {"status": "unavailable", "why": "you don't have " + ", ".join(
                    games.get(g, {}).get("title") or g for g in sorted(need - owned))})
                continue
            try:
                api("POST", "/api/mods", canon({k: c[k] for k in ("title", "calls", "game_id", "game_title", "desc", "verified") if k in c}))
                rep["cards"].append(row | {"status": "added"})
            except Exception as e:                           # noqa: BLE001
                rep["cards"].append(row | {"status": "failed", "why": str(e)})
        step("mod cards", "ok", f"{sum(1 for x in rep['cards'] if x['status'] == 'added')} added, "
                                f"{sum(1 for x in rep['cards'] if x['status'] == 'unavailable')} unavailable")
    (cfg.data_dir / "decant-rebuild.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


# ---------------------------------------------------------------- emulators / toolkits for this PC (wizard steps 5 + 6)

def _head(url: str) -> int | None:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"user-agent": "gbox-setup"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return int(r.headers.get("content-length") or 0) or None
    except Exception:
        return None


def _gh_asset(repo: str, test) -> tuple[str, int | None]:
    rel = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                                                   headers={"user-agent": "gbox-setup"}), timeout=30).read())
    a = next(a for a in rel["assets"] if test(a["name"]))
    return a["browser_download_url"], a.get("size")


def _renderdoc_url() -> str:
    page = urllib.request.urlopen(urllib.request.Request("https://renderdoc.org/builds", headers={"user-agent": "gbox-setup"}), timeout=30).read().decode()
    return re.search(r"https://renderdoc\.org/stable/[\d.]+/RenderDoc_[\d.]+_64\.zip", page).group(0)


def _blender_url() -> str:
    base = "https://download.blender.org/release/"
    idx = urllib.request.urlopen(base, timeout=30).read().decode()
    ver = max(re.findall(r'href="Blender(\d+)\.(\d+)/"', idx), key=lambda v: (int(v[0]), int(v[1])))
    d = f"{base}Blender{ver[0]}.{ver[1]}/"
    files = re.findall(r'href="(blender-[\d.]+-windows-x64\.zip)"', urllib.request.urlopen(d, timeout=30).read().decode())
    return d + max(files, key=lambda f: [int(x) for x in re.findall(r"\d+", f)[:3]])


def _addon_installed() -> bool:
    base = Path(os.environ.get("APPDATA", "")) / "Blender Foundation" / "Blender"
    return any(base.glob("*/scripts/addons/gbox_addon.py")) if base.exists() else False


def cmd_need(config: str, offline: bool = False) -> dict:
    """What this PC still needs for the games it has: emulators/cores (+ the BIOS they expect, never downloaded) and the
    toolkits, each with its official URL and download size."""
    cfg = _load_cfg(config)
    from gbox import provision, systems
    rt, win = cfg.runtime, sys.platform == "win32"
    try:
        plats = json.loads((cfg.data_dir / "decant-match.json").read_text()).get("platforms") or {}
    except (OSError, ValueError):
        plats = {}
    items = []

    def item(iid, group, name, have, where="", url="", note="", optional=False, manual="", size=None):
        if not offline and url and size is None and not manual:
            size = _head(url)
        items.append({"id": iid, "group": group, "name": name, "have": bool(have), "where": str(where or ""), "url": url,
                      "size": size, "note": note, "optional": optional, "manual": manual})
    ra = sorted((rt / "retroarch-win").glob("**/retroarch.exe")) if win else []
    seven = next((c for c in (shutil_which("7z"), "C:/Program Files/7-Zip/7z.exe", "C:/Program Files (x86)/7-Zip/7z.exe") if c and Path(c).exists()), None)
    item("retroarch", "emulators", "RetroArch (libretro nightly build)", ra, ra[0] if ra else "",
         f"{provision.BUILDBOT}/windows/x86_64/RetroArch.7z", "runs the libretro cores")
    if not seven and not ra:
        item("7zip", "emulators", "7-Zip (unpacks RetroArch's archive)", False, "", "https://www.7-zip.org/", "installed with winget (7zip.7zip)", size=2_000_000)
    cores, bios = {}, []
    broot = provision._bios_root(cfg)
    for plat in sorted(plats):
        core, need = systems.core_for(plat)
        if core:
            cores.setdefault(core, []).append(plat)
        if need:
            names = [n.split("->")[0] for n in need]
            bios.append({"platform": plat, "games": plats[plat], "files": names,
                         "found": [n for n in names if broot and (broot / n).exists()]})
    for core, ps in sorted(cores.items()):
        p = provision.core_path(cfg, core)
        item(f"core:{core}", "emulators", f"{core} core", p.exists(), p if p.exists() else "",
             f"{provision.BUILDBOT}/windows/x86_64/latest/{p.name}.zip", "for " + ", ".join(f"{x} ({plats[x]} games)" for x in ps))
    if "ps3" in plats:
        h = provision.rpcs3_home(cfg) / "rpcs3.exe"
        url, size = ("", None) if offline else _try(lambda: _gh_asset("RPCS3/rpcs3-binaries-win", lambda n: n.endswith(".7z")), ("", None))
        item("rpcs3", "emulators", "RPCS3 (PS3)", h.exists(), h if h.exists() else "", url, "PS3 firmware (PS3UPDAT.PUP) comes from Sony's site, not gBox", size=size)
    if "xbox360" in plats:
        item("xenia", "emulators", "Xenia Canary (Xbox 360)", (rt / "xenia").exists(), "", "https://github.com/xenia-canary/xenia-canary-releases",
             manual=f"download xenia_canary.zip from the official releases and unpack it into {rt / 'xenia'}")
    rd = sorted((rt / "tools").glob("RenderDoc_*/qrenderdoc.exe"))
    item("renderdoc", "toolkits", "RenderDoc (frame capture: Examine 3D, model extraction)", rd, rd[-1].parent if rd else "",
         "" if offline else _try(_renderdoc_url, "https://renderdoc.org/builds"))
    j = provision.jdk21(cfg)
    item("jdk21", "toolkits", "JDK 21 (Eclipse Temurin, for Ghidra)", j, j or "",
         "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse")
    g = provision.ghidra_home(cfg)
    url, size = ("", None) if offline else _try(lambda: _gh_asset("NationalSecurityAgency/ghidra", lambda n: n.endswith(".zip")), ("", None))
    item("ghidra", "toolkits", "Ghidra (reverse engineering: analyze_binary, ghidra_script)", g and (g / "support").exists(), g or "", url, size=size)
    b = provision.find_blender(cfg)
    item("blender", "toolkits", "Blender (optional: model editing, the gBox bridge)", b, b or "", "https://www.blender.org/download/",
         "point gBox at a Blender you already have", optional=True,
         manual="blender.org only serves downloads to browsers: get the Windows portable zip there, unzip it, then use the field below")
    item("blender-addon", "toolkits", "gBox Blender bridge add-on", _addon_installed(), "", "", "installs into Blender's user add-ons",
         optional=True, size=0)
    ff = shutil_which("ffmpeg")
    item("ffmpeg", "toolkits", "ffmpeg (optional: video, recordings)", ff, ff or "", "", "installed with winget (Gyan.FFmpeg)", optional=True, size=0)
    return {"items": items, "bios": bios, "runtime": str(rt), "platforms": plats}


def shutil_which(n):
    import shutil
    return shutil.which(n)


def _try(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _dl(url: str, dest: Path, label: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"user-agent": "gbox-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total, got, t = int(r.headers.get("content-length") or 0), 0, 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            if time.time() - t > 0.7:
                t = time.time()
                _say(progress={"pct": round(100 * got / total, 1) if total else None, "msg": f"{label}: {got / 1e6:.0f} / {total / 1e6:.0f} MB"})
    return dest


def _unpack(src: Path, dest: Path) -> Path:
    import shutil
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest / src.name, dirs_exist_ok=True)
    elif src.suffix.lower() == ".zip":
        zipfile.ZipFile(src).extractall(dest)
    elif src.suffix.lower() in (".7z", ".rar"):
        from gbox import provision
        subprocess.run([provision._seven_zip(), "x", "-y", f"-o{dest}", str(src)], check=True, capture_output=True)
    else:
        shutil.copy2(src, dest / src.name)
    return dest


def cmd_fetch(config: str, item: str, src: str = "") -> dict:
    """Install one component: from its official source, or (src) from an archive / folder / file this PC already has."""
    import shutil
    cfg = _load_cfg(config)
    from gbox import provision
    rt = cfg.runtime
    rt.mkdir(parents=True, exist_ok=True)
    s = Path(src) if src else None
    if s and not s.exists():
        raise SystemExit(json.dumps({"result": {"error": f"not found: {src}"}}))
    dl = rt / "downloads"
    if item == "retroarch":
        if s:
            exe = next(iter(sorted(s.glob("**/retroarch.exe"))), None) if s.is_dir() else None
            _unpack(exe.parent if exe else s, rt / "retroarch-win")
            return {"detail": f"RetroArch from {s}"}
        _say(progress={"msg": "downloading RetroArch from buildbot.libretro.com (about 240 MB) and unpacking it with 7-Zip"})
        return {"detail": provision.retroarch_exe(cfg)}
    if item == "7zip":
        return {"detail": provision._seven_zip()}
    if item.startswith("core:"):
        core = item[5:]
        if s:
            files = [s] if s.is_file() else sorted(s.glob(f"**/{core}_libretro.dll")) or sorted(s.glob("**/*_libretro.dll"))
            (rt / "cores").mkdir(parents=True, exist_ok=True)
            for f in files:
                if f.suffix.lower() == ".zip":
                    zipfile.ZipFile(f).extractall(rt / "cores")
                else:
                    shutil.copy2(f, rt / "cores" / f.name)
            return {"detail": f"{len(files)} core file(s) from {s}"}
        p = provision.ensure_core(cfg, core)
        provision.ensure_core_assets(cfg, core)
        return {"detail": str(p)}
    if item == "rpcs3":
        if s:
            exe = next(iter(sorted(s.glob("**/rpcs3.exe"))), None)
            shutil.copytree(exe.parent if exe else s, provision.rpcs3_home(cfg), dirs_exist_ok=True)
            return {"detail": f"RPCS3 from {s}"}
        return {"detail": json.dumps(provision.ensure_rpcs3(cfg, lambda p, m: _say(progress={"pct": p, "msg": m})))[:300]}
    if item == "renderdoc":
        if not s:
            url = _renderdoc_url()
            s = _dl(url, dl / url.rsplit("/", 1)[-1], "RenderDoc")
        _unpack(s, rt / "tools")
        got = sorted((rt / "tools").glob("RenderDoc_*/qrenderdoc.exe"))
        if not got:
            raise SystemExit(json.dumps({"result": {"error": f"no RenderDoc_*/qrenderdoc.exe under {rt / 'tools'} after unpacking {s.name}"}}))
        return {"detail": str(got[-1].parent)}
    if item == "jdk21":
        if s:
            _unpack(s, rt)
            return {"detail": str(provision.jdk21(cfg))}
        _say(progress={"msg": "downloading Temurin JDK 21 from adoptium.net (about 190 MB)"})
        return {"detail": json.dumps(provision.ensure_jdk21(cfg))[:300]}
    if item == "ghidra":
        if s:
            _unpack(s, rt)
            return {"detail": str(provision.ghidra_home(cfg))}
        _say(progress={"msg": "downloading Ghidra from GitHub (NationalSecurityAgency/ghidra, about 450 MB) + JDK 21 if missing"})
        return {"detail": json.dumps(provision.ensure_ghidra(cfg))[:300]}
    if item == "blender":
        if s and s.is_file() and s.suffix.lower() == ".exe":
            return {"detail": str(s), "overlay": {"blender_path": str(s).replace("\\", "/")}}
        if not s:
            url = _blender_url()
            s = _dl(url, dl / url.rsplit("/", 1)[-1], "Blender")
        _unpack(s, rt / "blender")
        exe = max((rt / "blender").glob("**/blender.exe"), key=lambda p: p.stat().st_mtime, default=None)
        if not exe:
            raise SystemExit(json.dumps({"result": {"error": "no blender.exe after unpacking"}}))
        return {"detail": str(exe), "overlay": {"blender_path": str(exe).replace("\\", "/")}}
    if item == "blender-addon":
        return {"detail": json.dumps(provision.install_blender_addon(cfg))[:300]}
    if item == "ffmpeg":
        return {"detail": json.dumps(provision.ensure_ffmpeg())[:300]}
    raise SystemExit(json.dumps({"result": {"error": f"no installer for {item}" + (" (see its note: install it by hand)" if item == "xenia" else "")}}))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m gbox.decant")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "pack"):
        p = sub.add_parser(name)
        p.add_argument("--server", default=os.environ.get("GBOX_SERVER", ""))
        p.add_argument("--src", default=str(ROOT), help="the gBox system folder to package")
        p.add_argument("--cheatdb-ssh", default="", help="host:dir of <data_dir>/cheatdb on the control-plane node")
        p.add_argument("--cheatdb-dir", default="", help="or a local / share path to <data_dir>/cheatdb")
        if name == "pack":
            p.add_argument("--out", required=True)
    m = sub.add_parser("match")
    m.add_argument("--config", required=True)
    r = sub.add_parser("rebuild")
    r.add_argument("--config", required=True)
    r.add_argument("--server", default="")
    r.add_argument("--only", default="", choices=["", "cheats", "scan", "characters", "cards"])
    n = sub.add_parser("need")
    n.add_argument("--config", required=True)
    n.add_argument("--offline", action="store_true")
    f = sub.add_parser("fetch")
    f.add_argument("item")
    f.add_argument("--config", required=True)
    f.add_argument("--from", dest="src", default="")
    a = ap.parse_args(argv)
    if a.cmd == "need":
        return print(json.dumps({"result": cmd_need(a.config, a.offline)}, default=str))
    if a.cmd == "fetch":
        try:
            return print(json.dumps({"result": cmd_fetch(a.config, a.item, a.src)}, default=str))
        except SystemExit:
            raise
        except Exception as e:                               # noqa: BLE001
            print(json.dumps({"result": {"error": f"{type(e).__name__}: {e}"}}))
            raise SystemExit(1)
    if a.cmd in ("plan", "pack"):
        tok = os.environ.get("GBOX_TOKEN", "")
        log = lambda msg: print(json.dumps({"log": msg}), file=sys.stderr, flush=True)
        res = build(Path(a.src), a.server, tok, Path(a.out) if a.cmd == "pack" else None, a.cheatdb_ssh,
                    Path(a.cheatdb_dir) if a.cheatdb_dir else None, log)
        print(json.dumps(res))
    elif a.cmd == "match":
        print(json.dumps({"result": cmd_match(a.config)}, default=str))
    elif a.cmd == "rebuild":
        print(json.dumps({"result": cmd_rebuild(a.config, a.server, a.only)}, default=str))


if __name__ == "__main__":
    main()

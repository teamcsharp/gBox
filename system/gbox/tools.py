"""Built-in typed tools. Each declares permissions, availability check, and an independent validator."""
import functools
import gzip
import os
import re
import json
import math
import shutil
import struct
import sys
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, model_validator

from .agent_contracts import validate_cheat_call

from . import adapters, catalog, provision, uap
from .models import CatalogEntry, Permission as P
from .registry import HOST_OS, Ctx, ToolUnavailable, Unsupported, tool
from .store import sha256

ROOT = Path(__file__).resolve().parent.parent
SESSIONS: dict[str, tuple[adapters.Adapter, dict]] = {}   # per-worker live runtime sessions


# --- Phase 0 contract tool ------------------------------------------------------------------

class EchoIn(BaseModel):
    message: str

class EchoOut(BaseModel):
    sha256: str
    length: int
    host_os: str

def _echo_validate(out: EchoOut, arts: dict[str, bytes]) -> list[str]:
    data = arts.get("echo.txt")
    if data is None:
        return ["artifact echo.txt missing"]
    return [] if sha256(data) == out.sha256 and len(data) == out.length else ["artifact does not match reported hash/length"]

@tool("echo_artifact", "1.0", EchoIn, EchoOut, capabilities=["contract-test"], artifacts=["echo.txt"],
      validation="artifact hash and length match output", validate=_echo_validate)
def echo_artifact(inp: EchoIn, ctx: Ctx):
    """Contract test: writes the message as an artifact and reports its hash."""
    data = inp.message.encode()
    ctx.artifact("echo.txt", data, "text/plain")
    return {"sha256": sha256(data), "length": len(data), "host_os": HOST_OS}


# --- catalog --------------------------------------------------------------------------------

class ScanIn(BaseModel):
    libraries: list[str] | None = None    # library ids; default: all configured libraries
    roots: list[str] | None = None        # ad-hoc plain folders (content-hashed), in addition to libraries
    include_steam: bool = True

class ScanOut(BaseModel):
    count: int
    per_library: dict[str, dict]
    problems: list[str]
    catalog_sha256: str                   # artifact catalog.jsonl.gz holding every entry

def _read_catalog_artifact(data: bytes) -> list[dict]:
    return [json.loads(ln) for ln in gzip.decompress(data).splitlines() if ln.strip()]

def _scan_validate(out: ScanOut, arts) -> list[str]:
    data = arts.get("catalog.jsonl.gz")
    if data is None or sha256(data) != out.catalog_sha256:
        return ["catalog artifact missing or hash mismatch"]
    rows = _read_catalog_artifact(data)
    p = [] if len(rows) == out.count else [f"artifact has {len(rows)} entries, output claims {out.count}"]
    if len({r["game_id"] for r in rows}) != len(rows):
        p.append("duplicate game_id in scan output")
    for r in rows[:50] + rows[-50:]:                # schema spot check (full check is done on ingest)
        CatalogEntry.model_validate(r)
    return p

def _scan_accept(store, out: ScanOut, actor: str):
    rows = [CatalogEntry.model_validate(r).model_dump() for r in _read_catalog_artifact(store.read_artifact(out.catalog_sha256))]
    store.upsert_catalog(rows)                     # Game Profiles are created on first access (server /api/profiles)
    pruned = {}
    for lib in out.per_library:                    # only libraries this scan actually covered
        if lib not in ("adhoc", "steam"):
            pruned[lib] = store.prune_catalog(lib, {r["game_id"] for r in rows if r.get("library") == lib})
    store.audit(actor, "catalog.ingest", "catalog", {"entries": len(rows), "per_library": out.per_library, "pruned": pruned,
                                                    "problems": len(out.problems), "artifact": out.catalog_sha256})

@tool("scan_library", "2.0", ScanIn, ScanOut, capabilities=["catalog"], timeout_s=7200,
      side_effects=["writes listing/hash cache in data_dir"], artifacts=["catalog.jsonl.gz", "scan_report.json"],
      validation="artifact hash + entry count + unique ids", validate=_scan_validate, on_accept=_scan_accept)
def scan_library(inp: ScanIn, ctx: Ctx):
    """Index configured libraries (HyperSpin/Attract-Mode trees, ROM folders) read-only, plus local Steam."""
    cfg = ctx.config
    cache, cache_path = catalog.cache_hash_db(cfg)
    entries, problems, per = [], [], {}
    for lib in cfg.libraries:
        if inp.libraries is not None and lib.id not in inp.libraries:
            continue
        root = lib.root()
        if not root or not root.exists():
            problems.append(f"library {lib.id}: path not reachable on this node: {root}")
            continue
        t = time.time()
        if lib.kind == "attract":
            e, p, stats = catalog.scan_attract(root, lib.id, cache)
        else:
            e, p = catalog.scan([root], {}, cache, lib_id=lib.id, do_hash=lib.hash,
                                platform_hint=lib.platform, recursive=lib.recursive, exclude_dirs=lib.exclude_dirs,
                                exclude_files=lib.exclude_files)
            stats = {}
        entries += e
        problems += p
        per[lib.id] = {"entries": len(e), "seconds": round(time.time() - t, 1), **stats}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    if inp.roots:
        e, p = catalog.scan([Path(r) for r in inp.roots], {p: "configured" for p in cfg.emulators}, cache)
        entries, problems, per["adhoc"] = entries + e, problems + p, {"entries": len(e)}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    if inp.include_steam and cfg.steam_root:
        e, p = catalog.scan_steam(cfg.steam_root)
        entries, problems, per["steam"] = entries + e, problems + p, {"entries": len(e)}
    try:                                                # decanted install: the recipes' ids for this PC's matching copies
        remap = json.loads((cfg.data_dir / "game_ids.json").read_text())   # (written by `python -m gbox.decant match`)
    except (OSError, ValueError):
        remap = {}
    for e in entries:
        if e.game_id in remap:
            e.game_id = e.profile_id = remap[e.game_id]
    seen, unique = set(), []
    for e in entries:                                   # same file reachable via two libraries -> keep first
        if e.game_id not in seen:
            seen.add(e.game_id)
            unique.append(e)
    blob = gzip.compress("\n".join(e.model_dump_json() for e in unique).encode())
    ctx.artifact("catalog.jsonl.gz", blob, "application/gzip")
    ctx.artifact("scan_report.json", json.dumps({"per_library": per, "problems": problems}, indent=1).encode(),
                 "application/json")
    return {"count": len(unique), "per_library": per, "problems": problems[:500], "catalog_sha256": sha256(blob)}


class HashIn(BaseModel):
    game: CatalogEntry

class HashOut(BaseModel):
    game_id: str
    hashes: dict[str, str]
    size: int

def _hash_accept(store, out: HashOut, actor: str):
    store.catalog_update(out.game_id, hashes=out.hashes, size=out.size)

@tool("hash_game", "1.0", HashIn, HashOut, capabilities=["catalog"], timeout_s=3600,
      validation="schema", on_accept=_hash_accept)
def hash_game(inp: HashIn, ctx: Ctx):
    """Content-hash one cataloged file on demand (sha1 + crc32), recorded on the catalog entry."""
    p = rom_path(inp.game, ctx.config)
    if p.is_dir():
        raise ValueError("directory-based games are not hashed")
    return {"game_id": inp.game.game_id, "hashes": catalog.file_hashes(p, {}), "size": p.stat().st_size}


def rom_path(g: CatalogEntry, config) -> Path:
    """Resolve a catalog entry to a local path on THIS node (libraries are mounted differently per OS)."""
    if g.library and g.rel_path:
        root = config.library(g.library).root()
        if not root:
            raise ToolUnavailable(f"library {g.library} has no path for {HOST_OS}")
        return root / g.rel_path
    return Path(g.launch["path"])


# --- runtime sessions -----------------------------------------------------------------------

class PrepareModIn(BaseModel):
    game: CatalogEntry
    mod: str


class PrepareModOut(BaseModel):
    ready: bool
    mod: str = ""                          # the folder to launch: the mod name, or <mod>~<build> when the running game holds the old copy open
    source_mod: str = ""                   # the canonical collection name; staged metadata retains this identity


@tool('prepare_mod', '1.1', PrepareModIn, PrepareModOut, capabilities=['runtime'], permissions=[P.EXECUTE], timeout_s=1800)
def prepare_mod(inp: PrepareModIn, ctx: Ctx):
    """Stage replacement files on the target worker without closing or changing its running game."""
    from . import filemods
    name = inp.mod
    if ctx.server:
        name = filemods.stage(ctx.config, ctx.server, ctx.headers, inp.game.game_id, inp.mod, ctx.progress)
    folder = filemods.mod_dir(ctx.config, inp.game.game_id, name)
    marker = filemods._file_path(folder, '.gbox-mod.json')
    if not marker.exists():
        raise RuntimeError('Replacement preparation did not complete')
    meta = json.loads(marker.read_text())
    if not isinstance(meta, dict) or (meta.get('name') and meta['name'] != inp.mod) or (
            meta.get('game_id') and meta['game_id'] != inp.game.game_id):
        raise RuntimeError('Prepared replacement metadata belongs to another mod or game')
    if meta.get('image') and not filemods._file_path(folder, meta['image']).is_file():
        raise RuntimeError('Prepared replacement image is missing')
    return {'ready': True, 'mod': name, 'source_mod': inp.mod}


class LaunchIn(BaseModel):
    game: CatalogEntry
    debug: bool = False                    # prefer an emulator with a full CPU debugger (registers/breakpoints)
    mod: str = ""                          # launch a file mod built with file_mod (folder games, e.g. PS3)
    examine: bool | None = None            # RenderDoc inside the emulator for Examine 3D (None = config examine_ready)

class LaunchOut(BaseModel):
    session_id: str
    adapter: str
    capabilities: dict[str, str]
    detail: dict

def _launch_accept(store, out: LaunchOut, actor: str):
    existing = store.get('session', out.session_id)
    expected = {'game_id': (out.detail.get('_game') or {}).get('game_id'), 'adapter': out.adapter,
                'pid': out.detail.get('pid')}
    if existing:
        observed = {'game_id': existing.get('game_id'), 'adapter': existing.get('adapter'),
                    'pid': (existing.get('detail') or {}).get('pid')}
        if observed != expected:
            raise RuntimeError('This launch result conflicts with the already registered native session')
    for checkpoint in out.detail.get('previous_checkpoints', []):
        old_sid = checkpoint['session_id']
        old = store.get('session', old_sid)
        if old and old.get('state') != 'ended':
            store.put('session', old_sid, old | {'state': 'ended', 'ended': time.time(),
                      'checkpoint': checkpoint['artifact'], 'exit': {'via': 'single_game', 'to': out.session_id}})
    g = out.detail.get("_game", {})
    actual_mod = out.detail.get("mod") or ""
    collection_mod = out.detail.get("collection_mod") or actual_mod
    prepared = ({"collection_mod": collection_mod, "staged_mod": actual_mod, "launch_mod": actual_mod}
                if collection_mod != actual_mod else {})
    if not existing:
        store.put("session", out.session_id, {"session_id": out.session_id, "game_id": g.get("game_id"), "title": g.get("title"),
                                          "mod": collection_mod, **prepared,
                                          "adapter": out.adapter, "capabilities": out.capabilities, "state": "running",
                                          "started": time.time(), "detail": {k: v for k, v in out.detail.items() if k != "_game"}})
    if g.get("game_id"):
        e = store.catalog_get(g["game_id"]) or {}
        registered = existing or store.get('session', out.session_id)
        upd = {"playable": f"launches ({out.adapter})", "last_played": registered['started']}
        if out.detail.get("staged_on"):
            upd["cached_on"] = sorted(set(e.get("cached_on") or []) | {out.detail["staged_on"]})
        store.catalog_update(g["game_id"], **upd)

def _launch_fail(store, job: dict, actor: str):
    gid = job["input"].get("game", {}).get("game_id")
    if gid:
        store.catalog_update(gid, playable=f"launch failed: {(job.get('error') or '')[:200]}")

_LAUNCH_LOCK = threading.RLock()


def _close_previous_games(ctx):
    """One emulator per worker. Preserve every current game before stopping any of them."""
    previous = list(SESSIONS.items())
    checkpoints = []
    for sid, (ad, game) in previous:
        proc = getattr(ad, 'proc', None)
        if proc and proc.poll() is not None:
            if getattr(ctx, 'server', None):
                httpx.post(f'{ctx.server}/api/sessions/{sid}/ended', headers=ctx.headers,
                           json={'returncode': proc.poll(), 'via': 'single_game'}, timeout=10).raise_for_status()
            SESSIONS.pop(sid, None)
            continue
        ctx.progress(71, 'Saving the previous game before switching')
        try:
            saved = state_transfer(StateXIn(session_id=sid, op='export'), ctx)['result']
        except Exception as exc:
            raise Unsupported(f"The previous game could not be saved: {exc}. It was kept running. Stop it in Sessions before starting another game.") from exc
        checkpoints.append({'session_id': sid, 'game_id': game.get('game_id'), **saved})
    for sid, (ad, _) in previous:
        if sid not in SESSIONS:
            continue
        ad.stop_game()
        proc = getattr(ad, 'proc', None)
        if proc and proc.poll() is None:
            raise RuntimeError('The previous emulator is still running; another game was not started')
        if getattr(ctx, 'server', None):
            snapshot = next(s for s in checkpoints if s['session_id'] == sid)
            httpx.post(f'{ctx.server}/api/sessions/{sid}/ended', headers=ctx.headers,
                       json={'via': 'single_game', 'checkpoint': snapshot['artifact']}, timeout=10).raise_for_status()
        SESSIONS.pop(sid, None)
        track_emulator(ctx.config, sid, None, add=False)
    return checkpoints


@tool("launch_game", "1.2", LaunchIn, LaunchOut, capabilities=["runtime"], permissions=[P.EXECUTE], timeout_s=900,
      side_effects=["starts emulator/game process", "may download a core/BIOS", "may stage a copy into cache"],
      validation="adapter reported content running", on_accept=_launch_accept, on_fail=_launch_fail)
def launch_game(inp: LaunchIn, ctx: Ctx):
    """Launch a cataloged game on this node; missing cores/BIOS are installed automatically. Streams to the UI."""
    with _LAUNCH_LOCK:
        return _launch_game(inp, ctx)


def _launch_game(inp: LaunchIn, ctx: Ctx):
    g = inp.game
    launch_mod = inp.mod
    ctx.progress(2, f"Loading {g.title} · {g.system or g.platform}")
    ad = adapters.for_game(g.model_dump(), ctx.config, debug=inp.debug)
    ad.progress = ctx.progress
    ad.game_id, ad.serial = g.game_id, g.serial            # per-game settings (graphics) applied at launch
    ad.examine = HOST_OS == "windows" and (inp.examine if inp.examine is not None else ctx.config.examine_ready)
    ctx.progress(5, f"Runtime: {ad.name}" + (f" · core {g.core}" if g.core else ""))
    if g.launch.get("kind") == "steam":
        checkpoints = _close_previous_games(ctx)
        detail = ad.launch_game(g.launch["appid"], (g.source_paths or [None])[0])
    elif isinstance(ad, adapters.RocketLauncherAdapter):
        checkpoints = _close_previous_games(ctx)
        detail = ad.launch_game(g.launch["emulator"], g.launch["name"])
    else:
        src = rom_path(g, ctx.config)
        if not src.exists():
            raise FileNotFoundError(f"ROM not reachable from this node: {src}")
        if isinstance(ad, adapters.RPCS3Adapter) and g.launch.get("kind") == "attract":
            eboot = catalog.ps3_stub_eboot(src)            # HyperSpin .txt stub -> its disc folder's EBOOT.BIN (#1093)
            if not eboot:
                raise FileNotFoundError(f"no PS3_GAME/USRDIR/EBOOT.BIN in the folder for {src.name} under {src.parent}")
            ad.serial = ad.serial or catalog.ps3_title_id(eboot)    # per-game RPCS3 config (Sessions -> Graphics)
            ctx.progress(8, f"PS3 game: {eboot}")
            src = eboot
        if g.game_id == "0871eee3b68cdea3":                # Resident Evil 6 (X360): boot profile "Everything unlocked"
            try:
                from . import re6_tool
                pre = re6_tool.pre_launch(ctx, inp.mod)
                if (pre.get("unlock") or {}).get("bytes_changed"):
                    ctx.progress(18, "RE6 save: everything unlocked (original backed up)")
            except Exception as e:                         # noqa: BLE001 - never block the launch
                print(f"gBox: re6 pre-launch failed: {e}", flush=True)
        if inp.mod:
            from . import filemods
            if not (filemods.mod_dir(ctx.config, g.game_id, inp.mod) / ".gbox-mod.json").exists() and ctx.server:
                ctx.progress(20, f"Fetching mod {inp.mod} from the central collection (Spark)")
                launch_mod = filemods.stage(ctx.config, ctx.server, ctx.headers, g.game_id, inp.mod, ctx.progress)
            src = filemods.launch_path(ctx.config, g.game_id, src, launch_mod)
            ctx.progress(28, f"Mod: {launch_mod}")
        emu = ctx.config.emulators.get(g.platform)
        # big disc images (CHD/ISO/GCZ...) stream poorly over SMB: stage them onto this node's fast local cache
        big = src.is_file() and src.stat().st_size > ctx.config.stage_min_mb * 1024 * 1024
        if g.platform not in ("ps3", "switch") and not (g.launch.get("archive_member") and not inp.mod) and ((emu and emu.stage_local) or (big and g.library and _stageable(src))):   # Switch XCI/NSP streams from the user's share; copying 15+ GB before play stalls launch
            mb = src.stat().st_size / 2**20
            ctx.progress(30, f"Staging {src.name} ({mb:,.0f} MB) to the fast local cache")
            last = [0.0]
            def copied(done, total):
                if time.time() - last[0] > 0.5:
                    last[0] = time.time()
                    ctx.progress(30 + 40 * done / total, f"Staging {src.name}: {done / 2**20:,.0f} / {total / 2**20:,.0f} MB")
            receipt = catalog.stage(src, g.game_id, ctx.config, copied)
            staged_on = __import__("platform").node()
            ctx.progress(70, f"Staged to cache ({'reused' if not receipt.get('copied', True) else 'copied'}) · evicted {len(receipt['evicted'])}")
            ctx.artifact("staging_receipt.json", json.dumps(receipt).encode(), "application/json", game=g.game_id)
            src = Path(receipt["dst"])
        if g.launch.get("archive_member") and not inp.mod:
            from . import rom_archives
            src = rom_archives.prepare(src, ctx.config, g.launch["archive_member"], ctx.progress)
            staged_on = __import__("platform").node()
        checkpoints = _close_previous_games(ctx)
        ctx.progress(72, f"Starting {ad.name} with {src.name}")
        detail = ad.launch_game(str(src))
    ctx.progress(100, "Running natively in its own window" if detail.get("local_window") else "Running — connecting the stream")
    sid = f"{ctx.worker}-{ctx.job_id}"
    gd = g.model_dump()
    if g.launch.get("kind") != "steam" and not isinstance(ad, adapters.RocketLauncherAdapter):
        gd["_rom_path"] = str(src)                     # for the inspector's ROM viewer
    SESSIONS[sid] = (ad, gd)
    if gd.get("game_id") == "0871eee3b68cdea3":                # Resident Evil 6 (X360): Auto QTE + saved switches at boot
        try:
            from . import re6_tool
            re6_tool.on_launch(sid, ctx)
        except Exception as e:                                 # noqa: BLE001 - never block the launch
            print(f"gBox: re6 boot hook failed: {e}", flush=True)
    if HOST_OS == "windows" and isinstance(ad, adapters.RetroArchAdapter) and ad.rewind_on:
        _ensure_rewind_hotkey()
    if HOST_OS == "windows" and isinstance(ad, adapters.RPCS3Adapter):
        _ensure_ps3_load_hotkey()
    if ctx.server and (not isinstance(ad, adapters.SteamAdapter) or ad.install_dir):     # live channel (input, inspector RPCs, exit) even without video
        threading.Thread(target=_pump, args=(sid, ad, ctx.server, ctx.headers), daemon=True).start()
    detail["_game"] = {"game_id": g.game_id, "title": g.title}
    detail["mod"] = launch_mod or ""                           # the actual prepared folder used by this process
    if launch_mod != inp.mod:
        detail["collection_mod"] = inp.mod
    detail['previous_checkpoints'] = checkpoints
    if sys.platform == "win32" and getattr(ad, "name", "") == "retroarch":
        threading.Thread(target=_ff_ramp, args=(sid, ad), daemon=True).start()
    track_emulator(ctx.config, sid, detail.get("pid") or getattr(getattr(ad, "proc", None), "pid", None))
    if "staged_on" in locals():
        detail["staged_on"] = staged_on
    return {"session_id": sid, "adapter": ad.name, "capabilities": ad.get_capabilities(), "detail": detail}


_HOTKEY = {"thread": None}


def _ensure_rewind_hotkey():
    """Keypad minus -> rewind 5 s in native RetroArch windows. Registered system-wide only while such a game runs."""
    if _HOTKEY["thread"] and _HOTKEY["thread"].is_alive():
        return

    def loop():
        import ctypes
        from ctypes import wintypes
        user32, VK_SUBTRACT, WM_HOTKEY, HK = ctypes.windll.user32, 0x6D, 0x0312, 0xB0C5
        if not user32.RegisterHotKey(None, HK, 0x4000, VK_SUBTRACT):      # MOD_NOREPEAT
            return
        msg = wintypes.MSG()
        try:
            while any(getattr(a, "rewind_on", False) for a, _ in SESSIONS.values()):
                while user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1):
                    for a, _ in list(SESSIONS.values()):
                        if getattr(a, "rewind_on", False):
                            threading.Thread(target=a.rewind, args=(5,), daemon=True).start()
                time.sleep(0.03)
        finally:
            user32.UnregisterHotKey(None, HK)                            # keypad minus works normally again
    _HOTKEY["thread"] = threading.Thread(target=loop, daemon=True, name="rewind-hotkey")
    _HOTKEY["thread"].start()


_PS3_HOTKEY = {"thread": None}


def _ensure_ps3_load_hotkey():
    """F4 -> load the newest save state (RPCS3 relaunch) while a PS3 game runs on this PC; released when none does."""
    if _PS3_HOTKEY["thread"] and _PS3_HOTKEY["thread"].is_alive():
        return

    def loop():
        import ctypes
        from ctypes import wintypes
        user32, VK_F4, WM_HOTKEY, HK = ctypes.windll.user32, 0x73, 0x0312, 0xB0C6
        if not user32.RegisterHotKey(None, HK, 0x4000, VK_F4):           # MOD_NOREPEAT
            return
        msg = wintypes.MSG()
        try:
            while any(isinstance(a, adapters.RPCS3Adapter) for a, _ in SESSIONS.values()):
                while user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1):
                    for a, _ in list(SESSIONS.values()):
                        if isinstance(a, adapters.RPCS3Adapter):
                            threading.Thread(target=a.load_state, daemon=True).start()
                time.sleep(0.03)
        finally:
            user32.UnregisterHotKey(None, HK)                            # F4 works normally again
    _PS3_HOTKEY["thread"] = threading.Thread(target=loop, daemon=True, name="ps3-load-hotkey")
    _PS3_HOTKEY["thread"].start()


def _stageable(src: Path) -> bool:
    # multi-file disc sets reference sibling tracks by relative path; copying only the sheet would break them
    return src.suffix.lower() not in (".cue", ".gdi", ".m3u")


def _rpc_answerer(sid: str, client):
    """Answer live-channel requests (pause/resume, reset, inspector reads) through one keep-alive client. A new httpx
    client per reply builds an SSL context and opens a TCP connection every time, on the path of every click (#1123)."""
    def answer(ev):
        try:
            result = {"ok": True, "data": session_rpc(sid, ev["op"], ev.get("args") or {})}
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            client.post(f"/api/sessions/{sid}/rpc/{ev['rpc']}", json=result)
        except httpx.HTTPError:
            pass
    return answer

def _pump(sid: str, ad, server: str, headers: dict):
    """Live session plumbing, three independent loops so nothing slow can stall the video:
    frames  - pushed the moment the encoder produces one (up to the stream fps, 60),
    input   - long-polled from the control plane and applied immediately,
    status  - every 3 s; marks the session ended when the emulator exits."""
    stream = ad.stream_session() if "stream_session" in ad.supported else None

    def frames():
        if stream is None:                               # local native window: nothing to stream
            return
        # one long-lived upload per session: [4-byte big-endian length][JPEG] ... (a POST per frame capped at ~6 fps)
        def body():
            last = -1
            while sid in SESSIONS:
                if stream.wait(last, 1.0):
                    last, data = stream.seq, stream.latest
                    yield len(data).to_bytes(4, "big") + data
                else:
                    yield b"\0\0\0\0"                     # keepalive (zero-length frame)
        while sid in SESSIONS:
            try:
                with httpx.Client(base_url=server, headers=headers, timeout=httpx.Timeout(10, read=None, write=None)) as c:
                    c.post(f"/api/sessions/{sid}/stream", content=body(), headers={"content-type": "application/octet-stream"})
            except httpx.HTTPError:
                time.sleep(1)

    answer = _rpc_answerer(sid, httpx.Client(base_url=server, headers=headers, timeout=10))

    def inputs():
        # one channel carries pad/keyboard events and read-only inspector requests ({"rpc": id, "op", "args"})
        with httpx.Client(base_url=server, headers=headers, timeout=15) as c:
            while sid in SESSIONS:
                try:
                    events = c.get(f"/api/sessions/{sid}/input", params={"wait": 5}).json()
                    pad = [e for e in events if "rpc" not in e]
                    for e in events:
                        if "rpc" in e:
                            threading.Thread(target=answer, args=(e,), daemon=True).start()
                    if pad and "send_input" in ad.supported:
                        ad.send_input(pad)
                except Exception:
                    time.sleep(0.5)

    threading.Thread(target=frames, daemon=True).start()
    threading.Thread(target=inputs, daemon=True).start()
    if sys.platform == "win32":                                  # mirror the operator's own pad to the controller glyph
        from . import padstate
        threading.Thread(target=padstate.watch_xinput, args=(server, headers, sid, lambda: sid in SESSIONS), daemon=True).start()
    with httpx.Client(base_url=server, headers=headers, timeout=10) as c:
        pid = getattr(getattr(ad, "proc", None), "pid", None)
        while sid in SESSIONS:
            time.sleep(3)
            try:
                now = getattr(getattr(ad, "proc", None), "pid", None)
                if now and now != pid:                     # emulator relaunched in place (RPCS3 load state): re-dock it
                    c.post(f"/api/sessions/{sid}/detail", json={"pid": now})
                    pid = now
                running = ad.proc.poll() is None if getattr(ad, "proc", None) else ad.query_runtime().get("running", True)
                if not running:
                    c.post(f"/api/sessions/{sid}/ended", json={"returncode": getattr(ad.proc, "returncode", None)})
                    SESSIONS.pop(sid, None)
            except Exception:
                pass


# --- inspector: read-only peeks over the live session channel (writes go through the audited write_memory job) ---
_ROM_CACHE: dict[str, bytes] = {}
ROM_CACHE_MAX = 128 * 1024 * 1024


def _rom_bytes(path: str) -> bytes:
    """ROM image for the tile viewer. Zips are unpacked (largest member); disc images are read as-is."""
    if path not in _ROM_CACHE:
        import zipfile
        p = Path(path)
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                member = max(z.infolist(), key=lambda i: i.file_size)
                data = z.read(member) if member.file_size <= ROM_CACHE_MAX else b""
        elif p.is_file() and p.stat().st_size <= ROM_CACHE_MAX:
            data = p.read_bytes()
        else:
            raise ValueError(f"ROM too large or not a file for byte view ({p.suffix}); use the RAM view")
        _ROM_CACHE.clear()                              # keep one ROM in memory
        _ROM_CACHE[path] = data
    return _ROM_CACHE[path]


def session_rpc(sid: str, op: str, args: dict):
    ad, g = SESSIONS[sid]
    if op == "read_memory":
        n = max(1, min(int(args.get("length", 256)), 1 << 20))       # up to 1 MiB per call (one CPU halt on debug stubs)
        return ad.read_memory(int(args["address"]), n).hex()
    if op == "read_rom":
        data = _rom_bytes(g["_rom_path"])
        off, n = int(args.get("offset", 0)), max(1, min(int(args.get("length", 4096)), 65536))
        return {"size": len(data), "offset": off, "hex": data[off:off + n].hex()}
    if op == "info":
        return {"platform": g.get("platform"), "core": g.get("core"), "title": g.get("title"), "emulator": ad.name, "game_id": g.get("game_id"),
                "rom": Path(g["_rom_path"]).name if g.get("_rom_path") else None,
                "capabilities": ad.get_capabilities(), "runtime": ad.query_runtime()}
    if op.startswith("debug_"):
        return _debug_rpc(ad, g, op[6:], args)
    if op == "state":
        return _semantic_state(ad, g, bool(args.get("player_only")))
    if op == "menu":                                   # the emulator's own menu (its controller settings live there)
        if getattr(ad, "name", "") != "retroarch":
            raise Unsupported(f"{getattr(ad, 'name', 'this emulator')}: open its controller settings from its own window")
        ad.cmd("MENU_TOGGLE")
        return {"menu": "toggled"}
    if op in ("pause", "resume"):                      # the pause button, instantly (no job queue, #1123)
        if op not in getattr(ad, "supported", ()):
            raise Unsupported(f"{getattr(ad, 'name', 'this emulator')} cannot {op} from gBox")
        return getattr(ad, op)() or {}
    if op == "reset":                                  # the console's reset switch, instantly (no job queue)
        if not callable(getattr(type(ad), "reset", None)):
            raise Unsupported(f"{getattr(ad, 'name', 'this emulator')} has no reset")
        return ad.reset() or {"reset": True}
    raise ValueError(f"rpc op {op} not allowed (read_memory, read_rom, info, state, reset, pause, resume, debug_*)")


def _semantic_state(ad, g: dict, player_only: bool = False):
    """Verified semantic state (profiles/*.json). On debug-stub sessions the whole read happens under one CPU halt."""
    from . import semantic
    if not g.get("_profile"):                        # retry until it matches (the game may still be booting)
        g["_profile"] = semantic.match(g, ad.read_memory)
    elif (fresh := next((p for p in semantic.load_profiles() if p["id"] == g["_profile"]["id"]), None)):
        g["_profile"] = fresh                        # profile edits apply to running sessions
    prof = g["_profile"]
    if not prof:
        return {"profile": None, "note": "no semantic profile for this game yet (see system/profiles/)"}
    dbg = getattr(ad, "dbg", None)
    if dbg is not None:
        with dbg.paused():
            st = semantic.Extractor(prof, ad.read_memory).state(player_only)
    else:
        st = semantic.Extractor(prof, ad.read_memory).state(player_only)
    st["evidence"] = prof.get("evidence", {})
    st["title"] = prof.get("title")
    return st


def _debug_rpc(ad, g: dict, op: str, args: dict):
    """CPU debugger ops. Halting/stepping/breakpoints change execution, never game memory (that's write_memory)."""
    from . import debug
    try:
        d = ad.debugger()
    except Exception as e:
        raise debug.Unavailable(f"no debugger for this session: {e}")
    addr = lambda k="address": int(str(args[k]), 16) if isinstance(args.get(k), str) else int(args[k])
    if op == "info":
        out = d.info()
        try:                                   # registers while running briefly halt the CPU: only when asked or halted
            want = "regs" in d.features and (args.get("regs", True) or out.get("halted"))
            out["regs"] = d.regs() if want else None
        except Exception as e:
            out["regs_error"] = str(e)
        out["vram"] = [{"label": l, "address": a, "size": n, "view": v} for l, a, n, v in debug.VRAM.get(g.get("platform"), [])]
        return out
    if op == "regs":
        return d.regs()
    if op == "disasm":
        a = addr() if args.get("address") not in (None, "") else None
        return d.disasm(a, max(1, min(int(args.get("count", 48)), 400)))
    if op in ("halt", "resume", "step"):
        return getattr(d, op)()
    if op == "break":
        return d.set_breakpoint(addr(), args.get("kind", "exec"), int(args.get("length", 4)))
    if op == "unbreak":
        return d.remove_breakpoint(addr(), args.get("kind", "exec"), int(args.get("length", 4)))
    raise ValueError(f"unknown debug op {op}")


_RECORDINGS: dict[int, tuple] = {}


def _record(ad, g, start: bool, ctx):
    """MP4 of a session's display (x11grab -> H.264). Stop uploads it as an artifact."""
    disp = getattr(getattr(ad, "display", None), "name", None)
    if not disp:
        raise Unsupported("recording needs a session display (Spark sessions)")
    key = id(ad)
    if start:
        if key in _RECORDINGS:
            return {"recording": True, "already": True}
        out = ctx.config.runtime / "recordings" / f"{g.get('game_id', 'session')}-{int(time.time())}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        w, h = ad.display.w, ad.display.h
        proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", "30", "-video_size", f"{w}x{h}",
                                 "-i", disp, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                                 "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _RECORDINGS[key] = (proc, out, time.time())
        return {"recording": True, "file": out.name}
    proc, out, t0 = _RECORDINGS.pop(key, (None, None, None))
    if not proc:
        return {"recording": False}
    proc.communicate(b"q", timeout=30)                 # 'q' lets ffmpeg finalise the MP4 index
    data = out.read_bytes()
    ref = ctx.artifact(out.name, data, "video/mp4", game=g.get("game_id"), title=g.get("title"), seconds=round(time.time() - t0, 1))
    return {"recording": False, "artifact": sha256(data), "bytes": len(data), "seconds": round(time.time() - t0, 1)}


class SessionIn(BaseModel):
    session_id: str
    op: str                                # any adapter op except memory writes (see write_memory)
    args: dict = {}

class SessionOut(BaseModel):
    result: dict
    session_id: str | None = None
    ended: bool = False

def _session_accept(store, out: SessionOut, actor: str):
    if out.ended and (s := store.get("session", out.session_id)) and s.get("state") != "ended":
        store.put("session", out.session_id, s | {"state": "ended", "ended": time.time(), "exit": out.result})

@tool("session_op", "1.0", SessionIn, SessionOut, capabilities=["runtime"], permissions=[P.EXECUTE],
      on_accept=_session_accept)
def session_op(inp: SessionIn, ctx: Ctx):
    """Call a runtime op (pause/resume/stop_game/save_state/query_runtime/step_frames...) on a live session."""
    if inp.op in ("record_start", "record_stop"):
        ad, g = SESSIONS[inp.session_id]
        res = _record(ad, g, inp.op == "record_start", ctx)
        return {"result": res, "session_id": inp.session_id, "ended": False}
    if inp.op == "log_tail":                                         # issue reports: the emulator's own console/log output
        ad, _ = SESSIONS[inp.session_id]
        n = int(inp.args.get("n", 60000))
        if callable(getattr(type(ad), "log_tail", None)):
            log, path = ad.log_tail(n), getattr(ad, "log_path", None)
        elif getattr(ad, "home", None) and (Path(ad.home) / "RPCS3.log").exists():     # RPCS3 writes its own log
            path = Path(ad.home) / "RPCS3.log"
            log = path.read_text(errors="replace")[-n:]
        else:
            log, path = "", None
        return {"result": {"log": log, "path": str(path or ""), "emulator": getattr(ad, "name", "?")},
                "session_id": inp.session_id, "ended": False}
    if inp.op == "reset":                                            # restart the emulated console (the session stays)
        ad, _ = SESSIONS[inp.session_id]
        if not callable(getattr(type(ad), "reset", None)):
            raise Unsupported(f"{getattr(ad, 'name', 'this emulator')} has no reset: relaunch the game instead")
        return {"result": ad.reset() or {"reset": True}, "session_id": inp.session_id, "ended": False}
    if inp.op not in adapters.OPS or inp.op in ("write_memory", "read_memory", "launch_game"):
        raise ValueError(f"op {inp.op} not allowed via session_op")
    if inp.op == "send_input":                                       # controller glyph shows gBox's presses
        from . import padstate
        padstate.report(ctx, inp.session_id, inp.args.get("events"), "agent")
    ad, _ = SESSIONS[inp.session_id]
    try:
        res = getattr(ad, inp.op)(**inp.args)
    except TypeError:
        if "slot" not in inp.args:
            raise
        res = getattr(ad, inp.op)(**{k: v for k, v in inp.args.items() if k != "slot"})   # emulator with one slot
    if inp.op == "save_state" and isinstance(res, dict):            # thumbnail for the save-state film strip
        if getattr(ad, 'name', '') == 'retroarch' and res.get('path'):
            _validate_state_container(Path(res['path']).read_bytes(), 'retroarch')
        try:
            png = ad.get_frame()
            ctx.artifact("state.png", png, "image/png", session=inp.session_id, slot=res.get("slot"))
            res["frame"] = sha256(png)
        except Exception:
            pass
    if inp.op == "stop_game":
        proc = getattr(ad, 'proc', None)
        if proc is not None and proc.poll() is None:
            raise RuntimeError('Emulator process is still running; stop was not confirmed')
        SESSIONS.pop(inp.session_id, None)
        track_emulator(ctx.config, inp.session_id, None, add=False)
    return {"result": res if isinstance(res, dict) else {"value": str(res)[:200]}, "session_id": inp.session_id,
            "ended": inp.op == "stop_game"}


class PokeIn(BaseModel):
    session_id: str
    address: str | int                     # "0x..." or int; several = comma list (e.g. x,y,z scale of a matrix)
    type: str = "f32"                      # u8 | u16 | u32 | i32 | f32
    value: float
    scale_original: bool = False           # value multiplies the value found there the first time (x1 .. x800 sliders)
    hold: bool = True                      # keep writing it (games re-compute many values every frame)


ORIGINALS: dict[tuple, float] = {}


@tool("poke", "1.0", PokeIn, SessionOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=60)
def poke(inp: PokeIn, ctx: Ctx):
    """Set a typed value at one or more live addresses (platform byte order), optionally as a multiple of the original
    value, optionally held. Drives the chat's sliders: any game value the agent has located can get a live slider."""
    import struct as S
    ad, g = SESSIONS[inp.session_id]
    end = ">" if g.get("platform") in BIG_ENDIAN else "<"
    fmt = end + {"u8": "B", "u16": "H", "u32": "I", "i32": "i", "f32": "f"}[inp.type]
    n = S.calcsize(fmt)
    addrs = [int(a, 0) for a in str(inp.address).split(",")] if isinstance(inp.address, str) else [inp.address]
    out = {}
    for a in addrs:
        if (inp.session_id, a) not in ORIGINALS:
            ORIGINALS[(inp.session_id, a)] = S.unpack(fmt, ad.read_memory(a, n))[0]
        orig = ORIGINALS[(inp.session_id, a)]
        v = orig * inp.value if inp.scale_original else inp.value
        if inp.type != "f32":
            v = int(round(v))
        data = S.pack(fmt, v)
        if inp.hold:
            getattr(freeze_memory, "__wrapped__", freeze_memory)(FreezeIn(session_id=inp.session_id, address=a, hex_bytes=data.hex()), ctx)
        else:
            ad.write_memory(a, data)
        time.sleep(0.05)
        back = S.unpack(fmt, ad.read_memory(a, n))[0]
        out[hex(a)] = {"original": orig, "now": v, "read_back": back,
                       "verified": abs(back - v) < 1e-4 * max(1, abs(v)) if inp.type == "f32" else back == v}
    return {"result": out, "session_id": inp.session_id}


class ReadMemIn(BaseModel):
    session_id: str
    address: int
    length: int

class ReadMemOut(BaseModel):
    address: int
    length: int
    sha256: str

def _readmem_validate(out: ReadMemOut, arts):
    d = arts.get("memory.bin")
    return [] if d is not None and len(d) == out.length and sha256(d) == out.sha256 else ["memory artifact mismatch"]

@tool("read_memory", "1.0", ReadMemIn, ReadMemOut, capabilities=["runtime", "memory"], artifacts=["memory.bin"],
      validate=_readmem_validate, validation="artifact length/hash match")
def read_memory(inp: ReadMemIn, ctx: Ctx):
    """Read emulated memory from a live session into an artifact."""
    ad, g = SESSIONS[inp.session_id]
    data = ad.read_memory(inp.address, inp.length)
    ctx.artifact("memory.bin", data, game=g["game_id"], address=hex(inp.address))
    return {"address": inp.address, "length": len(data), "sha256": sha256(data)}


class WriteMemIn(BaseModel):
    session_id: str
    address: int
    hex_bytes: str

@tool("write_memory", "1.0", WriteMemIn, SessionOut, capabilities=["runtime", "memory"],
      permissions=[P.MEMORY_WRITE], side_effects=["mutates live emulated memory"])
def write_memory(inp: WriteMemIn, ctx: Ctx):
    """Write emulated memory. Requires explicit memory_write permission."""
    ad, _ = SESSIONS[inp.session_id]
    before = ad.read_memory(inp.address, len(bytes.fromhex(inp.hex_bytes)))
    ctx.artifact("before.bin", before, address=hex(inp.address), note="rollback data")
    return {"result": ad.write_memory(inp.address, bytes.fromhex(inp.hex_bytes)) | {"rollback_hex": before.hex()}}


FREEZES: dict[tuple, threading.Event] = {}


class FreezeIn(BaseModel):
    session_id: str
    address: int
    hex_bytes: str
    enabled: bool = True
    interval_ms: int = 50


@tool("freeze_memory", "1.0", FreezeIn, SessionOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      side_effects=["keeps rewriting live emulated memory until released or the session ends"])
def freeze_memory(inp: FreezeIn, ctx: Ctx):
    """Hold bytes at an address (infinite lives/health/time). enabled=false releases the hold."""
    ad, _ = SESSIONS[inp.session_id]
    key, data = (inp.session_id, inp.address), bytes.fromhex(inp.hex_bytes)
    if (old := FREEZES.pop(key, None)):
        old.set()
    if not inp.enabled:
        return {"result": {"released": hex(inp.address)}, "session_id": inp.session_id}
    before = ad.read_memory(inp.address, len(data))
    ctx.artifact("before.bin", before, address=hex(inp.address), note="rollback data")
    stop = FREEZES[key] = threading.Event()

    def hold():
        while not stop.is_set() and inp.session_id in SESSIONS:
            try:
                ad.write_memory(inp.address, data)
            except Exception:
                pass
            stop.wait(max(inp.interval_ms, 10) / 1000)
    threading.Thread(target=hold, daemon=True).start()
    return {"result": {"frozen": hex(inp.address), "value": inp.hex_bytes, "previous": before.hex(), "every_ms": inp.interval_ms},
            "session_id": inp.session_id}


# ---- cheats: RetroArch's own engine where available, gBox constant-write engine for any memory-capable session ----
GCHEATS: dict[str, list[dict]] = {}


class CheatIn(BaseModel):
    session_id: str
    op: str = "list"                       # list | enable | disable | add | remove | search
    index: int | None = Field(default=None, description="Required for enable/disable: a nonnegative integer cheat index from list. To apply new code lines, use add instead.")
    codes: list[str] = Field(default_factory=list, description="Required for add: nonempty code lines. Add enables the new code immediately. Do not send codes with enable/disable; those operations use index.")
    desc: str = ""
    query: str = ""                        # search: filter descriptions

    @model_validator(mode="before")
    @classmethod
    def validate_operation_arguments(cls, values):
        # Validate before coercion so booleans cannot become cheat index 0/1.
        if isinstance(values, dict):
            validate_cheat_call(values.get("op", "list"), values.get("index"), values.get("codes", []))
        return values

class CheatOut(BaseModel):
    result: dict
    session_id: str


def _gcheat_apply(ad, ops):
    skip = False
    for kind, a, d in ops:
        if skip:
            skip = False
            continue
        if kind == "if":
            skip = ad.read_memory(a, len(d)) != d          # condition false -> skip the next op
        else:
            ad.write_memory(a, d)


def _gcheat_loop(sid: str, c: dict):
    ad, _ = SESSIONS[sid]
    dbg = getattr(ad, "dbg", None)
    while c["on"].is_set() and sid in SESSIONS:
        try:
            if dbg is not None:
                with dbg.paused():                         # one halt for the whole batch on debugger sessions
                    _gcheat_apply(ad, c["ops"])
            else:
                _gcheat_apply(ad, c["ops"])
        except Exception:
            pass
        time.sleep(0.05)


@tool("cheats", "1.0", CheatIn, CheatOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      side_effects=["enables/disables cheat codes in a live session"])
def cheats_tool(inp: CheatIn, ctx: Ctx):
    """List / toggle / add cheat codes for a live session (GameShark, Action Replay, Game Genie, CodeBreaker via the
    emulator; Gecko/AR constant writes and plain ADDRESS=VALUE via gBox)."""
    from . import cheats as C
    ad, g = SESSIONS[inp.session_id]
    if not getattr(ad, "cheats", None) and getattr(ad, "config", None):   # launched without a code list: read the database now
        from pathlib import Path as _P
        hits = C.find(_P(ad.config.data_dir) / "cheatdb" / "libretro-database" / "cht", g.get("platform", ""), g.get("title", ""))
        if hits:
            ad.cheats = [dict(e, enable=False) for e in C.parse_cht(hits[0].read_text(encoding="utf-8", errors="replace"))]
            ad.cheat_source = hits[0].name
    ra = list(getattr(ad, "cheats", []) or [])
    mine = GCHEATS.setdefault(inp.session_id, [])
    if inp.op in ("list", "search"):
        q = inp.query.lower()
        rows = [{"index": i, "desc": e.get("desc", ""), "enabled": e["enable"], "engine": "emulator",
                 "code": e.get("code") or (f"addr {e.get('address')} = {e.get('value')}" if e.get("address") else "")}
                for i, e in enumerate(ra)]
        rows += [{"index": len(ra) + i, "desc": c["desc"], "enabled": c["on"].is_set(), "engine": "gbox",
                  "code": " / ".join(c["lines"])} for i, c in enumerate(mine)]
        if q:
            rows = [r for r in rows if q in r["desc"].lower() or q in r["code"].lower()]
        return {"result": {"source": getattr(ad, "cheat_source", None), "count": len(rows), "cheats": rows[:400]},
                "session_id": inp.session_id}
    if inp.op == "add":
        ops, bad = C.decode(g.get("platform", ""), "\n".join(inp.codes))
        if not ops:
            raise ValueError(f"no code lines gBox can apply itself for {g.get('platform')}: {bad}")
        import threading as _t
        c = {"desc": inp.desc or "custom code", "lines": inp.codes, "ops": ops, "unsupported": bad, "on": _t.Event()}
        before = [{"address": hex(a), "bytes": ad.read_memory(a, len(d)).hex()} for k, a, d in ops[:64] if k == "w"]
        ctx.artifact("cheat_before.json", json.dumps(before).encode(), "application/json", note="rollback data", desc=c["desc"])
        mine.append(c)
        c["on"].set()
        _t.Thread(target=_gcheat_loop, args=(inp.session_id, c), daemon=True).start()
        return {"result": {"index": len(ra) + len(mine) - 1, "enabled": True, "ops": len(ops), "unsupported": bad},
                "session_id": inp.session_id}
    if inp.op in ("enable", "disable"):
        on = inp.op == "enable"
        if inp.index is None:
            raise ValueError("index required")
        if inp.index < len(ra):
            e = ra[inp.index]
            ops, bad = C.decode(g.get("platform", ""), e.get("code", "")) if e.get("code") else ([], ["no code"])
            if ops and not bad:                          # gBox can apply this code itself: verified writes on any core
                import threading as _t
                key = f"db{inp.index}"
                c = next((x for x in mine if x.get("key") == key), None)
                if c is None:
                    c = {"key": key, "desc": e.get("desc", ""), "lines": [e["code"]], "ops": ops, "unsupported": [], "on": _t.Event()}
                    mine.append(c)
                if on and not c["on"].is_set():
                    c["on"].set()
                    _t.Thread(target=_gcheat_loop, args=(inp.session_id, c), daemon=True).start()
                elif not on:
                    c["on"].clear()
                e["enable"] = on
                return {"result": {"index": inp.index, "enabled": on, "engine": "gbox", "desc": e.get("desc")},
                        "session_id": inp.session_id}
            return {"result": ad.cheat_set(inp.index, on) | {"engine": "emulator"}, "session_id": inp.session_id}
        c = mine[inp.index - len(ra)]
        if on and not c["on"].is_set():
            import threading as _t
            c["on"].set()
            _t.Thread(target=_gcheat_loop, args=(inp.session_id, c), daemon=True).start()
        elif not on:
            c["on"].clear()
        return {"result": {"index": inp.index, "enabled": on, "desc": c["desc"]}, "session_id": inp.session_id}
    raise ValueError(f"unknown op {inp.op}")


class FrameIn(BaseModel):
    session_id: str | None = None          # grab that session's display; default: host desktop
    region: list[int] | None = None        # x, y, w, h on the host desktop

class FrameOut(BaseModel):
    width: int
    height: int
    sha256: str
    mean_luma: float | None = None         # 0-255; ~0 means a black screen (content not drawing)
    covered: int = Field(default=0, ge=0, le=9)  # Window occlusion points, when confirmed for this captured PNG.
    capture_source: str | None = None

def _png_validate(out: FrameOut, arts):
    d = arts.get("frame.png", b"")
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        return ["frame.png is not a PNG"]
    w, h = int.from_bytes(d[16:20], "big"), int.from_bytes(d[20:24], "big")
    return [] if (w, h) == (out.width, out.height) and sha256(d) == out.sha256 else ["PNG header/hash mismatch"]

@tool("get_frame", "1.1", FrameIn, FrameOut, capabilities=["video"], artifacts=["frame.png"],
      validate=_png_validate, validation="PNG signature + IHDR size + hash",
      check=lambda c: None if shutil.which("ffmpeg") else "ffmpeg not on PATH")
def get_frame(inp: FrameIn, ctx: Ctx):
    """Capture one frame of a session display or the host desktop via ffmpeg (x11grab / gdigrab)."""
    capture = {'covered': 0}
    if inp.session_id:
        ad, g = SESSIONS[inp.session_id]
        d = ad.get_frame()
        if HOST_OS == 'windows':
            state = adapters.win_grab_state()
            pid = getattr(getattr(ad, 'proc', None), 'pid', None)
            # win_grab_state is shared: accept only metadata for the exact returned PNG and current emulator PID.
            if pid and state.get('pid') == pid and state.get('sha256') == sha256(d):
                covered = state.get('covered')
                if type(covered) is int and 0 <= covered <= 9:
                    capture['covered'] = covered
                    capture['capture_source'] = state.get('source')
        ctx.artifact("frame.png", d, "image/png", session=inp.session_id, game=g["game_id"], **capture)
    else:
        d = adapters.grab_png(None, inp.region)
        ctx.artifact("frame.png", d, "image/png", **capture)
    return {"width": int.from_bytes(d[16:20], "big"), "height": int.from_bytes(d[20:24], "big"), "sha256": sha256(d),
            "mean_luma": mean_luma(d), **capture}


def mean_luma(png: bytes) -> float | None:
    """Average brightness via ffmpeg signalstats (no imaging library needed)."""
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "f.png"
        f.write_bytes(png)
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                            "-f", "null", "-"], capture_output=True, text=True, timeout=30)
    for ln in (r.stdout + r.stderr).splitlines():
        if "YAVG=" in ln:
            return round(float(ln.split("YAVG=")[1]), 2)
    return None


# --- assets ---------------------------------------------------------------------------------

class UapIn(BaseModel):
    package_dir: str
    formats: list[str] = ["gltf", "obj"]

class UapOut(BaseModel):
    problems: list[str]
    stats: dict
    exported: dict[str, str]               # format -> artifact sha256

def _uap_validate(out: UapOut, arts):
    p = [] if not out.problems else ["package has validation problems"]
    if "model.gltf" in arts:                # independent round-trip: decode positions back out
        g = json.loads(arts["model.gltf"])
        if g.get("asset", {}).get("version") != "2.0":
            p.append("glTF asset.version != 2.0")
        n = sum(len(uap.read_accessor(g, m["primitives"][0]["attributes"]["POSITION"])) for m in g.get("meshes", []))
        if n != out.stats.get("vertices"):
            p.append(f"glTF round-trip vertex count {n} != {out.stats.get('vertices')}")
    return p

@tool("export_asset", "1.0", UapIn, UapOut, capabilities=["asset", "convert"], artifacts=["model.gltf", "model.obj"],
      validate=_uap_validate, validation="UAP validator + glTF round-trip vertex count")
def export_asset(inp: UapIn, ctx: Ctx):
    """Validate a UAP package and export it to glTF 2.0 / OBJ."""
    pkg = Path(inp.package_dir)
    m = uap.load(pkg)
    problems, exported = uap.validate(m, pkg), {}
    prov = {"uap": m.name, "source": m.source}
    if not problems:
        if "gltf" in inp.formats:
            d = json.dumps(uap.to_gltf(m)).encode()
            ctx.artifact("model.gltf", d, "model/gltf+json", **prov)
            exported["gltf"] = sha256(d)
        if "obj" in inp.formats:
            d = uap.to_obj(m).encode()
            ctx.artifact("model.obj", d, "model/obj", **prov)
            exported["obj"] = sha256(d)
    return {"problems": problems, "stats": uap.stats(m), "exported": exported}


class UScriptIn(BaseModel):
    path: str                              # a UE3 game folder (finds Cooked*/), or one package (.xxx/.upk/.u)
    op: str = "summary"                    # summary | members | disasm | search
    cls: str = ""                          # members: class name
    function: str = ""                     # disasm: Class.Function (or Class.State.Function)
    query: str = ""                        # search: regex over member names and disassembled script

class UScriptOut(BaseModel):
    result: dict


@functools.lru_cache(maxsize=64)
def _ue3_pkg(path: str):
    from . import ue3
    return ue3.Package(path)


def _ue3_files(path: str) -> list[str]:
    p = Path(path)
    if p.is_file():
        return [str(p)]
    pk = [x for x in p.rglob("*") if x.suffix.lower() in (".xxx", ".upk", ".u") and x.parent.name.lower().startswith("cooked")]
    def script_pkg(x):                                     # cooked script packages are stored fully compressed
        with open(x, "rb") as f:                           # (block size where a raw package has its version)
            h = f.read(8)
        return x.suffix.lower() == ".u" or (len(h) == 8 and h[4:8] == bytes([0, 1, 0, 0]))
    return sorted(str(x) for x in pk if script_pkg(x))


@tool("unreal_script", "1.0", UScriptIn, UScriptOut, capabilities=["analysis", "re"], timeout_s=900)
def unreal_script(inp: UScriptIn, ctx: Ctx):
    """Unreal Engine 3 script explorer (cooked console packages): classes, members (functions/states/properties with
    native vs script), UnrealScript bytecode disassembly, and regex search across every script function."""
    from . import ue3
    files = _ue3_files(inp.path)
    if not files:
        raise ValueError(f"no UE3 packages under {inp.path}")
    pkgs = []
    for f in files:
        try:
            pkgs.append((Path(f).stem, _ue3_pkg(f)))
        except Exception:
            pass                                           # non-script / unsupported compression
    if inp.op == "summary":
        return {"result": {"packages": [{"name": n, "version": p.version, "licensee": p.licensee, "classes": len(p.members())}
                                        for n, p in pkgs]}}

    def funcs(p):
        for i, e in enumerate(p.exports, 1):
            if e["class"] and p.ref(e["class"])[1] == "Function":
                yield i, p.path(i)

    def listing(p, i):
        try:
            code, flags = ue3.function_script(p, i)
        except ValueError:
            return None, "native (no script body)"
        return flags, "\n".join(ue3.disassemble(p, code))

    if inp.op == "members":
        for n, p in pkgs:
            m = p.members().get(inp.cls)
            if m is not None:
                kinds = {}
                for k, name in m:
                    kinds.setdefault(k, []).append(name)
                return {"result": {"package": n, "class": inp.cls, "members": kinds}}
        raise ValueError(f"class {inp.cls} not found")
    if inp.op == "disasm":
        for n, p in pkgs:
            for i, path in funcs(p):
                if path == inp.function:
                    flags, text = listing(p, i)
                    return {"result": {"package": n, "function": path, "flags": flags and hex(flags), "script": text}}
        raise ValueError(f"function {inp.function} not found")
    if inp.op == "search":
        rx, hits = re.compile(inp.query, re.I), []
        for n, p in pkgs:
            for i, path in funcs(p):
                _, text = listing(p, i)
                lines = [ln for ln in text.splitlines() if rx.search(ln)]
                if rx.search(path) or lines:
                    hits.append({"function": f"{n}:{path}", "lines": lines[:8]})
                if len(hits) >= 80:
                    return {"result": {"hits": hits, "truncated": True}}
        return {"result": {"hits": hits}}
    raise ValueError(f"unknown op {inp.op}")


class ScriptPatchIn(BaseModel):
    session_id: str
    op: str = "status"                     # status | locate | preset | revert
    preset: str = ""                       # preset name from the game profile's script_patches (e.g. hit / miss / off)

class ScriptPatchOut(BaseModel):
    result: dict

USCRIPT: dict[str, dict] = {}              # session -> {"where": {fn: addr}, "orig": {addr: bytes}, "active": preset}


def _guard(sid: str):
    """While a preset is on, check every 5 s that the patched bytes are still in place. A save-state load/restart
    (F2/F4 pressed in the game or asked by voice) reloads the script: then locate it again and re-apply."""
    import types
    f = getattr(script_patch, "__wrapped__", script_patch)
    quiet = types.SimpleNamespace(progress=lambda *a: None)
    while sid in SESSIONS:
        time.sleep(5)
        st = USCRIPT.get(sid)
        if not st or st.get("want", "off") == "off":
            break
        ad, _ = SESSIONS.get(sid, (None, None))
        try:
            intact = st["active"] != "off" and all(ad.read_memory(a, len(b)) == b for a, b in st.get("patched", {}).items())
        except Exception:
            intact = False
        if not intact:
            st.update(where={}, orig={}, patched={}, active="off")
            try:
                f(ScriptPatchIn(session_id=sid, op="status"), quiet)      # status re-applies st["want"]
            except Exception:
                pass                                       # still reloading: try again next round
    if sid in USCRIPT:
        USCRIPT[sid]["guard"] = False


# guest ranges where a PS3 game's heap lives (main memory, then the 0x30000000 user region)
PS3_HEAP = [(0x00010000, 0x10000000), (0x30000000, 0x40000000)]


@tool("script_patch", "1.0", ScriptPatchIn, ScriptPatchOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      side_effects=["rewrites UnrealScript bytecode in a live session (reverted by op=revert/off or on stop)"])
def script_patch(inp: ScriptPatchIn, ctx: Ctx):
    """Live UnrealScript patches from a game profile: locate the profile's functions in RAM (by their bytecode from
    the disc), then apply a named preset (same-length bytecode edits) or revert to the original bytes."""
    from . import semantic, ue3
    ad, g = SESSIONS[inp.session_id]
    prof = next((p for p in semantic.load_profiles() if p.get("script_patches") and p["match"].get("platform") == g.get("platform")
                 and (g.get("serial") in p["match"].get("serial", []) or any(s in (g.get("_rom_path") or "") for s in p["match"].get("serial", [])))), None)
    if not prof:
        raise ValueError(f"no script-patch profile for {g.get('title')} ({g.get('serial')})")
    sp, st = prof["script_patches"], USCRIPT.setdefault(inp.session_id, {"where": {}, "orig": {}, "active": "off"})
    if st.get("gen", 0) != getattr(ad, "generation", 0):   # the game reloaded (save state): addresses and patches are gone
        st.update(want=st["active"] if st["active"] != "off" else st.get("want", "off"), where={}, orig={}, active="off",
                  gen=getattr(ad, "generation", 0))
    if inp.op == "status" and st["active"] == "off" and st.get("want", "off") != "off":
        inp.op, inp.preset = "preset", st["want"]          # re-apply what the operator had on before the reload

    def restore():
        for a, b in st["orig"].items():
            ad.write_memory(a, b)
        st["orig"].clear()
        st["patched"] = {}
        st["active"] = "off"

    if inp.op in ("locate", "preset") and len(st["where"]) < len(sp["functions"]):
        usr = Path(g["_rom_path"]).parent                  # .../PS3_GAME/USRDIR/EBOOT.BIN
        pkg = _ue3_pkg(next(f for f in _ue3_files(str(usr)) if Path(f).stem == sp["package"]))
        pats = {}
        for key, fn in sp["functions"].items():
            i = next(i for i, e in enumerate(pkg.exports, 1) if e["outer"] > 0 and f"{pkg.path(e['outer'])}.{e['name']}" == fn)
            pats[key] = ue3.ram_pattern(pkg, ue3.function_script(pkg, i)[0])
        ctx.progress(10, "searching game memory for the script functions")
        chunk, over = 1 << 20, 4096
        spans = ad.regions() if hasattr(ad, "regions") else [(lo, hi - lo) for lo, hi in PS3_HEAP]
        for lo, size in spans:
            for a in range(lo, lo + size, chunk):
                try:
                    buf = ad.read_memory(a, min(chunk + over, lo + size - a))
                except Exception:
                    continue
                for key, rx in pats.items():
                    if key not in st["where"] and (m := rx.search(buf)):
                        st["where"][key] = a + m.start()
                if len(st["where"]) == len(pats):
                    break
            if len(st["where"]) == len(pats):
                break
        if len(st["where"]) < len(pats):
            raise RuntimeError(f"found {sorted(st['where'])} of {sorted(pats)} in RAM: is the game past its title screen?")
    if inp.op == "preset":
        if inp.preset not in sp["presets"]:
            raise ValueError(f"presets: {sorted(sp['presets'])}")
        restore()
        for e in sp["presets"][inp.preset]:
            a = st["where"][e["fn"]] + int(e["offset"], 16)
            new = bytes.fromhex(e["hex"])
            st["orig"][a] = ad.read_memory(a, len(new))
            ad.write_memory(a, new)
        st["active"] = st["want"] = inp.preset
        st["patched"] = {st["where"][e["fn"]] + int(e["offset"], 16): bytes.fromhex(e["hex"]) for e in sp["presets"][inp.preset]}
        if not st.get("guard") and inp.preset != "off":
            st["guard"] = True
            threading.Thread(target=_guard, args=(inp.session_id,), daemon=True).start()
    elif inp.op == "revert":
        restore()
        st["want"] = "off"
    return {"result": {"profile": prof["id"], "active": st["active"], "functions": {k: hex(v) for k, v in st["where"].items()},
                       "presets": {k: [e.get("why") for e in v] for k, v in sp["presets"].items()}}}


class AutoplayIn(BaseModel):
    session_id: str = ""
    op: str = "status"                     # list | start | stop | status
    mission: str = ""                      # mission name; empty = take over from wherever the player is right now
    goal: str = ""                         # games without missions: what to do ("make progress", "win this race"...)
    record: bool = False
    assist: bool = False                   # hold the player's HP while gBox plays (opt-in, released when it stops)

class AutoplayOut(BaseModel):
    result: dict

AUTOPLAY: dict[str, dict] = {}             # session_id -> {driver, thread, mission, result}
MISSIONS = Path(__file__).resolve().parent.parent / "profiles" / "missions"


def _missions(game_id=None):
    out = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(MISSIONS.glob("*.json"))]
    return [m for m in out if not game_id or m.get("game_id") == game_id]


@tool("autoplay", "1.0", AutoplayIn, AutoplayOut, capabilities=["runtime"], timeout_s=60)
def autoplay(inp: AutoplayIn, ctx: Ctx):
    """Let gBox play the live game (take control): runs a scripted mission (navigate / interact / fight) through the
    session's debugger. op=start | stop (hand control back) | status | list."""
    from .autoplay import Driver
    game_id = None
    if inp.session_id:
        r = httpx.get(f"{ctx.server}/api/sessions", headers=ctx.headers, timeout=30)
        game_id = next((s.get("game_id") for s in r.json() if s["session_id"] == inp.session_id), None)
    if inp.op == "list":
        return {"result": {"missions": [{"name": m["name"], "objective": m.get("objective"), "game_id": m.get("game_id")}
                                        for m in _missions(game_id)]}}
    run = AUTOPLAY.get(inp.session_id)
    if inp.op == "stop":
        if run:
            run["driver"].stopped = True
        _release_all(inp.session_id)                           # never leave a direction held: the character would keep running
        return {"result": {"stopped": bool(run), "mission": run and run["mission"]}}
    if inp.op == "status":
        return {"result": {"running": bool(run and run["thread"].is_alive()), "mission": run and run["mission"],
                           "last": run and run.get("result"), "steps": run and len(run["driver"].trace)}}
    if inp.op != "start":
        raise ValueError(f"unknown op {inp.op}")
    if run and run["thread"].is_alive():
        return {"result": {"already_running": run["mission"]}}
    d = Driver(ctx.server, ctx.headers["authorization"].split()[-1], inp.session_id, log=lambda *a: None)
    d.assist_hold_hp = inp.assist
    ad, g = SESSIONS[inp.session_id]
    m = None
    if inp.mission:
        m = next((x for x in _missions() if x["name"] == inp.mission), None)
    elif _missions(game_id):
        m = _takeover_mission(d, g, game_id)                   # continue from where the player is right now
    if m is None:                                              # any other game: watch the screen, decide, press
        run = AUTOPLAY[inp.session_id] = {"driver": d, "mission": "vision: " + (inp.goal or "make progress")}
        run["thread"] = threading.Thread(target=_vision_play, args=(run, ad, g, inp.goal, ctx.server), daemon=True)
        run["thread"].start()
        return {"result": {"started": run["mission"], "objective": "vision autoplay (any game): screen -> model -> buttons"}}
    run = AUTOPLAY[inp.session_id] = {"driver": d, "mission": m["name"]}
    cache = ctx.config.runtime / "autoplay"
    cache.mkdir(parents=True, exist_ok=True)

    def go():                                              # missions chain with "then" (e.g. Pioneer 2 -> Forest 1 battle)
        cur = m
        while cur:
            run["mission"] = cur["name"]
            try:
                run["result"] = {k: v for k, v in d.run_mission(cur, cache_dir=str(cache), record=inp.record).items() if k != "steps"}
            except Exception as e:
                run["result"] = {"ok": False, "error": str(e)}
            if not run["result"].get("ok") or d.stopped:
                break
        if getattr(d, "_assist_release", None):                  # stopped / failed mid-run: never leave HP held
            d._assist_release()
            cur = next((x for x in _missions() if x["name"] == cur.get("then")), None)
    run["thread"] = threading.Thread(target=go, daemon=True)
    run["thread"].start()
    return {"result": {"started": m["name"], "objective": m.get("objective")}}


class InvIn(BaseModel):
    session_id: str
    op: str = "list"                       # list | equip | give | set | meseta
    code: str = ""                         # item code hex, e.g. 000105 (DB's Saber), 010101 (Armor), 030000 (Monomate)
    value: int | None = None               # meseta: amount (max 999999)
    slot: int | None = None                # set: overwrite this slot
    count: int = 1                         # give: stack size for tools

class InvOut(BaseModel):
    result: dict

INV: dict[str, int] = {}


@tool("pso_inventory", "1.0", InvIn, InvOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=600)
def pso_inventory(inp: InvIn, ctx: Ctx):
    """Phantasy Star Online inventory in RAM (Dreamcast v2 and GameCube Episode I & II): list it, equip any weapon/frame/
    barrier/unit/mag (replaces what's equipped in that category, keeping the item's id) or give any item into a free slot."""
    from . import psoitems
    ad, g = SESSIONS[inp.session_id]
    plat = g.get("platform")
    if plat not in ("dreamcast", "gamecube"):
        raise Unsupported("the item sidebar knows the Dreamcast v2 and GameCube inventories")
    if inp.op == "meseta":
        if plat != "dreamcast":
            raise Unsupported("meseta is mapped for PSO Ver.2 Dreamcast only so far")
        # live value: TObjPlayer (*(u32*)0x8C42D92C) + 0xC20, verified 2026-10-06 against the in-game menu
        pl = struct.unpack("<I", ad.read_memory(0x8C42D92C, 4))[0]
        if not 0x8C000000 <= pl < 0x8D000000:
            raise RuntimeError("no player object yet (title screen / loading) - try again in game")
        before = struct.unpack("<I", ad.read_memory(pl + 0xC20, 4))[0]
        v = max(0, min(999999, 999999 if inp.value is None else inp.value))
        ad.write_memory(pl + 0xC20, struct.pack("<I", v))
        now = struct.unpack("<I", ad.read_memory(pl + 0xC20, 4))[0]
        return {"result": {"meseta": now, "was": before, "verified": now == v}}
    E, version = ("<", "dcv2") if plat == "dreamcast" else (">", "gc")
    base = INV.get(inp.session_id)
    if base is None or ad.read_memory(base, 8)[:4] not in (struct.pack(f"{E}I", 1), b"\0\0\0\0"):
        ctx.progress(10, "finding the inventory in RAM")
        lo, size = MAIN_RAM[plat][0]
        for o in range(lo, lo + size, 1 << 20):
            try:
                blk = ad.read_memory(o, min((1 << 20) + psoitems.SLOT * psoitems.SLOTS, lo + size - o))
            except Exception:
                continue
            a = psoitems.find_inventory(blk, o, E)
            if a:
                base = INV[inp.session_id] = a
                break
        if base is None:
            raise RuntimeError("inventory not found (equip a weapon first, then retry)")
    raw = ad.read_memory(base, psoitems.SLOT * psoitems.SLOTS)
    slots = [psoitems.decode_slot(raw[i * psoitems.SLOT:(i + 1) * psoitems.SLOT], E) for i in range(psoitems.SLOTS)]
    cat = {}
    try:
        cat = {i["code"]: i["name"] for i in httpx.get(f"{ctx.server}/api/pso/items", params={"version": version},
                                                        headers=ctx.headers, timeout=60).json()}
    except Exception:
        pass
    changed = None
    if inp.op in ("equip", "give", "set"):
        code = bytes.fromhex(inp.code)
        if len(code) != 3:
            raise ValueError("code = 3 bytes hex, e.g. 000105")
        data = bytearray(12)
        data[0:3] = code
        if code[0] == 3:
            data[5] = max(1, min(10, inp.count)) if code[1] in (0, 1, 3, 4, 5, 6, 7, 8, 9, 10) else 0
        if inp.op == "set" and inp.slot is not None:
            i = inp.slot
        elif inp.op == "equip":
            if code[0] == 3:
                raise ValueError("tools can't be equipped; use give")
            same = lambda s: s["equipped"] and (s["code"][:2] == "00" if code[0] == 0 else s["code"][:4] == code[:2].hex() if code[0] == 1
                                                 else s["code"][:2] == "02")
            i = next((k for k, s in enumerate(slots) if s["present"] and same(s)), None)
            if i is None:
                raise RuntimeError("nothing equipped in that category; give the item instead")
        else:
            i = next((k for k, s in enumerate(slots) if not s["present"]), None)
            if i is None:
                raise RuntimeError("inventory is full (30 items)")
            new_id = max([s["id"] for s in slots if s["present"]] + [0x10000]) + 1
            ad.write_memory(base + i * psoitems.SLOT, struct.pack(f"{E}II", 1, 0) + bytes(data) + struct.pack(f"{E}I", new_id) + b"\0" * 4)
            n = ad.read_memory(base - 4, 1)[0]
            ad.write_memory(base - 4, bytes([min(30, n + 1)]))
            changed = i
        if changed is None:
            old = raw[i * psoitems.SLOT + 8:i * psoitems.SLOT + 24]          # item data + id as the game's objects hold them
            ad.write_memory(base + i * psoitems.SLOT + 8, bytes(data))
            changed = i
            # the game draws/uses live item objects built from the inventory: patch the one with this item id too
            lo, size = MAIN_RAM[plat][0]
            for o in range(lo, lo + size, 1 << 20):
                try:
                    blk = ad.read_memory(o, min((1 << 20) + 16, lo + size - o))
                except Exception:
                    continue
                k = blk.find(old)
                while 0 <= k < (1 << 20):
                    if o + k != base + i * psoitems.SLOT + 8:
                        ad.write_memory(o + k, bytes(data))
                    k = blk.find(old, k + 4)
        raw = ad.read_memory(base, psoitems.SLOT * psoitems.SLOTS)
        slots = [psoitems.decode_slot(raw[k * psoitems.SLOT:(k + 1) * psoitems.SLOT], E) for k in range(psoitems.SLOTS)]
    items = [{"slot": k, **s, "name": cat.get(s["code"], s["code"])} for k, s in enumerate(slots) if s["present"]]
    return {"result": {"inventory_at": hex(base), "items": items, "changed_slot": changed,
                       "note": "Open the item menu (or change area) to see the change; equipped stats refresh on re-equip."}}


class OotIn(BaseModel):
    session_id: str
    op: str = "state"                      # state | skip_deku_tree | goto | give | kit | scale
    place: str = ""                        # goto: "end of the shadow temple", "final battle", "gohma", "kakariko"...
    item: str = ""                         # give: "hookshot", "longshot", "bow"...
    c_button: int = 0                      # give: also put it on C-left/down/right (1-3)
    kit: str = ""                          # kit: child | adult | endgame
    factor: float = 1.0                    # scale: Link's size multiplier (2 = twice as big)
    cutscene: bool = False                 # skip_deku_tree: play the Deku Tree farewell cutscene


class OotOut(BaseModel):
    result: dict


@tool("zelda_oot", "1.0", OotIn, OotOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=180)
def zelda_oot(inp: OotIn, ctx: Ctx):
    """Zelda: Ocarina of Time (N64 USA 1.0 / 1.1 / 1.2) on a live session: skip the Deku Tree, warp anywhere (dungeons, boss rooms,
    the final battle) with the gear for it, give/equip items, resize Link. Warps are guarded: a save state is taken first
    and reloaded automatically if the game hangs; the result says whether the warp landed."""
    import struct as _s
    from . import oot
    ad, g = SESSIONS[inp.session_id]
    oot.check(ad)
    if inp.op == "state":
        return {"result": oot.state(ad)}
    if inp.op == "give":
        r = oot.give(ad, inp.item, inp.c_button or None)
        if inp.c_button:
            r["note"] = "the C-button icon draws after the next area load (goto the current place to refresh it now)"
        return {"result": r}
    if inp.op == "kit":
        return {"result": oot.kit(ad, inp.kit or "adult")}
    if inp.op == "full_inventory":
        return {"result": oot.full_inventory(ad)}
    if inp.op == "scale":
        pl = _s.unpack(">I", oot._rd(ad, oot.play(ad) + 0x1C44, 4))[0]
        if not pl:
            raise RuntimeError("no Link actor right now (title screen / scene loading)")
        oot._wr(ad, pl + 0x50, _s.pack(">3f", *[0.01 * inp.factor] * 3))
        got = _s.unpack(">f", oot._rd(ad, pl + 0x50, 4))[0]
        return {"result": {"scale": inp.factor, "verified": abs(got - 0.01 * inp.factor) < 1e-6,
                           "note": "resets when Link is re-created (scene change); hold it with freeze/cheats if needed"}}
    if inp.op not in ("skip_deku_tree", "goto"):
        raise ValueError("op: state | skip_deku_tree | goto | give | kit | full_inventory | scale")
    if not oot.wait_gameplay(ad, 45):
        return {"result": {"landed": False, "note": "a cutscene or dialog is running: advance it (A) and ask again - warping mid-cutscene hangs the game"}}
    slot = 9
    try:
        ad.save_state(slot)                                     # undo point if the warp hangs the game
    except Exception:
        slot = None
    out = {}
    for attempt in range(3):                                    # warps are ignored during cutscenes/fades: retry
        out = oot.skip_deku_tree(ad, inp.cutscene) if inp.op == "skip_deku_tree" else oot.goto(ad, inp.place)
        out.pop("state", None)
        live = oot.alive(ad, 8)
        landed = oot.state(ad)["entrance"] == out.get("warp")
        if not live:
            if slot is not None:
                ad.load_state(slot)
            return {"result": {**out, "landed": False, "hung": True, "restored": slot is not None,
                               "note": "the game hung on this warp; the pre-warp save state was reloaded"}}
        if landed:
            return {"result": {**out, "landed": True, "attempts": attempt + 1, "state": oot.state(ad)}}
        time.sleep(4)
    return {"result": {**out, "landed": False, "note": "the game ignored the warp (cutscene/menu running) - try again in gameplay"}}


class DropsIn(BaseModel):
    session_id: str
    op: str = "status"                     # status | scale | all_rare | item | restore
    factor: float = 2.0                    # scale: 2 = double every rare rate, 3 = triple...
    code: str = ""                         # item: this item (code hex, e.g. 000105) drops from every enemy / box
    boxes: bool = True                     # also boxes' rare drops

class DropsOut(BaseModel):
    result: dict

DROPS: dict[str, dict] = {}


def rare_rate(p: int) -> float:
    """PSO packed rare probability byte -> chance per kill (newserv expand_rate / 2^32)."""
    return ((2 << max(0, ((p >> 3) & 0x1F) - 4)) * ((p & 7) + 7)) / 2**32


def rare_byte(rate: float) -> int:
    """Closest packed byte for a chance (capped at the format's max, ~87.5%)."""
    return min(range(1, 256), key=lambda p: abs(rare_rate(p) - rate))


@tool("pso_drops", "1.0", DropsIn, DropsOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=900)
def pso_drops(inp: DropsIn, ctx: Ctx):
    """Phantasy Star Online rare drops on a live session: finds the game's rare tables (ItemRT) in RAM by content and
    rewrites their probability bytes. op=scale factor=2|3|... (double/triple rare rates), all_rare (every rare slot at the
    format's maximum, ~87.5% per eligible kill/box), restore (original bytes), status."""
    from . import semantic
    ad, g = SESSIONS[inp.session_id]
    prof = next((pr for pr in semantic.load_profiles() if pr.get("drop_tables") and pr["match"].get("platform") == g.get("platform")
                 and pr["match"].get("title_contains", "").lower() in (g.get("title") or "").lower()), None)
    if not prof:
        raise Unsupported(f"no PSO drop-table profile for {g.get('title')} ({g.get('platform')}) yet")
    dt = prof["drop_tables"]
    st = DROPS.setdefault(inp.session_id, {"found": None, "orig": {}, "mode": "original"})
    if st["found"] is None or inp.op == "status":
        r = httpx.get(f"{ctx.server}/api/artifacts/{dt['itemrt_afs']}", headers=ctx.headers, timeout=120)
        r.raise_for_status()
        afs, n = r.content, int.from_bytes(r.content[4:8], "little")
        ents = [afs[o:o + s] for o, s in (struct.unpack_from("<II", afs, 8 + 8 * i) for i in range(n))]
        sig = {e[:dt["box_areas_at"]]: i for i, e in enumerate(ents)}
        found = {}
        ctx.progress(10, "scanning RAM for the rare tables")
        for base, size in MAIN_RAM.get(g.get("platform"), []):
            for o in range(base, base + size, 1 << 20):
                try:
                    blk = ad.read_memory(o, min((1 << 20) + dt["rt_entry"], base + size - o))
                except Exception:
                    continue
                for key, idx in sig.items():
                    k = blk.find(key)
                    while 0 <= k < (1 << 20):
                        found[o + k] = idx
                        k = blk.find(key, k + 4)
        st["found"] = found
    found = st["found"]
    if not found and inp.op != "status":
        raise RuntimeError("the rare tables are not in RAM right now (they load with a game/quest); start a game, then retry")
    E, M, BA, B = dt["rt_entry"], dt["monster_slots"], dt["box_rares_at"], dt["box_slots"]

    def slots(tbl):
        return [4 * i for i in range(M)] + ([BA + 4 * i for i in range(B)] if inp.boxes else [])
    if inp.op == "item" and len(bytes.fromhex(inp.code or "")) != 3:
        raise ValueError("item needs code = 3 bytes hex (look it up with the item list)")
    if inp.op in ("scale", "all_rare", "restore", "item"):
        for a in found:
            cur = bytearray(ad.read_memory(a, E))
            st["orig"].setdefault(a, bytes(cur))
            tbl = bytearray(st["orig"][a])
            if inp.op != "restore":
                if inp.op == "item" and inp.boxes:               # box rares only roll in their slot's area: cover every area
                    for k in range(B):
                        tbl[dt["box_areas_at"] + k] = 1 + k % 15
                for s_ in slots(tbl):
                    if inp.op == "item":                         # every slot: this item at the format's maximum chance
                        tbl[s_] = 0xFF
                        tbl[s_ + 1:s_ + 4] = bytes.fromhex(inp.code)
                    elif tbl[s_] and any(tbl[s_ + 1:s_ + 4]):
                        tbl[s_] = 0xFF if inp.op == "all_rare" else rare_byte(min(1.0, rare_rate(tbl[s_]) * inp.factor))
            ad.write_memory(a, bytes(tbl))
            st.setdefault("last", {})[a] = bytes(tbl)        # what we wrote: read back below to verify
        st["mode"] = {"scale": f"x{inp.factor:g}", "all_rare": "all rare (max)", "restore": "original",
                      "item": f"every drop = {inp.code}"}[inp.op]
    verified = None
    if inp.op in ("scale", "all_rare", "restore", "item") and found:
        bad = [hex(a) for a in found if ad.read_memory(a, E) != st["last"][a]]
        if inp.op == "item":
            want = bytes.fromhex(inp.code)
            bad = [hex(a) for a in found if any(ad.read_memory(a, E)[4 * i + 1:4 * i + 4] != want for i in range(M))]
        verified = {"ok": not bad, "tables_checked": len(found), "mismatched": bad}
    sample = []
    if found:
        a0 = next(iter(found))
        tbl = ad.read_memory(a0, E)
        o = st["orig"].get(a0, tbl)
        sample = [{"slot": i, "item": tbl[4 * i + 1:4 * i + 4].hex(), "rate": f"1/{round(1 / rare_rate(tbl[4 * i]))}",
                   "was": f"1/{round(1 / rare_rate(o[4 * i]))}"} for i in range(M) if tbl[4 * i] and any(tbl[4 * i + 1:4 * i + 4])][:8]
    return {"result": {"tables_in_ram": {hex(a): f"difficulty {i // 10}, section id {i % 10}" for a, i in found.items()},
                       "mode": st["mode"], "sample": sample, "verified_in_ram": verified,
                       "not_yet_verified": "that the game rolls from this copy: confirm by defeating an enemy and checking what drops",
                       "note": "Rare drops roll only when an enemy drops an item at all (its drop-anything rate, ItemPT)."}}


def _takeover_mission(d, g, game_id):
    """Pick the mission that starts where the player stands (PSO: office / Pioneer 2 / a field floor)."""
    try:
        st = d.state()
    except Exception:
        return None
    p = next((e for e in st.get("entities", []) if e["kind"] == "player"), None)
    if not p:
        return None
    ms = {m["name"]: m for m in _missions(game_id)}
    town = any(e["kind"] == "npc" for e in st["entities"])
    if town and p.get("room") == 41 and p["z"] < -1500 and "pso-v2-dc-office-to-forest1" in ms:
        return ms["pso-v2-dc-office-to-forest1"]
    if town and "pso-v2-dc-city-to-forest1" in ms:
        return ms["pso-v2-dc-city-to-forest1"]
    base = next(iter(ms.values()))                             # a field: explore and fight from here
    return {"name": "explore-here", "game_id": game_id, "objective": "explore this floor and fight from where you are",
            "move": base.get("move", "analog"), "attack_key": "y" if g.get("platform") == "dreamcast" else "a",   # measured: RetroPad y = attack, x = chat keyboard
            "interact_key": base.get("interact_key", "a"), "camera_reset_key": base.get("camera_reset_key"), "reach": 18 if g.get("platform") == "dreamcast" else None,
            "right_sign": base.get("right_sign"), "steps": [{"op": "explore", "kills": 999, "timeout": 3600}]}


VISION_PROMPT = """You are playing {title} ({platform}) for the operator. Goal: {goal}.
Look at the screenshot and decide the next inputs. Buttons: up down left right a b x y l r start select (hold time in seconds).
Reply ONLY with JSON: {{"thought": "<short>", "actions": [{{"keys": ["right"], "secs": 0.6}}, {{"keys": ["a"], "secs": 0.1}}]}}"""


def _sid_of(run, ad) -> str:
    return run.get("sid") or next((k for k, v in SESSIONS.items() if v[0] is ad), "")


def _release_all(sid: str) -> None:
    try:
        ad, _ = SESSIONS[sid]
        if "send_input" in ad.supported:
            ad.send_input([{"key": k, "down": False} for k in ("a", "b", "x", "y", "l", "r", "l2", "r2", "l3", "r3", "start", "select", "up", "down",
                                                   "left", "right", "lup", "ldown", "lleft", "lright")])
    except Exception:
        pass


def _vision_play(run, ad, g, goal, server):
    """Universal autoplay: screenshot -> vision model (on the Spark's Ollama) -> button presses, until stopped."""
    import base64
    from urllib.parse import urlparse
    d, host = run["driver"], urlparse(server).hostname
    llm = "http://127.0.0.1:11434/v1" if host in ("127.0.0.1", "localhost") else f"http://{host}:11434/v1"
    run["log"] = []
    from . import padstate
    sid = _sid_of(run, ad)

    def takeover():                                            # the operator grabs the controller: hand control back at once
        while not d.stopped:
            if padstate.player_active(sid):
                d.stopped, run["took_over"] = True, True
                _release_all(sid)
                return
            time.sleep(0.1)
    threading.Thread(target=takeover, daemon=True).start()
    while not d.stopped:
        try:
            png = ad.get_frame()
            r = httpx.post(f"{llm}/chat/completions", timeout=120, json={"model": "qwen2.5vl:7b", "temperature": 0.3, "messages": [
                {"role": "user", "content": [{"type": "text", "text": VISION_PROMPT.format(title=g.get("title"), platform=g.get("platform"),
                                                                                         goal=goal or "make progress in the game")},
                                             {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}).json()
            txt = r["choices"][0]["message"]["content"]
            plan = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
            run["log"] = (run["log"] + [plan.get("thought", "")])[-20:]
            for a in plan.get("actions", [])[:6]:
                if d.stopped:
                    break
                d.hold([k for k in a.get("keys", []) if isinstance(k, str)], max(0.05, min(3.0, float(a.get("secs", 0.2)))))
        except Exception as e:
            run["result"] = {"ok": False, "error": str(e)}
            time.sleep(2)
    run["result"] = {"ok": True, "stopped": True, "thoughts": run.get("log", [])[-5:]}


class MemSearchIn(BaseModel):
    session_id: str
    op: str = "start"                      # start | next | list
    type: str = "u32"                      # u8 | u16 | u32 | f32
    value: float | None = None             # start/next: exact value; start without value = unknown initial value
    cmp: str = "changed"                   # next: eq | ne | changed | unchanged | increased | decreased
    ranges: list[list[int]] = []           # [[address, size], ...]; default = the session's committed memory map

class MemSearchOut(BaseModel):
    result: dict

MSEARCH: dict[str, dict] = {}
# main RAM per platform as the emulators' debuggers address it (cheat searches default to it)
MAIN_RAM = {"gamecube": [[0x80000000, 0x1800000]], "wii": [[0x80000000, 0x1800000], [0x90000000, 0x4000000]],
            "dreamcast": [[0x8C000000, 0x1000000]], "n64": [[0x80000000, 0x800000]], "psx": [[0x80000000, 0x200000]],
            "gba": [[0x02000000, 0x40000], [0x03000000, 0x8000]], "nds": [[0x02000000, 0x400000]], "ps2": [[0x00000000, 0x2000000]]}
BIG_ENDIAN = {"ps3", "gamecube", "wii", "n64", "n64dd", "genesis", "segacd", "sega32x", "saturn", "x68000", "xbox360"}


def _finds(b: bytes, pat: bytes, align: int):
    i = b.find(pat)
    while i >= 0:
        if i % align == 0:
            yield i
        i = b.find(pat, i + 1)


@tool("memory_search", "1.0", MemSearchIn, MemSearchOut, capabilities=["runtime", "memory"], timeout_s=900)
def memory_search(inp: MemSearchIn, ctx: Ctx):
    """Cheat-search style RAM scan on a live session: start (snapshot, optionally = value), then next with
    changed/unchanged/increased/decreased/eq/ne until a few addresses are left (e.g. a 'precision aiming' flag:
    start while not aiming, aim, next changed, stop aiming, next changed, ...)."""
    import struct as S
    ad, g = SESSIONS[inp.session_id]
    w = {"u8": 1, "u16": 2, "u32": 4, "f32": 4}[inp.type]
    fmt = ("<>"[g.get("platform") in BIG_ENDIAN]) + {"u8": "B", "u16": "H", "u32": "I", "f32": "f"}[inp.type]

    def val(b, i):
        return S.unpack_from(fmt, b, i)[0]

    st = MSEARCH.get(inp.session_id)
    if inp.op == "start":
        ranges = inp.ranges or (ad.regions() if hasattr(ad, "regions") else MAIN_RAM.get(g.get("platform"), []))
        if not ranges:
            raise ValueError("give ranges=[[address, size]] for this emulator")
        blocks = []
        for a, n in ranges:
            for o in range(a, a + n, 1 << 20):
                try:
                    blocks.append((o, ad.read_memory(o, min(1 << 20, a + n - o))))
                except Exception:
                    pass
        st = MSEARCH[inp.session_id] = {"fmt": fmt, "w": w, "cands": None, "blocks": blocks}
        total = sum(len(b) for _, b in blocks)
        if inp.value is not None:
            pat = S.pack(fmt, inp.value if inp.type == "f32" else int(inp.value))
            st["cands"] = [(a + i, val(b, i)) for a, b in blocks for i in _finds(b, pat, w)]
            st["blocks"] = None
        return {"result": {"scanned_mb": round(total / 2**20, 1),
                           "candidates": len(st["cands"]) if st["cands"] is not None else total // w}}
    if not st or st["fmt"] != fmt:
        raise ValueError("op=start first (with the same type)")
    if inp.op == "next":
        def keep(old, new):
            return {"eq": new == inp.value, "ne": new != inp.value, "changed": new != old, "unchanged": new == old,
                    "increased": new > old, "decreased": new < old}[inp.cmp]
        if st["cands"] is None:                            # first comparison against the full snapshot
            if inp.cmp not in ("changed", "increased", "decreased"):
                raise ValueError("from an unknown start, filter with changed/increased/decreased first")
            cands = []
            for a, old in st["blocks"]:
                try:
                    new = ad.read_memory(a, len(old))
                except Exception:
                    continue
                for k in range(0, len(old), 4096):
                    if old[k:k + 4096] == new[k:k + 4096]:
                        continue                           # untouched block: nothing in it changed
                    for i in range(k, min(k + 4096, len(old)) - w + 1, w):
                        if keep(val(old, i), n := val(new, i)):
                            cands.append((a + i, n))
            st["cands"], st["blocks"] = cands, None
        else:
            cands, blk, buf = [], None, b""
            for a, old in st["cands"]:                     # sorted by address: one read per 1 MiB block
                if a >> 20 != blk:
                    blk = a >> 20
                    try:
                        buf = ad.read_memory(blk << 20, 1 << 20)
                    except Exception:
                        buf = None                         # block straddles unmapped memory: read singly
                try:
                    n = val(buf, a - (blk << 20)) if buf is not None else val(ad.read_memory(a, w), 0)
                except Exception:
                    continue
                if keep(old, n):
                    cands.append((a, n))
            st["cands"] = cands
    c = st["cands"] or []
    return {"result": {"candidates": len(c), "sample": [{"address": hex(a), "value": v} for a, v in c[:40]]}}


class LinkIn(BaseModel):
    op: str = "start"                      # start | stop | status
    host: str = ""                         # session whose moment triggers the minigame (e.g. Stranglehold)
    guest: str = ""                        # minigame session (e.g. Puyo Puyo Tetris, parked on a save state of the match)
    # watch specs: {"address": "0x..", "type": "u8|u16|u32|f32", "eq"|"ne"|"lt"|"gt": value}
    trigger: dict = {}                     # host: when true, a shot/moment starts
    win: dict = {}                         # guest: when true, the player won the match
    lose: dict = {}                        # guest: when true, the player lost
    on_win: str = "god_hit"                # host script_patch preset for a win
    on_lose: str = "god_miss"              # ... and for a loss
    poll_s: float = 0.1
    style: str = "pause"                   # pause: freeze the host | overlay: host keeps running in slow motion behind
    overlay_rects: list[list[float]] = []  #   the guest's UI clipped to these rects (fractions of its picture)
    slow_rate: float = 0.08                #   host speed while the minigame runs (overlay style)

class LinkOut(BaseModel):
    result: dict

LINKS: dict[str, dict] = {}


def _watch_true(ad, spec: dict, big: bool) -> bool:
    import struct as S
    w = {"u8": 1, "u16": 2, "u32": 4, "f32": 4}[spec.get("type", "u32")]
    fmt = ("<>"[big]) + {"u8": "B", "u16": "H", "u32": "I", "f32": "f"}[spec.get("type", "u32")]
    v = S.unpack(fmt, ad.read_memory(int(str(spec["address"]), 0), w))[0]
    return any(op in spec and f(v, spec[op]) for op, f in
               (("eq", lambda a, b: a == b), ("ne", lambda a, b: a != b), ("lt", lambda a, b: a < b), ("gt", lambda a, b: a > b)))


def _link_loop(key: str):
    """Host moment -> pause host, play the guest minigame from its save state -> verdict preset on the host -> resume."""
    L = LINKS[key]
    hs, gs = L["in"].host, L["in"].guest
    while L["on"]:
        try:
            had, hg = SESSIONS[hs]
            gad, gg = SESSIONS[gs]
            if not _watch_true(had, L["in"].trigger, hg.get("platform") in BIG_ENDIAN):
                time.sleep(L["in"].poll_s)
                continue
            overlay = L["in"].style == "overlay" and L["in"].overlay_rects and hasattr(had, "slowmo")
            had.slowmo(L["in"].slow_rate) if overlay else had.pause()
            L["state"], L["rounds"] = "minigame", L["rounds"] + 1
            gad.resume()
            gad.load_state()                               # back to the parked match
            if HOST_OS == "windows" and getattr(gad, "proc", None):   # RPCS3 load state = relaunch: wait for its window
                from . import overlay as ov
                for _ in range(120):
                    if ov.game_window(gad.proc.pid):
                        break
                    time.sleep(0.25)
            time.sleep(2)                                  # ponytail: settle after the reload; tune per game
            if overlay:                                    # Tetris UI over the slow-motion bullet scene
                from . import overlay as ov
                ov.overlay_on(gad.proc.pid, had.proc.pid, L["in"].overlay_rects)
            big = gg.get("platform") in BIG_ENDIAN
            while L["on"]:
                if _watch_true(gad, L["in"].win, big):
                    verdict = "win"
                    break
                if _watch_true(gad, L["in"].lose, big):
                    verdict = "lose"
                    break
                time.sleep(L["in"].poll_s)
            else:
                break
            gad.pause()
            if overlay:
                from . import overlay as ov
                ov.overlay_off(gad.proc.pid)
                had.slowmo(1.0)
            had.resume()
            getattr(script_patch, "__wrapped__", script_patch)(
                ScriptPatchIn(session_id=hs, op="preset", preset=L["in"].on_win if verdict == "win" else L["in"].on_lose), _quiet())
            L["history"].append({"round": L["rounds"], "verdict": verdict, "at": time.time()})
            L["state"] = "waiting"
            while L["on"] and _watch_true(had, L["in"].trigger, hg.get("platform") in BIG_ENDIAN):
                time.sleep(L["in"].poll_s)                 # let this moment finish before arming again
        except Exception as e:
            L["error"] = f"{type(e).__name__}: {e}"
            time.sleep(1)


@tool("game_link", "1.0", LinkIn, LinkOut, capabilities=["runtime", "memory", "mod"], permissions=[P.MEMORY_WRITE],
      side_effects=["pauses/resumes two live sessions and applies script-patch presets on the host"])
def game_link(inp: LinkIn, ctx: Ctx):
    """Cross-game link: when the host game's trigger fires (e.g. Stranglehold bullet-cam), pause it and play a match in
    the guest game (e.g. Puyo Puyo Tetris, from its save state); a win/lose applies the host preset (hit / miss)."""
    key = f"{inp.host}|{inp.guest}"
    if inp.op == "start":
        for need in ("trigger", "win", "lose"):
            if not getattr(inp, need).get("address"):
                raise ValueError(f"{need} needs an address (find it with memory_search)")
        LINKS[key] = {"in": inp, "on": True, "state": "waiting", "rounds": 0, "history": [], "error": None}
        threading.Thread(target=_link_loop, args=(key,), daemon=True).start()
    elif inp.op == "stop" and key in LINKS:
        LINKS[key]["on"] = False
    L = LINKS.get(key) or {}
    return {"result": {"running": L.get("on", False), "state": L.get("state"), "rounds": L.get("rounds", 0),
                       "history": L.get("history", [])[-10:], "error": L.get("error")}}


class BevyIn(BaseModel):
    name: str = "scene"
    # [{"package": "pso_dc_forest01", "translation": [x,y,z], "scale": 1.0, "rotation_y_deg": 0}]
    items: list[dict]
    camera: dict = {}                      # {"eye": [x,y,z], "target": [x,y,z]}
    screenshot: bool = True                # True: render, capture a PNG, exit; False: open an interactive window

class BevyOut(BaseModel):
    scene: str
    screenshot: str | None = None
    pid: int | None = None


VIEWER_SRC = Path(__file__).resolve().parent.parent / "projects" / "gbox_viewer"


@tool("bevy_scene", "1.0", BevyIn, BevyOut, capabilities=["asset", "bevy"], timeout_s=3600,
      side_effects=["writes glTF + scene files", "builds the gBox Bevy viewer on first use (cargo)"], artifacts=["bevy.png"])
def bevy_scene(inp: BevyIn, ctx: Ctx):
    """Put collection entries ({character: slug} / {environment: slug}) and gBox asset packages ({package}) into a Bevy
    scene and render it with the gBox Bevy viewer (Rust/Bevy, built once with cargo). screenshot=true returns a PNG
    artifact; false opens a window."""
    uroot = ctx.config.data_dir / "uap"
    share = Path("//10.89.1.246/ehm_eckx/gBox/system/gbox-data/uap")   # ponytail: packages extracted on the Spark
    if not all((uroot / it["package"]).exists() for it in inp.items if "package" in it) and share.exists():
        uroot = share
    # collection entries ({character: slug} / {environment: slug}) are read where the collection lives (the Spark's
    # cache, the same folder through the share on Windows)
    from . import characters as K
    croot = K.library_root(ctx.config).parent if HOST_OS != "windows" else Path("//10.89.1.246/ehm_eckx/gbox-cache")
    files = []                                             # (absolute model file, item options)
    for it in inp.items:
        opts = {k: v for k, v in it.items() if k not in ("package", "character", "environment")}
        if it.get("character") or it.get("environment"):
            sub = "environments" if it.get("environment") else "characters"
            slug = it.get("environment") or it.get("character")
            mp = croot / sub / slug / "meta.json"
            if not mp.exists():
                raise ValueError(f"no collection entry {sub}/{slug} (characters op=list / environments)")
            files.append((mp.parent / json.loads(mp.read_text())["model"], opts))
            continue
        pkg = uroot / it["package"]
        gl = pkg / f"{it['package']}.gltf"
        if not gl.exists():
            gl.write_text(json.dumps(uap.to_gltf(uap.load(pkg))))
        files.append((gl, opts))
    aroot = Path(os.path.commonpath([str(f.parent) for f, _ in files])) if files else uroot
    items = [{"gltf": os.path.relpath(f, aroot).replace("\\", "/"), **o} for f, o in files]
    sdir = ctx.config.data_dir / "bevy"
    sdir.mkdir(parents=True, exist_ok=True)
    scene = sdir / f"{inp.name}.json"
    scene.write_text(json.dumps({"assets_root": str(aroot).replace("\\", "/"), "items": items, "camera": inp.camera}, indent=1))
    target = ctx.config.runtime / "bevy-target"             # local SSD; Bevy's ~500 crates compile once
    exe = target / "release" / ("gbox_viewer.exe" if HOST_OS == "windows" else "gbox_viewer")
    if not exe.exists() or VIEWER_SRC.joinpath("src", "main.rs").stat().st_mtime > exe.stat().st_mtime:
        ctx.progress(10, "building the Bevy viewer (first build takes several minutes)")
        cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
        r = subprocess.run([cargo, "build", "--release"], cwd=VIEWER_SRC, capture_output=True, text=True,
                           env=dict(os.environ, CARGO_TARGET_DIR=str(target)), timeout=3000)
        if r.returncode:
            raise RuntimeError("cargo build failed:\n" + r.stderr[-3000:])
    if not inp.screenshot:
        p = subprocess.Popen([str(exe), str(scene)], cwd=sdir)
        return {"scene": str(scene), "pid": p.pid}
    png = sdir / f"{inp.name}.png"
    png.unlink(missing_ok=True)
    ctx.progress(70, "rendering")
    subprocess.run([str(exe), str(scene), "--screenshot", str(png)], cwd=sdir, capture_output=True, timeout=300)
    if not png.exists():
        raise RuntimeError("the viewer did not produce a screenshot")
    ctx.artifact("bevy.png", png.read_bytes(), "image/png", scene=inp.name)
    return {"scene": str(scene), "screenshot": str(png)}


class VideoIn(BaseModel):
    op: str = "search"                     # search | ingest | frame | knowledge
    query: str = ""                        # search: text; knowledge: filter
    url: str = ""                          # ingest/frame: a YouTube (or any yt-dlp supported) URL or id
    n: int = 8
    at: float = 0.0                        # frame: seconds into the video
    comments: int = 60                     # ingest: top comments to keep

class VideoOut(BaseModel):
    result: dict


def _ytdlp(args: list[str], cfg, timeout=300) -> subprocess.CompletedProcess:
    cookies = cfg.data_dir / "youtube_cookies.txt"         # Netscape cookie export; YouTube bot-checks some networks
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", *(["--cookies", str(cookies)] if cookies.exists() else []), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    if r.returncode and "confirm you" in r.stderr and "bot" in r.stderr:
        raise ToolUnavailable("YouTube asks this network to sign in: put a YouTube cookies.txt export at "
                              f"{cookies} (see the yt-dlp FAQ on exporting cookies)")
    return r


def _vtt_text(vtt: str) -> list[dict]:
    """WebVTT (incl. YouTube auto-captions with rolling duplicates) -> [{t, text}] one entry per new line of speech."""
    out, last, t = [], "", 0.0
    for block in vtt.split("\n\n"):
        lines = [x for x in block.strip().splitlines() if x.strip()]
        ts = next((x for x in lines if "-->" in x), None)
        if not ts:
            continue
        parts = ts.split("-->")[0].strip().split(":")      # hh:mm:ss.mmm or mm:ss.mmm
        h, m, s = parts if len(parts) == 3 else ["0", *parts]
        t = int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))
        for x in lines[lines.index(ts) + 1:]:
            x = re.sub(r"<[^>]+>", "", x).strip()
            if x and x != last:
                out.append({"t": round(t, 1), "text": x})
                last = x
    return out


@tool("video", "1.0", VideoIn, VideoOut, capabilities=["knowledge", "web"], timeout_s=900,
      side_effects=["writes data_dir/knowledge/videos/<id>.json + .md"], artifacts=["frame.png"])
def video_tool(inp: VideoIn, ctx: Ctx):
    """Video knowledge: search YouTube, ingest a video (transcript with timestamps, description, chapters, top comments)
    into the gBox knowledge base, grab a frame at a timestamp, or list what is already known."""
    kdir = ctx.config.data_dir / "knowledge" / "videos"
    kdir.mkdir(parents=True, exist_ok=True)
    if inp.op == "search":
        r = _ytdlp(["--flat-playlist", "--print", "%(id)s\t%(title)s\t%(channel)s\t%(duration_string)s",
                    f"ytsearch{max(1, min(inp.n, 25))}:{inp.query}"], ctx.config, 120)
        rows = [dict(zip(("id", "title", "channel", "duration"), ln.split("\t"))) for ln in r.stdout.splitlines() if "\t" in ln]
        return {"result": {"videos": [x | {"url": f"https://www.youtube.com/watch?v={x['id']}",
                                           "known": (kdir / f"{x['id']}.json").exists()} for x in rows]}}
    if inp.op == "knowledge":
        items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(kdir.glob("*.json"))]
        q = inp.query.lower()
        return {"result": {"videos": [{k: v.get(k) for k in ("id", "title", "channel", "url")} for v in items
                                      if not q or q in (v.get("title", "") + v.get("transcript_text", "")).lower()]}}
    if not inp.url:
        raise ValueError("url required")
    if inp.op == "ingest":
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = _ytdlp(["--skip-download", "--write-info-json", "--write-auto-subs", "--write-subs", "--sub-langs", "en.*,en",
                        "--sub-format", "vtt", *(["--write-comments", "--extractor-args", f"youtube:max_comments={inp.comments},all,0,0"]
                                                 if inp.comments else []),
                        "-o", str(Path(td) / "%(id)s.%(ext)s"), inp.url], ctx.config, 600)
            info_f = next(Path(td).glob("*.info.json"), None)
            if not info_f:
                raise RuntimeError("yt-dlp could not read the video:\n" + r.stderr[-1500:])
            info = json.loads(info_f.read_text(encoding="utf-8"))
            vtt = next(iter(sorted(Path(td).glob("*.vtt"), key=lambda p: (".en." not in p.name, p.name))), None)
            lines = _vtt_text(vtt.read_text(encoding="utf-8", errors="replace")) if vtt else []
        vid = info["id"]
        doc = {"id": vid, "url": info.get("webpage_url"), "title": info.get("title"), "channel": info.get("channel"),
               "duration": info.get("duration"), "upload_date": info.get("upload_date"), "description": info.get("description"),
               "chapters": info.get("chapters"), "transcript": lines, "transcript_text": " ".join(x["text"] for x in lines),
               "comments": [{"author": c.get("author"), "likes": c.get("like_count"), "text": c.get("text")}
                            for c in sorted(info.get("comments") or [], key=lambda c: -(c.get("like_count") or 0))[:inp.comments]],
               "ingested": time.time()}
        (kdir / f"{vid}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
        md = [f"# {doc['title']}", "", f"{doc['url']} · {doc['channel']} · {doc['duration']} s", "", "## Description", "",
              doc["description"] or "", "", "## Transcript", ""]
        md += [f"[{int(x['t'] // 60)}:{int(x['t'] % 60):02d}] {x['text']}" for x in lines]
        md += ["", "## Top comments", ""] + [f"- {c['author']} ({c['likes'] or 0}): {c['text']}" for c in doc["comments"]]
        (kdir / f"{vid}.md").write_text("\n".join(md), encoding="utf-8")
        return {"result": {"id": vid, "title": doc["title"], "transcript_lines": len(lines), "comments": len(doc["comments"]),
                           "knowledge": str(kdir / f"{vid}.md"), "excerpt": doc["transcript_text"][:1500]}}
    if inp.op == "frame":
        r = _ytdlp(["-f", "best[height<=720]/best", "-g", inp.url], ctx.config, 120)
        stream = r.stdout.strip().splitlines()[0] if r.stdout.strip() else None
        if not stream:
            raise RuntimeError("no stream URL:\n" + r.stderr[-1000:])
        import tempfile
        out = Path(tempfile.mkdtemp()) / "frame.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(inp.at), "-i", stream, "-frames:v", "1", str(out)],
                       check=True, timeout=120)
        sha = ctx.artifact("frame.png", out.read_bytes(), "image/png", url=inp.url, at=inp.at)
        return {"result": {"at": inp.at, "frame": getattr(sha, "sha256", sha)}}
    raise ValueError(f"unknown op {inp.op}")


class FileModIn(BaseModel):
    game_id: str
    op: str = "list"                       # list | build | remove
    name: str = ""
    # build: {"PS3_GAME/USRDIR/...": {"patch": [{"offset": "0x10", "hex": "ff"}]} | {"from": "<local file>"} | {"artifact": "<sha256>"}}
    changes: dict = {}

class FileModOut(BaseModel):
    result: dict


@tool("file_mod", "1.0", FileModIn, FileModOut, capabilities=["mod"], timeout_s=7200, permissions=[P.EXECUTE],
      side_effects=["copies the game once into the node cache", "writes mod folders (hard links + changed files)"])
def file_mod(inp: FileModIn, ctx: Ctx):
    """File-replacement mods for folder games: build a modded copy (original untouched, unchanged files hard-linked to
    one local base copy), list, remove (= rollback). Launch it with launch_game mod=<name>."""
    from . import filemods
    r = httpx.get(f"{ctx.server}/api/catalog/{inp.game_id}", headers=ctx.headers, timeout=30)
    r.raise_for_status()
    g = CatalogEntry.model_validate(r.json())
    rom = rom_path(g, ctx.config)
    if inp.op == "list":
        return {"result": {"game": g.title, "mods": filemods.list_mods(ctx.config, g.game_id)}}
    if inp.op == "remove":
        return {"result": {"removed": filemods.remove(ctx.config, g.game_id, inp.name)}}
    if inp.op == "build":
        if not inp.name or not inp.changes:
            raise ValueError("build needs a name and changes")
        changes = {}
        for rel, ch in inp.changes.items():
            if "artifact" in ch:                           # a file uploaded to gBox (e.g. an edited texture)
                r = httpx.get(f"{ctx.server}/api/artifacts/{ch['artifact']}", headers=ctx.headers, timeout=300)
                r.raise_for_status()
                ch = {"bytes": r.content}
            changes[rel] = ch
        build = filemods.build if filemods.is_folder_game(rom) else filemods.build_image   # folder game | ROM / disc image
        res = build(ctx.config, g.game_id, rom, inp.name, changes, ctx.progress)
        ctx.artifact("mod.json", json.dumps(res).encode(), "application/json", game=g.game_id, mod=inp.name)
        return {"result": res}
    raise ValueError(f"unknown op {inp.op}")


class RomExportIn(BaseModel):
    op: str = "export"                     # export | plan (what can be baked, no build) | list | remove
    mod_id: str = ""                       # a saved mod (/api/mods): its file mod + code patches + cheat codes
    game_id: str = ""                      # default: the game of the saved mod's file mod
    mods: list[str] = []                   # more to stack: file-mod names of this game and/or saved mod ids
    changes: dict = {}                     # extra file changes, file_mod format ({disc path: {from|patch}}, "@image")
    name: str = ""                         # export name (default: the mod's title); remove: the export's name
    formats: list[str] = ["bps", "ips", "xdelta"]   # patch formats (ips only <= 16 MiB, xdelta if xdelta3 is installed)
    wii_format: str = "iso"                # Wii rebuild: iso (USB loaders, Dolphin) | rvz (Dolphin only, smaller)

class RomExportOut(BaseModel):
    result: dict


@tool("rom_export", "1.0", RomExportIn, RomExportOut, capabilities=["mod", "export"], timeout_s=7200,
      permissions=[P.EXECUTE], side_effects=["writes the modded image + patch under gbox-data/exports (local only)"])
def rom_export(inp: RomExportIn, ctx: Ctx):
    """Export ROM hack: bake a mod into a bootable copy of the operator's own game file (N64 .z64 with fixed CRC,
    GameCube .iso, Wii .iso/.rvz rebuilt with dolphin-tool, PS2 .iso, PS3/Xbox 360 extracted folder) plus a shareable
    BPS/IPS/xdelta patch that holds no game data, and cheat files for codes. Live memory mods are reported as not
    bakeable, with the reason. Output stays on this gBox (exports/), downloadable by the operator only."""
    from . import romexport as RX
    if inp.op == "list":
        return {"result": {"exports": RX.list_exports(ctx.config, inp.game_id)}}
    if inp.op == "remove":
        return {"result": {"removed": RX.remove(ctx.config, inp.game_id, inp.name)}}
    saved = {m["id"]: m for m in httpx.get(f"{ctx.server}/api/mods", headers=ctx.headers, timeout=60).json()}
    ids = ([inp.mod_id] if inp.mod_id else []) + [m for m in inp.mods if m in saved]
    if inp.mod_id and inp.mod_id not in saved:
        raise ValueError(f"no saved mod {inp.mod_id}")
    docs = [saved[i] for i in dict.fromkeys(ids)]
    names = [m for m in inp.mods if m not in saved]
    gid = inp.game_id or next((c["input"].get("game_id") for d in docs for c in d.get("calls") or []
                               if c.get("tool") == "@launch" and c.get("input", {}).get("game_id")), None)
    gid = gid or (docs[0]["game_id"] if docs else "")
    if not gid:
        raise ValueError("game_id (or a saved mod_id) is required")
    if inp.op == "plan":
        return {"result": {"game_id": gid, "components": [c for d in docs for c in RX.classify(d, ctx.config)]
                           + [{"kind": "file_mod", "name": n} for n in names]}}
    r = httpx.get(f"{ctx.server}/api/catalog/{gid}", headers=ctx.headers, timeout=30)
    r.raise_for_status()
    g = CatalogEntry.model_validate(r.json())
    try:
        rom = rom_path(g, ctx.config)
    except ToolUnavailable:
        rom = Path(g.rel_path or "")
    res = RX.export(ctx.config, g.model_dump(), rom, mods=docs, file_mods=names, changes=inp.changes, name=inp.name,
                    formats=tuple(inp.formats), wii_format=inp.wii_format, server=ctx.server, headers=ctx.headers,
                    progress=ctx.progress)
    ctx.progress(99, "Export ready")
    ctx.artifact("export.json", json.dumps(res, default=str).encode(), "application/json", game=gid, export=res["name"])
    return {"result": res}


class GraphicsIn(BaseModel):
    game_id: str
    session_id: str = ""                  # prefer the emulator that is actually running
    op: str = "get"                        # get | set | best (strongest preset for this node's GPU)
    prefs: dict = {}

class GraphicsOut(BaseModel):
    result: dict


@tool("graphics", "1.0", GraphicsIn, GraphicsOut, capabilities=["runtime"],
      side_effects=["writes data_dir/graphics.json (applied at the game's next launch)"])
def graphics_tool(inp: GraphicsIn, ctx: Ctx):
    """Show and save only graphics controls that this game's active emulator actually consumes."""
    from . import graphics
    if inp.session_id and inp.session_id in SESSIONS:
        ad, running_game = SESSIONS[inp.session_id]
        if running_game.get("game_id") != inp.game_id:
            raise ValueError("graphics session does not match the selected game")
    else:
        r = httpx.get(f"{ctx.server}/api/catalog/{inp.game_id}", headers=ctx.headers, timeout=30)
        r.raise_for_status()
        ad = adapters.for_game(r.json(), ctx.config)
    emulator = ad.name
    choices = graphics.choices_for(emulator)
    gp = graphics.gpu()
    if inp.op == "set":
        if not choices:
            raise Unsupported(graphics.note_for(emulator))
        unsupported = set(inp.prefs) - set(choices)
        if unsupported:
            raise ValueError(f"{emulator} does not use graphics controls: {', '.join(sorted(unsupported))}")
        p = graphics.save(ctx.config, inp.game_id, inp.prefs)
    elif inp.op == "best":
        if not choices:
            raise Unsupported(graphics.note_for(emulator))
        p = graphics.save(ctx.config, inp.game_id,
                          {k: v for k, v in graphics.best_for_gpu(gp["vram_mb"]).items() if k in choices})
    elif inp.op == "get":
        p = graphics.get(ctx.config, inp.game_id)
    else:
        raise ValueError(f"unknown graphics operation {inp.op}")
    return {"result": {"emulator": emulator, "prefs": {k: p[k] for k in choices}, "gpu": gp,
                       "choices": choices, "restart_needed": inp.op != "get", "notes": graphics.note_for(emulator)}}


class ModIn(BaseModel):
    session_id: str
    op: str = "list"                       # list | save | apply | rollback | verify | delete
    name: str = ""
    desc: str = ""
    # save: changes = [{"kind": "write", "address": "0x...", "hex": "..."}, {"kind": "preset", "preset": "god"},
    #                  {"kind": "cheat", "codes": ["ADDR VALUE"], "desc": "..."}]; capture=true adds the session's live state
    changes: list[dict] = []
    capture: bool = False

class ModOut(BaseModel):
    result: dict

MODS_ON: dict[str, dict[str, list]] = {}   # session -> mod name -> undo steps


def _mod_dir(cfg, g: dict) -> Path:
    # ponytail: mods live in this node's data_dir (per game); move to the control plane if nodes must share them
    d = cfg.data_dir / "mods" / (g.get("game_id") or "unknown")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _quiet():
    import types
    return types.SimpleNamespace(progress=lambda *a: None)


def _mod_undo(sid, ad, undo):
    for step in reversed(undo):
        try:
            if step[0] == "write":
                ad.write_memory(step[1], step[2])
            elif step[0] == "preset":
                getattr(script_patch, "__wrapped__", script_patch)(
                    ScriptPatchIn(session_id=sid, op="preset" if step[1] != "off" else "revert", preset=step[1]), _quiet())
            elif step[0] == "cheat":
                mine, ra = GCHEATS.get(sid, []), len(getattr(ad, "cheats", []) or [])
                if 0 <= step[1] - ra < len(mine):
                    mine[step[1] - ra]["on"].clear()
        except Exception:
            pass                                           # best effort: undo the rest


@tool("mod", "1.0", ModIn, ModOut, capabilities=["runtime", "memory", "mod"], permissions=[P.MEMORY_WRITE],
      side_effects=["writes mod files under data_dir/mods", "applies/rolls back memory changes in a live session"])
def mod_tool(inp: ModIn, ctx: Ctx):
    """Mod builder for a live game: save a named changeset (memory writes, script-patch preset, cheat codes, or the
    session's current state), apply it with rollback data, roll it back, verify it is still in effect, list, delete."""
    ad, g = SESSIONS[inp.session_id]
    d = _mod_dir(ctx.config, g)
    on = MODS_ON.setdefault(inp.session_id, {})
    path = d / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', inp.name or 'mod')}.json"
    if inp.op == "list":
        mods = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]
        return {"result": {"game": g.get("title"), "mods": [{"name": m["name"], "desc": m.get("desc"), "changes": len(m["changes"]),
                                                             "applied": m["name"] in on} for m in mods]}}
    if inp.op == "save":
        changes = list(inp.changes)
        if inp.capture:
            st = USCRIPT.get(inp.session_id, {})
            if st.get("active", "off") != "off":
                changes.append({"kind": "preset", "preset": st["active"]})
            changes += [{"kind": "cheat", "codes": c["lines"], "desc": c["desc"]} for c in GCHEATS.get(inp.session_id, []) if c["on"].is_set()]
        if not changes:
            raise ValueError("nothing to save: give changes or capture=true with something active")
        m = {"name": inp.name or "mod", "desc": inp.desc, "game": {k: g.get(k) for k in ("game_id", "title", "platform", "serial")},
             "changes": changes, "created": time.time()}
        path.write_text(json.dumps(m, indent=1))
        ctx.artifact("mod.json", path.read_bytes(), "application/json", mod=m["name"])
        return {"result": {"saved": str(path), "changes": len(changes)}}
    if not path.exists():
        raise ValueError(f"no mod {inp.name!r} for {g.get('title')}")
    m = json.loads(path.read_text())
    if inp.op == "apply":
        if m["name"] in on:
            return {"result": {"applied": m["name"], "already": True}}
        undo = []
        try:
            for c in m["changes"]:
                if c["kind"] == "write":
                    a, new = int(str(c["address"]), 0), bytes.fromhex(c["hex"])
                    undo.append(("write", a, ad.read_memory(a, len(new)), new))
                    ad.write_memory(a, new)
                elif c["kind"] == "preset":
                    prev = USCRIPT.get(inp.session_id, {}).get("active", "off")
                    getattr(script_patch, "__wrapped__", script_patch)(
                        ScriptPatchIn(session_id=inp.session_id, op="preset", preset=c["preset"]), _quiet())
                    undo.append(("preset", prev, c["preset"]))
                elif c["kind"] == "cheat":
                    r = getattr(cheats_tool, "__wrapped__", cheats_tool)(
                        CheatIn(session_id=inp.session_id, op="add", codes=c["codes"], desc=c.get("desc", m["name"])), ctx)
                    undo.append(("cheat", r["result"]["index"]))
                else:
                    raise ValueError(f"unknown change kind {c['kind']}")
        except Exception:
            _mod_undo(inp.session_id, ad, undo)            # all or nothing
            raise
        on[m["name"]] = undo
        return {"result": {"applied": m["name"], "changes": len(undo)}}
    if inp.op == "rollback":
        _mod_undo(inp.session_id, ad, on.pop(m["name"], []))
        return {"result": {"rolled_back": m["name"]}}
    if inp.op == "verify":                                 # regression check: is every change still in effect?
        bad = []
        for step in on.get(m["name"], []):
            if step[0] == "write" and ad.read_memory(step[1], len(step[3])) != step[3]:
                bad.append(f"write {step[1]:#x} reverted")
            if step[0] == "preset" and USCRIPT.get(inp.session_id, {}).get("active") != step[2]:
                bad.append(f"preset {step[2]} not active")
        return {"result": {"mod": m["name"], "applied": m["name"] in on, "ok": m["name"] in on and not bad, "problems": bad}}
    if inp.op == "delete":
        path.unlink()
        return {"result": {"deleted": m["name"]}}
    raise ValueError(f"unknown op {inp.op}")


class PsoAreaIn(BaseModel):
    disc: str                              # PSO V2 .gdi on this node
    area: str = "FOREST01"                 # e.g. FOREST01, CAVE01, MACHINE01, CITY00...
    name: str | None = None

class PsoAreaOut(BaseModel):
    package_dir: str
    stats: dict
    textures: list[str]
    problems: list[str]


@tool("extract_pso_area", "1.0", PsoAreaIn, PsoAreaOut, capabilities=["asset", "extract"], timeout_s=1800,
      side_effects=["writes a UAP package under data_dir/uap"], artifacts=["manifest.json"],
      validate=lambda o, a: o.problems, validation="UAP validator on the written package")
def extract_pso_area(inp: PsoAreaIn, ctx: Ctx):
    """Phantasy Star Online (Dreamcast) environment -> static UAP package: every section's render geometry (d.rel) in
    world space + the area's PVM textures + the collision mesh (c.rel), ready for glTF/Blender/engines."""
    from . import ninja, psomap
    from .gdrom import GDRom
    disc = GDRom(inp.disc)
    base = f"PSO/SCENE/MAP_{inp.area.upper()}"
    # areas with variants (Pioneer 2: MAP_CITY00_00D.REL + MAP_CITY00.PVM) keep the textures under the plain name
    rel_base = base if base + "D.REL" in disc.files else next((base + v for v in ("_00", "_01") if base + v + "D.REL" in disc.files), base)
    pvm = next((f for f in (base + ".PVM", rel_base + ".PVM") if f in disc.files), base + ".PVM")
    name = inp.name or f"pso_dc_{inp.area.lower()}"
    pkg = ctx.config.data_dir / "uap" / name
    (pkg / "textures").mkdir(parents=True, exist_ok=True)
    ctx.progress(10, "decoding textures")
    textures = []
    for tn, chunk in ninja.pvm(disc.read(pvm)):
        try:
            w, h, rgba, _ = ninja.pvr_decode(chunk)
            (pkg / "textures" / f"{tn}.png").write_bytes(ninja.png(w, h, rgba))
            textures.append(f"textures/{tn}.png")
        except ValueError:
            textures.append(None)
    ctx.progress(40, "walking render sections")
    rel = disc.read(rel_base + "D.REL")
    m = psomap.render_manifest(rel, name, {"game_disc": Path(inp.disc).name, "files": [rel_base + "D.REL", pvm, rel_base + "C.REL"],
                                           "rel_sha256": sha256(rel), "extraction_method": "gbox.psomap.render_manifest"}, textures)
    from . import uap as U
    tris = psomap.collision(disc.read(rel_base + "C.REL"), be=False) if rel_base + "C.REL" in disc.files else []
    m.collision = [U.Mesh(name=f"{name}_collision", positions=[list(v) for t in tris for v in t[:3]],
                          indices=list(range(3 * len(tris))))] if tris else []
    m.provenance = [{"step": "extract_pso_area", "job": ctx.job_id, "worker": ctx.worker, "at": time.time()}]
    (pkg / "manifest.json").write_text(m.model_dump_json())
    problems = uap.validate(m, pkg)
    ctx.artifact("manifest.json", (pkg / "manifest.json").read_bytes(), "application/json", uap=name, **m.source)
    return {"package_dir": str(pkg), "stats": uap.stats(m), "textures": [t for t in textures if t], "problems": problems}


class PsoModelIn(BaseModel):
    disc: str                              # .gdi (Dreamcast) or .iso (GameCube) on this node
    archive: str                           # e.g. "PSO/BM_ENE_BM5_WOLF_A.BML"
    model: str                             # member, e.g. "bm5_s_kem_body.nj"
    name: str | None = None

class PsoModelOut(BaseModel):
    package_dir: str
    stats: dict
    textures: list[str]
    problems: list[str]

@tool("extract_pso_model", "1.0", PsoModelIn, PsoModelOut, capabilities=["asset", "extract"], timeout_s=900,
      side_effects=["writes a UAP package under data_dir/uap"], artifacts=["manifest.json"],
      validate=lambda o, a: o.problems, validation="UAP validator on the written package")
def extract_pso_model(inp: PsoModelIn, ctx: Ctx):
    """Phantasy Star Online model -> UAP package: BML -> NJ (skinned chunk model) + PVM textures (PNG), with provenance."""
    from . import ninja
    be = inp.disc.lower().endswith((".iso", ".gcm"))
    if be:
        from .gcdisc import GCDisc
        disc = GCDisc(inp.disc)
    else:
        from .gdrom import GDRom
        disc = GDRom(inp.disc)
    ctx.progress(10, f"reading {inp.archive}")
    raw = disc.read(inp.archive)
    arc = ninja.bml(raw, be)
    if inp.model not in arc:
        raise ValueError(f"{inp.model} not in {inp.archive}: {sorted(arc)}")
    model, texarc = arc[inp.model]
    name = inp.name or Path(inp.model).stem
    pkg = ctx.config.data_dir / "uap" / name
    (pkg / "textures").mkdir(parents=True, exist_ok=True)
    ctx.progress(30, "decoding textures")
    tex_files, by_name = [], {}
    for tn, chunk in (ninja.pvm(texarc) if texarc else []):
        try:
            w, h, rgba, _ = ninja.pvr_decode(chunk)
            (pkg / "textures" / f"{tn}.png").write_bytes(ninja.png(w, h, rgba))
            by_name[tn] = f"textures/{tn}.png"
            tex_files.append(tn)
        except ValueError:
            pass
    order = ninja.njtl(model, be) or tex_files
    textures = [by_name.get(n) for n in order]
    ctx.progress(60, "decoding model")
    nj = ninja.NJ(model, be)
    m = ninja.to_manifest(nj, name, {"game_disc": Path(inp.disc).name, "archive": inp.archive, "member": inp.model,
                                     "archive_sha256": sha256(raw), "extraction_method": "gbox.ninja (BML/PRS/NJCM/PVR)"},
                          textures)
    m.provenance = [{"step": "extract_pso_model", "job": ctx.job_id, "worker": ctx.worker, "at": time.time()}]
    (pkg / "manifest.json").write_text(m.model_dump_json())
    problems = uap.validate(m, pkg)
    ctx.artifact("manifest.json", (pkg / "manifest.json").read_bytes(), "application/json", uap=name, **m.source)
    return {"package_dir": str(pkg), "stats": uap.stats(m), "textures": [t for t in order], "problems": problems}


class BrowseIn(BaseModel):
    op: str = "open"                       # open | download
    url: str


class BrowseOut(BaseModel):
    result: dict


AUTOBROWSE = Path(os.environ.get("GBOX_AUTOBROWSE", r"C:\_tools\AutoBrowse"))


def autobrowse(op: str, url: str) -> dict:
    """Hand a URL to AutoBrowse (the running instance takes it via its gBox bridge; otherwise it starts)."""
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("http(s) URLs only")
    exe = AUTOBROWSE / "system" / "node_modules" / "electron" / "dist" / "electron.exe"
    if not exe.exists():
        raise ToolUnavailable(f"AutoBrowse not found at {AUTOBROWSE} (run its AutoBrowse-Windows.bat once to install)")
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    subprocess.Popen([str(exe), str(AUTOBROWSE / "system"), f"--{'download' if op == 'download' else 'open'}={url}"],
                     cwd=str(AUTOBROWSE / "system"), env=env, creationflags=0x00000008 | 0x00000200)   # detached, own group
    return {"sent_to": "AutoBrowse", "op": op, "url": url}


@tool("browse", "1.0", BrowseIn, BrowseOut, capabilities=["browser"], timeout_s=30,
      check=lambda c: None if HOST_OS == "windows" else "AutoBrowse runs on the Windows desktop")
def browse(inp: BrowseIn, ctx: Ctx):
    """Open a page in the operator's AutoBrowse browser, or queue a download in its downloader (resumable, ad-free)."""
    return {"result": autobrowse(inp.op, inp.url)}


class PickIn(BaseModel):
    session_id: str
    x: float                               # click, 0..1 across the game window
    y: float                               # click, 0..1 down the game window
    window_aspect: float = 4 / 3           # width / height of the window the click was in (letterboxing)
    extract: bool = True                   # make sure the picked thing exists as an asset package

class PickOut(BaseModel):
    result: dict


def project_point(eye, tgt, pt, fov_deg):
    """World point -> normalized screen (0..1) for a look-at camera (y up); None when behind the camera."""
    f = [tgt[i] - eye[i] for i in range(3)]
    n = math.sqrt(sum(v * v for v in f)) or 1.0
    f = [v / n for v in f]
    r = (f[1] * 0 - f[2] * 1, f[2] * 0 - f[0] * 0, f[0] * 1 - f[1] * 0)
    n = math.sqrt(sum(v * v for v in r)) or 1.0
    r = [v / n for v in r]
    u = (r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0])
    d = [pt[i] - eye[i] for i in range(3)]
    zc = sum(d[i] * f[i] for i in range(3))
    if zc <= 1:
        return None
    s = 1 / math.tan(math.radians(fov_deg) / 2)
    xc, yc = sum(d[i] * r[i] for i in range(3)), sum(d[i] * u[i] for i in range(3))
    return 0.5 + xc / zc * s * 0.5 * 0.75, 0.5 - yc / zc * s * 0.5               # 0.75 = 4:3; sign checked on a still frame


@tool("pick", "1.0", PickIn, PickOut, capabilities=["runtime", "memory", "asset"], timeout_s=900)
def pick(inp: PickIn, ctx: Ctx):
    """Live picker (plan phase 6): what is under this click in the running game? Projects every entity through the game's
    own camera (profile.camera: eye/target in RAM), returns the nearest one, and (extract=true) its model as an asset
    package (extracted from the disc on a node that has it), ready for the 3D viewer / Blender."""
    import struct as S
    from . import semantic
    ad, g = SESSIONS[inp.session_id]
    paused = False
    try:                                                      # freeze the world while camera + objects are read together
        already = (ad.query_runtime() or {}).get("state") == "PAUSED" if hasattr(ad, "query_runtime") else False
        if not already:                                       # (a game the operator paused stays paused)
            ad.pause(); paused = True
    except Exception:
        pass
    try:
        st = _semantic_state(ad, g)
        cam_raw = None
        prof = next((p for p in semantic.load_profiles() if p.get("id") == st.get("profile")), None)
        if prof and prof.get("camera"):
            cam_raw = (ad.read_memory(int(prof["camera"]["eye"], 16), 12), ad.read_memory(int(prof["camera"]["target"], 16), 12))
    finally:
        if paused:
            try:
                ad.resume()
            except Exception:
                pass
    if not prof or not prof.get("camera"):
        raise Unsupported(f"no camera mapping for {g.get('title')} yet (profile.camera)")
    cam = prof["camera"]
    e_, t_ = cam_raw
    end = ">" if g.get("platform") in BIG_ENDIAN else "<"
    eye, tgt = S.unpack(end + "3f", e_), S.unpack(end + "3f", t_)
    # the 4:3 picture is centred in the window: map the click into picture coordinates
    cx, cy = inp.x, inp.y
    if inp.window_aspect > 4 / 3:
        w = (4 / 3) / inp.window_aspect
        cx = (inp.x - (1 - w) / 2) / w
    elif inp.window_aspect < 4 / 3:
        h = inp.window_aspect / (4 / 3)
        cy = (inp.y - (1 - h) / 2) / h
    hits = []
    for e in st.get("entities", []):
        if e["kind"] == "player":
            continue
        depth = math.dist(eye, (e["x"], e["y"], e["z"]))
        if depth > 700:                                       # other rooms: can't be what the operator is looking at
            continue
        p = project_point(eye, tgt, (e["x"], e["y"] + 12, e["z"]), cam.get("fov", 45))
        if p and -0.1 <= p[0] <= 1.1 and -0.1 <= p[1] <= 1.1:
            hits.append((math.hypot(p[0] - cx, p[1] - cy), e, p, depth))
    if not hits:
        return {"result": {"picked": None, "note": "nothing projectable near the click"}}
    me = next((x for x in st.get("entities", []) if x["kind"] == "player"), {})
    near = [h for h in hits if h[0] < (0.2 if h[1]["kind"] in ("enemy", "npc") else 0.1)] or sorted(hits, key=lambda h: h[0])[:1]
    rank = {"enemy": 0, "npc": 1, "object": 2, "gate": 3}      # creatures first (they move: clicks lag them), then nearest
    near.sort(key=lambda h: (h[1].get("room") != me.get("room"), rank.get(h[1]["kind"], 2), h[3], h[0]))   # your room first
    hits = near + [h for h in sorted(hits, key=lambda h: h[0]) if h not in near]
    dist, e, p, _ = hits[0]
    out = {"picked": {k: e.get(k) for k in ("class", "kind", "entity_id", "ptr", "x", "y", "z", "hp", "room")},
           "screen": [round(p[0], 3), round(p[1], 3)], "click": [round(cx, 3), round(cy, 3)], "miss": round(dist, 3),
           "others": [{"class": h[1]["class"], "miss": round(h[0], 3)} for h in hits[1:4]]}
    model = (prof.get("models") or {}).get(e["class"])
    if model and model[1] and inp.extract:
        name = "pso_dc_" + e["class"].replace("TObjEne", "").lower()
        have = httpx.get(f"{ctx.server}/api/uap", params={"q": name}, headers=ctx.headers, timeout=60).json()
        if not any(x["package"] == name for x in have):
            ctx.progress(40, f"extracting {e['class']} from the disc")
            j = httpx.post(f"{ctx.server}/api/jobs", headers=ctx.headers, timeout=60, json={
                "tool": "extract_pso_model", "require_os": "linux",
                "input": {"disc": prof.get("disc"), "archive": model[0], "model": model[1], "name": name}}).json()
            t0 = time.time()
            while j.get("state") in ("queued", "running") and time.time() - t0 < 600:
                time.sleep(2)
                j = httpx.get(f"{ctx.server}/api/jobs/{j['id']}", headers=ctx.headers, timeout=60).json()
            if j.get("state") != "succeeded":
                out["asset_error"] = j.get("error") or j.get("state")
                return {"result": out}
        out["package"] = name
    elif not model:
        out["asset_note"] = f"no model mapping for {e['class']} yet (profile.models)"
    return {"result": out}


class PickPreviewIn(BaseModel):
    session_id: str
    x: float                               # click, 0..1 across the game window
    y: float                               # click, 0..1 down the game window
    window_aspect: float = 4 / 3           # width / height of the window the click was in (letterboxing)


class PickPreviewOut(BaseModel):
    result: dict


@tool("pick_preview", "1.0", PickPreviewIn, PickPreviewOut, capabilities=["runtime", "memory"], timeout_s=30)
def pick_preview(inp: PickPreviewIn, ctx: Ctx):
    """Fast live preview for the game eyedropper.  Reads semantic state without pausing/extracting,
    projects the entities through the game's camera, and returns the one under the cursor together
    with a snapshot of its live RAM and the profile evidence that describes where it lives in code."""
    from . import semantic
    ad, g = SESSIONS[inp.session_id]
    st = _semantic_state(ad, g)
    prof = next((p for p in semantic.load_profiles() if p.get("id") == st.get("profile")), None)
    if not prof or not prof.get("camera"):
        return {"result": {"picked": None, "note": f"no camera mapping for {g.get('title')} yet (profile.camera)"}}
    cam = prof["camera"]
    try:
        cam_raw = (ad.read_memory(int(cam["eye"], 16), 12), ad.read_memory(int(cam["target"], 16), 12))
    except Exception as e:
        return {"result": {"picked": None, "note": f"could not read camera: {e}"}}
    end = ">" if g.get("platform") in BIG_ENDIAN else "<"
    eye, tgt = struct.unpack(end + "3f", cam_raw[0]), struct.unpack(end + "3f", cam_raw[1])
    cx, cy = inp.x, inp.y
    if inp.window_aspect > 4 / 3:
        w = (4 / 3) / inp.window_aspect
        cx = (inp.x - (1 - w) / 2) / w
    elif inp.window_aspect < 4 / 3:
        h = inp.window_aspect / (4 / 3)
        cy = (inp.y - (1 - h) / 2) / h
    hits = []
    for e in st.get("entities", []):
        if e.get("kind") == "player":
            continue
        depth = math.dist(eye, (e.get("x", 0), e.get("y", 0), e.get("z", 0)))
        if depth > 700:
            continue
        p = project_point(eye, tgt, (e.get("x", 0), e.get("y", 0) + 12, e.get("z", 0)), cam.get("fov", 45))
        if p and -0.1 <= p[0] <= 1.1 and -0.1 <= p[1] <= 1.1:
            hits.append((math.hypot(p[0] - cx, p[1] - cy), e, p, depth))
    if not hits:
        return {"result": {"picked": None, "note": "nothing projectable near the click"}}
    me = next((x for x in st.get("entities", []) if x.get("kind") == "player"), {})
    near = [h for h in hits if h[0] < (0.2 if h[1].get("kind") in ("enemy", "npc") else 0.1)] or sorted(hits, key=lambda h: h[0])[:1]
    rank = {"enemy": 0, "npc": 1, "object": 2, "gate": 3}
    near.sort(key=lambda h: (h[1].get("room") != me.get("room"), rank.get(h[1].get("kind"), 2), h[3], h[0]))
    hits = near + [h for h in sorted(hits, key=lambda h: h[0]) if h not in near]
    dist, e, p, _ = hits[0]
    ptr_int = None
    if e.get("ptr"):
        try:
            ptr_int = int(str(e["ptr"]), 16)
        except Exception:
            ptr_int = None
    ram = None
    if ptr_int:
        try:
            ram = ad.read_memory(ptr_int, 64)
        except Exception as ex:
            ram = f"read failed: {ex}".encode()
    hex_dump = None
    if ram:
        if isinstance(ram, bytes):
            hex_dump = " ".join(f"{b:02x}" for b in ram)
        else:
            hex_dump = str(ram)
    evidence = prof.get("evidence", {})
    # Surface evidence that names this class, its entity struct, or its model.
    class_ev = {}
    needle = e.get("class", "")
    for k, v in evidence.items():
        if k in ("entities", "camera", "models") or (needle and (k == needle or (isinstance(v, (str, int)) and needle in str(v)))):
            class_ev[k] = v
    model = (prof.get("models") or {}).get(e.get("class"))
    out = {
        "picked": {k: e.get(k) for k in ("class", "kind", "entity_id", "ptr", "x", "y", "z", "hp", "room")},
        "screen": [round(p[0], 3), round(p[1], 3)],
        "click": [round(cx, 3), round(cy, 3)],
        "miss": round(dist, 3),
        "hex": hex_dump,
        "evidence": class_ev,
        "model": model,
        "others": [{"class": h[1].get("class"), "miss": round(h[0], 3)} for h in hits[1:4]],
    }
    return {"result": out}


class BlenderIn(BaseModel):
    package_dir: str

class BlenderOut(BaseModel):
    objects: list[dict]
    expected: dict

def _blender_validate(out: BlenderOut, arts):
    verts = sum(o.get("vertices", 0) for o in out.objects if o["type"] == "MESH")
    bones = sum(o.get("bones", 0) for o in out.objects if o["type"] == "ARMATURE")
    p = []
    if verts < out.expected["vertices"]:      # Blender may split verts on UV seams, never fewer
        p.append(f"Blender has {verts} vertices, package has {out.expected['vertices']}")
    if bones != out.expected["bones"]:
        p.append(f"Blender has {bones} bones, package has {out.expected['bones']}")
    return p

def _blender_check(c):
    return None if provision.find_blender(c) else "no blender found (blender_path / blender_search)"

class ConvertIn(BaseModel):
    glb: str                               # artifact sha256 of a binary glTF
    fmt: str = "fbx"                       # fbx | abc | blend
    name: str = "asset"

class ConvertOut(BaseModel):
    sha: str
    size: int


@tool("asset_convert", "1.0", ConvertIn, ConvertOut, capabilities=["asset", "blender"], timeout_s=900, check=_blender_check)
def asset_convert(inp: ConvertIn, ctx: Ctx):
    """GLB -> FBX (textures embedded) / Alembic / .blend through Blender in the background (on a node that has Blender)."""
    if inp.fmt not in ("fbx", "abc", "blend"):
        raise ValueError("fmt must be fbx, abc or blend")
    r = httpx.get(f"{ctx.server}/api/artifacts/{inp.glb}", headers=ctx.headers, timeout=300)
    r.raise_for_status()
    with tempfile.TemporaryDirectory() as td:
        src, out = Path(td) / "in.glb", Path(td) / f"{inp.name}.{inp.fmt}"
        src.write_bytes(r.content)
        op = {"fbx": "bpy.ops.export_scene.fbx(filepath=o, path_mode='COPY', embed_textures=True)",
              "abc": "bpy.ops.wm.alembic_export(filepath=o)", "blend": "bpy.ops.wm.save_as_mainfile(filepath=o)"}[inp.fmt]
        py = f"import bpy,sys; i,o=sys.argv[-2:]; bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=i); {op}"
        p = subprocess.run([provision.find_blender(ctx.config), "-b", "--factory-startup", "--python-expr", py, "--", str(src), str(out)],
                           capture_output=True, text=True, timeout=800)
        if not out.exists():
            raise RuntimeError(f"Blender export failed: {(p.stderr or p.stdout)[-600:]}")
        data = out.read_bytes()
    ctx.artifact(out.name, data, "application/octet-stream", source=inp.glb)
    return {"sha": sha256(data), "size": len(data)}


@tool("open_in_blender", "1.0", BlenderIn, BlenderOut, capabilities=["asset", "blender"], timeout_s=600,
      side_effects=["writes a .blend file artifact"], artifacts=["scene.blend", "blender_report.json"],
      validate=_blender_validate, validation="vertex/bone counts match UAP", check=_blender_check)
def open_in_blender(inp: BlenderIn, ctx: Ctx):
    """Reconstruct a UAP package in Blender (headless) and save a .blend with an object report."""
    m = uap.load(Path(inp.package_dir))
    if probs := uap.validate(m, Path(inp.package_dir)):
        raise ValueError(f"UAP invalid: {probs}")
    work = Path(tempfile.mkdtemp())
    (work / "model.gltf").write_text(json.dumps(uap.to_gltf(m)))
    for mat in m.materials:
        if mat.texture:
            (work / mat.texture).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(inp.package_dir) / mat.texture, work / mat.texture)
    script = ROOT / "clients" / "blender" / "gbox_bridge.py"
    r = subprocess.run([provision.find_blender(ctx.config), "--background", "--factory-startup", "--python", str(script),
                        "--", str(work / "model.gltf"), str(work / "scene.blend"), str(work / "report.json"),
                        str(m.unit_scale_m)], timeout=540, capture_output=True, text=True)
    if r.returncode or not (work / "report.json").exists():
        raise RuntimeError(f"blender failed ({r.returncode}): {(r.stderr or r.stdout)[-1500:]}")
    report = (work / "report.json").read_bytes()
    ctx.artifact("scene.blend", (work / "scene.blend").read_bytes(), "application/x-blender", uap=m.name)
    ctx.artifact("blender_report.json", report, "application/json")
    return {"objects": json.loads(report)["objects"], "expected": uap.stats(m)}


# --- analysis -------------------------------------------------------------------------------

class GhidraIn(BaseModel):
    binary_path: str
    processor: str | None = None           # e.g. "SuperH4:LE:32:default" for Dreamcast

class GhidraOut(BaseModel):
    functions: int
    strings: int
    program: dict

def _ghidra_exe(c) -> Path | None:
    h = provision.ghidra_home(c)
    return h / "support" / ("analyzeHeadless.bat" if HOST_OS == "windows" else "analyzeHeadless") if h else None

def _ghidra_env(cfg=None) -> dict:
    """Pin a JDK 21 for gBox's headless runs (the host default may be newer); never edits the Ghidra install."""
    env = dict(os.environ)
    jdk = provision.jdk21(cfg) if cfg is not None else next((Path(p) for p in ("/usr/lib/jvm/java-21-openjdk-arm64",
                                                                             "/usr/lib/jvm/java-21-openjdk-amd64") if Path(p).exists()), None)
    if jdk:
        env["JAVA_HOME"] = str(jdk)
        env["PATH"] = f"{jdk / 'bin'}{os.pathsep}" + env.get("PATH", "")
    return env


def _ghidra_check(c):
    exe = _ghidra_exe(c)
    return None if exe and exe.exists() else "ghidra not installed (run `gbox setup` or set ghidra_home)"

def _ghidra_validate(out: GhidraOut, arts):
    d = arts.get("analysis.json")
    if not d:
        return ["analysis.json missing"]
    a = json.loads(d)
    return [] if len(a["functions"]) == out.functions and len(a["strings"]) == out.strings else ["counts mismatch artifact"]

@tool("analyze_binary", "1.0", GhidraIn, GhidraOut, capabilities=["analysis", "ghidra"], timeout_s=3600,
      artifacts=["analysis.json"], validate=_ghidra_validate, validation="artifact counts", check=_ghidra_check)
def analyze_binary(inp: GhidraIn, ctx: Ctx):
    """Headless Ghidra import+analysis; exports functions and defined strings as an artifact."""
    gh = _ghidra_exe(ctx.config)
    work = Path(tempfile.mkdtemp())
    out = work / "analysis.json"
    cmd = [str(gh), str(work), "gbox", "-import", inp.binary_path, "-deleteProject",
           "-scriptPath", str(ROOT / "adapters" / "ghidra"), "-postScript", "ExportAnalysis.java", str(out)]
    if inp.processor:
        cmd += ["-processor", inp.processor]
    r = subprocess.run(cmd, timeout=3500, capture_output=True, text=True, env=_ghidra_env(ctx.config))
    if r.returncode or not out.exists():
        raise RuntimeError(f"ghidra failed ({r.returncode}): {(r.stdout + r.stderr)[-1500:]}")
    d = out.read_bytes()
    a = json.loads(d)
    ctx.artifact("analysis.json", d, "application/json", binary=inp.binary_path, tool="ghidra")
    return {"functions": len(a["functions"]), "strings": len(a["strings"]), "program": a["program"]}


# --- provisioning ---------------------------------------------------------------------------

class ProvisionIn(BaseModel):
    with_ghidra: bool = True

class ProvisionOut(BaseModel):
    receipts: list[dict]
    failed: list[str]

@tool("provision_node", "1.0", ProvisionIn, ProvisionOut, capabilities=["provision"], permissions=[P.INSTALL],
      timeout_s=3600, side_effects=["installs packages/cores/ghidra", "edits /etc/fstab (backed up) for library mounts"],
      artifacts=["provision.json"], validate=lambda o, a: [f"step failed: {s}" for s in o.failed],
      validation="every setup step reports ok/installed")
def provision_node(inp: ProvisionIn, ctx: Ctx):
    """Resolve and install this node's dependencies (same as `gbox setup`)."""
    receipts = provision.setup(ctx.config, inp.with_ghidra, log=lambda m: ctx.log.append(m))
    ctx.artifact("provision.json", json.dumps(receipts, indent=1).encode(), "application/json")
    return {"receipts": receipts, "failed": [r["step"] for r in receipts if r["status"] in ("failed", "missing")]}


# --- Ghidra: run any installed Ghidra script headlessly (every script in the Tools table is dispatchable) ---

class GhidraScriptIn(BaseModel):
    binary_path: str
    script: str                            # file name, e.g. "FindCryptoScript.java"
    args: list[str] = []
    processor: str | None = None

class GhidraScriptOut(BaseModel):
    script: str
    returncode: int
    log_sha256: str

@tool("ghidra_script", "1.0", GhidraScriptIn, GhidraScriptOut, capabilities=["analysis", "ghidra"], timeout_s=3600,
      artifacts=["ghidra_script.log"], check=_ghidra_check,
      validate=lambda o, a: [] if sha256(a.get("ghidra_script.log", b"")) == o.log_sha256 else ["log artifact mismatch"],
      validation="script log artifact hash")
def ghidra_script(inp: GhidraScriptIn, ctx: Ctx):
    """Import a binary into a throwaway Ghidra project, auto-analyze, and run one Ghidra script on it."""
    gh, work = _ghidra_exe(ctx.config), Path(tempfile.mkdtemp())
    cmd = [str(gh), str(work), "gbox", "-import", inp.binary_path, "-deleteProject",
           "-scriptPath", str(ROOT / "adapters" / "ghidra"), "-postScript", inp.script, *inp.args]
    if inp.processor:
        cmd += ["-processor", inp.processor]
    r = subprocess.run(cmd, timeout=3500, capture_output=True, text=True, env=_ghidra_env(ctx.config))
    log = (r.stdout + r.stderr).encode()
    ctx.artifact("ghidra_script.log", log, "text/plain", script=inp.script, binary=inp.binary_path)
    if r.returncode != 0 or b"REPORT SCRIPT ERROR" in log:   # don't report success for a script that failed
        raise RuntimeError(f"ghidra exited {r.returncode}: {log.decode(errors='replace')[-800:]}")
    return {"script": inp.script, "returncode": r.returncode, "log_sha256": sha256(log)}


# --- LLM router -----------------------------------------------------------------------------

class LLMIn(BaseModel):
    prompt: str
    system: str | None = None
    endpoint: str | None = None            # name; default = first configured

class LLMOut(BaseModel):
    text: str
    endpoint: str
    model: str

@tool("llm_complete", "1.0", LLMIn, LLMOut, capabilities=["llm"], permissions=[P.NETWORK], timeout_s=300,
      artifacts=["llm_transcript.json"], validate=lambda o, a: [] if o.text.strip() else ["empty completion"],
      validation="non-empty text; LLM output is a hypothesis artifact, never evidence of success",
      check=lambda c: None if c.llm_endpoints else "no llm_endpoints configured")
def llm_complete(inp: LLMIn, ctx: Ctx):
    """Route a completion to a configured OpenAI-compatible endpoint (local Ollama/LM Studio or online)."""
    import os
    eps = ctx.config.llm_endpoints
    ep = next((e for e in eps if e.name == inp.endpoint), None) if inp.endpoint else eps[0]
    if not ep:
        raise ToolUnavailable(f"endpoint {inp.endpoint} not configured")
    headers = {"Authorization": f"Bearer {os.environ[ep.api_key_env]}"} if ep.api_key_env else {}
    msgs = ([{"role": "system", "content": inp.system}] if inp.system else []) + [{"role": "user", "content": inp.prompt}]
    r = httpx.post(f"{ep.url.rstrip('/')}/chat/completions", json={"model": ep.model, "messages": msgs},
                   headers=headers, timeout=280)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    ctx.artifact("llm_transcript.json", json.dumps({"request": msgs, "response": text, "model": ep.model}).encode(),
                 "application/json", endpoint=ep.name)
    return {"text": text, "endpoint": ep.name, "model": ep.model}


# --- agent roles (plan §19): what an LLM orchestrator can dispatch, and with which tools ---
AGENTS = [
    {"name": "orchestrator", "role": "Owns the task plan; splits requests into typed tool jobs and delegates to the roles below",
     "tools": ["*"], "status": "defined", "notes": "Today the coding agent (Claude Code) plays this role through the inbox + API."},
    {"name": "reverse_engineering", "role": "Static/runtime hypotheses: functions, structures, loaders",
     "tools": ["analyze_binary", "ghidra_script", "read_memory", "session_op"], "status": "defined"},
    {"name": "game_state", "role": "Semantic state discovery (player/enemy/room) from memory diffs + RE",
     "tools": ["read_memory", "session_op", "get_frame", "ghidra_script"], "status": "defined"},
    {"name": "autoplay_strategy", "role": "Route/strategy improvement from evaluated runs", "tools": ["launch_game", "session_op", "read_memory", "get_frame"],
     "status": "planned", "notes": "Needs the semantic-state extractor (Phase 2) first."},
    {"name": "asset", "role": "Dependency extraction and normalization into UAP packages", "tools": ["export_asset", "read_memory", "get_frame"], "status": "defined"},
    {"name": "conversion", "role": "Rig/material/format conversion", "tools": ["export_asset", "open_in_blender"], "status": "defined"},
    {"name": "mod", "role": "Transformation planning/building with reversible changesets", "tools": ["write_memory", "export_asset"],
     "status": "planned", "notes": "Mod builder (Phase 8) not built yet."},
    {"name": "validator", "role": "Independent evaluation; never the proposer", "tools": ["get_frame", "read_memory", "session_op"],
     "status": "active", "notes": "Server-side validators on every tool result are live."},
    {"name": "knowledge_curator", "role": "Consolidation, dedup, promote validated facts / deprecate contradicted ones",
     "tools": ["llm_complete"], "status": "planned"},
    {"name": "llm_router", "role": "Routes completions to local (Spark Ollama) or online models", "tools": ["llm_complete"], "status": "active"},
]

# tool modules register themselves on import. One failing import (a missing optional package on this machine) must cost
# that tool only, never the whole worker: it's reported and the rest load.
# pso_mods_tool: PSO Ver.2 DC mods | re_mods_tool: RE4 GC items/ammo/Mercenaries | zelda_tool: every Zelda
# ac_mods_tool: Armored Core | characters: character library (list / get / use / extract)
# scene_capture: Examine 3D (pause + RenderDoc frame -> glTF scene)
def _load_tool_modules(names=("pso_mods_tool", "re_mods_tool", "zelda_tool", "ac_mods_tool", "characters", "scene_capture", "tasks_tool", "blender_copy",
                              "live_link",   # live_link: Blender Live Link push -> build, validate, hot-swap into the running game
                              "re4r",   # re4r: Resident Evil 4 (2023, Steam) via REFramework + gBox's Lua bridge
                              "re6_tool",   # re6_tool: Resident Evil 6 (X360 in Xenia): Mercenaries loadouts, items, swaps
                              "oot_live",   # oot_live: OoT actors at a picture point, statues kept in rooms (gbox.oot_swap)
                              "re_inventory",   # re_inventory: any Resident Evil's live inventory (give/remove/set/loadout)
                              "aki_wrestling",   # aki_wrestling: No Mercy / Revenge / World Tour writers (via characters op=use|match)
                              "yukes_sd",   # yukes_sd: WWF SmackDown! 2 (PS1) reader + writer (via characters op=use|match|extract)
                              "aki_wcw",   # aki_wcw: WCW vs. nWo World Tour writer + extractor (via characters op=use|match|extract)
                              "re_lab_tool",   # re_lab_tool: re_executable (a title's executable -> ELF for Ghidra)
                              "doa2_lab",      # verified native fighter archive decomposition/reintegration
                              "mashup",        # mashup: natural-language cross-title planner and dispatcher
                              "favorite_capabilities",  # exact-build coverage and verified unlock launch plans
                              "rea_tool",      # complete pinned REA CLI/MCP capability catalog
                              "stage_warp",    # stage_warp: put the player on a named stage/level of the live game
                              "mk64_items",    # mk64_items: Mario Kart 64 items (always have / infinite items per player)
                              "gta_mods_tool",   # gta_mods_tool: PS2 GTAs (car jump, ped rain, ...)
                              "stranglehold")):   # stranglehold: PS3 bullet-time interception systems and chat driver
    import importlib
    import subprocess
    import sys
    from . import deps
    for n in names:
        for attempt in (0, 1):
            try:
                importlib.import_module(f".{n}", __package__)
                LOAD_ERRORS.pop(n, None)
                break
            except ModuleNotFoundError as e:
                LOAD_ERRORS[n] = f"{type(e).__name__}: {e}"
                if attempt or not deps.install_for(e.name):   # any missing package: installed here once, then retried
                    break
            except Exception as e:                   # noqa: BLE001
                LOAD_ERRORS[n] = f"{type(e).__name__}: {e}"
                break
        if n in LOAD_ERRORS:
            print(f"gBox: tool module {n} not loaded on this machine: {LOAD_ERRORS[n]}", flush=True)


LOAD_ERRORS: dict[str, str] = {}   # tool module -> why it didn't load here (shown in the worker's "unavailable")


_load_tool_modules()


class StateXIn(BaseModel):
    session_id: str
    op: str = "export"                      # export: save + upload | export_saved: upload an existing checkpoint | import: load
    artifact: str = ""                      # import: digest of the exported state
    slot: int | None = None                 # export/import: default 9; export_saved: exact slot, or latest when omitted
    not_before: float = 0                    # export_saved: reject a stale checkpoint


class StateXOut(BaseModel):
    result: dict


_STATE_TRANSFER_LOCK = threading.RLock()


def _validate_state_container(data: bytes, adapter_name: str) -> None:
    """Check recognized RetroArch envelopes only, without interpreting a core's MEM layout.

    Nonempty raw core states and other adapters retain their existing handling. Container
    decoding is bounded by flycast_state.unpack's RZIP/RASTATE limits; its
    Flycast serializer, Maple and PVR inspectors are deliberately not called.
    This proves container completeness, not that a game will restore correctly.
    """
    if adapter_name != 'retroarch':
        return
    if not data:
        raise RuntimeError('Saved checkpoint is empty')
    if not data.startswith((b'#RZIPv', b'RASTATE')):
        return
    from .flycast_state import unpack
    try:
        if not unpack(data):
            raise ValueError('empty decoded checkpoint')
    except ValueError as error:
        raise RuntimeError(f'Saved checkpoint container could not be validated: {error}') from error


@tool("state_transfer", "1.3", StateXIn, StateXOut, capabilities=["runtime"], permissions=[P.EXECUTE], timeout_s=180)
def state_transfer(inp: StateXIn, ctx: Ctx):
    with _STATE_TRANSFER_LOCK:
        return _state_transfer(inp, ctx)


def _state_transfer(inp: StateXIn, ctx: Ctx):
    """Move a running game between machines (Spark <-> this PC) through a save state: RetroArch cores, and GameCube/Wii on
    standalone Dolphin (the same release on both machines)."""
    session = SESSIONS.get(inp.session_id)
    if session is None:
        raise Unsupported('This session ended. Open the running game before transferring its state.')
    ad, g = session
    kind = getattr(ad, "name", "")
    if kind == "retroarch":
        states, pattern = ctx.config.runtime / "states", "*.state*"
    elif kind == "dolphin":                                    # same Dolphin release on both machines (2609): states are compatible
        exe = getattr(ad, "_exe", None)
        states = (exe().parent / "User" / "StateSaves") if exe else (ctx.config.runtime / "dolphin-user" / "StateSaves")
        pattern = "*.s01"                                       # the adapter's save/load hotkeys use slot 1
    else:
        raise Unsupported(f"{kind or '?'} save states can't move between machines (different emulator builds)")
    requested_slot = 9 if inp.slot is None else inp.slot

    def matches_game(f):
        if kind == 'retroarch':
            return bool(re.search(r'\.state(-?\d+)?$', f.name)) and (
                not g.get('_rom_path') or f.name.startswith(Path(g['_rom_path']).stem + '.'))
        return f.match(pattern) and f.suffix.lower() != '.png'

    def candidates():
        fs = [f for f in states.rglob(pattern) if f.is_file() and f.suffix.lower() != ".png"] if states.exists() else []
        # Deduplicate aliases to a single file; distinct core-directory checkpoints remain ambiguous for an exact slot.
        return list({f.resolve(): f for f in fs if f.resolve().is_relative_to(states.resolve()) and matches_game(f)}.values())

    def native_slot(f):
        if kind == 'dolphin':
            return 1
        match = re.search(r'\.state(-?\d+)?$', f.name)
        return int(match[1] or 0)

    def newest():
        fs = candidates()
        return max(fs, key=lambda f: f.stat().st_mtime) if fs else None

    def requested_saved():
        fs = [f for f in candidates() if native_slot(f) == inp.slot]
        if len(fs) > 1:
            raise RuntimeError('the requested saved slot has ambiguous checkpoint files')
        return fs[0] if fs else None

    def checkpoint_details(f, saved=None):
        details = {'path': str(f), 'selection': 'latest_saved_checkpoint' if saved is None else
                   ('verified_adapter_path' if saved.get('verified') else 'newest_after_save')}
        if saved is not None:
            details.update({k: saved[k] for k in ('verified', 'requested_slot', 'slot_verified', 'warning') if k in saved})
        actual = native_slot(f)
        details['slot'] = actual
        if saved is not None:
            # Dolphin's hotkeys always use slot 1; RetroArch receives the requested slot.
            details['requested_slot'] = requested_slot if kind == 'retroarch' else 1
            details['slot_verified'] = actual == details['requested_slot']
            if actual != details['requested_slot'] and not details.get('warning'):
                details['warning'] = 'RetroArch used a different slot; this result identifies the actual saved file.'
        return details

    def save_and_wait():
        t0 = time.time()
        saved = ad.save_state(requested_slot) if kind == "retroarch" else ad.save_state()
        saved = saved if isinstance(saved, dict) else {}
        if saved.get('path'):
            if saved.get('verified') is not True:
                raise RuntimeError('the adapter did not verify its saved checkpoint')
            f = Path(saved['path']).resolve()
            if not f.is_relative_to(states.resolve()) or not f.is_file() or not matches_game(f):
                raise RuntimeError('the verified checkpoint path does not belong to this game and state directory')
            stat = f.stat()
            if stat.st_size <= 0 or stat.st_mtime < t0 - 1 or (
                    saved.get('bytes') is not None and stat.st_size != saved['bytes']):
                raise RuntimeError('the verified checkpoint file is stale, empty or changed')
            details = checkpoint_details(f, saved)
            if kind == 'retroarch':
                if saved.get('slot') is not None and saved['slot'] != details['slot']:
                    raise RuntimeError('the verified checkpoint slot disagrees with its native filename')
                ad.slot = details['slot']
            return f, details
        if saved.get('verified') is False:
            raise RuntimeError('the adapter did not verify its saved checkpoint')
        if saved.get('verified') is True:
            raise RuntimeError('the adapter reported a verified checkpoint without its native path')
        for _ in range(100):                                   # RetroArch writes the file asynchronously
            f = newest()
            if f and f.stat().st_mtime >= t0 - 1 and f.stat().st_size > 0:
                time.sleep(0.5)
                if kind == 'retroarch':
                    # Hotkeys and dropped slot commands can disagree with our cached slot.
                    # The file actually written identifies the emulator's current slot.
                    ad.slot = checkpoint_details(f, saved)['slot']
                return f, checkpoint_details(f, saved)
            time.sleep(0.2)
        raise RuntimeError("the emulator didn't write a save state")
    if inp.op in ("export", "export_saved"):
        if inp.op == "export":
            f, details = save_and_wait()
        else:
            f = newest() if inp.slot is None else requested_saved()
            details = checkpoint_details(f) if f else {}
            if f and inp.slot is not None:
                details.update(selection='requested_saved_slot', requested_slot=inp.slot, slot_verified=True)
        if not f or (inp.op == "export_saved" and (
                f.stat().st_size <= 0 or f.stat().st_mtime < inp.not_before - 1)):
            raise RuntimeError("the reported game moment has no matching saved checkpoint")
        data = f.read_bytes()
        _validate_state_container(data, kind)
        ctx.artifact(f.name, data, "application/octet-stream", note="state transfer", game=g.get("game_id"), **details)
        # artifacts upload with the job result and are stored by content: the digest is known now (ctx.artifact returns None)
        return {"result": {"artifact": sha256(data), "bytes": len(data), "file": f.name, **details}}
    if inp.op == "import":
        r = httpx.get(f"{ctx.server}/api/artifacts/{inp.artifact}", headers=ctx.headers, timeout=120)
        r.raise_for_status()
        if sha256(r.content) != inp.artifact:
            raise ValueError('Saved-state download did not match the preserved checkpoint')
        _validate_state_container(r.content, kind)              # refuse before even creating the native placeholder
        f, details = save_and_wait()                            # this machine's verified state file for the game
        f.write_bytes(r.content)
        time.sleep(0.3)
        load = ad.load_state(ad.slot) if kind == "retroarch" else ad.load_state()
        load = load if isinstance(load, dict) else {}
        verified = (load.get('load_verified') is True or load.get('verified') is True) and load.get('loaded', True) is True
        if kind == 'retroarch' and load.get('slot') is not None and load['slot'] != details['slot']:
            verified = False
        if load.get('path') and Path(load['path']).resolve() != f.resolve():
            verified = False
        result = {'file': f.name, 'bytes': len(r.content), **details,
                  'load_requested': True, 'load_verified': verified, 'load_result': load}
        if verified:
            result['loaded'] = True
        return {'result': result}
    raise ValueError("op: export | export_saved | import")


# ---- no hidden games left behind: emulators this worker started are recorded; a restarted worker closes the old ones ----
def _running_file(config) -> Path:
    return Path(config.runtime) / "gbox-running.json"


def _ff_ramp(sid: str, ad) -> None:
    """Hold Select + R2 on the operator's pad = fast-forward that ramps 2x (first 1.5 s) -> 4x (to 3.5 s) -> 16x.
    RetroArch runs fast-forward at one fixed ratio (16x here), so lower speeds come from switching it on for part of the
    frames: each 1/60 s tick earns (speed - 1) extra frames, a fast-forwarded tick spends 15.
    ponytail: 2x/4x advance in small bursts (16 frames at once); a smooth ratio needs RetroArch to accept a runtime ratio."""
    import ctypes
    try:
        xi = ctypes.windll.xinput1_4
    except OSError:
        return

    class GP(ctypes.Structure):
        _fields_ = [("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                    ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]

    class ST(ctypes.Structure):
        _fields_ = [("packet", ctypes.c_uint), ("gp", GP)]
    st, t0, credit, on = ST(), None, 0.0, False

    def ff(want):
        nonlocal on
        if want != on:
            try:
                ad.cmd("FAST_FORWARD")                         # a toggle
                on = want
            except Exception:
                pass
    while sid in SESSIONS:
        time.sleep(1 / 60)
        held = xi.XInputGetState(0, ctypes.byref(st)) == 0 and st.gp.buttons & 0x0020 and st.gp.rt > 60   # Back + RT
        if not held:
            t0, credit = None, 0.0
            ff(False)
            continue
        t0 = t0 or time.time()
        el = time.time() - t0
        speed = 2.0 if el < 1.5 else 4.0 if el < 3.5 else 16.0
        if speed >= 16:
            ff(True)
            continue
        credit += speed - 1.0
        if credit >= 15.0:
            credit -= 15.0
            ff(True)
        else:
            ff(False)
    ff(False)


def track_emulator(config, sid: str, pid: int | None, add: bool = True) -> None:
    f = _running_file(config)
    try:
        d = json.loads(f.read_text()) if f.exists() else {}
    except (OSError, ValueError):
        d = {}
    if add and pid:
        d[sid] = {"pid": int(pid), "ts": time.time()}
    else:
        d.pop(sid, None)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d))
    except OSError:
        pass


def reap_orphans(config) -> list[int]:
    """At worker start: close emulators a previous run of this worker launched (they'd keep running invisibly, with no
    session gBox can stop). Only PIDs gBox recorded itself are touched."""
    f = _running_file(config)
    try:
        d = json.loads(f.read_text()) if f.exists() else {}
    except (OSError, ValueError):
        d = {}
    killed = []
    for sid, e in d.items():
        pid = e.get("pid")
        try:
            if sys.platform == "win32":
                r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                ok = r.returncode == 0
            else:
                os.kill(pid, 15)
                ok = True
        except (OSError, ProcessLookupError):
            ok = False
        if ok:
            killed.append(pid)
    try:
        f.write_text("{}")
    except OSError:
        pass
    return killed

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

from . import adapters, catalog, ghost_runs, provision, rewind, ring_record, uap
from .models import CatalogEntry, Permission as P
from .registry import HOST_OS, Cancelled, Ctx, ToolUnavailable, Unsupported, tool
from .store import sha256

ROOT = Path(__file__).resolve().parent.parent
class SessionGone(Unsupported, KeyError):
    """A session op for a game this worker no longer holds (worker restarted, or another game replaced it)."""
    def __str__(self):
        return str(self.args[0]) if self.args else "session not running"


class _Sessions(dict):
    def __getitem__(self, sid):
        try:
            return super().__getitem__(sid)
        except KeyError:
            raise SessionGone(f"This game session ({sid}) is no longer running on this PC: the worker restarted or "
                              "another game replaced it. Relaunch the game to continue.") from None


SESSIONS: dict[str, tuple[adapters.Adapter, dict]] = _Sessions()   # per-worker live runtime sessions


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
    include_steam: bool | None = None  # None: Steam only when steam_root is configured; true: also auto-detect the install (Windows registry); false: skip

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
    if inp.include_steam is not False:                   # opt-in auto-detection: an unconfigured PC is not scanned by surprise
        steam_root = cfg.steam_root or (catalog.default_steam_root() if inp.include_steam else None)
        if steam_root:
            e, p = catalog.scan_steam(steam_root)
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


class SaveMGOAssetsIn(BaseModel):
    game: CatalogEntry
    op: str = 'inventory'
    paths: list[str] = Field(default_factory=list, max_length=6000)
    members: list[dict] = Field(default_factory=list, max_length=10000)
    archive_path: str = ''


class SaveMGOAssetsOut(BaseModel):
    result: dict
    report_sha256: str


def _savemgo_assets_validate(out: SaveMGOAssetsOut, arts):
    report = arts.get('savemgo-assets.json')
    return [] if report is not None and sha256(report) == out.report_sha256 else ['SaveMGO extraction report missing or differs']


@tool('savemgo_assets', '1.0', SaveMGOAssetsIn, SaveMGOAssetsOut,
      capabilities=['asset-extract'], platforms=['windows'], permissions=[P.EXECUTE, P.FILE_MUTATION], timeout_s=3600,
      artifacts=['savemgo-assets.json'], validate=_savemgo_assets_validate,
      validation='verified source identity and hashed extraction report',
      side_effects=['stages the complete owned package locally', 'writes selected native assets to a separate export folder'])
def savemgo_assets(inp: SaveMGOAssetsIn, ctx: Ctx):
    """Inspect or export owned MGO native assets without touching its installed game or personal profile."""
    from . import savemgo, savemgo_assets as reader
    if inp.game.launch.get('kind') != 'savemgo_bundle' or inp.game.platform != 'ps3':
        raise Unsupported('This reader supports only the verified SaveMGO bundle')
    if HOST_OS != 'windows':
        raise ToolUnavailable('Select a Windows PC to inspect its locally staged SaveMGO package')
    if inp.op not in {'inventory', 'index', 'export'}:
        raise ValueError('Choose inventory, index or export')
    if inp.op == 'export' and not (inp.paths or inp.members):
        raise ValueError('Select files or archive members to export')
    ctx.nowait = True
    ctx.progress(1, 'Preparing verified Metal Gear Online asset source on this PC')
    bundle = savemgo.prepare(rom_path(inp.game, ctx.config), ctx.config, ctx.progress,
        expected_fingerprint=inp.game.launch.get('source_fingerprint'))
    root = bundle['data_root']
    identity = bundle['source_fingerprint']
    def cancellation():
        if getattr(ctx, '_cancel', False):
            raise Cancelled('SaveMGO asset export cancelled by the operator')
        return False
    if inp.op == 'inventory':
        result = reader.inventory(root, source_fingerprint=identity,
            progress=lambda p: ctx.progress(96, f"Inspecting {p['files']} native game assets"))
    elif inp.op == 'index':
        result = reader.archive_index(root, inp.archive_path)
    else:
        paths = inp.paths
        if '*' in paths:
            if paths != ['*']:
                raise ValueError('All-files selection cannot be combined with individual paths')
        output = ctx.config.data_dir / 'asset-exports' / sha256(inp.game.game_id.encode())[:16] / 'savemgo'
        result = reader.export(root, output, paths=paths, members=inp.members,
                               source_fingerprint=identity,
                               progress=lambda p: ctx.progress(96, f"{p.get('phase', 'export').title()} native game assets: {p.get('files', 0)} files"),
                               cancel=cancellation)
        # Large exports remain on the selected PC; never upload gigabytes of
        # native data just because the operator opened an inventory window.
        if result['bytes'] <= 128 * 2**20:
            import io
            import zipfile
            folder = Path(result['directory']).resolve()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_STORED) as archive:
                for row in result['files']:
                    path = folder / row['output']
                    if not path.resolve().is_relative_to(folder):
                        raise ValueError('Export package path escapes its bundle')
                    for part in (path, *path.parents):
                        if part == folder.parent:
                            break
                        if part.is_symlink() or getattr(part.stat(), 'st_file_attributes', 0) & 0x400:
                            raise ValueError('Export package contains a linked path')
                    if path.stat().st_size != row['size'] or row['size'] > 128 * 2**20:
                        raise ValueError('Export package size differs from its manifest')
                    data = path.read_bytes()
                    if sha256(data) != row['sha256']:
                        raise ValueError('Export package changed after verification')
                    archive.writestr(row['output'], data)
                archive.writestr('manifest.json', json.dumps({
                    'source_fingerprint': identity, 'native_only': True, 'files': result['files']}).encode())
            if buf.tell() <= 129 * 2**20:
                ctx.artifact('savemgo-native-assets.zip', buf.getvalue(), 'application/zip',
                             game_id=inp.game.game_id, source_fingerprint=identity, native_only=True)
                result['download'] = 'savemgo-native-assets.zip'
    result = dict(result, worker=ctx.worker, game_id=inp.game.game_id,
                  source_fingerprint=identity, source_verified=True)
    report = json.dumps(result, default=str, ensure_ascii=True).encode()
    ctx.artifact('savemgo-assets.json', report, 'application/json', game_id=inp.game.game_id)
    ctx.progress(100, 'Native assets inspected' if inp.op != 'export' else 'Selected native assets exported; format conversion is separate')
    return {'result': result, 'report_sha256': sha256(report)}

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
    if g.launch.get("path"):
        return Path(g.launch["path"])
    # Entries built from a raw path (library=None, launch={"kind": "rom"}) carry only source_paths,
    # often recorded on another OS. Remap a configured library root to this node's root.
    for src in g.source_paths or []:
        s = str(src).replace("\\", "/")
        for lib in getattr(config, "libraries", []) or []:
            here = lib.root()
            for os_, other in (lib.paths or {}).items():
                o = str(other).replace("\\", "/").rstrip("/")
                if here and o and (s == o or s.startswith(o + "/")):
                    return here / s[len(o):].lstrip("/")
        if Path(src).is_absolute() and Path(src).exists():
            return Path(src)
    raise ToolUnavailable(f"{g.title or g.game_id}: no library, launch path or source path resolvable on {HOST_OS}")


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
    mod_title: str = ""                    # the operator's name for that build (labels only: launch bar, loader)
    examine: bool | None = None            # RenderDoc inside the emulator for Examine 3D (None = config examine_ready, off by default)
    rewind: bool | None = None             # Select+L2 checkpoint rewind where the emulator has no native one (None = gbox.toml [rewind])
    keep_session: str = ""                 # game_link: launch alongside the named live session instead of closing games first
    capture_backend: str = ""              # Examine 3D capture session (#971): "auto" | "vulkan" | "glcore"; agent-owned,
                                           # its own config files, RenderDoc inside, no rewind/recording, window off-screen
    capture_for: str = ""                  # the operator session this capture session captures (scene_relay)
    boot_timeout_s: float | None = Field(default=None, ge=10, le=600)   # how long the emulator may take to report the
                                           # game running (None = the adapter's default, 30 s for RetroArch); the
                                           # launch failure remedy relaunches a slow boot with a longer one

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


def _session_ended_on_server(ctx, sid) -> bool:
    """True only when the control plane positively reports this session as ended; any doubt keeps the save path."""
    if not getattr(ctx, 'server', None):
        return False
    try:
        r = httpx.get(f'{ctx.server}/api/sessions/{sid}', headers=ctx.headers, timeout=5)
        return r.status_code == 200 and (r.json() or {}).get('state') == 'ended'
    except Exception:
        return False


def _close_previous_games(ctx, keep: str = ""):
    """One emulator per worker, except the session named by `keep` stays up (game_link host + guest on one worker).
    Preserve every current game before stopping any of them."""
    previous = [(sid, ad, game) for sid, (ad, game) in SESSIONS.items() if sid != keep]
    checkpoints = []
    for sid, ad, game in previous:
        proc = getattr(ad, 'proc', None)
        if proc and proc.poll() is not None:
            from . import memory_card_sessions
            memory_card_sessions.finish(sid,ad,ctx)
            from . import gameplay_actions
            gameplay_actions.stop(sid)
            if getattr(ctx, 'server', None):
                httpx.post(f'{ctx.server}/api/sessions/{sid}/ended', headers=ctx.headers,
                           json={'returncode': proc.poll(), 'via': 'single_game'}, timeout=10).raise_for_status()
            sr = rewind.detach(sid)
            SESSIONS.pop(sid, None)
            _teardown(sid, sr)
            continue
        if _session_ended_on_server(ctx, sid):
            # The control plane already ended this session (app relaunch, lost stop): nobody is playing it, so it is
            # closed without a save instead of blocking every new launch on this PC.
            ctx.progress(71, 'Closing a leftover emulator the server had already ended')
            checkpoints.append({'session_id': sid, 'game_id': game.get('game_id'), 'artifact': None, 'orphan': True})
            continue
        ctx.progress(71, 'Saving the previous game before switching')
        try:
            saved = state_transfer(StateXIn(session_id=sid, op='export'), ctx)['result']
        except Exception as exc:
            title = game.get('title') or game.get('game_id') or sid
            raise Unsupported(f"The previous game ({title}) could not be saved: {exc}. It was kept running. Stop it in Sessions "
                              "(or close its emulator window) before starting another game.") from exc
        checkpoints.append({'session_id': sid, 'game_id': game.get('game_id'), **saved})
    for sid, ad, _ in previous:
        if sid not in SESSIONS:
            continue
        sr = rewind.detach(sid)                     # every game was saved above; the ring takes nothing more
        ad.stop_game()
        proc = getattr(ad, 'proc', None)
        if proc and proc.poll() is None:
            rewind.reattach(sid, sr, lambda sid=sid: sid in SESSIONS)
            raise RuntimeError('The previous emulator is still running; another game was not started')
        from . import memory_card_sessions
        memory_card_sessions.finish(sid,ad,ctx)
        from . import gameplay_actions
        gameplay_actions.stop(sid)
        snapshot = next(s for s in checkpoints if s['session_id'] == sid)
        if getattr(ctx, 'server', None) and not snapshot.get('orphan'):
            httpx.post(f'{ctx.server}/api/sessions/{sid}/ended', headers=ctx.headers,
                       json={'via': 'single_game', 'checkpoint': snapshot['artifact']}, timeout=10).raise_for_status()
        SESSIONS.pop(sid, None)
        track_emulator(ctx.config, sid, None, add=False)
        _teardown(sid, sr)
    return checkpoints


STOP_SAVE_CAP_S = 2.0          # Save & stop (only when the operator asks for it) waits at most this long for the save
STOP_MOMENT_CAP_S = 4.0        # Stop with moment (last played): the save + upload of the moment, then the game closes anyway
STOP_TEARDOWN_WAIT_S = 1.0     # rewind / gameplay-ring teardown awaited at most this long; the rest ends in the background


def _within(fn, seconds: float, name: str):
    """Run fn on a daemon thread and wait at most `seconds`: (finished, result, error)."""
    box = {}

    def run():
        try:
            box['result'] = fn()
        except Exception as e:                       # noqa: BLE001 - reported to the caller
            box['error'] = e
    t = threading.Thread(target=run, daemon=True, name=name)
    t.start()
    t.join(max(0.0, seconds))
    return not t.is_alive(), box.get('result'), box.get('error')


def _teardown(sid: str, sr, wait: float = STOP_TEARDOWN_WAIT_S) -> bool:
    """After the emulator is gone: close its rewind (gives the operator's save slot back, deletes the ring) and stop the
    gameplay ring's ffmpeg. A checkpoint still waiting on the dead emulator, or ffmpeg finalising its last segment
    (up to 8 + 5 s), went on the Stop button's clock before (#1504); now it finishes in the background."""
    def work():
        if sr is not None:
            try:
                sr.close()
            except Exception as e:                   # noqa: BLE001
                print(f'gBox: rewind teardown of {sid} failed: {e}', flush=True)
        try:
            ring_record.stop(sid)
        except Exception as e:                       # noqa: BLE001
            print(f'gBox: gameplay ring teardown of {sid} failed: {e}', flush=True)
        try:
            ghost_runs.stop(sid)                     # ghost runs (#1098): the run in progress is kept as session_end
        except Exception as e:                       # noqa: BLE001
            print(f'gBox: ghost-run recorder teardown of {sid} failed: {e}', flush=True)
    return _within(work, wait, f'session-teardown-{sid}')[0]


def _stop_session(sid: str, args: dict, ctx) -> dict:
    """Stop = the emulator's process tree killed now (#1504). A save happens only when the operator asked for one
    (args.save), capped at STOP_SAVE_CAP_S and skipped past it; cleanup never holds the answer."""
    ad, _ = SESSIONS[sid]
    t0 = time.monotonic()
    timings, saved, moment = {}, None, None
    if args.get('moment'):
        # last played (gbox/last_played.py): the moment the operator stopped at, uploaded with this result so "Reload with
        # your last moment" can bring it back. Best effort within moment_cap_s; past it the game is closed regardless.
        cap = float(args.get('moment_cap_s') or STOP_MOMENT_CAP_S)

        def keep_moment():
            out = {'artifact': state_transfer(StateXIn(session_id=sid, op='export'), ctx)['result']['artifact']}
            try:
                png = ad.get_frame()
                ctx.artifact('moment.png', png, 'image/png', session=sid, note='last played moment')
                out['frame'] = sha256(png)
            except Exception:                        # noqa: BLE001 - a moment without a picture still reloads
                pass
            return out
        done, res, err = _within(keep_moment, cap, f'stop-moment-{sid}')
        moment = res if done and err is None else {'skipped': True, 'reason': f'{type(err).__name__}: {err}' if err else
                                                   f'saving took longer than {cap:g} s'}
        timings['moment_s'] = round(time.monotonic() - t0, 3)
    if args.get('save'):
        cap = float(args.get('save_cap_s') or STOP_SAVE_CAP_S)

        def save():
            with rewind.guard(sid, 'save_state'):
                return ad.save_state()
        done, res, err = _within(save, cap, f'stop-save-{sid}')
        if done and err is None:
            saved = res if isinstance(res, dict) else {'value': str(res)[:200]}
        else:
            saved = {'skipped': True, 'reason': f'{type(err).__name__}: {err}' if err else f'the save took longer than {cap:g} s'}
        timings['save_s'] = round(time.monotonic() - t0, 3)
    sr = rewind.detach(sid)
    t = time.monotonic()
    res = ad.stop_game()
    timings['kill_s'] = round(time.monotonic() - t, 3)
    proc = getattr(ad, 'proc', None)
    if proc is not None and proc.poll() is None:
        rewind.reattach(sid, sr, lambda: sid in SESSIONS)
        raise RuntimeError('Emulator process is still running; stop was not confirmed')
    from . import memory_card_sessions
    memory_card_sessions.finish(sid,ad,ctx)
    SESSIONS.pop(sid, None)
    from . import gameplay_actions
    gameplay_actions.stop(sid)
    track_emulator(ctx.config, sid, None, add=False)
    t = time.monotonic()
    timings['teardown_done'] = _teardown(sid, sr)
    timings['teardown_s'] = round(time.monotonic() - t, 3)
    timings['total_s'] = round(time.monotonic() - t0, 3)
    out = dict(res) if isinstance(res, dict) else {'value': str(res)[:200]}
    out['via'] = 'stop'
    out['timings'] = timings
    if saved is not None:
        out['save'] = saved
    if moment is not None:
        out['moment'] = moment
    return {'result': out, 'session_id': sid, 'ended': True}


@tool("launch_game", "1.2", LaunchIn, LaunchOut, capabilities=["runtime"], permissions=[P.EXECUTE], timeout_s=900,
      side_effects=["starts emulator/game process", "may download a core/BIOS", "may stage a copy into cache"],
      validation="adapter reported content running", on_accept=_launch_accept, on_fail=_launch_fail)
def launch_game(inp: LaunchIn, ctx: Ctx):
    """Launch a cataloged game on this node; missing cores/BIOS are installed automatically. Streams to the UI."""
    with _LAUNCH_LOCK:
        diag: dict = {}
        _LAUNCH_DIAG.d = diag                                  # _launch_game records how far it got (one launch at a time)
        try:
            return _launch_game(inp, ctx)
        except Exception as exc:
            ad = diag.get('_adapter')
            # A cancellation after native boot proof but before session
            # registration must not strand a game outside the session ledger.
            if getattr(ad, 'name', None) in {'doa3_native', 'savemgo'} and not any(sr[0] is ad for sr in tuple(SESSIONS.values())):
                try:
                    diag['native_cleanup'] = ad.stop_game()
                except Exception as cleanup_error:
                    diag['native_cleanup_error'] = str(cleanup_error)[:500]
            try:
                from . import memory_card_sessions
                if ad is not None and getattr(ad,'memory_card_context',None):
                    memory_card_sessions.abandon(ad,ctx)
            except Exception:pass
            _launch_failure_evidence(inp, ctx, diag, exc)
            raise
        finally:
            _LAUNCH_DIAG.d = None


_LAUNCH_DIAG = threading.local()


def _launch_failure_evidence(inp: LaunchIn, ctx: Ctx, diag: dict, exc: BaseException):
    """A failed launch leaves its evidence on the job: launch-failure.json (adapter, core, stage reached, timings,
    staging) and the emulator's own log tail, for the launch failure report (gbox/launch_failures.py)."""
    try:
        ad = diag.pop("_adapter", None)
        log = ""
        if ad is not None and callable(getattr(type(ad), "log_tail", None)):
            try:
                log = ad.log_tail(60000) or ""
            except Exception:                                  # noqa: BLE001 - the log may be gone with the process
                log = ""
        info = {k: v for k, v in diag.items() if not k.startswith("_")} | {
            "error": f"{type(exc).__name__}: {exc}"[:4000], "game_id": inp.game.game_id, "mod": inp.mod,
            "boot_timeout_s": inp.boot_timeout_s, "host_os": HOST_OS, "worker_name": __import__("platform").node()}
        ctx.artifact("launch-failure.json", json.dumps(info, default=str, indent=1).encode(), "application/json",
                     game=inp.game.game_id)
        if log:
            ctx.artifact("emulator-log.txt", log.encode("utf-8", "replace"), "text/plain", game=inp.game.game_id)
    except Exception:                                          # noqa: BLE001 - evidence never hides the real error
        pass


def _capture_plan(ad, g, want: str, ctx) -> dict:
    """Backend of an agent-owned Examine 3D capture session (gbox/capture_backend.py): "auto" = the matrix's choice,
    "vulkan" / "glcore" = that driver. RenderDoc is installed on this PC first if it has none (pinned portable build)."""
    from . import capture_backend, scene_capture
    if HOST_OS != "windows":
        raise Unsupported("Examine 3D capture sessions run on a Windows worker (RenderDoc)")
    core = getattr(getattr(ad, "cfg", None), "core", None) or g.core
    plan = capture_backend.plan(ad.name, core)
    if plan is None:
        raise Unsupported(f"{ad.name}{' / ' + str(core) if core else ''} has no 3D capture path (2D frame only)")
    if want in ("vulkan", "glcore") and want != plan["driver"] and ad.name == "retroarch":
        plan = plan | {"driver": want, "attach": "layer" if want == "vulkan" else "inject",
                       "ra_cfg": {"video_driver": want}, "core_options": {} if want == "glcore" else plan["core_options"]}
    ctx.progress(4, f"Capture session: {plan['driver']} with RenderDoc ({'Vulkan layer' if plan['attach'] == 'layer' else 'injected'})")
    rd = scene_capture.renderdoc_dir(provision=True)
    return plan | {"renderdoc": str(rd)}


def _examine_for_launch(inp_examine, examine_ready, host_os):
    """RenderDoc injection (Examine 3D) is opt-in for normal gameplay. Injecting renderdoc.dll
    into every Windows launch hung Dolphin's D3D12 renderer: Soul Calibur II froze ~70 s into
    attract mode with 0% GPU / 0.1% CPU and renderdoc.dll loaded (#1973). A scene capture that
    needs RenderDoc relaunches a dedicated capture session through scene_support.relay() (Vulkan
    layer, no injection), so gameplay never needs RenderDoc resident. Explicit inp.examine and
    the config examine_ready flag remain the two opt-in routes."""
    if host_os != "windows":
        return False
    if inp_examine is not None:
        return bool(inp_examine)
    return bool(examine_ready)


def _launch_game(inp: LaunchIn, ctx: Ctx):
    g = inp.game
    launch_mod = inp.mod
    timings, staging = {}, None
    unlock_result = {'state': 'research_pending', 'applied': False}
    diag = getattr(_LAUNCH_DIAG, "d", None)
    diag = {} if diag is None else diag
    diag["timings"] = timings                                 # filled as the stages pass (a failure shows how far it got)
    t_start = mark = time.monotonic()

    def lap(name):
        nonlocal mark
        now = time.monotonic()
        timings[name] = round(timings.get(name, 0) + now - mark, 3)
        mark = now
    ctx.nowait = True                                     # progress lines never wait on the control plane (registry.Ctx)
    ctx.progress(2, f"Loading {g.title} · {g.system or g.platform}")
    diag["stage"] = "pick emulator"
    ad = adapters.for_game(g.model_dump(), ctx.config, debug=inp.debug, mod=inp.mod)
    ad.capture_gameplay = not getattr(ctx,'agent_use',False) and not inp.capture_backend
    ad.api_server, ad.api_headers = ctx.server or '', ctx.headers
    ad.tas_server, ad.tas_headers = ctx.server or '', ctx.headers
    ad.progress = ctx.progress
    diag.update(_adapter=ad, adapter=ad.name, core=getattr(getattr(ad, "cfg", None), "core", None) or g.core,
                stage="prepare")
    if inp.boot_timeout_s:
        ad.boot_timeout_s = float(inp.boot_timeout_s)
    ad.game_id, ad.serial = g.game_id, g.serial            # per-game settings (graphics) applied at launch
    ad.examine = _examine_for_launch(inp.examine, ctx.config.examine_ready, HOST_OS)
    if inp.capture_backend:
        ad.capture_backend = _capture_plan(ad, g, inp.capture_backend, ctx)
        ad.examine = True
    try:                                                  # Windows: pick + wake the output device while we stage
        prepare = getattr(ad, "prepare_audio", None)
        if prepare:
            prepare()
    except Exception as e:                                 # noqa: BLE001 - never block the launch
        print(f"gBox: audio device prefetch failed: {e}", flush=True)
    ctx.progress(5, f"Runtime: {ad.name}" + (f" · core {g.core}" if g.core else ""))
    lap("runtime_s")
    if g.launch.get("kind") == "steam":
        checkpoints = _close_previous_games(ctx, keep=inp.keep_session)
        lap("close_previous_s")
        detail = ad.launch_game(g.launch["appid"], (g.source_paths or [None])[0])
    elif isinstance(ad, adapters.RocketLauncherAdapter):
        checkpoints = _close_previous_games(ctx, keep=inp.keep_session)
        lap("close_previous_s")
        detail = ad.launch_game(g.launch["emulator"], g.launch["name"])
    else:
        src = rom_path(g, ctx.config)
        # A complete mod is its own game copy. Do not wake/stat the library
        # share just to obtain a base ROM that this launch will never read.
        local_mod = None
        if inp.mod:
            from . import filemods
            folder = filemods.mod_dir(ctx.config, g.game_id, inp.mod)
            if (folder / ".gbox-mod.json").is_file():
                candidate = filemods.launch_path(ctx.config, g.game_id, src, inp.mod)
                if candidate.is_file():
                    local_mod = candidate
        if local_mod is None and not src.exists():
            raise FileNotFoundError(f"ROM not reachable from this node: {src}")
        lap("rom_s")
        if local_mod is None and isinstance(ad, adapters.RPCS3Adapter) and g.launch.get("kind") == "attract":
            eboot = catalog.ps3_stub_eboot(src)            # HyperSpin .txt stub -> its disc folder's EBOOT.BIN (#1093)
            if not eboot:
                raise FileNotFoundError(f"no PS3_GAME/USRDIR/EBOOT.BIN in the folder for {src.name} under {src.parent}")
            ad.serial = ad.serial or catalog.ps3_title_id(eboot)    # per-game RPCS3 config (Sessions -> Graphics)
            ctx.progress(8, f"PS3 game: {eboot}")
            src = eboot
        from . import game_unlocks
        unlock_result = game_unlocks.pre_launch(g.model_dump(), ctx, inp.mod)
        if unlock_result.get('applied'):
            ctx.progress(18, 'Applying verified on-load unlock profile (original save backed up)')
        if inp.mod:
            from . import filemods
            if not (filemods.mod_dir(ctx.config, g.game_id, inp.mod) / ".gbox-mod.json").exists() and ctx.server:
                ctx.progress(20, f"Fetching mod {inp.mod} from the central collection (Spark)")
                launch_mod = filemods.stage(ctx.config, ctx.server, ctx.headers, g.game_id, inp.mod, ctx.progress)
            src = local_mod or filemods.launch_path(ctx.config, g.game_id, src, launch_mod)
            ctx.progress(28, f"Using local build: {launch_mod}")
            diag["staged_mod"] = launch_mod
        lap("mod_s")
        emu = ctx.config.emulators.get(g.platform)
        # big disc images (CHD/ISO/GCZ...) stream poorly over SMB: stage them onto this node's fast local cache
        big = src.is_file() and src.stat().st_size > ctx.config.stage_min_mb * 1024 * 1024
        if g.platform not in ("ps3", "switch") and not (g.launch.get("archive_member") and not inp.mod) and ((emu and emu.stage_local) or (big and g.library and _stageable(src))):   # Switch XCI/NSP streams from the user's share; copying 15+ GB before play stalls launch
            mb = src.stat().st_size / 2**20
            ctx.progress(30, f"Staging {src.name} ({mb:,.0f} MB) to the fast local cache")
            receipt = _stage_for_launch(src, g, ctx, must_wait=bool(emu and emu.stage_local))
            staging = {k: receipt[k] for k in ("copied", "hashed", "seconds", "mb_s", "resumed_from", "background",
                                                "eta_s", "size") if k in receipt}
            diag["staging"] = staging
            if receipt.get("background"):
                left = f"~{receipt['eta_s'] / 60:,.0f} min at {receipt['mb_s']} MB/s" if receipt.get("eta_s") else "share not answering yet"
                ctx.progress(70, f"Playing {src.name} from the library share; the cache copy continues in the background "
                                 f"({left}), so the next launch is local")
            else:
                staged_on = __import__("platform").node()
                ctx.progress(70, f"Staged to cache ({'copied' if receipt.get('copied') else 'reused'}) · evicted {len(receipt['evicted'])}")
                ctx.artifact("staging_receipt.json", json.dumps(receipt).encode(), "application/json", game=g.game_id)
                src = Path(receipt["dst"])
        lap("stage_s")
        if g.launch.get("archive_member") and not inp.mod:
            from . import rom_archives
            src = rom_archives.prepare(src, ctx.config, g.launch["archive_member"], ctx.progress)
            staged_on = __import__("platform").node()
            lap("unpack_s")
        if isinstance(ad, adapters.SaveMGOAdapter):
            diag['stage'] = 'prepare bundled SaveMGO runtime'
            src = ad.prepare_bundle(src)
            staged_on = __import__('platform').node()
            lap('bundle_s')
        if g.game_id in ('b7aecee966090bfa','66062703301f4969') and not getattr(ad,'tas_playback',None):
            from . import sm64_startup
            src,startup=sm64_startup.prepare_launch(src,ctx.config)
            diag['native_startup']=startup
            if startup.get('applied'):ctx.progress(71,'Mario 64: native title startup; automatic empty-save Options disabled')
        diag["stage"] = "close the previous game"
        checkpoints = _close_previous_games(ctx, keep=inp.keep_session)
        lap("close_previous_s")
        from . import memory_card_sessions
        memory_card_sessions.recover_pending(ctx)
        ad.memory_card_rom=str(src)
        memory_card_sessions.checkout(f'{ctx.worker}-{ctx.job_id}',ad,g.model_dump(),ctx)
        ctx.progress(72, f"Starting {ad.name} with {src.name}")
        diag["stage"] = "start the emulator"
        detail = ad.launch_game(str(src))
        if callable(getattr(type(ad), '_boot_frame', None)):
            frame = ad._boot_frame()
            if frame:
                ctx.artifact('native-boot.png', frame[1], 'image/png', game=g.game_id,
                             capture_source='native-back-buffer')
                detail['boot_frame_sha256'] = sha256(frame[1])
    lap("emulator_start_s")                                   # the adapter returns once the content runs (first frames)
    timings["total_s"] = round(time.monotonic() - t_start, 3)
    detail["timings"] = timings                               # #1506: where a launch's time went, per stage
    detail['unlocks'] = unlock_result
    if staging is not None:
        detail["staging"] = staging
    ctx.progress(100, "Running natively in its own window" if detail.get("local_window") else "Running — connecting the stream")
    sid = f"{ctx.worker}-{ctx.job_id}"
    gd = g.model_dump()
    gd['mod'] = launch_mod or ''
    if g.launch.get("kind") != "steam" and not isinstance(ad, adapters.RocketLauncherAdapter):
        gd["_rom_path"] = str(src)                     # for the inspector's ROM viewer
    SESSIONS[sid] = (ad, gd)
    if not inp.capture_backend:
        try:
            from . import gameplay_actions
            detail['action_capture']=gameplay_actions.start(sid,ad,gd,ctx)
        except Exception as error:detail['action_capture']={'state':'unavailable','reason':str(error)[:240]}
    if getattr(ad,'memory_card_context',None):
        from . import memory_card_sessions
        try:detail['memory_cards']=memory_card_sessions.watch(sid,ad,gd,ctx)
        except Exception as error:
            # A card-monitor failure must not turn an already running game into
            # a failed launch. The staged card and recovery journal stay intact.
            detail['memory_cards']={'supported':False,'reason':str(error)[:500]}
    if not inp.capture_backend:
        try:
            from . import gameplay_replay
            detail['gameplay_memory'] = gameplay_replay.start(sid,ad,gd,ctx.server,ctx.headers,lambda:sid in SESSIONS)
        except Exception as e:
            detail['gameplay_memory'] = {'state':'unsupported','reason':type(e).__name__}
        try:
            from . import tas
            detail['tas_capture'] = tas.start(sid, ad, gd, ctx.server, ctx.headers, lambda:sid in SESSIONS)
        except Exception as e:
            detail['tas_capture'] = {'state':'unavailable','reason':str(e)[:240]}
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
        threading.Thread(target=_pump, args=(sid, ad, ctx.server, ctx.headers, ctx), daemon=True).start()
    detail["_game"] = {"game_id": g.game_id, "title": g.title}
    detail["mod"] = launch_mod or ""                           # the actual prepared folder used by this process
    if launch_mod != inp.mod:
        detail["collection_mod"] = inp.mod
    detail['previous_checkpoints'] = checkpoints
    # Select+L2 rewind / Select+R2 fast-forward on the operator's own pad, in every game (#454, #1382): RetroArch's own
    # rewind where it is on, gBox's checkpoint ring elsewhere, the 2x/4x/16x ramp for R2 in both cases (gbox/rewind.py)
    if inp.capture_backend:                                    # Examine 3D capture session: no checkpoint ring, no recording
        detail["capture_session"] = {k: v for k, v in ad.capture_backend.items() if k != "core_options"} | {
            "capture_for": inp.capture_for, "core_options": ad.capture_backend.get("core_options") or {}}
        detail["rewind"] = {"rewind": "unsupported", "reason": "Examine 3D capture session"}
        detail["recording"] = {"state": "unsupported", "reason": "Examine 3D capture session"}
    else:
        try:
            from . import pso_controls
            if pso_controls.is_pso(gd):
                detail["pso_controls"] = pso_controls.on_launch(sid, ad, gd, ctx)
        except Exception as e:                                 # never block a game launch
            detail["pso_controls"] = {"state": "unsupported", "reason": str(e)}
        try:
            detail["rewind"] = rewind.start(sid, ad, ctx.config, gd, inp.rewind, lambda: sid in SESSIONS)
        except Exception as e:                                 # noqa: BLE001 - never block the launch
            detail["rewind"] = {"rewind": "unsupported", "reason": f"rewind setup failed: {e}"}
        # background gameplay ring (#1084): records while the operator's pad is in use, clipped later with the recording tool
        try:
            detail["recording"] = ring_record.start(sid, ad, ctx.config, gd, lambda: sid in SESSIONS)
        except Exception as e:                                 # noqa: BLE001 - never block the launch
            detail["recording"] = {"state": "unsupported", "reason": f"recording setup failed: {e}"}
        # ghost runs (#1098): every run of a profiled game (Super Mario Bros.) recorded from RAM per frame, raced later
        try:
            detail["ghost_runs"] = ghost_runs.start(sid, ad, gd, ctx.server, ctx.headers, lambda: sid in SESSIONS)
        except Exception as e:                                 # noqa: BLE001 - never block the launch
            detail["ghost_runs"] = {"state": "unsupported", "reason": f"ghost-run recorder setup failed: {e}"}
    track_emulator(ctx.config, sid, detail.get("pid") or getattr(getattr(ad, "proc", None), "pid", None))
    if "staged_on" in locals():
        detail["staged_on"] = staged_on
    caps = rewind.capabilities(sid, ad.get_capabilities())
    try:                                                       # Examine 3D: supported / relaunch_under_capture / unsupported
        from .scene_support import session_support
        detail["scene_capture"] = session_support(ad, HOST_OS)
        caps["scene_capture"] = detail["scene_capture"]["status"]
    except Exception as e:                                     # noqa: BLE001 - never block the launch
        detail["scene_capture"] = {"status": "unsupported", "reason": f"capability check failed: {e}", "fallback": "frame_2d"}
        caps["scene_capture"] = "unsupported"
    return {"session_id": sid, "adapter": ad.name, "capabilities": caps, "detail": detail}


def _emulator_in_front(fg_pid: int | None, docked_pids: set, emulator_pids: set, docked_ok: bool, fg_is_gbox: bool = False) -> bool:
    """Should a game hotkey be held right now? Only while the emulator's own window is the foreground window (fg_pid is
    the emulator or one of its child processes), or, with docked_ok, while gBox is: the foreground window has the emulator
    docked inside it (docked_pids = the processes owning that window's child windows) or is the gBox app itself
    (fg_is_gbox: gBox.exe, e.g. showing the game as a GPU capture). Any other application in front (Blender, a
    browser...) -> False: the key is released and reaches that application untouched."""
    if not fg_pid or not emulator_pids:
        return False
    if fg_pid in emulator_pids:
        return True
    return bool(docked_ok and (fg_is_gbox or set(docked_pids or ()) & set(emulator_pids)))


def _exe_name(pid: int | None) -> str:
    """Lower-case image name of a process ("gbox.exe"), "" when unknown."""
    if not pid:
        return ""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, int(pid))                 # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        ok = k32.QueryFullProcessImageNameW(wintypes.HANDLE(h), 0, buf, ctypes.byref(n))
        return Path(buf.value).name.lower() if ok else ""
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


def _process_tree(pids) -> set:
    """pids + every descendant process (wrappers/launchers start the real emulator)."""
    out = set()
    for p in pids:
        if p:
            out.add(p)
            try:
                out.update(adapters._win_descendants(p))
            except OSError:
                pass
    return out


def _foreground_pids(user32, children: bool = True) -> tuple:
    """(foreground window's process id, the process ids owning that window's child windows: a game docked in gBox)."""
    import ctypes
    from ctypes import wintypes
    fg = user32.GetForegroundWindow()
    if not fg:
        return None, set()
    pid, kids = wintypes.DWORD(), set()
    user32.GetWindowThreadProcessId(wintypes.HWND(fg), ctypes.byref(pid))

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        kids.add(p.value)
        return True
    if children:
        user32.EnumChildWindows(wintypes.HWND(fg), cb, 0)
    return pid.value, kids


def _scoped_hotkey(name: str, hk_id: int, vk: int, sessions, fire, docked_ok: bool) -> threading.Thread:
    """Hold RegisterHotKey(vk) ONLY while the emulator is the foreground window (_emulator_in_front), checked every 30 ms:
    registered when it comes to the front, unregistered the moment anything else does, so the key is never taken from
    another application. A press that lands in the gap after a switch is replayed to the window now in front.
    sessions() -> the adapters this hotkey serves (the loop ends, releasing the key, when there are none)."""
    def loop():
        import ctypes
        from ctypes import wintypes
        user32, WM_HOTKEY, msg = ctypes.windll.user32, 0x0312, wintypes.MSG()
        held, tree, tree_at, tree_key, names = False, set(), 0.0, None, {}
        try:
            while targets := sessions():
                pids = tuple(sorted({p for a in targets if (p := getattr(getattr(a, "proc", None), "pid", None))}))
                if pids != tree_key or time.monotonic() - tree_at > 2.0:      # emulator + children, refreshed every 2 s
                    tree, tree_at, tree_key = _process_tree(pids), time.monotonic(), pids
                fg_pid, docked = _foreground_pids(user32, children=docked_ok)
                if len(names) > 256:
                    names.clear()
                if docked_ok and fg_pid and fg_pid not in names:
                    names[fg_pid] = _exe_name(fg_pid)
                front = _emulator_in_front(fg_pid, docked, tree, docked_ok, names.get(fg_pid) == "gbox.exe")
                if front and not held:
                    held = bool(user32.RegisterHotKey(None, hk_id, 0x4000, vk))      # MOD_NOREPEAT
                elif not front and held:
                    user32.UnregisterHotKey(None, hk_id)
                    held = False
                while user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1):
                    if front:
                        fire(targets)
                    else:                                                     # pressed as another app came to the front
                        sc = user32.MapVirtualKeyW(vk, 0)
                        user32.keybd_event(vk, sc, 0, 0)
                        user32.keybd_event(vk, sc, 2, 0)                      # KEYEVENTF_KEYUP
                time.sleep(0.03)
        finally:
            if held:
                user32.UnregisterHotKey(None, hk_id)                          # the key works normally again
    t = threading.Thread(target=loop, daemon=True, name=name)
    t.start()
    return t


_HOTKEY = {"thread": None}


def _ensure_rewind_hotkey():
    """Keypad minus -> rewind 5 s in native RetroArch windows. Held only while that RetroArch window (on its own or docked
    in the gBox window) is in front: Blender and every other app keep keypad minus (zoom out) when they are in front."""
    if _HOTKEY["thread"] and _HOTKEY["thread"].is_alive():
        return

    def fire(targets):
        for a in targets:
            threading.Thread(target=a.rewind, args=(5,), daemon=True).start()
    _HOTKEY["thread"] = _scoped_hotkey(
        "rewind-hotkey", 0xB0C5, 0x6D,                                           # VK_SUBTRACT
        lambda: [a for a, _ in list(SESSIONS.values()) if getattr(a, "rewind_on", False)], fire, docked_ok=True)


_PS3_HOTKEY = {"thread": None}


def _ensure_ps3_load_hotkey():
    """F4 -> load the newest save state (RPCS3 relaunch) while RPCS3's own window is in front; released whenever anything
    else is. Docked in gBox, gBox's own F4 (main.js, held while gBox is in front) loads instead, so the two never overlap."""
    if _PS3_HOTKEY["thread"] and _PS3_HOTKEY["thread"].is_alive():
        return

    def fire(targets):
        for a in targets:
            threading.Thread(target=a.load_state, daemon=True).start()
    _PS3_HOTKEY["thread"] = _scoped_hotkey(
        "ps3-load-hotkey", 0xB0C6, 0x73,                                         # VK_F4
        lambda: [a for a, _ in list(SESSIONS.values()) if isinstance(a, adapters.RPCS3Adapter)], fire, docked_ok=False)


def _stage_for_launch(src: Path, g, ctx, must_wait: bool = False) -> dict:
    """The cache copy of a big library file for this launch (#1506). A file already cached comes back at once (its
    hashes remembered, not re-read). A copy that will finish within config.stage_wait_s is waited for; a longer one
    (7.4 GB at ~10-20 MB/s over Wi-Fi = 6-13 min) goes on in the background, capped at stage_background_mb_s while a
    game plays here, and the game starts from the library share now: {"background": True, ...}."""
    job = catalog.stage_begin(src, g.game_id, ctx.config)
    if isinstance(job, dict):
        return job
    budget = 0.0 if must_wait else float(ctx.config.stage_wait_s or 0)
    t0, shown = time.monotonic(), 0.0
    while not job.finished.wait(0.25):
        done, total, rate = job.done, job.total, job.rate()
        left_s = (total - done) / rate if rate else float("inf")
        if time.monotonic() - shown > 0.5:
            shown = time.monotonic()
            eta = f" · {left_s:,.0f} s left" if rate else ""
            ctx.progress(30 + 40 * done / max(total, 1), f"Staging {src.name}: {done / 2**20:,.0f} / {total / 2**20:,.0f} MB{eta}")
        waited, measured = time.monotonic() - t0, time.monotonic() - job.t0 >= 3
        if budget and (waited >= budget or (measured and waited + left_s > budget)):
            cap = float(ctx.config.stage_background_mb_s or 0) * 2**20
            job.limit = (lambda: cap if SESSIONS else None) if cap > 0 else None
            return {"background": True, "src": str(src), "dst": None, "size": total, "copied": False, "done": done,
                    "mb_s": round(rate / 2**20, 1), "eta_s": round(left_s) if rate else None, "evicted": []}
    return job.result()


def _stageable(src: Path) -> bool:
    # multi-file disc sets reference sibling tracks by relative path; copying only the sheet would break them
    return src.suffix.lower() not in (".cue", ".gdi", ".m3u")


def _rpc_answerer(sid: str, client, ctx=None):
    """Answer live-channel requests (pause/resume, reset, inspector reads) through one keep-alive client. A new httpx
    client per reply builds an SSL context and opens a TCP connection every time, on the path of every click (#1123)."""
    def answer(ev):
        try:
            result = {"ok": True, "data": session_rpc(sid, ev["op"], ev.get("args") or {}, ctx=ctx)}
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if ev.get('op') in ('pso_controls','memory_cards','pso_face'):
            result['pso_command'] = True
        try:
            client.post(f"/api/sessions/{sid}/rpc/{ev['rpc']}", json=result)
        except httpx.HTTPError:
            pass
    return answer

class _EmulatorLiveness:
    """Whether the session's emulator process still runs, polled at most every `every` seconds (poll() per frame at
    60 fps would be wasted work). Adapters without a process handle count as alive."""

    def __init__(self, ad, every: float = 0.5, clock=time.monotonic):
        self.ad, self.every, self.clock = ad, every, clock
        self.at, self.alive = -1e9, True

    def __call__(self) -> bool:
        now = self.clock()
        if now - self.at >= self.every:
            self.at = now
            proc = getattr(self.ad, "__dict__", {}).get("proc")
            try:
                self.alive = proc is None or proc.poll() is None
            except Exception:                            # noqa: BLE001 - unknown means keep streaming
                self.alive = True
        return self.alive


def _stream_event_reporter(sid: str, server: str, headers: dict):
    """Encoder stalls/restarts go to the control plane (GET /api/sessions/{sid}/stream/health) from one background
    thread with a bounded queue: reporting can never block or slow the frame path."""
    import queue
    q = queue.Queue(maxsize=50)

    def run():
        with httpx.Client(base_url=server, headers=headers, timeout=5) as c:
            while sid in SESSIONS or not q.empty():
                try:
                    ev = q.get(timeout=5)
                except queue.Empty:
                    continue
                try:
                    c.post(f"/api/sessions/{sid}/stream/event", json=ev)
                except httpx.HTTPError:
                    pass
    threading.Thread(target=run, daemon=True, name=f"stream-events-{sid}").start()

    def report(ev: dict):
        try:
            q.put_nowait(ev)
        except queue.Full:
            pass
    return report


def _pump(sid: str, ad, server: str, headers: dict, ctx=None):
    """Live session plumbing, three independent loops so nothing slow can stall the video:
    frames  - pushed the moment the encoder produces one (up to the stream fps, 60),
    input   - long-polled from the control plane and applied immediately,
    status  - every 3 s; marks the session ended when the emulator exits."""
    stream = ad.stream_session() if "stream_session" in ad.supported else None
    if stream is not None and hasattr(stream, "events"):
        stream.label = sid
        stream.on_event = _stream_event_reporter(sid, server, headers)

    def frames():
        if stream is None:                               # local native window: nothing to stream
            return
        # one long-lived upload per session: [4-byte big-endian length][JPEG] ... (a POST per frame capped at ~6 fps)
        def body():
            last, live = -1, _EmulatorLiveness(ad)
            while sid in SESSIONS:
                if stream.wait(last, 1.0):
                    last, data = stream.seq, stream.latest
                    # An exited emulator leaves its virtual display empty (black). Those grabs are never sent: the
                    # operator keeps the last real game frame until the session ends or the game comes back.
                    yield (len(data).to_bytes(4, "big") + data) if live() else b"\0\0\0\0"
                else:
                    yield b"\0\0\0\0"                     # keepalive (zero-length frame)
        while sid in SESSIONS:
            try:
                with httpx.Client(base_url=server, headers=headers, timeout=httpx.Timeout(10, read=None, write=None)) as c:
                    c.post(f"/api/sessions/{sid}/stream", content=body(), headers={"content-type": "application/octet-stream"})
            except httpx.HTTPError as e:
                if sid in SESSIONS:
                    print(f"gBox stream: upload of {sid} interrupted at {adapters._wall()} "
                          f"({type(e).__name__}); reconnecting", flush=True)
                time.sleep(1)

    answer = _rpc_answerer(sid, httpx.Client(base_url=server, headers=headers, timeout=10), ctx)

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
                    if pad:
                        game_pad = rewind.feed(sid, pad)      # Consume time chords before injecting game input.
                        ring_record.touch(sid, pad)           # the operator's pad in use: the gameplay ring records
                    if pad and "send_input" in ad.supported:
                        ad.send_input(game_pad)
                except Exception:
                    time.sleep(0.5)

    threading.Thread(target=frames, daemon=True).start()
    threading.Thread(target=inputs, daemon=True).start()
    if sys.platform == "win32":                                  # mirror the operator's own pad to the controller glyph
        from . import padstate
        threading.Thread(target=padstate.watch_xinput, args=(server, headers, sid, lambda: sid in SESSIONS), daemon=True).start()
    with httpx.Client(base_url=server, headers=headers, timeout=10) as c:
        pid = getattr(getattr(ad, "proc", None), "pid", None)
        scene_watch = _scene_row_watch(ad)                 # Examine 3D row still settling (#971)
        while sid in SESSIONS:
            time.sleep(3)
            try:
                now = getattr(getattr(ad, "proc", None), "pid", None)
                if now and now != pid:                     # emulator relaunched in place (RPCS3 load state): re-dock it
                    c.post(f"/api/sessions/{sid}/detail", json={"pid": now})
                    pid = now
                if scene_watch:                                # the Vulkan layer loads once the game boots
                    scene_watch = _refresh_scene_row(c, sid, ad)
                running = ad.proc.poll() is None if getattr(ad, "proc", None) else ad.query_runtime().get("running", True)
                if not running:
                    from . import gameplay_actions
                    gameplay_actions.stop(sid)
                    from . import memory_card_sessions
                    memory_card_sessions.finish(sid,ad,ctx)
                    rc = getattr(getattr(ad, "proc", None), "returncode", None)
                    end = {"returncode": rc}
                    if rc not in (None, 0) and callable(getattr(type(ad), "log_tail", None)):
                        try:                                   # a crash report (gbox/launch_failures.py) wants the log
                            end["log_tail"] = (ad.log_tail(20000) or "")[-20000:]
                        except Exception:                      # noqa: BLE001
                            pass
                    c.post(f"/api/sessions/{sid}/ended", json=end)
                    rewind.stop(sid)
                    ring_record.stop(sid)
                    try:
                        ghost_runs.stop(sid)
                    except Exception:                  # noqa: BLE001
                        pass
                    SESSIONS.pop(sid, None)
            except Exception:
                pass


def _scene_row_watch(ad) -> bool:
    """Whether this session's Examine 3D row may still change: started with RenderDoc's Vulkan layer, which hasn't
    loaded yet (Yuzu / RPCS3 create their Vulkan device once the game boots, after the launch check, #971)."""
    info = getattr(getattr(ad, "proc", None), "renderdoc", None)
    return isinstance(info, dict) and info.get("attach") == "layer" and "error" not in info and not info.get("loaded")


def _refresh_scene_row(c, sid: str, ad) -> bool:
    """Re-rate a pending Examine 3D row; once it settles, post it to the session detail (the Examine 3D panel and
    the relay decision read it there). Returns whether to keep watching."""
    from .scene_support import session_support
    row = session_support(ad, HOST_OS)
    if row.get("layer") == "pending":
        return True
    c.post(f"/api/sessions/{sid}/detail", json={"scene_capture": row, "examine": row.get("status") == "supported"})
    return False



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


def session_rpc(sid: str, op: str, args: dict, ctx=None):
    ad, g = SESSIONS[sid]
    if op=='memory_cards':
        from .memory_card_sessions import execute
        return execute(sid,args,ctx)
    if op=='pso_face':
        from .pso_faces import live
        return live(sid,args,ctx)
    if op == 'pso_controls':
        from .pso_live import execute
        return execute(sid, args, ctx)
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
                "capabilities": rewind.capabilities(sid, ad.get_capabilities()), "runtime": ad.query_runtime(),
                "fast_forward": rewind.fast_forward_status(sid, ad), "time_controls": rewind.status(sid)}
    if op == "normal_speed":
        return rewind.set_fast_forward(sid, ad, on=False, recover=True)
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
    if out.ended and (s := store.get("session", out.session_id)):
        from .session_exit import intentional
        m = out.result.get("moment") if isinstance(out.result.get("moment"), dict) else {}
        if s.get('state') == 'ended' and not (intentional(out.result) or m.get('artifact')):
            return  # No new close intent or checkpoint: preserve the verified terminal record.
        moment_ts = s.get('moment_ts') if s.get('checkpoint') == m.get('artifact') else None
        kept = {"checkpoint": m["artifact"], "moment_ts": moment_ts or time.time(), **({"moment_frame": m["frame"]} if m.get("frame") else {})} \
            if m.get("artifact") else {}                     # last played: the moment saved as the game stopped
        from .session_exit import merge
        store.put("session", out.session_id, s | {"state": "ended", "ended": s.get("ended") or time.time(),
                                                  "exit": merge(s.get("exit"), out.result), **kept})

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
            raise Unsupported(f"{getattr(ad, 'name', 'this emulator')} has no reset of its own (POST /api/sessions/{{sid}}/reset "
                              "relaunches the same game and mod on this PC instead, the old copy closing only once it runs)")
        return {"result": ad.reset() or {"reset": True}, "session_id": inp.session_id, "ended": False}
    if inp.op not in adapters.OPS or inp.op in ("write_memory", "read_memory", "launch_game"):
        raise ValueError(f"op {inp.op} not allowed via session_op")
    if inp.op == "stop_game":
        return _stop_session(inp.session_id, inp.args or {}, ctx)
    if inp.op == "send_input":                                       # controller glyph shows gBox's presses
        from . import padstate
        padstate.report(ctx, inp.session_id, inp.args.get("events"), "agent")
    ad, _ = SESSIONS[inp.session_id]
    if inp.op == "fast_forward":
        return {"result": rewind.set_fast_forward(inp.session_id, ad, inp.args.get("on"),
                                                recover=inp.args.get("on") is False),
                "session_id": inp.session_id, "ended": False}
    if inp.op == "rewind" and rewind.mode(inp.session_id) == "checkpoint":   # gBox's checkpoint ring, not the emulator's buffer
        res = rewind.step(inp.session_id, float(inp.args.get("seconds", 5.0)))
    else:
        with rewind.guard(inp.session_id, inp.op):                          # the ring takes no checkpoint during a save / load
            try:
                res = getattr(ad, inp.op)(**inp.args)
            except TypeError:
                if "slot" not in inp.args:
                    raise
                res = getattr(ad, inp.op)(**{k: v for k, v in inp.args.items() if k != "slot"})   # emulator with one slot
    if inp.op in ('save_state','load_state') and isinstance(res,dict):
        try:
            path=res.get('path')
            if not path and getattr(ad,'name','')=='retroarch':path=ad.checkpoint_target()
            if not path and getattr(ad,'name','')=='dolphin':path=Path(ad.state_dir())/(ad.serial+'.s01')
            callback=getattr(ad,'gameplay_checkpoint',None)
            if path and Path(path).is_file() and callback:callback(Path(path),'checkpoint' if inp.op=='save_state' else 'restore')
        except Exception:pass  # Capture must not alter the result of a completed state operation.
    if inp.op == "save_state" and isinstance(res, dict):            # thumbnail for the save-state film strip
        if getattr(ad, 'name', '') == 'retroarch' and res.get('path'):
            _validate_state_container(Path(res['path']).read_bytes(), 'retroarch')
        try:
            png = ad.get_frame()
            ctx.artifact("state.png", png, "image/png", session=inp.session_id, slot=res.get("slot"))
            res["frame"] = sha256(png)
        except Exception:
            pass
    return {"result": res if isinstance(res, dict) else {"value": str(res)[:200]}, "session_id": inp.session_id,
            "ended": False}


# --- background gameplay ring (#1084) -------------------------------------------------------

class RecordingIn(BaseModel):
    session_id: str
    op: str = "status"                     # status | export | enable | disable
    in_s: float | None = None              # export: the clip starts this many recorded seconds before the newest moment (None: all)
    out_s: float = 0.0                     # export: and ends this many seconds before it (0 = the newest moment)
    target_mb: float = 20.0                # export: file size goal in MiB; the bitrate (and, if needed, the resolution) follow it

class RecordingOut(BaseModel):
    session_id: str
    op: str
    status: dict
    clip: dict | None = None               # export: {sha256, name, bytes, seconds, kbps, width, height, encoder, fits, ...}

def _recording_validate(out: RecordingOut, arts) -> list[str]:
    if out.op != "export":
        return []
    clip = out.clip or {}
    data = arts.get(clip.get("name") or "")
    if data is None:
        return ["exported clip artifact missing"]
    if sha256(data) != clip.get("sha256") or len(data) != clip.get("bytes"):
        return ["clip artifact hash / size does not match the output"]
    return [] if data[4:8] == b"ftyp" else ["clip artifact is not an MP4"]

@tool("recording", "1.0", RecordingIn, RecordingOut, capabilities=["video", "runtime"], permissions=[P.EXECUTE], timeout_s=900,
      side_effects=["background ffmpeg capture of the session while the pad is in use (bounded ring on local disk)"],
      artifacts=["replay-*.mp4"], validation="clip artifact hash + size + MP4 signature", validate=_recording_validate,
      check=lambda c: None if shutil.which("ffmpeg") else "ffmpeg not on PATH")
def recording(inp: RecordingIn, ctx: Ctx):
    """Background gameplay ring of a session (#1084): status (timeline, encoder), export the range in_s..out_s seconds
    before the newest recorded moment as an MP4 of about target_mb, or enable / disable the capture for the session."""
    ring = ring_record.get(inp.session_id)
    op = inp.op.lower()
    clip = None
    if op in ("enable", "disable"):
        ring.set_enabled(op == "enable")
    elif op == "export":
        ctx.progress(10, "Copying the recorded segments")
        res = ring.export(inp.in_s, inp.out_s, inp.target_mb, progress=ctx.progress)
        path = res.pop("file")
        try:
            data = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)
        ctx.artifact(res["name"], data, "video/mp4", session=inp.session_id, game=ring.meta.get("game_id"),
                     title=ring.meta.get("title"), seconds=res["seconds"], in_s=res["in_s"], out_s=res["out_s"],
                     target_mb=res["target_mb"], encoder=res["encoder"], replay=True)
        clip = res | {"sha256": sha256(data), "bytes": len(data)}
        ctx.progress(100, f"Clip ready: {len(data) / 2**20:.1f} MB, {res['seconds']:.0f} s, {res['height']}p ({res['encoder']})")
    elif op != "status":
        raise ValueError(f"unknown op {inp.op} (status, export, enable, disable)")
    return {"session_id": inp.session_id, "op": op, "status": ring.status(), "clip": clip}


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


def _gcheat_loop(sid: str, c: dict, on=None):
    from contextlib import nullcontext
    ad, _ = SESSIONS[sid]
    dbg = getattr(ad, "dbg", None)
    on = c["on"] if on is None else on     # capture before thread start, not after a later re-enable
    while on.is_set() and sid in SESSIONS:
        try:
            with c.get("lock") or nullcontext():
                # Native-table handoff clears the event under this same lock.
                # Recheck here so a waiting iteration cannot write after transfer.
                if not on.is_set() or sid not in SESSIONS:
                    break
                if dbg is not None:
                    with dbg.paused():                     # one halt for the whole batch on debugger sessions
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
    from . import native_cheat_runtime as NCR
    def probe_native(index, ops):
        before = []
        for kind, address, data in ops:
            original = ad.read_memory(address, len(data))
            if len(original) != len(data):
                raise RuntimeError(f"Native cheat read returned too few bytes at {address:#x}")
            before.append({"address": hex(address), "bytes": original.hex()})
        ctx.artifact("cheat_before.json", json.dumps(before).encode(), "application/json",
                     note="rollback data before native cheat enable", index=index)
        _gcheat_apply(ad, ops)
        for kind, address, data in ops:
            if ad.read_memory(address, len(data)) != data:
                raise RuntimeError(f"Native cheat write did not read back correctly at {address:#x}; freeze was not enabled")
    native = NCR.runtime(ad, g.get("platform", ""), mine,
                         lambda c: threading.Thread(target=_gcheat_loop, args=(inp.session_id, c, c["on"]), daemon=True).start()) \
        if any(NCR.is_native(e) for e in ra) or getattr(ad, '_gbox_native_cheats', None) is not None else None
    if inp.op in ("list", "search"):
        q = inp.query.lower()
        rows = [{"index": i, "desc": e.get("desc", ""), "enabled": e["enable"], "engine": "emulator",
                 "code": e.get("code") or (f"addr {e.get('address')} = {e.get('value')}" if e.get("address") else "")}
                for i, e in enumerate(ra)]
        for row in rows:
            if native is not None and row["index"] in native.logical:
                row["enabled"] = native.enabled(row["index"])
                if any(c.get("native_runtime") is native and c.get("native_index") == row["index"] for c in mine):
                    row["engine"] = native.engine(row["index"])
        rows += [{"index": len(ra) + i, "desc": c["desc"],
                  "enabled": c["native_runtime"].enabled(c["native_index"]) if "native_runtime" in c else c["on"].is_set(),
                  "engine": c["native_runtime"].engine(c["native_index"]) if "native_runtime" in c else "gbox",
                  "code": " / ".join(c["lines"])} for i, c in enumerate(mine)]
        if q:
            rows = [r for r, s in sorted(((r, C.match_query(q, r["desc"], r["code"])) for r in rows),
                                         key=lambda x: -x[1]) if s > 0]
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
            if native is not None and NCR.is_native(e):
                return {"result": native.set(inp.index, on, probe=probe_native), "session_id": inp.session_id}
            ops, bad = C.decode(g.get("platform", ""), e.get("code", "") or "")
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
        if "native_runtime" in c:
            result = c["native_runtime"].set(c["native_index"], on, probe=probe_native)
            return {"result": result | {"index": inp.index, "database_index": c["native_index"]},
                    "session_id": inp.session_id}
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
    """Mean full-range BT.601 luma of a PNG frame: 0-255, ~0 means a black screen.

    Decoded in-process with Pillow (a declared dependency; emulation_issue.py uses the same measure). The probe is
    best effort and must never fail a capture: #1546's observer get_frame job dcad3153a9564007 failed because an
    ffmpeg signalstats subprocess timed out after 30 s on a loaded operator PC. ffmpeg's YAVG is also limited-range
    for colour PNGs (black 16, white 235), so the `< 6` / `<= 3` black-screen guards never fired on black frames.
    """
    try:
        from io import BytesIO
        from PIL import Image, ImageStat
        with Image.open(BytesIO(png)) as im:
            return round(ImageStat.Stat(im.convert("L")).mean[0], 2)
    except Exception:                      # no Pillow / undecodable: hardened ffmpeg fallback, still non-fatal
        return _ffmpeg_luma(png)


def _ffmpeg_luma(png: bytes, timeout: float = 10) -> float | None:
    """ffmpeg signalstats YAVG mapped to full range; None on any failure (missing ffmpeg, timeout, bad output)."""
    exe = shutil.which("ffmpeg")
    if not exe or png[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            f = Path(t) / "f.png"
            f.write_bytes(png)
            r = subprocess.run([exe, "-hide_banner", "-nostdin", "-i", str(f), "-frames:v", "1", "-vf",
                                "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    for ln in ((r.stdout or "") + (r.stderr or "")).splitlines():
        if "YAVG=" in ln:
            try:
                y = float(ln.split("YAVG=")[1].split()[0])
            except (IndexError, ValueError):
                return None
            if png[25:26] not in (b"\x00", b"\x04"):   # colour/palette PNG -> limited-range YUV; grey stays full
                y = (y - 16) * 255 / 219
            return round(min(255.0, max(0.0, y)), 2)
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
    op: str = "state"                      # state | skip_deku_tree | goto | give | kit | full_inventory | scale_link | scale_sword | scale_status | scale_release
    place: str = ""                        # goto: "end of the shadow temple", "final battle", "gohma", "kakariko"...
    item: str = ""                         # give: "hookshot", "longshot", "bow"...
    c_button: int = 0                      # give: also put it on C-left/down/right (1-3)
    kit: str = ""                          # kit: child | adult | endgame
    factor: float = 1.0                    # scale_link / scale_sword: size multiplier (2 = twice as big; 1 = back to normal)
    reach: bool = True                     # scale_sword: the sword's hit range grows with it (sMeleeWeaponLengths in code)
    cutscene: bool = False                 # skip_deku_tree: play the Deku Tree farewell cutscene


class OotOut(BaseModel):
    result: dict


@tool("zelda_oot", "1.0", OotIn, OotOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=180)
def zelda_oot(inp: OotIn, ctx: Ctx):
    """Zelda: Ocarina of Time (N64 USA 1.0 / 1.1 / 1.2) on a live session: skip the Deku Tree, warp anywhere (dungeons, boss rooms,
    the final battle) with the gear for it, give/equip items, make Link bigger (scale_link) or only his sword (scale_sword:
    hand and shield stay, the hit range follows) - both held across scene changes by gbox.oot_scale, factor 1 restores.
    Warps are guarded: a save state is taken first and reloaded automatically if the game hangs; the result says whether
    the warp landed."""
    from . import oot, oot_scale
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
    if inp.op in ("scale", "scale_link"):                     # scale: the old name of scale_link
        return {"result": oot_scale.hold_link(ad, inp.session_id, inp.factor)}
    if inp.op == "scale_sword":
        return {"result": oot_scale.apply_sword(ad, inp.session_id, inp.factor, inp.reach)}
    if inp.op == "scale_status":
        now = oot_scale.link_scale(ad)
        return {"result": oot_scale.status(inp.session_id) | {"link_scale": list(now) if now else None}}
    if inp.op == "scale_release":
        return {"result": oot_scale.release(ad, inp.session_id)}
    if inp.op not in ("skip_deku_tree", "goto"):
        raise ValueError("op: state | skip_deku_tree | goto | give | kit | full_inventory | scale_link | scale_sword | "
                         "scale_status | scale_release")
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
    guest: str = ""                        # minigame session (e.g. Tetris DS, parked on a save state of the match); it may
                                           #   run on another worker: it is then driven through the control plane
    # watch specs: {"address": "0x..", "type": "u8|u16|u32|f32", "eq"|"ne"|"lt"|"gt"|"ge"|"le": value}
    #   + "path": pointer steps from address (int = deref at that offset; {"walk": next_off, "until": {"offset", "mask"}}
    #     follows a linked list; {"add": off}), e.g. GWorld -> ... -> player pawn -> field;
    #   or {"any": [spec, ...]} / {"all": [spec, ...]}
    trigger: dict = {}                     # host: when true, a shot/moment starts
    win: dict = {}                         # guest: when true, the player won the match
    lose: dict = {}                        # guest: when true, the player lost
    on_win: str = "god_hit"                # host script_patch preset for a win
    on_lose: str = "god_miss"              # ... and for a loss
    poll_s: float = 0.1
    style: str = "pause"                   # pause: freeze the host | overlay: host keeps running in slow motion behind
                                           #   the guest's UI | pip: freeze the host, the guest's picture in a corner of it
    overlay_rects: list[list[float]] = []  #   the guest's UI clipped to these rects (fractions of its picture)
    slow_rate: float = 0.08                #   host speed while the minigame runs (overlay style)
    pip_box: list[float] = [0.56, 0.04, 0.4, 0.6]   # pip style: x, y, w, h of the guest window as fractions of the host's
    guest_reload: bool = True              # load the guest's parked save state at the start of every round

class LinkOut(BaseModel):
    result: dict

LINKS: dict[str, dict] = {}


_WATCH_OPS = (("eq", lambda a, b: a == b), ("ne", lambda a, b: a != b), ("lt", lambda a, b: a < b),
              ("gt", lambda a, b: a > b), ("ge", lambda a, b: a >= b), ("le", lambda a, b: a <= b))


def _watch_address(ad, spec: dict, big: bool) -> int | None:
    """The address a watch spec reads: its address, followed along its pointer path. None = a null pointer on the way
    (e.g. no player pawn during a loading screen)."""
    import struct as S
    def ptr(a):
        return S.unpack(("<>"[big]) + "I", ad.read_memory(a, 4))[0]
    a = int(str(spec["address"]), 0)
    for step in spec.get("path", []):
        if not isinstance(step, dict):
            step = {"deref": step}
        if "deref" in step:
            a = ptr(a + int(str(step["deref"]), 0))
        elif "walk" in step:                               # linked list: first node whose until-field has the mask bits
            u, nxt = step["until"], int(str(step["walk"]), 0)
            for _ in range(int(step.get("max", 64))):
                if not a or ptr(a + int(str(u["offset"]), 0)) & int(str(u.get("mask", "0xFFFFFFFF")), 0):
                    break
                a = ptr(a + nxt)
            else:
                return None
        elif "add" in step:
            a += int(str(step["add"]), 0)
        if not a:
            return None
    return a


def _watch_true(ad, spec: dict, big: bool) -> bool:
    import struct as S
    if "any" in spec:
        return any(_watch_true(ad, s, big) for s in spec["any"])
    if "all" in spec:
        return all(_watch_true(ad, s, big) for s in spec["all"])
    typ = spec.get("type", "u32")
    w = {"u8": 1, "u16": 2, "u32": 4, "f32": 4}[typ]
    fmt = ("<>"[big]) + {"u8": "B", "u16": "H", "u32": "I", "f32": "f"}[typ]
    if spec.get("path"):
        try:
            a = _watch_address(ad, spec, big)
        except Exception:                                  # unmapped pointer mid-chain: the object is not there yet
            return False
        if a is None:
            return False
    else:
        a = int(str(spec["address"]), 0)
    v = S.unpack(fmt, ad.read_memory(a, w))[0]
    return any(op in spec and f(v, spec[op]) for op, f in _WATCH_OPS)


class RemoteSession:
    """A live session on another worker, driven through the control plane: memory reads and pause/resume over the
    session's live channel (POST /api/sessions/{sid}/rpc), save-state loads as a session_op job routed to its worker.
    Lets a game_link host (Stranglehold on the operator's PC) use a guest that runs elsewhere (Tetris DS on the Spark)."""
    name = "remote"
    supported = {"read_memory", "pause", "resume", "load_state"}

    def __init__(self, sid: str, server: str, headers: dict | None = None, call=None):
        self.sid, self.server, self.headers = sid, server, headers or {}
        self._call = call or self._http
        self._info = None

    def _http(self, method: str, path: str, body: dict | None = None):
        r = httpx.request(method, f"{self.server}{path}", headers=self.headers, json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _rpc(self, op: str, args: dict | None = None):
        return self._call("POST", f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args or {}})

    def info(self) -> dict:
        if self._info is None:
            self._info = self._rpc("info") or {}
        return self._info

    def read_memory(self, address: int, length: int) -> bytes:
        return bytes.fromhex(self._rpc("read_memory", {"address": address, "length": length}))

    def pause(self) -> dict:
        return self._rpc("pause") or {}

    def resume(self) -> dict:
        return self._rpc("resume") or {}

    def load_state(self, slot: int | None = None, wait_s: float = 90) -> dict:
        j = self._call("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": self.sid, "op": "load_state", "args": {} if slot is None else {"slot": slot}}})
        t0 = time.time()
        while j.get("state") in ("queued", "running") and time.time() - t0 < wait_s:
            time.sleep(0.5)
            j = self._call("GET", f"/api/jobs/{j['id']}", None)
        if j.get("state") != "succeeded":
            raise RuntimeError(f"guest load_state: {j.get('state')} {j.get('error') or ''}".strip())
        return (j.get("output") or {}).get("result") or {}


def _link_session(L: dict, sid: str):
    """(adapter, game) for a link session: this worker's own, else a RemoteSession through the control plane."""
    if sid in SESSIONS:
        return SESSIONS[sid]
    if not L.get("server"):
        raise KeyError(f"session {sid} is not on this worker and no control plane is known")
    rem = L.setdefault("remote", {})
    if sid not in rem:
        ad = RemoteSession(sid, L["server"], L.get("headers"), L.get("call"))
        rem[sid] = (ad, {"platform": ad.info().get("platform"), "title": ad.info().get("title"), "remote": True})
    return rem[sid]


def _link_loop(key: str):
    """Host moment -> pause host, play the guest minigame from its save state -> verdict preset on the host -> resume."""
    L = LINKS[key]
    hs, gs = L["in"].host, L["in"].guest
    while L["on"]:
        try:
            had, hg = SESSIONS[hs]
            gad, gg = _link_session(L, gs)
            if not _watch_true(had, L["in"].trigger, hg.get("platform") in BIG_ENDIAN):
                time.sleep(L["in"].poll_s)
                continue
            overlay = L["in"].style == "overlay" and L["in"].overlay_rects and hasattr(had, "slowmo")
            local_windows = HOST_OS == "windows" and getattr(gad, "proc", None) and getattr(had, "proc", None)
            pip = L["in"].style == "pip"
            had.slowmo(L["in"].slow_rate) if overlay else had.pause()
            L["state"], L["rounds"] = "minigame", L["rounds"] + 1
            gad.resume()
            if L["in"].guest_reload:
                gad.load_state()                           # back to the parked match
            if HOST_OS == "windows" and getattr(gad, "proc", None):   # RPCS3 load state = relaunch: wait for its window
                from . import overlay as ov
                for _ in range(120):
                    if ov.game_window(gad.proc.pid):
                        break
                    time.sleep(0.25)
            time.sleep(2)                                  # ponytail: settle after the reload; tune per game
            if overlay and local_windows:                  # Tetris UI over the slow-motion bullet scene
                from . import overlay as ov
                ov.overlay_on(gad.proc.pid, had.proc.pid, L["in"].overlay_rects)
            if pip:                                        # guest picture in a corner of the frozen host
                if local_windows:
                    from . import overlay as ov
                    L["pip"] = {"session_id": gs, "window": ov.pip_on(gad.proc.pid, had.proc.pid, L["in"].pip_box)}
                else:                                      # another worker: the app shows its stream picture-in-picture
                    L["pip"] = {"session_id": gs, "mjpeg": f"/api/sessions/{gs}/mjpeg", "title": gg.get("title")}
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
            if (overlay or pip) and local_windows:
                from . import overlay as ov
                ov.overlay_off(gad.proc.pid)
            if overlay:
                had.slowmo(1.0)
            L["pip"] = None
            # the verdict goes in while the host is still frozen, so the shot cannot resolve before it
            getattr(script_patch, "__wrapped__", script_patch)(
                ScriptPatchIn(session_id=hs, op="preset", preset=L["in"].on_win if verdict == "win" else L["in"].on_lose), _quiet())
            had.resume()
            L["history"].append({"round": L["rounds"], "verdict": verdict, "at": time.time()})
            L["state"] = "waiting"
            while L["on"] and _watch_true(had, L["in"].trigger, hg.get("platform") in BIG_ENDIAN):
                time.sleep(L["in"].poll_s)                 # let this moment finish before arming again
        except Exception as e:
            L["error"] = f"{type(e).__name__}: {e}"
            if L.get("state") == "minigame":               # never leave the host frozen after a failed round
                L["state"] = "waiting"
                try:
                    SESSIONS[hs][0].resume()
                    while L["on"] and _watch_true(SESSIONS[hs][0], L["in"].trigger, SESSIONS[hs][1].get("platform") in BIG_ENDIAN):
                        time.sleep(L["in"].poll_s)         # no new round for the moment that failed
                except Exception:
                    pass
            time.sleep(1)


@tool("game_link", "1.0", LinkIn, LinkOut, capabilities=["runtime", "memory", "mod"], permissions=[P.MEMORY_WRITE],
      side_effects=["pauses/resumes two live sessions and applies script-patch presets on the host"])
def game_link(inp: LinkIn, ctx: Ctx):
    """Cross-game link: when the host game's trigger fires (e.g. Stranglehold precision aim), pause it and play a match
    in the guest game (e.g. Tetris DS or Puyo Puyo Tetris, from its save state; the guest may run on another worker);
    a win/lose applies the host preset (hit / miss) before the host resumes."""
    key = f"{inp.host}|{inp.guest}"
    if inp.op == "start":
        def has_address(spec):
            return bool(spec.get("address")) or any(has_address(s) for s in spec.get("any", []) + spec.get("all", []))
        for need in ("trigger", "win", "lose"):
            if not has_address(getattr(inp, need)):
                raise ValueError(f"{need} needs an address (find it with memory_search)")
        if key in LINKS:
            LINKS[key]["on"] = False                       # a restart replaces the running loop
        LINKS[key] = {"in": inp, "on": True, "state": "waiting", "rounds": 0, "history": [], "error": None, "pip": None,
                      "server": getattr(ctx, "server", None), "headers": getattr(ctx, "headers", None)}
        threading.Thread(target=_link_loop, args=(key,), daemon=True).start()
    elif inp.op == "stop" and key in LINKS:
        LINKS[key]["on"] = False
    L = LINKS.get(key) or {}
    return {"result": {"running": L.get("on", False), "state": L.get("state"), "rounds": L.get("rounds", 0),
                       "history": L.get("history", [])[-10:], "error": L.get("error"), "pip": L.get("pip"),
                       "guest_remote": inp.guest not in SESSIONS if inp.guest else None}}


class BevyIn(BaseModel):
    name: str = "scene"
    # [{"package": "pso_dc_forest01", "translation": [x,y,z], "scale": 1.0, "rotation_y_deg": 0}]
    items: list[dict] = []
    camera: dict = {}                      # {"eye": [x,y,z], "target": [x,y,z]}
    screenshot: bool = True                # render: True = capture a PNG and exit; False = open an interactive window
    op: str = "render"                     # render | open | snapshot | set_camera | add | remove | close | list
    index: int | None = None               # remove: which item (0-based)

class BevyOut(BaseModel):
    scene: str = ""
    screenshot: str | None = None
    pid: int | None = None
    items: list[dict] = []
    live: list[dict] = []
    scenes: list[dict] = []
    renders: list[dict] = []


VIEWER_SRC = Path(__file__).resolve().parent.parent / "projects" / "gbox_viewer"

# Live Bevy windows on this worker: name -> {"proc": Popen, "scene": Path (scene.json), "spec": {...}}
BEVY: dict[str, dict] = {}


def _abs(p) -> str:                        # glTF paths in scene.json: absolute, forward slashes (Path.join on the
    return str(Path(p).resolve()).replace("\\", "/")   # viewer side makes them pass through unchanged on every OS)


def _bevy_viewer_exe(ctx) -> Path:
    target = ctx.config.runtime / "bevy-target"        # local SSD; Bevy's ~500 crates compile once
    return target / "release" / ("gbox_viewer.exe" if HOST_OS == "windows" else "gbox_viewer")


def _bevy_build(ctx, target: Path, exe: Path):
    if exe.exists() and VIEWER_SRC.joinpath("src", "main.rs").stat().st_mtime <= exe.stat().st_mtime:
        return
    ctx.progress(10, "building the Bevy viewer (first build takes several minutes)")
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
    r = subprocess.run([cargo, "build", "--release"], cwd=VIEWER_SRC, capture_output=True, text=True,
                       env=dict(os.environ, CARGO_TARGET_DIR=str(target)), timeout=3000)
    if r.returncode:
        raise RuntimeError("cargo build failed:\n" + r.stderr[-3000:])


def _bevy_resolve(ctx, items: list[dict]) -> list[tuple[Path, dict]]:
    """Resolve {character|environment|package} entries to absolute glTF files + item options."""
    uroot = ctx.config.data_dir / "uap"
    share = Path("//10.89.1.246/ehm_eckx/gBox/system/gbox-data/uap")   # ponytail: packages extracted on the Spark
    if not all((uroot / it["package"]).exists() for it in items if "package" in it) and share.exists():
        uroot = share
    # collection entries ({character: slug} / {environment: slug}) are read where the collection lives (the Spark's
    # cache, the same folder through the share on Windows)
    from . import characters as K
    croot = K.library_root(ctx.config).parent if HOST_OS != "windows" else Path("//10.89.1.246/ehm_eckx/gbox-cache")
    files = []                                             # (absolute model file, item options)
    for it in items:
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
    return files


def _bevy_scene_spec(ctx, items: list[dict]) -> dict:
    """Resolve items into the scene.json spec: absolute glTF paths + camera."""
    files = _bevy_resolve(ctx, items)
    aroot = Path(os.path.commonpath([str(f.parent) for f, _ in files])) if files else (ctx.config.data_dir / "uap")
    spec = {"assets_root": _abs(aroot),
            "items": [{"gltf": _abs(f), **o} for f, o in files],
            "camera": {},
            "_src": items}                    # the original portable items ({package}/{character}/...) for cross-node reuse
    return spec


def _bevy_scene_path(ctx, name: str) -> Path:
    sdir = ctx.config.data_dir / "bevy"
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir / f"{name}.json"


def _bevy_write(spec: dict, scene: Path):
    scene.write_text(json.dumps(spec, indent=1))


def _bevy_wait_png(png: Path, timeout_s: float = 60.0) -> Path | None:
    """The viewer's screenshot once it is fully written (the same non-zero size on two polls 0.5 s apart)."""
    t0, last = time.time(), -1
    while time.time() - t0 < timeout_s:
        size = png.stat().st_size if png.exists() else 0
        if size > 0 and size == last:
            return png
        last = size
        time.sleep(0.5)
    return png if (png.exists() and png.stat().st_size > 0) else None


@tool("bevy_scene", "1.1", BevyIn, BevyOut, capabilities=["asset", "bevy"], timeout_s=3600,
      side_effects=["writes glTF + scene files", "builds the gBox Bevy viewer on first use (cargo)",
                    "op=open/snapshot/set_camera/add/remove/close drive a live viewer window"],
      artifacts=["bevy.png"])
def bevy_scene(inp: BevyIn, ctx: Ctx):
    """Render gBox Bevy scenes and drive a live viewer reactively.

    One-shot (op=render, the default): put collection entries ({character: slug} / {environment: slug}) and gBox asset
    packages ({package: 'pso_dc_forest01'}) into a Bevy scene and render it with the gBox Bevy viewer (Rust/Bevy,
    built once with cargo). screenshot=true returns a PNG artifact; false opens a window and returns its pid.

    Reactive ops (the viewer's window stays open and reacts to file commands):
      op=open          start the viewer on a scene (items + camera), keep the window, return pid
      op=snapshot      capture the live window to {name}.png and return it as an artifact
      op=set_camera    move the live camera ({camera: {eye, target}})
      op=add           add more items to the live scene (items=[...])
      op=remove        drop item {index} from the live scene
      op=close         close the live window
      op=list          live sessions + saved scenes and renders on this node
    """
    sdir = ctx.config.data_dir / "bevy"
    sdir.mkdir(parents=True, exist_ok=True)
    if inp.op == "list":
        live = [{"name": n, "pid": s["proc"].pid, "items": len(s["spec"]["items"]), "camera": s["spec"]["camera"]}
                for n, s in BEVY.items() if s["proc"].poll() is None]
        scenes = [{"name": f.stem, "mtime": f.stat().st_mtime,
                   "items": len(json.loads(f.read_text()).get("items", []))}
                  for f in sorted(sdir.glob("*.json"))]
        renders = [{"name": f.stem, "mtime": f.stat().st_mtime} for f in sorted(sdir.glob("*.png"))]
        return {"live": live, "scenes": scenes, "renders": renders}

    if inp.op in ("open", "render"):
        scene = _bevy_scene_path(ctx, inp.name)
        if inp.items:
            spec = _bevy_scene_spec(ctx, inp.items)
            if inp.camera:
                spec["camera"] = inp.camera
            if not inp.screenshot and inp.op == "render":      # backward-compatible window mode
                inp.op = "open"
            _bevy_write(spec, scene)
        elif scene.exists():                                   # re-render / reopen a saved scene
            try:
                spec = json.loads(scene.read_text())
            except Exception as e:
                raise ValueError(f"scene {inp.name} is not readable: {e}")
        else:
            raise ValueError("bevy_scene op=render/open needs items, or an already saved scene name")
        if inp.op == "render":
            png = sdir / f"{inp.name}.png"
            png.unlink(missing_ok=True)
            target = ctx.config.runtime / "bevy-target"
            _bevy_build(ctx, target, _bevy_viewer_exe(ctx))
            ctx.progress(70, "rendering")
            subprocess.run([str(_bevy_viewer_exe(ctx)), str(scene), "--screenshot", str(png)],
                           cwd=sdir, capture_output=True, timeout=300)
            if not png.exists():
                raise RuntimeError("the viewer did not produce a screenshot")
            ctx.artifact("bevy.png", png.read_bytes(), "image/png", scene=inp.name)
            return {"scene": str(scene), "screenshot": str(png), "items": spec["items"]}
        # op=open: live window
        _bevy_build(ctx, ctx.config.runtime / "bevy-target", _bevy_viewer_exe(ctx))
        p = subprocess.Popen([str(_bevy_viewer_exe(ctx)), str(scene), "--live"], cwd=sdir)
        BEVY[inp.name] = {"proc": p, "scene": scene, "spec": spec}
        return {"scene": str(scene), "pid": p.pid, "items": spec["items"]}

    sess = BEVY.get(inp.name)
    if inp.op in ("snapshot", "set_camera", "add", "remove") and (not sess or sess["proc"].poll() is not None):
        raise ValueError(f"no live viewer named {inp.name} (bevy_scene op=open first, or op=list)")
    if inp.op == "close":
        if sess:
            (sess["scene"].parent / f"{inp.name}.quit").write_text("")
            try:
                sess["proc"].wait(timeout=10)
            except subprocess.TimeoutExpired:
                sess["proc"].terminate()
            BEVY.pop(inp.name, None)
        return {"scene": str(_bevy_scene_path(ctx, inp.name))}
    assert sess is not None                                     # guarded above for snapshot/set_camera/add/remove
    if inp.op == "snapshot":
        png = sdir / f"{inp.name}.png"
        png.unlink(missing_ok=True)
        (sess["scene"].parent / f"{inp.name}.shot").write_text(_abs(png))
        got = _bevy_wait_png(png)
        if got is None:
            raise RuntimeError("the viewer did not produce a screenshot")
        ctx.artifact("bevy.png", got.read_bytes(), "image/png", scene=inp.name)
        return {"scene": str(sess["scene"]), "screenshot": str(got), "pid": sess["proc"].pid}
    if inp.op == "set_camera":
        if inp.camera:
            sess["spec"]["camera"] = inp.camera
            _bevy_write(sess["spec"], sess["scene"])
        return {"scene": str(sess["scene"]), "pid": sess["proc"].pid, "camera": sess["spec"]["camera"],
                "items": sess["spec"]["items"]}
    if inp.op == "add":
        for f, o in _bevy_resolve(ctx, inp.items):
            sess["spec"]["items"].append({"gltf": _abs(f), **o})
        _bevy_write(sess["spec"], sess["scene"])
        return {"scene": str(sess["scene"]), "pid": sess["proc"].pid, "items": sess["spec"]["items"]}
    if inp.op == "remove":
        i = inp.index if inp.index is not None else len(sess["spec"]["items"]) - 1
        if 0 <= i < len(sess["spec"]["items"]):
            sess["spec"]["items"].pop(i)
            _bevy_write(sess["spec"], sess["scene"])
        return {"scene": str(sess["scene"]), "pid": sess["proc"].pid, "items": sess["spec"]["items"]}
    raise ValueError(f"bevy_scene: op={inp.op} needs items (open/render/add) or a live session (snapshot/set_camera/remove)")


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
    op: str = "list"                       # list | build | remove | delete_build (this PC's copies + staged copies)
    name: str = ""
    # build: {"PS3_GAME/USRDIR/...": {"patch": [{"offset": "0x10", "hex": "ff"}]} | {"from": "<local file>"} | {"artifact": "<sha256>"}}
    changes: dict = {}
    retention_node: str = ''

class FileModOut(BaseModel):
    result: dict


@tool("file_mod", "1.0", FileModIn, FileModOut, capabilities=["mod"], timeout_s=7200, permissions=[P.EXECUTE],
      side_effects=["copies the game once into the node cache", "writes mod folders (hard links + changed files)"])
def file_mod(inp: FileModIn, ctx: Ctx):
    """File-replacement mods for folder games: build a modded copy (original untouched, unchanged files hard-linked to
    one local base copy), list, remove (= rollback). Launch it with launch_game mod=<name>.
    delete_build (Builds ▸ Delete): this PC's copies of a build, its staged copies included; refused while a running
    game on this PC uses one."""
    from . import filemods
    if inp.op in ("delete_build", "quarantine_build"):  # no catalog / base ROM required
        if not inp.name:
            raise ValueError("delete_build needs the build's name")
        r = httpx.get(f"{ctx.server}/api/sessions?include_ended=false", headers=ctx.headers, timeout=30)
        r.raise_for_status()
        # (any running session of the build blocks it, wherever it runs: over-cautious beats a half-deleted copy)
        in_use = [str(s.get(k) or "") for s in r.json() if s.get("state") == "running" and s.get("game_id") == inp.game_id
                  for k in ("mod", "collection_mod")]
        if inp.op == 'quarantine_build':
            from . import build_quarantine
            res = build_quarantine.worker(ctx, inp.game_id, inp.name, [m for m in in_use if m])
        else:
            res = filemods.delete_build(ctx.config, inp.game_id, inp.name, [m for m in in_use if m])
        if res["errors"]:
            raise RuntimeError("some copies could not be deleted (open in another program?): " + "; ".join(res["errors"]))
        return {"result": res}
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
        from . import build_record                     # the Builds view: which job built it and the exact call
        build_record.stamp_marker(filemods.mod_dir(ctx.config, g.game_id, inp.name),
                                  build_call=build_record.call_of("file_mod", inp), **build_record.from_ctx(ctx))
        ctx.artifact("mod.json", json.dumps(res).encode(), "application/json", game=g.game_id, mod=inp.name)
        return {"result": res}
    raise ValueError(f"unknown op {inp.op}")


class BuildLocalIn(BaseModel):
    op: str = "download"                   # download | locate | export
    game_id: str
    name: str                              # the build (its collection folder name)
    dest: str = ""                         # export: an existing folder on this PC (absolute path)
    format: str = "same"                   # export: same (the original's container) | plain | patch | zip
    label: str = ""                        # export: the build's display name (names the export folder)

class BuildLocalOut(BaseModel):
    result: dict


@tool("build_local", "1.0", BuildLocalIn, BuildLocalOut, capabilities=["mod"], timeout_s=7200, permissions=[P.EXECUTE],
      side_effects=["copies a build from the central collection into this PC's cache (never launches it)",
                    "export: writes the build into the chosen folder on this PC"])
def build_local(inp: BuildLocalIn, ctx: Ctx):
    """A build on this PC (#1639, the download icon on the Mods cards and Builds rows). download: pull the build from
    the central collection into this PC's cache (filemods.stage: the pinned manifest, resumable, a running game's copy
    is never touched) so it plays at once, offline; nothing is launched. locate: this PC's folder of the build. export:
    download if needed, then write it to `dest` (gbox.build_export: the same format as the original game file by
    default, or plain / patch / zip)."""
    from . import build_export as BX
    from . import filemods
    if inp.op not in ("download", "locate", "export"):
        raise ValueError(f"unknown op {inp.op}")
    filemods.mod_dir(ctx.config, inp.game_id, inp.name)            # names must be single cache-folder components
    if inp.op == "locate":
        d = BX.locate(ctx.config, inp.game_id, inp.name)
        return {"result": {"here": bool(d), **(BX.summary(d) if d else {})}}
    if inp.op == "export":
        dest = Path(inp.dest or "")
        if not inp.dest or not dest.is_absolute():
            raise ValueError("choose a folder on this PC to export to (an absolute path)")
        if not dest.is_dir():
            raise ValueError(f"{dest} is not a folder on this PC")
        if inp.format not in BX.FORMATS:
            raise ValueError(f"format: one of {', '.join(BX.FORMATS)}")
    share = .4 if inp.op == "export" else 1.0                       # an export spends the rest of its bar writing

    def fetching(pct, msg):                                         # stage: 20 = checking, 20..28 = the download
        ctx.progress(round(share * (2 if pct <= 20 else min(99, 4 + 95 * (pct - 20) / 8)), 1), msg)
    have = BX.locate(ctx.config, inp.game_id, inp.name)
    if ctx.server:
        alias = filemods.stage(ctx.config, ctx.server, ctx.headers, inp.game_id, inp.name, fetching)
        folder = filemods.mod_dir(ctx.config, inp.game_id, alias)
    else:
        folder = have
    if folder is None or not (folder / ".gbox-mod.json").is_file():
        raise ValueError(f"build {inp.name} is neither on this PC nor in the central collection")
    filemods._LOCAL_CACHE.clear()                                   # the next heartbeat lists it as on this PC
    info = BX.summary(folder)
    if inp.op == "download":
        ctx.progress(100, f"{inp.name} is on this PC ({info['size'] >> 20} MB): it plays offline")
        return {"result": {"here": True, "already": bool(have and have == folder), **info}}
    r = httpx.get(f"{ctx.server}/api/catalog/{inp.game_id}", headers=ctx.headers, timeout=30)
    r.raise_for_status()
    g = CatalogEntry.model_validate(r.json())
    try:
        rom = rom_path(g, ctx.config)
    except ToolUnavailable:
        rom = None
    game = g.model_dump(mode="json") | {"source_name": Path(g.rel_path or (g.launch or {}).get("path") or "").name}
    meta = json.loads((folder / ".gbox-mod.json").read_text(encoding="utf-8"))
    res = BX.export(ctx.config, game=game, rom=rom if rom and Path(rom).exists() else None, folder=folder, meta=meta,
                    dest=Path(inp.dest), fmt=inp.format, label=inp.label or inp.name,
                    progress=lambda f, m: ctx.progress(round(40 + 60 * min(1.0, f), 1), m))
    return {"result": {"build": inp.name, "game_id": inp.game_id, **res}}


class RomExportIn(BaseModel):
    original: bool = False                # explicitly export unchanged complete library file/archive
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
    from . import romexport_recovery as recovery
    response = httpx.get(f"{ctx.server}/api/mods", headers=ctx.headers, timeout=60)
    response.raise_for_status()
    saved = response.json()
    gid, docs, names = recovery.selection(inp.model_dump(), saved)
    r = httpx.get(f"{ctx.server}/api/catalog/{gid}", headers=ctx.headers, timeout=30)
    r.raise_for_status()
    g = CatalogEntry.model_validate(r.json())
    plan = recovery.plan(ctx.config, g.model_dump(), docs, names, inp.changes, saved, inp.original)
    if inp.op == "plan":
        return {"result": plan}
    if inp.op != "export":
        raise ValueError("Unknown ROM export operation; use plan, export, list or remove")
    recovery.require_ready(plan)
    try:
        rom = rom_path(g, ctx.config)
    except ToolUnavailable:
        rom = Path(g.rel_path or "")
    res = recovery.export_original(ctx.config, g.model_dump(), rom, inp.name, ctx.progress) if inp.original else RX.export(ctx.config, g.model_dump(), rom, mods=docs, file_mods=names, changes=inp.changes, name=inp.name,
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


PICK_FRAME = (640, 480)                   # picture the probe projects into (4:3; the click is mapped into it)


def _picture_xy(inp: PickIn):
    """The 4:3 picture is centred in the window: map the click into picture coordinates (0..1)."""
    cx, cy = inp.x, inp.y
    if inp.window_aspect > 4 / 3:
        w = (4 / 3) / inp.window_aspect
        cx = (inp.x - (1 - w) / 2) / w
    elif inp.window_aspect < 4 / 3:
        h = inp.window_aspect / (4 / 3)
        cy = (inp.y - (1 - h) / 2) / h
    return cx, cy


def _pick_from_probe(scan: dict, cx: float, cy: float) -> dict:
    """Pick result from a gbox.entity_probe scan (profiles with entities.layout struct_array + camera pos_angles_fov)."""
    from . import entity_probe
    w, h = scan["frame"]
    hit = entity_probe.Probe.under_point(cx * w, cy * h, scan)
    e = hit["entity"]
    out = {"picked": entity_probe.summary(e) if e else None, "contained": hit["contained"], "miss": hit["miss"],
           "click": [round(cx, 3), round(cy, 3)], "click_px": [round(cx * w, 1), round(cy * h, 1)],
           "others": [entity_probe.summary(o) for o in hit["others"]], "camera": scan["camera"],
           "entities": len(scan["entities"]), "diagnostics": scan["diagnostics"][:20]}
    check = scan.get("recheck") or scan.get("camera_check")
    if check is not None:
        out["camera_check"] = {k: check.get(k) for k in ("stable", "cut", "eye", "angle", "fov", "source_changed")}
        if check.get("cut") and scan.get("camera"):
            out["warning"] = "the camera cut while the game was read: the boxes may belong to the previous shot, click again"
    if e is None:
        out["note"] = "nothing projectable near the click" if scan["camera"] else "camera unreadable (see diagnostics)"
    elif e.get("model"):
        out["asset_note"] = f"model {e['model']}: extracting it from the disc is the next stage (no reader for this game yet)"
    return out


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
        cam_raw = probe_scan = None
        prof = next((p for p in semantic.load_profiles() if p.get("id") == st.get("profile")), None)
        if prof and (prof.get("camera") or {}).get("layout") == "pos_angles_fov":      # table-of-records games (AUF)
            from . import entity_probe
            probe = entity_probe.Probe(prof, ad.read_memory)
            probe_scan = probe.scan(*PICK_FRAME, entities=st.get("entities"))
            probe_scan["recheck"] = probe.recheck(probe_scan)      # a shot change around the click shows up here
        elif prof and prof.get("camera"):
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
    cx, cy = _picture_xy(inp)
    if probe_scan is not None:
        return {"result": _pick_from_probe(probe_scan, cx, cy)}
    e_, t_ = cam_raw
    end = ">" if g.get("platform") in BIG_ENDIAN else "<"
    eye, tgt = S.unpack(end + "3f", e_), S.unpack(end + "3f", t_)
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
    archives_only: bool = False

class ProvisionOut(BaseModel):
    receipts: list[dict]
    failed: list[str]

@tool("provision_node", "1.0", ProvisionIn, ProvisionOut, capabilities=["provision"], permissions=[P.INSTALL],
      timeout_s=3600, side_effects=["installs packages/cores/ghidra", "edits /etc/fstab (backed up) for library mounts"],
      artifacts=["provision.json"], validate=lambda o, a: [f"step failed: {s}" for s in o.failed],
      validation="every setup step reports ok/installed")
def provision_node(inp: ProvisionIn, ctx: Ctx):
    """Resolve and install this node's dependencies (same as `gbox setup`)."""
    receipts = ([provision._receipt('archives', 'ok', provision._seven_zip())] if inp.archives_only else
                provision.setup(ctx.config, inp.with_ghidra, log=lambda m: ctx.log.append(m)))
    ctx.artifact("provision.json", json.dumps(receipts, indent=1).encode(), "application/json")
    return {"receipts": receipts, "failed": [r["step"] for r in receipts if r["status"] in ("failed", "missing")]}


@tool('provision_archives', '1.0', ProvisionIn, ProvisionOut, capabilities=['provision'], permissions=[P.INSTALL],
      timeout_s=1800, side_effects=['installs missing platform archive tools'], artifacts=['provision.json'])
def provision_archives(inp: ProvisionIn, ctx: Ctx):
    """Install/verify only this worker's archive backend. Older workers cannot accidentally run full setup."""
    return provision_node(ProvisionIn(archives_only=True), ctx)


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
     "tools": ["analyze_binary", "ghidra_script", "ida", "n64recomp", "decomp_me", "read_memory", "session_op"], "status": "defined"},
    {"name": "game_state", "role": "Semantic state discovery (player/enemy/room) from memory diffs + RE",
     "tools": ["read_memory", "session_op", "get_frame", "ghidra_script"], "status": "defined"},
    {"name": "autoplay_strategy", "role": "Route/strategy improvement from evaluated runs", "tools": ["launch_game", "session_op", "read_memory", "get_frame"],
     "status": "planned", "notes": "Needs the semantic-state extractor (Phase 2) first."},
    {"name": "asset", "role": "Dependency extraction and normalization into UAP packages", "tools": ["export_asset", "read_memory", "get_frame", "scene_capture", "ninja_ripper"], "status": "defined"},
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
def _load_tool_modules(names=("native_face_editor", "auf_live", "twin_snakes_faces", "doa2_faces", "gta3_face_takeover", "gta3_items", "pso_face_build", "pso_faces", "pso_loadouts", "gameplay_demo", "sprite_faces", "smb1_sprite_build", "photo_skin", "gameplay_memory", "tas_tool", "ollama_assist", "inspection_builds", "live_controls", "pso_mods_tool", "re_mods_tool", "zelda_tool", "ac_mods_tool", "characters", "scene_capture", "tasks_tool", "blender_copy", "texture_review", "mesh_workspace", "hops_workspace",
                              "live_link",   # live_link: Blender Live Link push -> build, validate, hot-swap into the running game
                              "re4r",   # re4r: Resident Evil 4 (2023, Steam) via REFramework + gBox's Lua bridge
                              "ue_steam",   # ue_steam: generic Unreal Engine Steam game static analysis (locomotion/animation)
                              "re6_tool",   # re6_tool: Resident Evil 6 (X360 in Xenia): Mercenaries loadouts, items, swaps
                              "re5_tool",   # re5_tool: Resident Evil 5 Gold (PS3 in RPCS3): unlock all (save edit)
                              "oot_live",   # oot_live: OoT actors at a picture point, statues kept in rooms (gbox.oot_swap)
                              "twin_snakes_live",   # twin_snakes_live: Twin Snakes GC loaded cast + live body writes
                              "re_inventory",   # re_inventory: any Resident Evil's live inventory (give/remove/set/loadout)
                              "aki_wrestling",   # aki_wrestling: No Mercy / Revenge / World Tour writers (via characters op=use|match)
                              "yukes_sd",   # yukes_sd: WWF SmackDown! 2 (PS1) reader + writer (via characters op=use|match|extract)
                              "aki_wcw",   # aki_wcw: WCW vs. nWo World Tour writer + extractor (via characters op=use|match|extract)
                              "re_lab_tool",   # re_lab_tool: re_executable (a title's executable -> ELF for Ghidra)
                              "assimilate",    # assimilate: fingerprint a game (formats, engine, nearest assimilated titles)
                              "doa2_lab",      # verified native fighter archive decomposition/reintegration
                              "mashup",        # mashup: natural-language cross-title planner and dispatcher
                              "favorite_capabilities",  # exact-build coverage and verified unlock launch plans
                              "title_assets",  # bounded exact-title native exports and durable extraction plans
                              "pickwhip",      # pickwhip: pick_name (local-LLM naming of a pick whip target)
                              "rea_tool",      # complete pinned REA CLI/MCP capability catalog
                              "native_decomp",  # DecompPipeline local tasks, XenonRecomp and RexGlue SDK
                              "decomp_tools",  # decomp_tools: decomp_me (opt-in REST), ida (headless export), n64recomp
                              "ninja_ripper",  # ninja_ripper: NinjaRipper launch/attach/rip on agent test PCs, .rip -> GLB
                              "stage_warp",    # stage_warp: put the player on a named stage/level of the live game
                              "sprite_capture",   # sprite_capture: a 2D sprite's animation (PNG sequence, sheet, preview, MP4) from the live game
                              "mk64_items",    # mk64_items: Mario Kart 64 items (always have / infinite items per player)
                              "mgs_vr_tool",   # mgs_vr_tool: Metal Gear Solid VR Missions (complete mission, unlock all)
                              "sa2_mods",      # sa2_mods: Sonic Adventure 2 (DC/GC USA): finish stage, A rank, emblems
                              "gta_mods_tool",   # gta_mods_tool: PS2 GTAs (car jump, ped rain, ...)
                              "stranglehold",   # stranglehold: PS3 bullet-time interception systems and chat driver
                              "universal_modder",   # universal_modder: um_* tools (scan, kb, backup, publish check, sprite, mod, comfy, render3d)
                              "ghidra_bridge_tool",   # ghidra_bridge: the operator's Ghidra as JSON functions (Dryxio/ghidra-bridge)
                              "re_agent",        # re_agent: ReAgent reverser/checker/fix loop over the Ghidra Bridge
                              "gta_live",        # gta_live: GTA pools/player/vehicles/weather/time/wanted/spawn (Ariane ops)
                              "audio_cpp",       # audio_cpp: local audio.cpp speech service (status/start/stop/speak/transcribe)
                              "evidence_capture",   # evidence_capture: PR evidence frames (runs in the control plane)
                              "pick_tool")):     # pick_identify / pick_replace (+ pick_prepare, pick_ghidra): the pick whip backend
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
    with _STATE_TRANSFER_LOCK, rewind.guard(inp.session_id, "transfer"):   # no checkpoint while the state moves
        return _state_transfer(inp, ctx)


def _state_transfer(inp: StateXIn, ctx: Ctx):
    """Move a running game between machines (Spark <-> this PC) through a save state: RetroArch cores, and GameCube/Wii on
    standalone Dolphin (the same release on both machines)."""
    session = SESSIONS.get(inp.session_id)
    if session is None:
        raise Unsupported('This session ended. Open the running game before transferring its state.')
    ad, g = session
    kind = getattr(ad, "name", "")
    if kind == "retroarch":                                    # a capture session keeps its states in its own folder
        sd = getattr(ad, "state_dir", None)
        states = Path(sd()) if callable(sd) and getattr(ad, "states_override", None) else ctx.config.runtime / "states"
        pattern = "*.state*"
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
        ctx.artifact(f.name, data, "application/octet-stream", note="state transfer", game=g.get("game_id"),
                     session=inp.session_id, **details)          # last played finds the moment by session
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


# Select + R2 fast-forward ramp and Select + L2 rewind: gbox/rewind.py (started per session in _launch_game)


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

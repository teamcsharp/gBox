"""Built-in typed tools. Each declares permissions, availability check, and an independent validator."""
import gzip
import os
import json
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

from . import adapters, catalog, provision, uap
from .models import CatalogEntry, Permission as P
from .registry import HOST_OS, Ctx, ToolUnavailable, tool
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
            e, p = catalog.scan([root], {}, cache, lib_id=lib.id, do_hash=lib.hash)
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

class LaunchIn(BaseModel):
    game: CatalogEntry

class LaunchOut(BaseModel):
    session_id: str
    adapter: str
    capabilities: dict[str, str]
    detail: dict

def _launch_accept(store, out: LaunchOut, actor: str):
    g = out.detail.get("_game", {})
    store.put("session", out.session_id, {"session_id": out.session_id, "game_id": g.get("game_id"), "title": g.get("title"),
                                          "adapter": out.adapter, "capabilities": out.capabilities, "state": "running",
                                          "started": time.time(), "detail": {k: v for k, v in out.detail.items() if k != "_game"}})
    if g.get("game_id"):
        e = store.catalog_get(g["game_id"]) or {}
        upd = {"playable": f"launches ({out.adapter})", "last_played": time.time()}
        if out.detail.get("staged_on"):
            upd["cached_on"] = sorted(set(e.get("cached_on") or []) | {out.detail["staged_on"]})
        store.catalog_update(g["game_id"], **upd)

def _launch_fail(store, job: dict, actor: str):
    gid = job["input"].get("game", {}).get("game_id")
    if gid:
        store.catalog_update(gid, playable=f"launch failed: {(job.get('error') or '')[:200]}")

@tool("launch_game", "1.1", LaunchIn, LaunchOut, capabilities=["runtime"], permissions=[P.EXECUTE], timeout_s=900,
      side_effects=["starts emulator/game process", "may download a core/BIOS", "may stage a copy into cache"],
      validation="adapter reported content running", on_accept=_launch_accept, on_fail=_launch_fail)
def launch_game(inp: LaunchIn, ctx: Ctx):
    """Launch a cataloged game on this node; missing cores/BIOS are installed automatically. Streams to the UI."""
    g = inp.game
    ctx.progress(2, f"Loading {g.title} · {g.system or g.platform}")
    ad = adapters.for_game(g.model_dump(), ctx.config)
    ad.progress = ctx.progress
    ctx.progress(5, f"Runtime: {ad.name}" + (f" · core {g.core}" if g.core else ""))
    if g.launch.get("kind") == "steam":
        detail = ad.launch_game(g.launch["appid"])
    elif isinstance(ad, adapters.RocketLauncherAdapter):
        detail = ad.launch_game(g.launch["emulator"], g.launch["name"])
    else:
        src = rom_path(g, ctx.config)
        if not src.exists():
            raise FileNotFoundError(f"ROM not reachable from this node: {src}")
        emu = ctx.config.emulators.get(g.platform)
        # big disc images (CHD/ISO/GCZ...) stream poorly over SMB: stage them onto this node's fast local cache
        big = src.is_file() and src.stat().st_size > ctx.config.stage_min_mb * 1024 * 1024
        if (emu and emu.stage_local) or (big and g.library and _stageable(src)):
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
        ctx.progress(72, f"Starting {ad.name} with {src.name}")
        detail = ad.launch_game(str(src))
    ctx.progress(100, "Running natively in its own window" if detail.get("local_window") else "Running — connecting the stream")
    sid = f"{ctx.worker}-{ctx.job_id}"
    gd = g.model_dump()
    if g.launch.get("kind") != "steam" and not isinstance(ad, adapters.RocketLauncherAdapter):
        gd["_rom_path"] = str(src)                     # for the inspector's ROM viewer
    SESSIONS[sid] = (ad, gd)
    if HOST_OS == "windows" and isinstance(ad, adapters.RetroArchAdapter) and ad.rewind_on:
        _ensure_rewind_hotkey()
    if ctx.server and ("stream_session" in ad.supported or isinstance(ad, adapters.RetroArchAdapter)):
        threading.Thread(target=_pump, args=(sid, ad, ctx.server, ctx.headers), daemon=True).start()
    detail["_game"] = {"game_id": g.game_id, "title": g.title}
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


def _stageable(src: Path) -> bool:
    # multi-file disc sets reference sibling tracks by relative path; copying only the sheet would break them
    return src.suffix.lower() not in (".cue", ".gdi", ".m3u")


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

    def answer(ev):
        try:
            result = {"ok": True, "data": session_rpc(sid, ev["op"], ev.get("args") or {})}
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            httpx.post(f"{server}/api/sessions/{sid}/rpc/{ev['rpc']}", json=result, headers=headers, timeout=10)
        except httpx.HTTPError:
            pass

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
    with httpx.Client(base_url=server, headers=headers, timeout=10) as c:
        while sid in SESSIONS:
            time.sleep(3)
            try:
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
        n = max(1, min(int(args.get("length", 256)), 65536))
        return ad.read_memory(int(args["address"]), n).hex()
    if op == "read_rom":
        data = _rom_bytes(g["_rom_path"])
        off, n = int(args.get("offset", 0)), max(1, min(int(args.get("length", 4096)), 65536))
        return {"size": len(data), "offset": off, "hex": data[off:off + n].hex()}
    if op == "info":
        return {"platform": g.get("platform"), "core": g.get("core"), "title": g.get("title"),
                "rom": Path(g["_rom_path"]).name if g.get("_rom_path") else None,
                "capabilities": ad.get_capabilities(), "runtime": ad.query_runtime()}
    raise ValueError(f"rpc op {op} not allowed (read-only: read_memory, read_rom, info)")


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
        store.put("session", out.session_id, s | {"state": "ended", "ended": time.time(), "exit": out.result})

@tool("session_op", "1.0", SessionIn, SessionOut, capabilities=["runtime"], permissions=[P.EXECUTE],
      on_accept=_session_accept)
def session_op(inp: SessionIn, ctx: Ctx):
    """Call a runtime op (pause/resume/stop_game/save_state/query_runtime/step_frames...) on a live session."""
    if inp.op not in adapters.OPS or inp.op in ("write_memory", "read_memory", "launch_game"):
        raise ValueError(f"op {inp.op} not allowed via session_op")
    ad, _ = SESSIONS[inp.session_id]
    res = getattr(ad, inp.op)(**inp.args)
    if inp.op == "stop_game":
        SESSIONS.pop(inp.session_id, None)
    return {"result": res if isinstance(res, dict) else {"value": str(res)[:200]}, "session_id": inp.session_id,
            "ended": inp.op == "stop_game"}


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


class FrameIn(BaseModel):
    session_id: str | None = None          # grab that session's display; default: host desktop
    region: list[int] | None = None        # x, y, w, h on the host desktop

class FrameOut(BaseModel):
    width: int
    height: int
    sha256: str
    mean_luma: float | None = None         # 0-255; ~0 means a black screen (content not drawing)

def _png_validate(out: FrameOut, arts):
    d = arts.get("frame.png", b"")
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        return ["frame.png is not a PNG"]
    w, h = int.from_bytes(d[16:20], "big"), int.from_bytes(d[20:24], "big")
    return [] if (w, h) == (out.width, out.height) and sha256(d) == out.sha256 else ["PNG header/hash mismatch"]

@tool("get_frame", "1.0", FrameIn, FrameOut, capabilities=["video"], artifacts=["frame.png"],
      validate=_png_validate, validation="PNG signature + IHDR size + hash",
      check=lambda c: None if shutil.which("ffmpeg") else "ffmpeg not on PATH")
def get_frame(inp: FrameIn, ctx: Ctx):
    """Capture one frame of a session display or the host desktop via ffmpeg (x11grab / gdigrab)."""
    if inp.session_id:
        ad, g = SESSIONS[inp.session_id]
        d = ad.get_frame()
        ctx.artifact("frame.png", d, "image/png", session=inp.session_id, game=g["game_id"])
    else:
        d = adapters.grab_png(None, inp.region)
        ctx.artifact("frame.png", d, "image/png")
    return {"width": int.from_bytes(d[16:20], "big"), "height": int.from_bytes(d[20:24], "big"), "sha256": sha256(d),
            "mean_luma": mean_luma(d)}


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

def _ghidra_env() -> dict:
    """Pin a JDK 21 for G-Box's headless runs (the host default may be newer); never edits the Ghidra install."""
    env = dict(os.environ)
    for jdk in ("/usr/lib/jvm/java-21-openjdk-arm64", "/usr/lib/jvm/java-21-openjdk-amd64"):
        if Path(jdk).exists():
            env["JAVA_HOME"] = jdk
            env["PATH"] = f"{jdk}/bin:" + env.get("PATH", "")
            break
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
    r = subprocess.run(cmd, timeout=3500, capture_output=True, text=True, env=_ghidra_env())
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
    r = subprocess.run(cmd, timeout=3500, capture_output=True, text=True, env=_ghidra_env())
    log = (r.stdout + r.stderr).encode()
    ctx.artifact("ghidra_script.log", log, "text/plain", script=inp.script, binary=inp.binary_path)
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

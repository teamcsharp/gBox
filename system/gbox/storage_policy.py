"""Worker storage policy (operator 2026-10-26, about the i9-NUC whose C: filled up): "I don't want any games being put
on the C drive of that computer ... I want to opt into the builds and only download builds when I choose to download
them." The purge of unplayed games and automatically sent builds is gbox/storage_purge.py.

No game data on a Windows system drive
  game_dir(config, path, kind)   every worker writer of game data whose default folder is not the cache itself (extracts,
                                 recordings, rewind checkpoints, ROM exports, play-disc copies, temp files) asks here:
                                 a folder on the system drive (%SystemDrive%, normally C:) becomes <cache>/.gbox-redirected/
                                 <kind> when the configured cache (cache_dirs.windows, e.g. D:/gBox/cache) is on another
                                 drive; SystemDriveRefused when it is not (strict=False keeps the default instead).
  require_off_system(...)        the cache root itself (staged library copies, builds, base copies): nothing to redirect to,
                                 so a cache on the system drive refuses the write.
  redirect_temp(config)          Python's temp folder on a Windows worker moves off the system drive.
  system_drive_report(config)    which configured gBox roots are on the system drive (worker start-up, the purge report).

Builds are opt-in ([builds] auto_send = false)
  A build reaches a PC when the operator downloads it there (POST /api/builds/{gid}/{name}/local op=download, the app's
  download icon), which leaves a receipt: a store document per (PC, build) on the control plane and, on the PC, a
  sidecar beside the build (<cache>/mods/<gid>/.<name>.receipt.json). The operator's own launches and swaps copy what
  they ask for. Everything else (agent and Hermes test sessions, background testing, the screensaver / MercMode /
  roulette demos, the launch-failure restage, verification launches) copies a build only when that PC holds a receipt
  for it: check_build_copy() raises BuildNotOptedIn in filemods before the first byte moves. The control plane stamps
  each claimed job with permit() (operator?, auto_send, the PC's receipts); the worker evaluates it in the job's context.
"""
from __future__ import annotations

import contextvars
import json
import ntpath
import os
import platform
import re
import shutil
import tempfile
import time
from pathlib import Path

REDIRECT_DIR = ".gbox-redirected"          # <cache>/.gbox-redirected/<kind>: game data moved off the system drive
RECEIPT_KIND = "build_receipt"             # store: "<pc>/<game_id>/<name>" -> {pc, game_id, name, by, ts, job}
RECEIPT_SUFFIX = ".receipt.json"           # <cache>/mods/<game_id>/.<name>.receipt.json on the PC
OPERATOR_ACTORS = ("operator", "gbox-agent")   # the operator, and the in-app chat agent acting on their words
TEMP_MAX_AGE_S = 7 * 86400                 # leftovers in the redirected temp folder older than this are swept at start
POLICY_RX = re.compile(r"BuildNotOptedIn|SystemDriveRefused|has not downloaded it there|off this PC's system drive")

# The job a worker tool runs for (registry._run_with_fitting sets it around the tool function): filemods reads its
# permit when a build would be copied. None outside a worker job (the control plane, local scripts, tests).
JOB: contextvars.ContextVar = contextvars.ContextVar("gbox_storage_job", default=None)


class SystemDriveRefused(RuntimeError):
    """Game data would land on a Windows system drive and no other drive is configured for it."""


class BuildNotOptedIn(RuntimeError):
    """Automatic work needed a build on a PC the operator never downloaded it to (and [builds] auto_send is off)."""


# ------------------------------------------------------------------------------------------------ the system drive

_ACTIVE = {"on": False}       # the rule binds a worker process (worker.run activates it); scripts and tests opt in


def activate(on: bool = True) -> None:
    """Apply the system-drive rule in this process (every gBox worker does at start: worker.run)."""
    _ACTIVE["on"] = bool(on)


def _host_os() -> str:
    return platform.system().lower()


def system_drive(os_name: str | None = None, env=None) -> str | None:
    """'C:' (from %SystemDrive%) on Windows, None elsewhere: only Windows has a system-drive rule."""
    if (os_name or _host_os()) != "windows":
        return None
    d = str((os.environ if env is None else env).get("SystemDrive") or "C:").strip().rstrip("\\/")
    return d.upper() if re.fullmatch(r"[A-Za-z]:", d) else "C:"


def drive_of(path) -> str:
    """'D:' for D:/x, '\\\\server\\share' for a UNC path, '' when the path names no drive (POSIX, relative off Windows)."""
    p = str(path)
    if not ntpath.splitdrive(p)[0] and not os.path.isabs(p):
        p = os.path.abspath(p)                         # a relative folder resolves where gBox runs (on Windows: a drive)
    return ntpath.splitdrive(p)[0].upper()


def _drive(drive):
    """The system drive the rule protects: `drive` when given ("" = none), else the detected one in an activated
    (worker) process, else None (no rule)."""
    if drive is not None:
        return drive or None
    return system_drive() if _ACTIVE["on"] else None


def on_system_drive(path, *, drive: str | None = None) -> bool:
    """`path` is on the Windows system drive. `drive` overrides the detected one ("" = no rule; tests pass "C:")."""
    d = _drive(drive)
    return bool(d and path is not None and str(path) and drive_of(path) == d.upper())


def cache_root(config, *, drive: str | None = None) -> Path | None:
    """The configured cache when it is off the system drive (redirected game data goes under it), else None."""
    try:
        root = Path(config.cache)
    except Exception:                                    # noqa: BLE001 - a config without a cache: nowhere to go
        return None
    return None if on_system_drive(root, drive=drive) else root


def _refusal(what: str, path, drive: str) -> str:
    return (f"gBox keeps game data off this PC's system drive ({drive}): {what} would go to {path}. Set a cache folder "
            f"on another drive in gbox.toml (cache_dirs = {{ windows = \"D:/gBox/cache\" }}) and restart gBox.")


def game_dir(config, path, kind: str, *, strict: bool = True, drive: str | None = None) -> Path:
    """Where game data of `kind` whose default folder is `path` goes on this PC: `path` itself unless it is on a
    Windows system drive; then <cache>/.gbox-redirected/<kind> (the configured cache off the system drive), or
    SystemDriveRefused when the cache is on the system drive too (strict=False: keep `path`)."""
    path = Path(path)
    d = _drive(drive)
    if not on_system_drive(path, drive=d or ""):
        return path
    root = cache_root(config, drive=d)
    if root is None:
        if strict:
            raise SystemDriveRefused(_refusal(kind.replace("_", " "), path, d))
        return path
    return root / REDIRECT_DIR / kind


def require_off_system(config, path, what: str, *, drive: str | None = None) -> Path:
    """The cache root itself (staged library copies, builds, base copies): nothing to redirect to."""
    d = _drive(drive)
    if on_system_drive(path, drive=d or ""):
        raise SystemDriveRefused(_refusal(what, path, d))
    return Path(path)


def extract_root(config, *, strict: bool = True, drive: str | None = None) -> Path:
    """The extract cache (archives, CHD conversions, list sets): runtime/extract, off the system drive."""
    return game_dir(config, Path(config.runtime) / "extract", "extract", strict=strict, drive=drive)


def redirect_temp(config, *, drive: str | None = None) -> str | None:
    """Python's temp folder (tempfile) on a Windows worker: moved to <cache>/.gbox-redirected/tmp when it is on the
    system drive and the cache is not (writers stage disc images and extractions there). Leftovers older than a week
    are swept. Returns the new folder, or None when nothing changed."""
    d = _drive(drive)
    if not d or not on_system_drive(tempfile.gettempdir(), drive=d):
        return None
    root = cache_root(config, drive=d)
    if root is None:
        return None
    target = root / REDIRECT_DIR / "tmp"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None                                      # the drive is missing: temp stays where it was
    cutoff = time.time() - TEMP_MAX_AGE_S
    try:
        for e in os.scandir(target):
            try:
                if e.stat(follow_symlinks=False).st_mtime < cutoff:
                    (shutil.rmtree(e.path, ignore_errors=True) if e.is_dir(follow_symlinks=False) else os.unlink(e.path))
            except OSError:
                continue
    except OSError:
        pass
    tempfile.tempdir = str(target)
    return str(target)


def system_drive_report(config, *, drive: str | None = None) -> list[dict]:
    """The configured gBox roots on the system drive: [{root, path, note}] (empty off Windows or when none are)."""
    d = _drive(drive)
    if not d:
        return []
    out = []
    for root, path, note in (
            ("cache", getattr(config, "cache", None), "staged games and builds are refused there (cache_dirs.windows)"),
            ("runtime", getattr(config, "runtime", None), "emulators, saves, recordings and extracts (runtime_dirs.windows)"),
            ("data_dir", getattr(config, "data_dir", None), "this PC's gBox database, artifacts and gameplay memory"),
            ("temp", tempfile.gettempdir(), "Python temp files (redirected when the cache is on another drive)")):
        if path is not None and on_system_drive(path, drive=d):
            out.append({"root": root, "path": str(path), "note": note})
    return out


# ------------------------------------------------------------------------------------------------ builds are opt-in

def auto_send(config) -> bool:
    return bool(getattr(getattr(config, "builds", None), "auto_send", False))


def _key(game_id: str, name: str) -> str:
    return f"{game_id}/{name}"


def record_receipt(store, pc: str, game_id: str, name: str, *, by: str = "operator", job: str = "",
                   at: float | None = None) -> dict:
    """The operator downloaded this build to this PC: automatic work may use (and refresh) it there."""
    doc = {"pc": pc, "game_id": game_id, "name": name, "by": by, "job": job or "", "ts": time.time() if at is None else at}
    store.put(RECEIPT_KIND, f"{pc}/{game_id}/{name}", doc)
    return doc


def forget_receipts(store, game_id: str, name: str, pcs=None) -> list[str]:
    """The build was deleted (everywhere, or on these PCs): its receipts go with it."""
    wanted = None if pcs is None else {str(p).lower() for p in pcs}
    gone = []
    for doc in store.all(RECEIPT_KIND):
        if doc.get("game_id") == game_id and doc.get("name") == name and (
                wanted is None or str(doc.get("pc") or "").lower() in wanted):
            store.delete(RECEIPT_KIND, f"{doc.get('pc')}/{game_id}/{name}")
            gone.append(str(doc.get("pc") or ""))
    return gone


def receipt_keys(store, pc: str) -> list[str]:
    """"game_id/name" of every build the operator downloaded to this PC (by worker name, any case)."""
    pc = str(pc or "").lower()
    if not pc:
        return []
    try:
        docs = store.all(RECEIPT_KIND)
    except Exception:                                    # noqa: BLE001 - another store implementation
        return []
    return sorted({_key(d["game_id"], d["name"]) for d in docs
                   if str(d.get("pc") or "").lower() == pc and d.get("game_id") and d.get("name")})


def receipt_file(cfg, game_id: str, name: str) -> Path:
    return Path(cfg.cache) / "mods" / game_id / f".{name}{RECEIPT_SUFFIX}"


def write_local_receipt(cfg, game_id: str, name: str, **facts) -> bool:
    try:
        p = receipt_file(cfg, game_id, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"game_id": game_id, "name": name, "pc": platform.node(), "ts": time.time(), **facts}),
                     encoding="utf-8")
        return True
    except OSError:
        return False


def has_local_receipt(cfg, game_id: str, name: str) -> bool:
    try:
        return receipt_file(cfg, game_id, name).is_file()
    except (OSError, ValueError, TypeError):
        return False


def operator_job(job: dict, parent: dict | None = None) -> bool:
    """The operator's own request (their click, or the in-app chat agent on their words), not automation: an
    agent / MCP / Hermes / screensaver / launch-failure ("gbox-auto") job, or a tool running inside one, is not."""
    actor = job.get("actor")
    if actor not in OPERATOR_ACTORS or (actor == "operator" and job.get("agent_use")):
        return False
    if parent:
        p = parent.get("actor")
        if p not in OPERATOR_ACTORS or (p == "operator" and parent.get("agent_use")):
            return False
    return True


def permit(store, config, job: dict, worker: dict | None) -> dict:
    """What a claimed job may copy onto its PC (stamped on the job the worker receives, never stored)."""
    origin = job.get("origin") if isinstance(job.get("origin"), dict) else {}
    parent = None
    if origin.get("parent_job"):
        try:
            parent = store.get("job", origin["parent_job"])
        except Exception:                                # noqa: BLE001
            parent = None
    return {"operator": operator_job(job, parent), "auto_send": auto_send(config),
            "receipts": receipt_keys(store, (worker or {}).get("name") or "")}


def copy_refusal(cfg, game_id: str, name: str, ctx=None) -> str | None:
    """Why the current worker job may not copy this build onto this PC (None: it may)."""
    ctx = JOB.get() if ctx is None else ctx
    if ctx is None or not getattr(ctx, "server", None):
        return None                                      # not a worker job (local run, the control plane, a test)
    p = getattr(ctx, "build_permit", None)
    actor = getattr(ctx, "actor", None)
    if isinstance(p, dict):
        operator, auto, receipts = bool(p.get("operator")), bool(p.get("auto_send")), set(p.get("receipts") or ())
    else:                                                # a control plane that stamps no permit: the job's own facts
        operator = actor in OPERATOR_ACTORS and (actor == "gbox-agent" or not getattr(ctx, "agent_use", False))
        auto, receipts = auto_send(cfg), set()
    if operator or auto or _key(game_id, name) in receipts or has_local_receipt(cfg, game_id, name):
        return None
    pc = platform.node()
    return (f"build {name} would have to be copied onto {pc}, but the operator has not downloaded it "
            f"there. Builds reach a PC only when the operator downloads them ([builds] auto_send = false), so this "
            f"{actor or 'automatic'} job does not copy it. Download it on {pc} (Builds ▸ download icon) or run this "
            "on a PC that has it.")


def check_build_copy(cfg, game_id: str, name: str, dest=None, *, ctx=None, drive: str | None = None) -> None:
    """Before a build's files are copied or downloaded onto this PC: off the system drive, and opted in."""
    if dest is not None:
        require_off_system(cfg, dest, f"build {name}", drive=drive)
    why = copy_refusal(cfg, game_id, name, ctx)
    if why:
        raise BuildNotOptedIn(why)


def build_on_pc(worker: dict | None, game_id: str, name: str) -> bool:
    """The PC's heartbeat lists this build (the build itself or a staged copy of it)."""
    for r in (worker or {}).get("local_builds") or []:
        if isinstance(r, dict) and r.get("game_id") == game_id and (
                r.get("name") == name or r.get("staged_of") == name or str(r.get("name") or "").split("~")[0] == name):
            return True
    return False


def sendable(store, config, worker: dict | None, game_id: str, name: str) -> bool:
    """Automatic work may use this build on this PC without copying anything the operator did not ask for: the PC
    holds the central collection itself (Linux control-plane node), already has it, holds a receipt, or auto_send."""
    if auto_send(config) or (worker or {}).get("os") == "linux" or build_on_pc(worker, game_id, name):
        return True
    return _key(game_id, name) in receipt_keys(store, (worker or {}).get("name") or "")

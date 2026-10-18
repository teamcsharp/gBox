"""Bounded read-only evidence for a server-validated Cxbx launch.

No emulator installation, archive extraction, save access, process attachment,
or game launch occurs here. The tool wrapper authenticates the historical job.
Files describe the current worker snapshot, not necessarily launch-time bytes.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time


BINARY_LIMIT = 128 * 1024 * 1024
TEXT_LIMIT = 128 * 1024
LOG_SAMPLE = 32 * 1024
CHUNK = 64 * 1024
SETTINGS_KEYS = {
    "gui": {"datastoragetoggle", "datacustomlocation", "consoletypetoggle",
            "ignoreinvalidxbesig", "ignoreinvalidxbesec"},
    "core": {"revision", "flagslle", "krnldebugmode", "krnldebuglogfile",
             "allowadminprivilege", "loggedmodules", "loglevel", "logpopuptestcase"},
    "video": {"videoresolution", "adapter", "direct3ddevice", "vsync",
              "fullscreen", "maintainaspect", "renderresolution"},
    "audio": {"adapter", "pcm", "xadpcm", "unknowncodec", "muteonunfocus"},
    "hacks": {"disablepixelshaders", "useallcores", "skiprdtscpatching"},
}


def _stamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value <= 0:
        raise ValueError("Launch timestamps must be finite positive numbers")
    return float(value)


def _plain_path(path: Path):
    """Reject links/junctions in every component, including configured roots."""
    for part in reversed((path, *path.parents)):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Diagnostic paths must not contain symlinks or reparse points")


def _inside(root: Path, path: Path):
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Diagnostic path must be absolute without traversal")
    # lexical comparison precedes filesystem operations on the candidate
    if not path.is_relative_to(root):
        raise ValueError("Diagnostic path is outside the expected runtime directory")
    _plain_path(path)
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("Diagnostic path escaped its runtime directory")


def _identity(info):
    # Python 3.12 Windows stat uses creation time for legacy st_ctime, while
    # fstat may expose change time. Compare birth time across path/handle there.
    identity_time = getattr(info, "st_birthtime_ns", info.st_ctime_ns) if os.name == "nt" else info.st_ctime_ns
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, identity_time)


def _final_path(reader):
    """Verify the Windows handle target before reading, closing parent-link races."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes as w
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = w.DWORD
    result = ctypes.create_unicode_buffer(32768)
    size = kernel.GetFinalPathNameByHandleW(msvcrt.get_osfhandle(reader.fileno()), result, len(result), 0)
    if size == 0 or size >= len(result):
        raise ValueError("Cannot verify diagnostic file handle path")
    value = result.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _snapshot(root: Path, path: Path, *, limit: int, content=False, log=False):
    """Open fixed files read-only; never allocate or hash an unbounded file."""
    _inside(root, path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Diagnostic source must be a regular file")
    if not log and before.st_size > limit:
        raise ValueError("Diagnostic source exceeds its size limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as reader:
        opened = os.fstat(reader.fileno())
        if _identity(before) != _identity(opened):
            raise ValueError("Diagnostic source changed while opening")
        final = _final_path(reader)
        if final is not None and final != path:
            raise ValueError("Diagnostic file handle points to a different path")
        _inside(root, path)
        result = {"path": str(path), "size": opened.st_size,
                  "mtime": opened.st_mtime, "ctime": opened.st_ctime}
        if log and opened.st_size > 2 * LOG_SAMPLE:
            head = reader.read(LOG_SAMPLE)
            reader.seek(opened.st_size - LOG_SAMPLE)
            tail = reader.read(LOG_SAMPLE)
            if len(head) != LOG_SAMPLE or len(tail) != LOG_SAMPLE:
                raise ValueError("Diagnostic log changed while sampling")
            result.update(sampled=True, head=head.decode("utf8", "replace"),
                          tail=tail.decode("utf8", "replace"),
                          head_sha256=hashlib.sha256(head).hexdigest(),
                          tail_sha256=hashlib.sha256(tail).hexdigest())
        else:
            # Exact initial length plus one detects growth; bounded even under a writer.
            remaining, digest, chunks = opened.st_size + 1, hashlib.sha256(), []
            while remaining:
                data = reader.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                digest.update(data)
                if content or log:
                    chunks.append(data)
            if remaining != 1:
                raise ValueError("Diagnostic source changed size while reading")
            result["sha256"] = digest.hexdigest()
            if content or log:
                result["text"] = b"".join(chunks).decode("utf-8-sig", "replace")
            if log:
                result["sampled"] = False
        after = os.fstat(reader.fileno())
        if _identity(opened) != _identity(after) or opened.st_ctime_ns != after.st_ctime_ns:
            raise ValueError("Diagnostic source changed while reading")
        _inside(root, path)
        if _identity(opened) != _identity(path.stat()):
            raise ValueError("Diagnostic source was replaced while reading")
    result["state"] = "read"
    return result


def _read(root, path, **kwargs):
    try:
        return _snapshot(root, path, **kwargs)
    except FileNotFoundError:
        return {"path": str(path), "state": "missing"}
    except (OSError, ValueError) as exc:
        return {"path": str(path), "state": "unavailable", "reason": str(exc)}


def _settings(text):
    # Cxbx deliberately permits repeated keys; ConfigParser would lose evidence.
    section, values = "", {}
    for line in text.splitlines():
        if match := re.fullmatch(r"\s*\[([^\]]+)\]\s*(?:[;#].*)?", line):
            section = match[1].lower()
        elif not line.lstrip().startswith((";", "#")) and "=" in line:
            key, value = line.split("=", 1)
            key = key.strip().lower()
            if key in SETTINGS_KEYS.get(section, set()):
                values.setdefault(section, {}).setdefault(key, []).append(value.strip()[:2048])
    return values


def _reject_constant(value):
    raise ValueError(f"Non-finite installation receipt value: {value}")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        _reject_constant(value)
    return parsed


def collect(config, *, xbe: Path, launch: dict) -> dict:
    """Collect only the fixed runtime and exact extracted XBE of a trusted job."""
    ids = {key: launch.get(key) for key in ("game_id", "job_id", "worker_id", "session_id")}
    if any(not isinstance(value, str) or not value for value in ids.values()) \
            or ids["session_id"] != f'{ids["worker_id"]}-{ids["job_id"]}':
        raise ValueError("Diagnostic launch identity is incomplete or inconsistent")
    started, finished = _stamp(launch.get("started")), _stamp(launch.get("finished"))
    if finished < started:
        raise ValueError("Diagnostic launch time interval is inverted")
    detail = launch.get("detail")
    if not isinstance(detail, dict) or not isinstance(detail.get("rom"), str) \
            or Path(detail["rom"]) != xbe:
        raise ValueError("Diagnostic XBE must match the exact launch receipt")
    runtime = config.runtime.absolute()
    extraction = runtime / "extract"
    if xbe.name.lower() != "default.xbe" or not xbe.is_relative_to(extraction):
        raise ValueError("Diagnostic XBE must be default.xbe in this worker's extracted runtime")
    # Fail closed on unsafe roots even when the specific executable was removed.
    _plain_path(runtime)
    home = runtime / "xbox" / "cxbx"
    files = {name: _read(runtime, home / name, limit=BINARY_LIMIT)
             for name in ("cxbxr-ldr.exe", "cxbxr-emu.dll", "cxbx.exe", "SDL2.dll")}
    files["default.xbe"] = _read(extraction, xbe, limit=BINARY_LIMIT)
    settings = _read(runtime, home / "settings.ini", limit=TEXT_LIMIT, content=True)
    if settings.get("state") == "read":
        settings["selected_values"] = _settings(settings.pop("text"))
    receipt = _read(runtime, home / ".gbox-installed.json", limit=TEXT_LIMIT, content=True)
    if receipt.get("state") == "read":
        raw = receipt.pop("text")
        try:
            parsed = json.loads(raw, parse_constant=_reject_constant, parse_float=_finite_float)
            if not isinstance(parsed, dict):
                raise ValueError("Installation receipt is not an object")
            receipt["recorded"] = {key: parsed[key] for key in ("source", "tag", "sha256", "at")
                                   if key in parsed and isinstance(parsed[key], (str, int, float, bool, type(None)))}
            receipt["authority"] = "local installation metadata; not a binary verification"
        except (ValueError, RecursionError) as exc:
            receipt["parse_error"] = str(exc)
    logs = {name: _read(runtime, home / name, limit=TEXT_LIMIT, log=True)
            for name in ("gbox-kernel.log", "gbox-launch.log")}
    for value in logs.values():
        value["attribution"] = "current file; historical launch association is not independently established"
        if value.get("state") == "read":
            value["mtime_before_launch"] = value["mtime"] < started
    pid = detail.get("launch_pid")
    process = {"state": "not_inspected", "reason": "Historical launch has no verified process creation identity; PID alone is insufficient"}
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        process["recorded_launch_pid"] = pid
    return {"schema": 1, "read_only": True, "snapshot_at": time.time(),
            "scope": "Current fixed Cxbx files and exact historical extracted XBE; no saves or processes read",
            "launch": ids | {"started": started, "finished": finished},
            "files": files, "settings": settings, "installation_receipt": receipt,
            "logs": logs, "process": process,
            "limitations": ["Current file hashes do not prove launch-time bytes or archive completeness",
                            "A stable render window or nonblack capture does not establish gameplay",
                            "No game launch, save access, settings change, or runtime repair was performed"]}

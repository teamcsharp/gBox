"""Read N64 ROMs from common archives and normalize their byte order in memory."""
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile


ROM_EXTENSIONS = (".z64", ".v64", ".n64")
MAX_ROM_BYTES = 128 * 1024 * 1024
# 7-Zip reads the archive from the library share (SMB). A fixed 120 s limit failed a whole swap when the share
# stalled (#1053: OoT, 24 MB .7z). Allow at least MIN_7Z_SECONDS, more for big archives, and retry once.
MIN_7Z_SECONDS = 300
MIN_7Z_BYTES_PER_SECOND = 64 * 1024
CACHE_ENV = "GBOX_N64_ROM_CACHE"


def cache_dir() -> Path | None:
    """Where unpacked archive ROMs are kept (normalized .z64), so later reads skip the share and 7-Zip.
    GBOX_N64_ROM_CACHE overrides it; an empty value disables the cache."""
    v = os.environ.get(CACHE_ENV)
    if v is not None:
        return Path(v) if v.strip() else None
    from .side_dirs import side_dir
    return side_dir("gbox-cache") / "n64-rom"


def _cache_file(path: Path) -> Path | None:
    root = cache_dir()
    if root is None:
        return None
    st = path.stat()
    key = hashlib.sha256(f"{path.resolve()}\0{st.st_size}\0{st.st_mtime_ns}".encode()).hexdigest()[:24]
    return root / f"{key}.z64"


def _cached(path: Path) -> bytes | None:
    try:
        f = _cache_file(path)
        if f is None or not f.is_file():
            return None
        data = f.read_bytes()
    except OSError:
        return None
    return data if data[:4] == b"\x80\x37\x12\x40" and len(data) % 4 == 0 else None


def _store(path: Path, data: bytes) -> None:
    """Best effort: a cache that can't be written never fails the read."""
    try:
        f = _cache_file(path)
        if f is None:
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=f.parent, suffix=".part")
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, f)
    except OSError:
        pass


def _7z_timeout(path: Path) -> float:
    return max(MIN_7Z_SECONDS, path.stat().st_size / MIN_7Z_BYTES_PER_SECOND)


def _check_size(size: int) -> None:
    if size > MAX_ROM_BYTES:
        raise ValueError(f"N64 ROM exceeds the {MAX_ROM_BYTES // 1024**2} MiB extraction limit")


def _from_7z(path: Path) -> bytes:
    exe = next((p for name in ("7z", "7zz", "7zr") if (p := shutil.which(name))), None)
    if not exe:
        raise RuntimeError("7-Zip is needed to read this .7z N64 ROM; install 7z on this worker")
    listing = subprocess.run([exe, "l", "-slt", str(path)], capture_output=True, text=True, timeout=60, check=True)
    entries = listing.stdout.split("----------", 1)
    if len(entries) != 2:
        raise ValueError(f"7-Zip could not list ROMs in {path.name}")
    members = []
    for block in entries[1].split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        name = fields.get("Path", "")
        if name.lower().endswith(ROM_EXTENSIONS) and fields.get("Folder") != "+":
            members.append((name, int(fields.get("Size", "0"))))
    if not members:
        raise ValueError(f"no .z64, .v64, or .n64 ROM in {path.name}")
    name, size = members[0]
    _check_size(size)
    timeout = _7z_timeout(path)
    for attempt in (1, 2):
        try:
            extracted = subprocess.run([exe, "x", "-so", str(path), name], capture_output=True, timeout=timeout,
                                       check=True)
            break
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise
    if len(extracted.stdout) != size:
        raise ValueError(f"7-Zip returned an incomplete N64 ROM from {path.name}")
    return extracted.stdout


def normalize(data: bytes) -> bytes:
    """Convert .v64 halfword order or .n64 word order to big-endian .z64 bytes."""
    if data[:4] == b"\x80\x37\x12\x40":
        return data
    if len(data) % 4:
        raise ValueError("N64 ROM size is not a multiple of four bytes")
    out = bytearray(len(data))
    if data[:4] == b"\x37\x80\x40\x12":
        out[0::2], out[1::2] = data[1::2], data[0::2]
    elif data[:4] == b"\x40\x12\x37\x80":
        out[0::4], out[1::4], out[2::4], out[3::4] = data[3::4], data[2::4], data[1::4], data[0::4]
    else:
        raise ValueError("not an N64 ROM (expected .z64, .v64, or .n64 data)")
    return bytes(out)


def read(path: str | Path) -> bytes:
    """Return big-endian ROM bytes without changing the operator's original file."""
    path = Path(path)
    archived = path.suffix.lower() in (".7z", ".zip")
    if archived and (hit := _cached(path)) is not None:
        return hit
    if path.suffix.lower() == ".7z":
        data = _from_7z(path)
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            member = next((m for m in archive.infolist() if not m.is_dir() and m.filename.lower().endswith(ROM_EXTENSIONS)), None)
            if member is None:
                raise ValueError(f"no .z64, .v64, or .n64 ROM in {path.name}")
            _check_size(member.file_size)
            data = archive.read(member)
    else:
        _check_size(path.stat().st_size)
        data = path.read_bytes()
    data = normalize(data)
    if archived:
        _store(path, data)
    return data

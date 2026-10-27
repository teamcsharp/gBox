"""Inspect ROM archives and prepare complete disc sets in a local, reusable cache."""
import hashlib
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import threading
import zipfile
import tarfile

_LOCK = threading.Lock()
ARCHIVE_SUFFIXES = {'.zip', '.7z', '.rar', '.tar', '.gz', '.bz2', '.xz', '.lzma', '.zst',
                    '.tgz', '.tbz', '.tbz2', '.txz', '.tzst', '.cab', '.arj', '.lzh', '.lha',
                    '.wim', '.swm', '.esd', '.cpio', '.rpm', '.deb', '.xar', '.001'}


def is_archive(src):
    return Path(src).suffix.lower() in ARCHIVE_SUFFIXES


def _tar(src):
    return str(src).lower().endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz', '.tbz2', '.tar.xz', '.txz'))


def seven_zip():
    for exe in (shutil.which("7zz"), shutil.which("7z"), "C:/Program Files/7-Zip/7z.exe",
                "C:/Program Files (x86)/7-Zip/7z.exe"):
        if exe and Path(exe).is_file():
            return exe
    raise RuntimeError("7-Zip is required on this worker. Run provision_node (archive tools) or gBox setup; "
                       "Linux: install 7zip / p7zip-full; Windows: winget install 7zip.7zip")


def safe_name(name):
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or not path.parts:
        raise ValueError(f"Unsafe ROM archive member: {name!r}")
    return name


def members(src):
    src = Path(src)
    if _tar(src):
        with tarfile.open(src) as archive:
            out = []
            for item in archive:
                if item.isdir() and item.name in ('.', './'):
                    continue
                safe_name(item.name)
                if not (item.isfile() or item.isdir()):
                    raise ValueError('ROM archives cannot contain links or special files')
                if item.isfile():
                    out.append({'name': item.name, 'size': item.size})
            return out
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as z:
            out = []
            for m in z.infolist():
                safe_name(m.filename)
                if (m.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("ROM archives cannot contain symbolic links")
                if not m.is_dir():
                    out.append({"name": safe_name(m.filename), "size": m.file_size})
            return out
    p = subprocess.run([seven_zip(), "l", "-slt", "-ba", "-sccUTF-8", str(src)],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=60, encoding="utf8", errors="replace")
    if p.returncode:
        raise ValueError(f"Cannot read ROM archive {src.name}: {p.stderr[:300]}")
    out = []
    for block in p.stdout.replace("\r", "").split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" not in fields:
            continue
        name = safe_name(fields["Path"])
        if fields.get("Symbolic Link") or fields.get("Hard Link"):
            raise ValueError("ROM archives cannot contain links")
        if fields.get("Folder") == "+" or fields.get("Attributes", "").startswith("D"):
            continue
        out.append({"name": name, "size": int(fields.get("Size", 0))})
    return out


def boot_member(entries):
    from .catalog import EXT_PLATFORM, SNIFF_EXT
    # A disc descriptor references ALL tracks; selecting the largest BIN loses audio/data tracks.
    for suffix in ("/ps3_game/usrdir/eboot.bin", "/default.xbe", ".m3u", ".gdi", ".cue", ".lst"):
        choices = sorted(e["name"] for e in entries if ("/" + e["name"].lower()).endswith(suffix))
        if choices:
            return choices[0]
    choices = [e for e in entries if Path(e["name"]).suffix.lower() in set(EXT_PLATFORM) | SNIFF_EXT]
    return max(choices, key=lambda e: e["size"])["name"] if choices else None


@contextmanager
def open_member(src, member):
    """Read one validated member as a stream; bound and reap external extractors."""
    safe_name(member)
    if _tar(src):
        with tarfile.open(src) as archive:
            item = archive.getmember(member)
            if not item.isfile():
                raise ValueError('Archive member is not a regular file')
            with archive.extractfile(item) as stream:
                yield stream
        return
    if Path(src).suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as archive, archive.open(member) as stream:
            yield stream
        return
    proc = subprocess.Popen([seven_zip(), "x", "-so", "-spd", "--", str(Path(src).resolve()), member],
                            stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    timer = threading.Timer(60, proc.kill)
    timer.start()
    try:
        yield proc.stdout
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()


def prefix(src, member, size):
    """Read a bounded disc header without unpacking a multi-gigabyte game during indexing."""
    with open_member(src, member) as stream:
        return stream.read(size)


def repair_cue(path):
    """Repair an unambiguous renamed track in the extracted COPY; never change the ROM library."""
    text = path.read_text(encoding="utf8", errors="replace")
    names = re.findall(r'FILE\s+"([^"]+)"', text, re.I)
    missing = [name for name in names if not (path.parent / safe_name(name)).is_file()]
    if not missing:
        return
    candidates = [f for f in path.parent.glob("*.bin") if f.name not in names]
    if len(missing) != 1 or len(candidates) != 1 or candidates[0].stem != path.stem:
        raise ValueError(f"Disc sheet {path.name} references missing tracks: {missing}")
    path.write_text(text.replace('"' + missing[0] + '"', '"' + candidates[0].name + '"'), encoding="utf8")


def _source_identity(src, config, member):
    from . import catalog
    stat = src.stat()
    identity = {"source": str(src.resolve()), "size": stat.st_size, "member": member}
    # Staging touches mtime on every use for LRU. Its recorded content hash is
    # reusable only while the record still describes this exact file version.
    db = catalog._db_load(config.cache)
    record = db.get(str(src)) if isinstance(db, dict) else None
    digest = record.get("sha1") if isinstance(record, dict) else None
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{40}", digest) \
            and record.get("ident") == catalog._ident(stat):
        identity["sha1"] = digest.lower()
    else:
        identity["mtime_ns"] = stat.st_mtime_ns
    return identity


def prepare(src, config, member, progress=lambda *_: None):
    """Extract once, retain relative track paths, and publish a cache only after extraction succeeds."""
    src = Path(src)
    member = safe_name(member)
    identity = _source_identity(src, config, member)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    from . import storage_policy                       # never an extracted game on a Windows system drive
    root = storage_policy.extract_root(config)
    out = root / ("rom-" + key)
    marker = out / ".gbox-extracted.json"
    with _LOCK:
        if marker.is_file() and (out / member).is_file():
            if json.loads(marker.read_text()) == identity:
                return out / member
        entries = members(src)
        if member not in {e["name"] for e in entries}:
            raise ValueError(f"Boot member missing from ROM archive: {member}")
        root.mkdir(parents=True, exist_ok=True)
        required = sum(e["size"] for e in entries)
        if shutil.disk_usage(root).free < required + 64 * 1024**2:
            raise OSError(f"Not enough local disk space to unpack {src.name} ({required / 1024**3:.1f} GiB)")
        progress(32, f"Unpacking {src.name}")
        with tempfile.TemporaryDirectory(prefix="rom-part-", dir=root) as temp:
            work = Path(temp)
            if _tar(src):
                with tarfile.open(src) as archive:
                    for e in entries:
                        dst = work / e['name']
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(e['name']) as reader, dst.open('wb') as writer:
                            shutil.copyfileobj(reader, writer)
            elif src.suffix.lower() == ".zip":
                with zipfile.ZipFile(src) as z:
                    for info in z.infolist():
                        name = safe_name(info.filename)
                        if info.is_dir():
                            continue
                        dst = work / name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(info) as reader, dst.open("wb") as writer:
                            shutil.copyfileobj(reader, writer)
            else:
                p = subprocess.run([seven_zip(), "x", "-y", "-sccUTF-8", f"-o{work}", str(src)],
                                   capture_output=True, stdin=subprocess.DEVNULL, timeout=1800)
                if p.returncode:
                    raise RuntimeError(f"ROM extraction failed: {p.stderr.decode('utf8', 'replace')[:300]}")
            for e in entries:
                f = work / e["name"]
                if f.is_symlink() or not f.is_file() or f.stat().st_size != e["size"]:
                    raise ValueError(f"Incomplete ROM extraction: {e['name']}")
            for cue in work.rglob("*.cue"):
                repair_cue(cue)
            (work / ".gbox-extracted.json").write_text(json.dumps(identity))
            # The content-addressed destination is owned by this cache. Failed extractions never reach it.
            if out.exists():
                raise RuntimeError(f"Incomplete existing ROM cache: {out}")
            os.replace(work, out)
        progress(70, "ROM archive ready")
        return out / member

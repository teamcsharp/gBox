"""Prepare byte-preserving Xbox DVD folders using a pinned XboxDev extractor."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
import time
import zipfile

from .config import HOST_OS
from .registry import ToolUnavailable, Unsupported

TAG = "build-202609111233"
URL = f"https://github.com/XboxDev/extract-xiso/releases/download/{TAG}/extract-xiso-Win64_Release.zip"
ZIP_SHA256 = "fc891dfa72f08e3838a2f8b7ec34a8e4d61678da1cc8fee879677f00bf114ce3"
EXE_SHA256 = "7e97536f978735d586a2f78327aa337b9a19b3e364fa715316fb42d07d33e0b7"
MAGIC = b"MICROSOFT*XBOX*MEDIA"
# These are the descriptor bases checked by the pinned XboxDev release.
BASES = (0, 0x0FD90000, 0x02080000, 0x18300000)
MAX_IMAGE = 16 * 1024**3
MAX_FILES = 100000
MAX_LISTING = 16 * 1024**2
MAX_RECEIPT = 32 * 1024**2
_LOCK = threading.Lock()


def _plain(path: Path):
    if ".." in path.parts:
        raise ValueError("Xbox disc paths cannot traverse parent directories")
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Xbox disc paths cannot traverse links or junctions: {part}")


def _sha(path: Path) -> str:
    _plain(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def layout(path: Path) -> dict:
    """Require a complete recognized XDVDFS descriptor and a bounded root table."""
    _plain(path)
    size = path.stat().st_size
    if not 0x10800 <= size <= MAX_IMAGE:
        raise Unsupported("Xbox disc image size is outside the supported XISO/DVD range")
    found = []
    with path.open("rb") as stream:
        for base in BASES:
            at = base + 0x10000
            if at + 2048 > size:
                continue
            stream.seek(at)
            block = stream.read(2048)
            if block[:20] != MAGIC:
                continue
            if block[-20:] != MAGIC:
                raise ValueError("Xbox disc has an incomplete XDVDFS descriptor")
            sector, length = struct.unpack_from("<II", block, 20)
            offset = base + sector * 2048
            if not 14 <= length <= MAX_LISTING or offset < at + 2048 or offset + length > size:
                raise ValueError("Xbox disc root directory is outside its image bounds")
            found.append({"base": base, "root_sector": sector, "root_bytes": length})
    if len(found) != 1:
        raise Unsupported("Xbox disc needs exactly one recognized XDVDFS volume; unknown or ambiguous image format")
    return found[0]


def _name(name: str) -> str:
    name = name.replace("\\", "/")
    parts = name.split("/")
    if not name or len(name) > 1024 or len(parts) > 32:
        raise ValueError("Xbox disc has an invalid or excessively deep path")
    for part in parts:
        device = part.split(".")[0].upper()
        if (not part or part in (".", "..") or len(part.encode("utf8")) > 255
                or part[-1] in ". " or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or device in {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
                or re.fullmatch(r"(?:COM|LPT)[0-9\u00b9\u00b2\u00b3]", device)):
            raise ValueError(f"Xbox disc contains an unsafe Windows path: {name!r}")
    return name


def listing(text: str, image_size: int) -> tuple[dict[str, int], set[str]]:
    """Validate the entire bounded upstream listing before allowing any writes."""
    files, directories, seen = {}, set(), set()
    summary = None
    for line in text.splitlines():
        entry = re.fullmatch(r"([/\\].+) \((\d+) bytes\)", line)
        if entry:
            raw, count = entry.groups()
            directory = raw.endswith(("/", "\\"))
            name = _name(raw.replace("\\", "/")[1:].rstrip("/") if directory else raw.replace("\\", "/")[1:])
            if name.casefold() in seen:
                raise ValueError("Xbox disc contains duplicate or case-colliding paths")
            seen.add(name.casefold())
            size = int(count)
            if size > 0xFFFFFFFF or len(seen) > MAX_FILES:
                raise ValueError("Xbox disc exceeds supported file/count limits")
            if directory:
                directories.add(name)
            else:
                files[name] = size
        elif re.fullmatch(r"\d+ files in .+ total \d+ bytes", line):
            if summary is not None:
                raise ValueError("Xbox disc listing contains more than one summary")
            summary = (int(line.split()[0]), int(re.search(r"total (\d+) bytes$", line).group(1)))
        elif line and not line.startswith(("extract-xiso ", "listing ")):
            raise ValueError("Unrecognized XboxDev disc listing")
    if not files or summary != (len(files), sum(files.values())):
        raise ValueError("Xbox disc listing is incomplete or empty")
    if summary[1] > min(MAX_IMAGE, image_size):
        raise ValueError("Xbox disc file sizes exceed the image bounds")
    file_keys = {name.casefold() for name in files}
    for name in (*files, *directories):
        parts = name.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            if parent.casefold() in file_keys:
                raise ValueError("Xbox disc uses a file as a parent directory")
            directories.add(parent)
    roots = [name for name in files if name.lower() == "default.xbe"]
    if len(roots) != 1:
        raise Unsupported("Xbox DVD image must contain exactly one root default.xbe; Xbox 360 is not supported")
    return files, directories


def validate_archive(entries):
    """The containing archive must also be safe on the destination Windows host."""
    paths = set()
    if len(entries) > MAX_FILES:
        raise ValueError("Xbox archive has too many members")
    for entry in entries:
        name = _name(entry["name"]).casefold()
        if name in paths:
            raise ValueError("Xbox archive contains duplicate or case-colliding paths")
        paths.add(name)
    for name in paths:
        parts = name.split("/")
        if any("/".join(parts[:index]) in paths for index in range(1, len(parts))):
            raise ValueError("Xbox archive uses a file as a parent directory")


def ensure_extractor(config) -> Path:
    if HOST_OS != "windows":
        raise ToolUnavailable("Xbox disc extraction needs a Windows worker")
    home = (config.runtime / "xbox" / "tools" / f"extract-xiso-{TAG}").absolute()
    _plain(home)
    exe = home / "extract-xiso.exe"
    if home.exists():
        for name in ("extract-xiso.exe", "LICENSE.TXT"):
            _plain(home / name)
        if ({item.name for item in home.iterdir()} != {"extract-xiso.exe", "LICENSE.TXT"}
                or not exe.is_file() or not (home / "LICENSE.TXT").is_file() or _sha(exe) != EXE_SHA256):
            raise ToolUnavailable(f"Pinned XboxDev extractor is incomplete or changed: {home}")
        return exe
    import httpx
    payload = bytearray()
    with httpx.stream("GET", URL, timeout=180, follow_redirects=True) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            payload.extend(chunk)
            if len(payload) > 1024**2:
                raise ToolUnavailable("XboxDev extractor download exceeds its expected size")
    if hashlib.sha256(payload).hexdigest() != ZIP_SHA256:
        raise ToolUnavailable("XboxDev extractor download checksum did not match the pinned release")
    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="extract-xiso-install-", dir=home.parent) as temporary:
        stage = Path(temporary)
        _plain(stage)
        if not stage.resolve().is_relative_to(home.parent.resolve()):
            raise ValueError("XboxDev staging directory escaped its runtime")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            expected = {"artifacts/extract-xiso.exe", "artifacts/LICENSE.TXT"}
            if len(entries) != 2 or {item.filename for item in entries} != expected:
                raise ToolUnavailable("XboxDev extractor archive has unexpected paths")
            for item in entries:
                if item.is_dir() or item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000 or item.file_size > 1024**2:
                    raise ToolUnavailable("XboxDev extractor archive contains an unsupported member")
                (stage / Path(item.filename).name).write_bytes(archive.read(item))
        if _sha(stage / exe.name) != EXE_SHA256:
            raise ToolUnavailable("XboxDev executable checksum did not match the pinned release")
        os.replace(stage, home)
    return exe


def _run(argv, *, limit: int, timeout: float, progress=lambda: None) -> bytes:
    """Bound native-tool output and time, including malformed/cyclic images."""
    process = subprocess.Popen([str(arg) for arg in argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    output, exceeded, read_error = bytearray(), threading.Event(), []
    def collect():
        try:
            while chunk := process.stdout.read(65536):
                if len(output) + len(chunk) > limit:
                    exceeded.set()
                    process.kill()
                    break
                output.extend(chunk)
        except OSError as error:
            read_error.append(error)
    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("XboxDev disc preparation exceeded its time limit")
            try:
                process.wait(timeout=min(2, max(0.01, deadline-time.monotonic())))
            except subprocess.TimeoutExpired:
                progress()
        reader.join(timeout=5)
        if exceeded.is_set():
            raise ValueError("XboxDev disc listing/output exceeds its size limit")
        if reader.is_alive() or read_error:
            raise ValueError("XboxDev disc output was incomplete")
        if process.returncode:
            raise ValueError("XboxDev rejected this disc image: " + output.decode("utf8", "replace")[-1000:])
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()


def _inventory(root: Path) -> tuple[dict[str, dict], set[str]]:
    _plain(root)
    files, directories, seen, total = {}, set(), set(), 0
    def failed(error):
        raise error
    for folder, dirs, names in os.walk(root, followlinks=False, onerror=failed):
        for name in dirs + names:
            path = Path(folder) / name
            _plain(path)
            relative = _name(path.relative_to(root).as_posix())
            if relative.casefold() in seen or len(seen) >= MAX_FILES:
                raise ValueError("Xbox DVD folder has duplicate paths or too many files")
            seen.add(relative.casefold())
            if path.is_dir():
                directories.add(relative)
            elif path.is_file():
                size = path.stat().st_size
                total += size
                if size > 0xFFFFFFFF or total > MAX_IMAGE:
                    raise ValueError("Xbox DVD folder exceeds its supported size bounds")
                files[relative] = {"size": size, "sha256": _sha(path)}
            else:
                raise ValueError("Xbox DVD extraction contains a non-regular file")
    return files, directories


def prepare(image: str | Path, config, progress=lambda *_: None) -> Path:
    """Never modify the input image; publish an independently checked DVD cache."""
    image = Path(image).absolute()
    descriptor = layout(image)
    progress(33, "Checking Xbox disc image content")
    before = image.stat()
    digest = _sha(image)
    root = (config.runtime / "xbox" / "discs").absolute()
    _plain(root)
    home = root / ("disc-" + digest[:24])
    with _LOCK:
        _plain(home)
        if home.exists():
            marker = home / "receipt.json"
            _plain(marker)
            if not marker.is_file() or marker.stat().st_size > MAX_RECEIPT:
                raise ValueError("Existing Xbox DVD cache has no valid receipt; it was left intact")
            try:
                receipt = json.loads(marker.read_text(encoding="utf8"))
            except (ValueError, UnicodeError) as error:
                raise ValueError("Existing Xbox DVD receipt is invalid; cache was left intact") from error
            files, directories = _inventory(home / "disc")
            if (not isinstance(receipt, dict) or receipt.get("format") != 1 or receipt.get("image_sha256") != digest
                    or receipt.get("layout") != descriptor or receipt.get("extractor_sha256") != EXE_SHA256
                    or receipt.get("files") != files or receipt.get("directories") != sorted(directories)
                    or {p.name for p in home.iterdir()} != {"receipt.json", "disc"}):
                raise ValueError("Existing Xbox DVD cache content differs; it was left intact")
            boot = receipt.get("boot")
            if boot not in files or boot.lower() != "default.xbe":
                raise ValueError("Existing Xbox DVD cache has no valid boot executable")
            return home / "disc" / boot
        tool = ensure_extractor(config)
        progress(35, "Inspecting Xbox DVD files")
        output = _run([tool, "-m", "-l", image], limit=MAX_LISTING, timeout=60)
        files, directories = listing(output.decode("utf8", "strict"), before.st_size)
        root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(root).free < sum(files.values()) + 64 * 1024**2:
            raise OSError("Not enough local disk space to prepare the Xbox DVD folder")
        with tempfile.TemporaryDirectory(prefix="xbox-disc-stage-", dir=root) as temporary:
            work = Path(temporary)
            _plain(work)
            if not work.resolve().is_relative_to(root.resolve()):
                raise ValueError("Xbox DVD staging directory escaped its runtime")
            disc = work / "disc"
            progress(40, "Preparing Xbox DVD folder without changing game files")
            _run([tool, "-m", "-x", "-q", "-d", disc, image], limit=65536, timeout=1800,
                 progress=lambda: progress(42, "Preparing Xbox DVD files"))
            actual, actual_dirs = _inventory(disc)
            if {name: meta["size"] for name, meta in actual.items()} != files or actual_dirs != directories:
                raise ValueError("Xbox DVD extraction differs from its checked listing")
            boot = next(name for name in files if name.lower() == "default.xbe")
            with (disc / boot).open("rb") as stream:
                if stream.read(4) != b"XBEH":
                    raise ValueError("Xbox DVD boot file is not an XBE executable")
            after = image.stat()
            if (after.st_size, after.st_mtime_ns, after.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino) or _sha(image) != digest:
                raise ValueError("Xbox source image changed during preparation")
            receipt = {"format": 1, "image_sha256": digest, "layout": descriptor, "extractor_sha256": EXE_SHA256,
                       "boot": boot, "files": actual, "directories": sorted(directories)}
            (work / "receipt.json").write_text(json.dumps(receipt, sort_keys=True), encoding="utf8")
            os.replace(work, home)
    progress(70, "Xbox DVD folder ready")
    return home / "disc" / boot

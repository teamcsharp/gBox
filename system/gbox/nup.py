"""NUP (NX Package) containers: the clean-room Switch 1/2 archive format used by the operator's dumps.

A `.nup` is a plaintext container (no keys, no tickets): a superblock, a table of contents describing packages
(base / update / addon), a directory tree and file records, then a blob region of raw or Zstandard extents. NUP
Extractor (https://github.com/SPIN0ZAi/nup-extractor, MIT) is the reference implementation; this module is the
gBox port of its documented format (docs/SPEC.md, reproduced in docs/nup.md) and its Python reader, so extraction
runs on every gBox worker (Linux aarch64 Spark, Windows PCs) instead of only where a Windows GUI .exe exists.

The reader follows the spec's conformance rules: the TOC SHA-256 is verified before any TOC value is trusted, every
offset and size is bounds-checked, unknown codecs/flags/kinds are rejected, and extraction never trusts a container
file name as a path (it is sanitised per component and must stay under the destination).

Used by `gbox.switch_nup` (catalog identity), the `switch_nup` tool (info/list/extract/verify/materialize), and the
`python -m gbox.nup` CLI. A materialised folder is a deconstructed Switch title (`exefs/`, `romfs/` at its root):
Eden's `AppLoader_DeconstructedRomDirectory` boots it, and `switch_mods` uses its `romfs/` as the base for LayeredFS.
"""
from __future__ import annotations

import hashlib
import json
import mmap
import os
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

MAGIC = b"NUP\x01"
TOC_MAGIC = b"TOC\x01"
HEADER_SIZE = 0x80
PKG_SIZE = 0x40
DIR_SIZE = 0x18
FILE_SIZE = 0x50
EXTENT_ALIGN = 16
NO_DIR = 0xFFFFFFFF

CODEC_RAW = 0
CODEC_ZSTD = 1
CODEC_NAMES = {CODEC_RAW: "raw", CODEC_ZSTD: "zstd"}

KIND_BASE = 0
KIND_UPDATE = 1
KIND_ADDON = 2
KIND_ADDON_UPDATE = 3
KIND_SYSTEM = 4
KIND_NAMES = {KIND_BASE: "base", KIND_UPDATE: "update", KIND_ADDON: "addon",
              KIND_ADDON_UPDATE: "addon_update", KIND_SYSTEM: "system"}

TLV_NPDM = 0x0001
TLV_NACP = 0x0002
TLV_ICON = 0x0003
TLV_DISPLAY_VERSION = 0x0004
TLV_TITLE_NAME = 0x0005
TLV_PUBLISHER = 0x0006
TLV_BUILD_ID = 0x0007
TLV_SOURCE_DUMP = 0x0008
TLV_LOCALIZED_TITLES = 0x0009
TLV_LOCALIZED_ICONS = 0x000A

PKG_FLAG_STANDALONE_UPDATE = 0x01
MAX_PROBLEMS = 200                      # verify() reports at most this many, then counts the rest
MARKER = ".gbox-nup.json"               # written by materialise(): what the extracted folder is
BUFFER = 1 << 20                        # extraction buffer: 1 MiB writes read faster than 128 KiB on both nodes

_SUPER = struct.Struct("<4sHHQQ32sQQII16s32s")
_TOC_HEAD = struct.Struct("<4sIQQQQQ")
_PKG = struct.Struct("<QIIIIBBHIQI20x")
_DIR = struct.Struct("<IIIIQ")
_FILE = struct.Struct("<IIQQQ32sBBH12x")
_TLV = struct.Struct("<HHI")

assert (_SUPER.size, _PKG.size, _DIR.size, _FILE.size, _TOC_HEAD.size) == (0x80, 0x40, 0x18, 0x50, 0x30)

_UTF8 = "utf-8"
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_WIN_BAD = set('<>:"|?*')
_TITLE_TAG = re.compile(r"\[([0-9A-Fa-f]{16})\]")


class NupError(ValueError):
    """Malformed, nonconforming or unsafe NUP data (fail closed)."""


class NupCancelled(Exception):
    """The operator cancelled this extraction/verification."""


# --- records ----------------------------------------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class NupPackage:
    """One package record: a base game, an update or an add-on."""

    index: int
    title_id: int
    root_dir: int
    exefs_dir: int
    romfs_dir: int
    version: int
    kind: int
    flags: int
    meta_offset: int
    meta_size: int

    @property
    def kind_name(self) -> str:
        return KIND_NAMES.get(self.kind, f"kind{self.kind}")

    @property
    def title_id_hex(self) -> str:
        return f"{self.title_id:016X}"

    @property
    def version_str(self) -> str:
        return f"{self.version >> 16}.{(self.version >> 8) & 0xFF}.{self.version & 0xFF}"

    @property
    def standalone_update(self) -> bool:
        return bool(self.flags & PKG_FLAG_STANDALONE_UPDATE)

    @property
    def is_game(self) -> bool:
        return self.kind in (KIND_BASE, KIND_UPDATE)


@dataclass(slots=True, frozen=True)
class NupDir:
    name: str
    first_child: int
    child_count: int


@dataclass(slots=True, frozen=True)
class NupFile:
    name: str
    size: int
    sha256: bytes
    extent_offset: int
    extent_size: int
    codec: int

    @property
    def codec_name(self) -> str:
        return CODEC_NAMES.get(self.codec, f"codec{self.codec}")

    @property
    def sha256_hex(self) -> str:
        return self.sha256.hex()


@dataclass(slots=True, frozen=True)
class NupNode:
    """A child of a directory: a subdirectory or a file."""

    is_dir: bool
    index: int
    name: str


@dataclass(slots=True, frozen=True)
class PlannedFile:
    """One output of an extraction plan: the container file and where it lands (relative to the destination)."""

    file_index: int
    relpath: str
    size: int


# --- helpers ----------------------------------------------------------------------------------------------------------

def is_nup(path: str | Path) -> bool:
    """Whether the file starts with the NUP magic (reads 4 bytes; a directory is not a NUP)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == MAGIC
    except OSError:
        return False


def title_id_from_name(path: str | Path) -> str | None:
    """The bracketed 16-hex title id a dump tool puts in the file name (`Game [0400...].nup`), else None."""
    m = _TITLE_TAG.search(Path(path).name)
    return m[1].upper() if m else None


def base_title_id(title_id: str | int) -> str | int:
    """The base application id of an update (low 12 bits 0x800 cleared), same type in and out."""
    value = int(title_id, 16) if isinstance(title_id, str) else title_id
    if (value & 0xFFF) == 0x800:
        value -= 0x800
    return f"{value:016X}" if isinstance(title_id, str) else value


def _text(raw: bytes) -> str:
    return raw.decode(_UTF8, "replace")


def _decode_localized(payload: bytes) -> dict[str, bytes]:
    """SPEC §5.1 LocalizedRecord sequence: {lowercase BCP-47 tag: payload bytes}; empty/duplicate tags rejected."""
    out: dict[str, bytes] = {}
    at = 0
    while at < len(payload):
        lang_len = payload[at]
        at += 1
        if at + lang_len + 4 > len(payload):
            raise NupError("localized record header overruns its TLV")
        lang = payload[at:at + lang_len].decode("ascii", "replace").lower()
        at += lang_len
        (data_len,) = struct.unpack_from("<I", payload, at)
        at += 4
        if at + data_len > len(payload):
            raise NupError("localized record data overruns its TLV")
        if not lang:
            raise NupError("localized record with an empty language tag")
        if lang in out:
            raise NupError(f"duplicate localized language {lang!r}")
        out[lang] = payload[at:at + data_len]
        at += data_len
    return out


def _icon_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "application/octet-stream"


def _fs(path: Path) -> str:
    """A filesystem path string Windows can open beyond MAX_PATH (Linux is unchanged)."""
    text = str(path)
    if os.name == "nt" and len(text) > 240 and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + str(path.absolute())
    return text


def _throttled(progress: Callable[[dict], None] | None, interval: float = 0.5):
    """A progress callback that reports at most every `interval` seconds (plus the final file).

    A 186k-file RomFS would otherwise post 186k progress messages; a job's control-plane posts are seconds apart under
    load, so the extraction would spend more time reporting than copying.
    """
    if progress is None:
        return None
    last = [0.0]

    def report(ev: dict) -> None:
        now = time.time()
        final = ev.get("files_done") is not None and ev.get("files_done") == ev.get("files_total")
        if final or now - last[0] >= interval:
            last[0] = now
            progress(ev)
    return report


def _clean_component(name: str) -> tuple[str, bool]:
    """One path component of an extracted file: never a separator, never `.`/`..`, valid on this OS.

    Returns (safe name, changed). Names are labels in the spec; extraction must not let one escape the destination
    or make a file the host cannot create. Only characters this OS rejects are replaced, so a Linux materialisation
    keeps the exact RomFS spelling.
    """
    if not name or name in (".", ".."):
        raise NupError(f"unsafe file name {name!r}")
    if "/" in name or "\\" in name or "\x00" in name:
        raise NupError(f"file name contains a path separator: {name!r}")
    bad = _WIN_BAD if os.name == "nt" else set()
    kept = "".join("_" if (ch in bad or ord(ch) < 32) else ch for ch in name)
    if os.name == "nt":
        kept = kept.rstrip(" .")
        if not kept:
            kept = "_"
        if kept.split(".")[0].upper() in _RESERVED:
            kept = "_" + kept
    return kept, kept != name


def _safe_relpath(relpath: str) -> tuple[str, list[tuple[str, str]]]:
    """Validate every component of a planned relative path; returns (path, [(from, to)] renames)."""
    parts, renames = [], []
    for part in relpath.split("/"):
        safe, changed = _clean_component(part)
        parts.append(safe)
        if changed:
            renames.append((part, safe))
    return "/".join(parts), renames


# --- reader -----------------------------------------------------------------------------------------------------------

class NupReader:
    """A validated NUP container. Use as a context manager so the mmap and handle are released (Windows locks)."""

    def __init__(self, path: str | Path, *, light: bool = False, validate_tree: bool = True):
        """Parse and validate the container.

        `light` skips the directory/file arrays and the tree checks: enough for catalog identity and `info` (a 21 MB
        TOC with 186k files parses in a fraction of the time), while extraction needs the full reader.
        """
        self.path = Path(path)
        self.light = light
        self._fh = None
        self._mm: mmap.mmap | bytes = b""
        self._closed = False
        try:
            size = self.path.stat().st_size
            self._fh = open(self.path, "rb")
            try:
                self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
            except (ValueError, OSError):
                self._mm = b""                                  # empty or unmappable: use _read_at
                self._fh.seek(0)
            self._parse_head(size)
            self._parse_toc()
            if not light and validate_tree:
                self._check_tree()
        except BaseException:
            self.close()
            raise

    # -- file access

    def _read_at(self, offset: int, size: int) -> bytes:
        if isinstance(self._mm, mmap.mmap):
            return bytes(self._mm[offset:offset + size])
        self._fh.seek(offset)
        return self._fh.read(size)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if isinstance(self._mm, mmap.mmap):
            try:
                self._mm.close()
            except BufferError:                                # a memoryview outlived close(): release it first
                pass
        self._mm = b""
        if self._fh is not None:
            self._fh.close()

    def __enter__(self) -> "NupReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- superblock and TOC

    def _parse_head(self, size: int) -> None:
        raw = self._read_at(0, HEADER_SIZE)
        if len(raw) < HEADER_SIZE:
            raise NupError(f"{self.path.name}: too short for a NUP superblock ({size} bytes)")
        (magic, header_size, header_version, toc_offset, toc_size, toc_sha256, blob_offset, file_size,
         package_count, flags, uuid, reserved) = _SUPER.unpack(raw)
        if magic[:3] != b"NUP":
            raise NupError(f"{self.path.name}: not a NUP container (magic {magic!r})")
        if magic[3] != 1:
            raise NupError(f"{self.path.name}: unsupported NUP major version {magic[3]}")
        if header_size < HEADER_SIZE:
            raise NupError(f"{self.path.name}: header_size {header_size:#x} < {HEADER_SIZE:#x}")
        if reserved != b"\0" * 32:
            raise NupError(f"{self.path.name}: superblock reserved bytes are not zero")
        if flags:
            raise NupError(f"{self.path.name}: unknown superblock flags {flags:#x}")
        if header_version < 1:
            raise NupError(f"{self.path.name}: header_version {header_version} is not valid")
        if toc_offset != header_size:
            raise NupError(f"{self.path.name}: toc_offset {toc_offset:#x} != header_size {header_size:#x}")
        if toc_size == 0 or toc_offset + toc_size > size:
            raise NupError(f"{self.path.name}: TOC {toc_offset:#x}+{toc_size:#x} is outside the file")
        if blob_offset < toc_offset + toc_size:
            raise NupError(f"{self.path.name}: blob region overlaps the TOC")
        if blob_offset % EXTENT_ALIGN:
            raise NupError(f"{self.path.name}: blob_offset {blob_offset:#x} is not 16-byte aligned")
        if file_size != size:
            raise NupError(f"{self.path.name}: superblock file_size {file_size} != actual {size}")
        if package_count < 1:
            raise NupError(f"{self.path.name}: package_count is 0")
        self.super = {"magic": magic, "header_size": header_size, "header_version": header_version,
                      "toc_offset": toc_offset, "toc_size": toc_size, "toc_sha256": toc_sha256,
                      "blob_offset": blob_offset, "file_size": file_size, "package_count": package_count,
                      "flags": flags, "uuid": uuid}
        self.size = size
        toc = self._read_at(toc_offset, toc_size)
        if len(toc) != toc_size:
            raise NupError(f"{self.path.name}: short read for the TOC")
        actual = hashlib.sha256(toc).digest()
        if actual != toc_sha256:
            raise NupError(f"{self.path.name}: TOC SHA-256 mismatch (container corrupt or tampered)")
        self._toc = toc
        self.toc_sha256 = actual.hex()

    def _parse_toc(self) -> None:
        toc = self._toc
        if len(toc) < _TOC_HEAD.size:
            raise NupError(f"{self.path.name}: TOC shorter than its header")
        magic, package_count, dir_count, file_count, pool_off, pool_size, reserved = _TOC_HEAD.unpack_from(toc, 0)
        if magic != TOC_MAGIC:
            raise NupError(f"{self.path.name}: bad TOC magic {magic!r}")
        if reserved:
            raise NupError(f"{self.path.name}: TOC reserved field is not zero")
        if package_count != self.super["package_count"]:
            raise NupError(f"{self.path.name}: package_count {package_count} != superblock "
                           f"{self.super['package_count']}")
        need_files = _TOC_HEAD.size + package_count * PKG_SIZE
        need = need_files + dir_count * DIR_SIZE + file_count * FILE_SIZE
        if need > len(toc):
            raise NupError(f"{self.path.name}: TOC truncated ({len(toc)} < {need} for its records)")
        if pool_off < need or pool_off + pool_size > len(toc):
            raise NupError(f"{self.path.name}: string pool {pool_off}+{pool_size} is outside the TOC")
        if (pool_off - (need)) % 4:
            raise NupError(f"{self.path.name}: children array is not 4-byte aligned")
        self.dir_count, self.file_count = dir_count, file_count
        self.pool = toc[pool_off:pool_off + pool_size]
        self.packages: list[NupPackage] = []
        at = _TOC_HEAD.size
        for index in range(package_count):
            (title_id, root_dir, exefs_dir, romfs_dir, version, kind, flags, r1, r2,
             meta_offset, meta_size) = _PKG.unpack_from(toc, at)
            at += PKG_SIZE
            if r1 or r2:
                raise NupError(f"{self.path.name}: package {index} reserved bytes are not zero")
            if kind >= len(KIND_NAMES):
                raise NupError(f"{self.path.name}: package {index} has unknown kind {kind}")
            if flags & ~PKG_FLAG_STANDALONE_UPDATE:
                raise NupError(f"{self.path.name}: package {index} has unknown flags {flags:#x}")
            if root_dir >= dir_count:
                raise NupError(f"{self.path.name}: package {index} root_dir {root_dir} is out of bounds")
            for name, value in (("exefs_dir", exefs_dir), ("romfs_dir", romfs_dir)):
                if value != NO_DIR and value >= dir_count:
                    raise NupError(f"{self.path.name}: package {index} {name} {value} is out of bounds")
            if meta_size and meta_offset + meta_size > self.size:
                raise NupError(f"{self.path.name}: package {index} meta block is outside the file")
            if meta_size and meta_offset < self.super["blob_offset"]:
                raise NupError(f"{self.path.name}: package {index} meta block sits inside the TOC region")
            self.packages.append(NupPackage(index, title_id, root_dir, exefs_dir, romfs_dir, version, kind,
                                            flags, meta_offset, meta_size))
        has_base = any(p.kind == KIND_BASE for p in self.packages)
        for p in self.packages:
            if p.kind == KIND_UPDATE and not has_base and not p.standalone_update:
                raise NupError(f"{self.path.name}: package {p.index} is an update without a base and without the "
                               "standalone_update flag")
        if self.light:
            self.dirs, self.files, self.children = [], [], ()
            return
        self.dirs: list[NupDir] = []
        for _ in range(dir_count):
            name_off, name_len, first, count, reserved2 = _DIR.unpack_from(toc, at)
            at += DIR_SIZE
            if reserved2:
                raise NupError(f"{self.path.name}: directory record reserved field is not zero")
            self.dirs.append(NupDir(self._pool(name_off, name_len), first, count))
        self.files: list[NupFile] = []
        for _ in range(file_count):
            name_off, name_len, size, extent_offset, extent_size, sha, codec, codec_flags, reserved3 = \
                _FILE.unpack_from(toc, at)
            at += FILE_SIZE
            if reserved3:
                raise NupError(f"{self.path.name}: file record reserved field is not zero")
            if codec not in CODEC_NAMES:
                raise NupError(f"{self.path.name}: unknown extent codec {codec}")
            if codec_flags:
                raise NupError(f"{self.path.name}: unknown codec_flags {codec_flags}")
            if codec == CODEC_RAW and size != extent_size and size:
                raise NupError(f"{self.path.name}: raw file {self._pool(name_off, name_len)!r} has extent "
                               f"{extent_size} != size {size}")
            if size == 0 and (extent_offset or extent_size or codec != CODEC_RAW):
                raise NupError(f"{self.path.name}: zero-length file has a nonempty extent")
            if size and not extent_size:
                raise NupError(f"{self.path.name}: file with nonzero size has an empty extent")
            if size:
                if extent_offset < self.super["blob_offset"] or extent_offset + extent_size > self.size:
                    raise NupError(f"{self.path.name}: extent of {self._pool(name_off, name_len)!r} is outside the "
                                   "blob region")
                if extent_offset % EXTENT_ALIGN:
                    raise NupError(f"{self.path.name}: extent of {self._pool(name_off, name_len)!r} is not "
                                   "16-byte aligned")
            self.files.append(NupFile(self._pool(name_off, name_len), size, sha, extent_offset, extent_size, codec))
        slots = (pool_off - at) // 4
        self.children = struct.unpack_from(f"<{slots}I", toc, at) if slots else ()
        self._check_extents()

    def _pool(self, offset: int, length: int) -> str:
        if offset + length > len(self.pool):
            raise NupError(f"{self.path.name}: string reference {offset}+{length} is outside the string pool")
        return _text(self.pool[offset:offset + length])

    def _check_extents(self) -> None:
        """Reject partially overlapping extents (identical ranges are the spec's dedup and are allowed)."""
        ranges = sorted({(f.extent_offset, f.extent_size) for f in self.files if f.size})
        for (a, asz), (b, bsz) in zip(ranges, ranges[1:]):
            if b < a + asz and (a != b or asz != bsz):
                raise NupError(f"{self.path.name}: overlapping file extents at {a:#x} and {b:#x}")

    def _check_tree(self) -> None:
        slots = len(self.children)
        used = 0
        child_ranges = []
        for index, d in enumerate(self.dirs):
            if d.first_child + d.child_count > slots:
                raise NupError(f"{self.path.name}: children of directory {index} ({d.name!r}) are out of bounds")
            used += d.child_count
            child_ranges.append((d.first_child, d.first_child + d.child_count, index))
        if used != slots:
            raise NupError(f"{self.path.name}: {slots - used} child slots are unreferenced")
        for (a1, a2, ai), (b1, b2, bi) in zip(sorted(child_ranges), sorted(child_ranges)[1:]):
            if a2 > b1 and a1 != b1:
                raise NupError(f"{self.path.name}: child ranges of directories {ai} and {bi} overlap")
        for slot in self.children:
            if slot >= self.dir_count and slot - self.dir_count >= self.file_count:
                raise NupError(f"{self.path.name}: child slot {slot} is out of range")
        # A file node may be referenced by several directories; orphans are a producer conformance problem that
        # verify() reports, not a reason to refuse a readable container.

    # -- tree

    def children_of(self, dir_index: int) -> list[NupNode]:
        if dir_index >= len(self.dirs):
            raise NupError(f"{self.path.name}: no directory {dir_index}")
        d = self.dirs[dir_index]
        out: list[NupNode] = []
        for slot in self.children[d.first_child:d.first_child + d.child_count]:
            if slot >= self.dir_count:
                fi = slot - self.dir_count
                if fi >= len(self.files):
                    raise NupError(f"{self.path.name}: child slot {slot} is out of range")
                out.append(NupNode(False, fi, self.files[fi].name))
            else:
                out.append(NupNode(True, slot, self.dirs[slot].name))
        return out

    def resolve(self, package: NupPackage | int, relpath: str) -> NupNode | None:
        """The node at a '/'-separated path under a package root (case-insensitive on each component), or None."""
        pkg = package if isinstance(package, NupPackage) else self.packages[package]
        current = NupNode(True, pkg.root_dir, "")
        for part in relpath.replace("\\", "/").split("/"):
            if not part:
                continue
            if not current.is_dir:
                return None
            want = part.lower()
            nxt = next((c for c in self.children_of(current.index) if c.name.lower() == want), None)
            if nxt is None:
                return None
            current = nxt
        return current

    def find_package(self, *, kind: int | None = None, index: int | None = None,
                     title_id: int | str | None = None) -> NupPackage | None:
        """The first package matching every given criterion."""
        tid = int(title_id, 16) if isinstance(title_id, str) else title_id
        for p in self.packages:
            if index is not None and p.index != index:
                continue
            if kind is not None and p.kind != kind:
                continue
            if tid is not None and p.title_id != tid:
                continue
            return p
        return None

    def primary_package(self) -> NupPackage:
        """The package whose metadata identifies the title: the base, else the first (standalone update / addon)."""
        return next((p for p in self.packages if p.kind == KIND_BASE), self.packages[0])

    def package_of(self, package: int | str | None) -> NupPackage:
        """Resolve a caller's package selector: index, kind name (`base`, `update`, `addon`, `system`), or None."""
        if package is None:
            return self.primary_package()
        if isinstance(package, int):
            if 0 <= package < len(self.packages):
                return self.packages[package]
            raise NupError(f"{self.path.name}: no package {package}")
        name = str(package).strip().lower()
        for p in self.packages:
            if p.kind_name == name:
                return p
        if name.isdigit():
            return self.package_of(int(name))
        raise NupError(f"{self.path.name}: no package of kind {package!r}")

    def walk(self, package: NupPackage | int, *, prefix: str = "") -> Iterator[tuple[str, NupFile]]:
        """Every file under a package root, depth first: (relative path, file record)."""
        for rel, _fi, f in self.walk_indexed(package, prefix=prefix):
            yield rel, f

    def walk_indexed(self, package: NupPackage | int, *, prefix: str = "") \
            -> Iterator[tuple[str, int, NupFile]]:
        """Every file under a package root: (relative path, file index, file record)."""
        pkg = package if isinstance(package, NupPackage) else self.packages[package]
        stack: list[tuple[int, str]] = [(pkg.root_dir, prefix)]
        while stack:
            di, base = stack.pop()
            for node in self.children_of(di):
                rel = f"{base}{node.name}" if not base else f"{base}/{node.name}"
                if node.is_dir:
                    stack.append((node.index, rel))
                else:
                    yield rel, node.index, self.files[node.index]

    # -- metadata

    def meta_records(self, package: NupPackage) -> list[tuple[int, bytes]]:
        """The package's meta TLVs in order (unknown types included; the caller skips what it does not know)."""
        if not package.meta_size:
            return []
        block = self._read_at(package.meta_offset, package.meta_size)
        out, at = [], 0
        while at + _TLV.size <= len(block):
            tlv_type, reserved, size = _TLV.unpack_from(block, at)
            if at + _TLV.size + size > len(block):
                raise NupError(f"{self.path.name}: meta TLV {tlv_type:#x} overruns its block")
            out.append((tlv_type, block[at + _TLV.size:at + _TLV.size + size]))
            at += _TLV.size + size
        return out

    def meta(self, package: NupPackage) -> dict[int, bytes]:
        """TLV type -> payload, first occurrence winning (SPEC §5)."""
        out: dict[int, bytes] = {}
        for tlv_type, payload in self.meta_records(package):
            out.setdefault(tlv_type, payload)
        return out

    def localized(self, package: NupPackage, tlv_type: int) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for t, payload in self.meta_records(package):
            if t == tlv_type:
                out.update(_decode_localized(payload))
        return out

    def icon(self, package: NupPackage) -> dict | None:
        """The default-language icon: {bytes, mime, sha256}, or None. Localized icons are exposed separately."""
        payload = self.meta(package).get(TLV_ICON)
        if not payload:
            return None
        return {"bytes": payload, "mime": _icon_mime(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    def title_name(self, package: NupPackage | None = None, lang: str | None = None) -> str | None:
        pkg = package or self.primary_package()
        if lang:
            value = self.localized(pkg, TLV_LOCALIZED_TITLES).get(lang.lower())
            if value:
                return _text(value)
        value = self.meta(pkg).get(TLV_TITLE_NAME)
        return _text(value) if value else None

    def describe(self, *, include_icon: bool = False, icon_limit: int = 512 * 1024) -> dict:
        """What the catalog, a launch and an operator want to know; no file content is read except small metadata."""
        primary = self.primary_package()
        packages = []
        for p in self.packages:
            meta = self.meta(p)
            icon = self.icon(p)
            localized = {lang: _text(value)
                         for lang, value in self.localized(p, TLV_LOCALIZED_TITLES).items()}
            build_id = meta.get(TLV_BUILD_ID)
            entry = {
                "index": p.index, "title_id": p.title_id_hex, "base_title_id": f"{int(base_title_id(p.title_id)):016X}",
                "kind": p.kind, "kind_name": p.kind_name, "version": p.version, "version_str": p.version_str,
                "display_version": _text(meta[TLV_DISPLAY_VERSION]) if TLV_DISPLAY_VERSION in meta else None,
                "flags": p.flags, "standalone_update": p.standalone_update,
                "root_dir": p.root_dir, "exefs_dir": p.exefs_dir, "romfs_dir": p.romfs_dir,
                "has_exefs": p.exefs_dir != NO_DIR, "has_romfs": p.romfs_dir != NO_DIR,
                "meta_size": p.meta_size,
                "title": _text(meta[TLV_TITLE_NAME]) if TLV_TITLE_NAME in meta else None,
                "publisher": _text(meta[TLV_PUBLISHER]) if TLV_PUBLISHER in meta else None,
                "source_dump": _text(meta[TLV_SOURCE_DUMP]) if TLV_SOURCE_DUMP in meta else None,
                "localized_titles": localized,
                "build_id": build_id.hex().upper() if build_id else None,
                "has_npdm": TLV_NPDM in meta, "has_nacp": TLV_NACP in meta,
                "icon": (None if not icon else
                         {"mime": icon["mime"], "bytes": len(icon["bytes"]), "sha256": icon["sha256"]}),
            }
            if icon and include_icon and len(icon["bytes"]) <= icon_limit:
                import base64
                entry["icon_b64"] = base64.b64encode(icon["bytes"]).decode("ascii")
            if not self.light:
                rows = list(self.walk(p))
                entry["file_count"] = len(rows)
                entry["bytes"] = sum(f.size for _rel, f in rows)
            packages.append(entry)
        info = {
            "path": str(self.path), "size": self.size, "format": "NUP", "magic": MAGIC.hex(),
            "header": {"version": self.super["header_version"], "size": self.super["header_size"]},
            "uuid": self.super["uuid"].hex(),
            "toc": {"offset": self.super["toc_offset"], "size": self.super["toc_size"], "sha256": self.toc_sha256},
            "blob_offset": self.super["blob_offset"],
            "counts": {"packages": len(self.packages), "dirs": self.dir_count, "files": self.file_count},
            "packages": packages,
            "primary": packages[primary.index],
            "title_id": primary.title_id_hex,
            "base_title_id": f"{int(base_title_id(primary.title_id)):016X}",
            "title": packages[primary.index]["title"],
            "publisher": packages[primary.index]["publisher"],
            "kind": primary.kind_name,
            "standalone_update": primary.standalone_update,
        }
        if not self.light:
            info["files_total"] = len(self.files)
            info["bytes_total"] = sum(f.size for f in self.files)
        return info

    # -- extraction

    def plan(self, *, mode: str = "all", package: int | str | None = None,
             subtree: str = "") -> list[PlannedFile]:
        """The output plan for an extraction: relpath -> container file.

        mode:
          * `all`     every package under its canonical folder (base/, updates/<v>/, dlc/<tid>/<i>/); a single
                      package goes to the destination root.
          * `package` one package's tree at the destination root.
          * `subtree` one directory's children at the destination root (e.g. `romfs` dumps the RomFS contents).
        """
        out: list[PlannedFile] = []
        if mode == "subtree":
            pkg = self.package_of(package)
            node = self.resolve(pkg, subtree) if subtree else NupNode(True, pkg.root_dir, "")
            if node is None:
                raise NupError(f"{self.path.name}: no subtree {subtree!r} in package {pkg.index}")
            if not node.is_dir:
                raise NupError(f"{self.path.name}: subtree {subtree!r} is a file; extract its parent directory")
            out.extend(PlannedFile(fi, rel, self.files[fi].size) for rel, fi in self._walk_index(node.index))
            return out
        if mode == "package":
            pkg = self.package_of(package)
            out.extend(PlannedFile(fi, rel, self.files[fi].size)
                       for rel, fi in self._walk_index(pkg.root_dir))
            return out
        if mode != "all":
            raise NupError(f"unknown extraction mode {mode!r} (all, package, subtree)")
        single = len(self.packages) == 1
        seen: set[str] = set()
        for pkg in self.packages:
            prefix = "" if single else self.package_prefix(pkg)
            for rel, fi in self._walk_index(pkg.root_dir):
                path = f"{prefix}/{rel}" if prefix else rel
                if path in seen:
                    raise NupError(f"{self.path.name}: two packages produce the same output path {path!r}; "
                                   "extract them one package at a time")
                seen.add(path)
                out.append(PlannedFile(fi, path, self.files[fi].size))
        return out

    @staticmethod
    def package_prefix(pkg: NupPackage) -> str:
        """The canonical all-packages folder of a package: base, updates/<version>, dlc/<title id>/<index>."""
        if pkg.kind == KIND_BASE:
            return "base"
        if pkg.kind == KIND_UPDATE:
            return f"updates/{pkg.version}"
        if pkg.kind in (KIND_ADDON, KIND_ADDON_UPDATE):
            return f"dlc/{pkg.title_id:016x}/{pkg.index}"
        return f"pkg_{pkg.index}_{pkg.kind_name}"

    def _walk_index(self, dir_index: int, prefix: str = "") -> Iterator[tuple[str, int]]:
        stack: list[tuple[int, str]] = [(dir_index, prefix)]
        while stack:
            di, base = stack.pop()
            for node in self.children_of(di):
                rel = f"{base}/{node.name}" if base else node.name
                if node.is_dir:
                    stack.append((node.index, rel))
                else:
                    yield rel, node.index

    def extraction_plan(self, *, mode: str = "all", package: int | str | None = None,
                        subtree: str = "") -> list[PlannedFile]:
        """plan() with unsafe names rejected before any file is written."""
        plan = self.plan(mode=mode, package=package, subtree=subtree)
        for item in plan:
            _safe_relpath(item.relpath)
        return plan

    def extract(self, dest: str | Path, *, mode: str = "all", package: int | str | None = None,
                subtree: str = "", verify: bool = True, overwrite: bool = False,
                progress: Callable[[dict], None] | None = None, cancel: Callable[[], bool] | None = None,
                dry_run: bool = False, plan: list[PlannedFile] | None = None) -> dict:
        """Write an extraction plan under `dest`; returns counts, bytes and any renamed components.

        `plan` runs an explicit selection (gbox.nup_models pulls only model sources); otherwise mode/package/subtree
        build one. Every file is hashed while it is written and compared with the container's SHA-256 before it is
        renamed into place, so a corrupt extent never appears as a complete extracted file.
        """
        plan = plan if plan is not None else self.extraction_plan(mode=mode, package=package, subtree=subtree)
        for item in plan:
            _safe_relpath(item.relpath)
        target = Path(dest)
        total = sum(item.size for item in plan)
        if dry_run:
            return {"mode": mode, "out": str(target), "files": len(plan), "bytes": total, "dry_run": True,
                    "renamed": []}
        target.mkdir(parents=True, exist_ok=True)
        root = target.resolve()
        started = time.time()
        done = written = 0
        renames: list[dict] = []
        report = _throttled(progress)
        for item in plan:
            if cancel and cancel():
                raise NupCancelled("cancelled by the operator")
            safe, changed = _safe_relpath(item.relpath)
            for original, replacement in changed:
                if len(renames) < 100:
                    renames.append({"from": original, "to": replacement})
            out = (target / safe)
            if not out.resolve().is_relative_to(root):
                raise NupError(f"refusing to write outside {root}: {item.relpath!r}")
            if out.exists() and not overwrite:
                raise NupError(f"{out} already exists; pass overwrite=True to replace it")
            out.parent.mkdir(parents=True, exist_ok=True)
            written += self._write_file(item.file_index, out, verify=verify)
            done += 1
            if report:
                report({"phase": "extract", "file": safe, "files_done": done, "files_total": len(plan),
                        "bytes_done": written, "bytes_total": total, "percent": round(100 * done / len(plan), 1)
                        if plan else 100.0, "elapsed_s": round(time.time() - started, 1)})
        return {"mode": mode, "out": str(target), "files": done, "bytes": written,
                "renamed": renames, "elapsed_s": round(time.time() - started, 2)}

    def _write_file(self, file_index: int, out: Path, *, verify: bool) -> int:
        """Stream one file to `out` (atomically), hashing as it goes; returns bytes written."""
        f = self.files[file_index]
        tmp = out.with_name(out.name + ".gbox-part")
        digest = hashlib.sha256()
        written = 0
        try:
            with open(_fs(tmp), "wb", buffering=BUFFER) as fh:
                if f.size == 0:
                    pass
                elif f.codec == CODEC_RAW:
                    view = memoryview(self._mm)[f.extent_offset:f.extent_offset + f.extent_size] \
                        if isinstance(self._mm, mmap.mmap) else memoryview(self._read_at(f.extent_offset, f.extent_size))
                    try:
                        for at in range(0, len(view), BUFFER):
                            chunk = view[at:at + BUFFER]
                            fh.write(chunk)
                            digest.update(chunk)
                            written += len(chunk)
                    finally:
                        view.release()
                elif f.codec == CODEC_ZSTD:
                    import zstandard
                    comp = (memoryview(self._mm)[f.extent_offset:f.extent_offset + f.extent_size]
                            if isinstance(self._mm, mmap.mmap)
                            else memoryview(self._read_at(f.extent_offset, f.extent_size)))
                    try:
                        with zstandard.ZstdDecompressor().stream_reader(comp) as reader:
                            while True:
                                chunk = reader.read(BUFFER)
                                if not chunk:
                                    break
                                fh.write(chunk)
                                digest.update(chunk)
                                written += len(chunk)
                    finally:
                        comp.release()
                else:                                          # unreachable: the reader rejects unknown codecs
                    raise NupError(f"{self.path.name}: unknown codec {f.codec}")
            if written != f.size:
                raise NupError(f"{self.path.name}: {f.name!r} decompressed to {written} bytes, expected {f.size}")
            if verify and digest.digest() != f.sha256:
                raise NupError(f"{self.path.name}: SHA-256 mismatch for {f.name!r} (corrupt or tampered extent)")
            os.replace(_fs(tmp), _fs(out))
            return written
        except BaseException:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

    def file_bytes(self, file_index: int, *, limit: int | None = None) -> bytes:
        """One extracted file in memory (metadata previews, tests, small assets). `limit` refuses larger files."""
        f = self.files[file_index]
        if limit is not None and f.size > limit:
            raise NupError(f"{f.name!r} is {f.size} bytes (limit {limit})")
        if f.size == 0:
            return b""
        if f.codec == CODEC_RAW:
            return self._read_at(f.extent_offset, f.extent_size)
        import zstandard
        return zstandard.ZstdDecompressor().decompress(self._read_at(f.extent_offset, f.extent_size),
                                                       max_output_size=f.size)

    def head(self, file_index: int, size: int = 16) -> bytes:
        """The first `size` uncompressed bytes of a file (magic sniffing), without reading the rest."""
        f = self.files[file_index]
        if f.size == 0:
            return b""
        if f.codec == CODEC_RAW:
            return self._read_at(f.extent_offset, min(size, f.extent_size))
        import zstandard
        comp = (memoryview(self._mm)[f.extent_offset:f.extent_offset + f.extent_size]
                if isinstance(self._mm, mmap.mmap) else memoryview(self._read_at(f.extent_offset, f.extent_size)))
        try:
            with zstandard.ZstdDecompressor().stream_reader(comp) as reader:
                return reader.read(size)
        finally:
            comp.release()

    def materialize(self, dest: str | Path, *, verify: bool = True, overwrite: bool = True,
                    apply_updates: bool = True, progress: Callable[[dict], None] | None = None,
                    cancel: Callable[[], bool] | None = None) -> dict:
        """Extract a bootable deconstructed title: the base package, with updates overlaid, at `dest` root.

        Updates shadow base files by path (SPEC Appendix A), so the folder is the newest content. Add-ons are not
        overlaid: an emulator registers them as separate content, never as files of the base. A marker file records
        what the folder is (title id, name, packages), which the catalog and `switch_mods` read.
        """
        base = next((p for p in self.packages if p.kind == KIND_BASE), None)
        updates = sorted((p for p in self.packages if p.kind == KIND_UPDATE), key=lambda p: p.version)
        chosen: list[NupPackage] = [base] if base else []
        if apply_updates:
            chosen += updates
        if not chosen:
            chosen = [self.primary_package()]
        ordered = chosen
        plan: dict[str, int] = {}
        for pkg in ordered:
            for rel, fi in self._walk_index(pkg.root_dir):
                plan[rel] = fi                            # a later package's file shadows an earlier one
        for rel in plan:                                  # refuse an unsafe container before writing anything
            _safe_relpath(rel)
        target = Path(dest)
        target.mkdir(parents=True, exist_ok=True)
        root = target.resolve()
        total = sum(self.files[fi].size for fi in plan.values())
        started = time.time()
        written = done = 0
        renames: list[dict] = []
        report = _throttled(progress)
        for rel, fi in plan.items():
            if cancel and cancel():
                raise NupCancelled("cancelled by the operator")
            safe, changed = _safe_relpath(rel)
            for original, replacement in changed:
                if len(renames) < 100:
                    renames.append({"from": original, "to": replacement})
            out = target / safe
            if not out.resolve().is_relative_to(root):
                raise NupError(f"refusing to write outside {root}: {rel!r}")
            out.parent.mkdir(parents=True, exist_ok=True)
            written += self._write_file(fi, out, verify=verify)
            done += 1
            if report:
                report({"phase": "materialize", "file": safe, "files_done": done, "files_total": len(plan),
                        "bytes_done": written, "bytes_total": total,
                        "percent": round(100 * done / len(plan), 1) if plan else 100.0,
                        "elapsed_s": round(time.time() - started, 1)})
        primary = base or self.primary_package()
        icon = self.icon(primary)
        marker = {
            "schema": 1,
            "kind": "nup-materialized",
            "source": str(self.path.resolve()),
            "source_size": self.size,
            "uuid": self.super["uuid"].hex(),
            "title_id": primary.title_id_hex,
            "base_title_id": f"{int(base_title_id(primary.title_id)):016X}",
            "kind_name": primary.kind_name,
            "standalone_update": primary.standalone_update and base is None,
            "title": self.title_name(primary),
            "publisher": _text(self.meta(primary)[TLV_PUBLISHER]) if TLV_PUBLISHER in self.meta(primary) else None,
            "display_version": (_text(self.meta(primary)[TLV_DISPLAY_VERSION])
                                if TLV_DISPLAY_VERSION in self.meta(primary) else None),
            "build_id": (self.meta(primary)[TLV_BUILD_ID].hex().upper()
                         if TLV_BUILD_ID in self.meta(primary) else None),
            "icon_sha256": icon["sha256"] if icon else None,
            "packages": [{"index": p.index, "kind": p.kind_name, "title_id": p.title_id_hex,
                          "version": p.version, "display_version": (
                              _text(self.meta(p)[TLV_DISPLAY_VERSION]) if TLV_DISPLAY_VERSION in self.meta(p) else None)}
                         for p in ordered],
            "packages_available": [{"index": p.index, "kind": p.kind_name, "title_id": p.title_id_hex,
                                    "version": p.version} for p in self.packages],
            "addons_skipped": [p.index for p in self.packages if p.kind in (KIND_ADDON, KIND_ADDON_UPDATE)],
            "files": done, "bytes": written, "renamed": renames,
            "extracted_at": time.time(), "tool": "gbox.nup",
        }
        (target / MARKER).write_text(json.dumps(marker, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"folder": str(target), "marker": str(target / MARKER), "files": done, "bytes": written,
                "title_id": primary.title_id_hex, "title": marker["title"], "kind": primary.kind_name,
                "standalone_update": marker["standalone_update"], "packages": marker["packages"],
                "addons_skipped": marker["addons_skipped"], "renamed": renames,
                "has_exefs": (target / "exefs").is_dir(), "has_romfs": (target / "romfs").is_dir(),
                "warnings": self._materialize_warnings(base, updates), "elapsed_s": round(time.time() - started, 2)}

    def _materialize_warnings(self, base: NupPackage | None, updates: list[NupPackage]) -> list[str]:
        out = []
        if base is None:
            out.append("this container has no base package: the extracted update cannot boot without a matching "
                       "base title elsewhere")
        if base is not None and not updates:
            out.append("no update package in this container: the extracted base is the version it contains")
        if any(p.kind in (KIND_ADDON, KIND_ADDON_UPDATE) for p in self.packages):
            out.append("add-on packages were not overlaid: an emulator registers DLC as separate content")
        return out

    # -- verification

    def verify(self, *, deep: bool = False, progress: Callable[[dict], None] | None = None,
               cancel: Callable[[], bool] | None = None, max_problems: int = MAX_PROBLEMS) -> dict:
        """Structural conformance, and with `deep` every file's SHA-256 and extent sharing.

        Structural checks that the reader already enforces are reported as OK; this adds the producer rules a readable
        container may still break: sorted unique children, one reachable tree, no unreferenced files, child ranges.
        """
        problems: list[str] = []
        if self.light:
            raise NupError(f"{self.path.name}: verification needs a full reader (light=True skips the tree)")

        def fail(message: str) -> None:
            if len(problems) < max_problems:
                problems.append(message)

        ranges = sorted((d.first_child, d.first_child + d.child_count, i) for i, d in enumerate(self.dirs))
        for (a1, a2, ai), (b1, b2, bi) in zip(ranges, ranges[1:]):
            if a2 > b1 and a1 != b1:
                fail(f"child slot ranges of directories {ai} and {bi} overlap")
        for di, d in enumerate(self.dirs):
            kids = self.children[d.first_child:d.first_child + d.child_count]
            names = [self.files[k - self.dir_count].name if k >= self.dir_count else self.dirs[k].name for k in kids]
            if names != sorted(names):
                fail(f"directory {di} ({d.name!r}): children are not sorted by name")
            if len(set(names)) != len(names):
                fail(f"directory {di} ({d.name!r}): duplicate child names")
        visited: set[int] = set()
        for p in self.packages:
            stack = [(p.root_dir, (p.root_dir,))]
            while stack:
                di, path = stack.pop()
                if di in path[:-1]:
                    fail(f"cycle through directory {di}")
                    continue
                if di in visited:
                    continue
                visited.add(di)
                for node in self.children_of(di):
                    if node.is_dir:
                        stack.append((node.index, path + (node.index,)))
        orphans = set(range(self.dir_count)) - visited
        if orphans:
            fail(f"{len(orphans)} unreachable directory node(s)")
        referenced = {slot - self.dir_count for slot in self.children if slot >= self.dir_count}
        unreferenced = set(range(self.file_count)) - referenced
        if unreferenced:
            names = [self.files[i].name for i in sorted(unreferenced)[:8]]
            fail(f"{len(unreferenced)} file node(s) not referenced by any directory: {names}")
        if deep:
            seen: dict[tuple[int, int, int], bytes] = {}
            for fi, f in enumerate(self.files):
                if cancel and cancel():
                    raise NupCancelled("cancelled by the operator")
                try:
                    digest = hashlib.sha256()
                    if f.size == 0:
                        pass
                    elif f.codec == CODEC_RAW:
                        blob = (memoryview(self._mm)[f.extent_offset:f.extent_offset + f.extent_size]
                                if isinstance(self._mm, mmap.mmap)
                                else memoryview(self._read_at(f.extent_offset, f.extent_size)))
                        try:
                            for at in range(0, len(blob), BUFFER):
                                digest.update(blob[at:at + BUFFER])
                        finally:
                            blob.release()
                    else:
                        import zstandard
                        comp = (memoryview(self._mm)[f.extent_offset:f.extent_offset + f.extent_size]
                                if isinstance(self._mm, mmap.mmap)
                                else memoryview(self._read_at(f.extent_offset, f.extent_size)))
                        try:
                            with zstandard.ZstdDecompressor().stream_reader(comp) as reader:
                                while True:
                                    chunk = reader.read(BUFFER)
                                    if not chunk:
                                        break
                                    digest.update(chunk)
                        finally:
                            comp.release()
                    if digest.digest() != f.sha256:
                        fail(f"file {fi} ({f.name!r}): SHA-256 mismatch")
                except (NupError, OSError, ValueError) as exc:
                    fail(f"file {fi} ({f.name!r}): {exc}")
                key = (f.extent_offset, f.extent_size, f.codec)
                if key in seen and seen[key] != f.sha256:
                    fail(f"file {fi} ({f.name!r}): shares an extent with different content")
                seen.setdefault(key, f.sha256)
                if progress and (fi % 200 == 0 or fi + 1 == len(self.files)):
                    progress({"phase": "verify", "file": f.name, "files_done": fi + 1,
                              "files_total": len(self.files), "percent": round(100 * (fi + 1) / len(self.files), 1)})
        return {"ok": not problems, "deep": deep, "problems": problems, "problems_total": len(problems),
                "truncated": len(problems) >= max_problems, "files": len(self.files),
                "bytes": sum(f.size for f in self.files), "packages": len(self.packages)}


# --- CLI --------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """`python -m gbox.nup info|list|extract|verify|materialize ...` (mirrors `nup-extractor`'s reference CLI)."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m gbox.nup", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="container and package metadata")
    p.add_argument("file"), p.add_argument("--icon", action="store_true", help="include the icon as base64")
    p = sub.add_parser("list", help="file nodes in the tree")
    p.add_argument("file"), p.add_argument("--limit", type=int, default=0), p.add_argument("--search", default="")
    p = sub.add_parser("extract", help="extract a package or subtree")
    p.add_argument("file"), p.add_argument("dest")
    p.add_argument("--mode", choices=("all", "package", "subtree"), default="package")
    p.add_argument("--package", default=None, help="index or kind (base/update/addon)")
    p.add_argument("--subtree", default="", help="e.g. romfs or exefs")
    p.add_argument("--no-verify", action="store_true"), p.add_argument("--overwrite", action="store_true")
    p = sub.add_parser("verify", help="structural (and deep) integrity check")
    p.add_argument("file"), p.add_argument("--deep", action="store_true")
    p = sub.add_parser("materialize", help="extract a bootable title folder (base + updates overlaid)")
    p.add_argument("file"), p.add_argument("dest")
    p.add_argument("--no-updates", action="store_true"), p.add_argument("--no-verify", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "info":
        with NupReader(args.file) as reader:
            print(json.dumps(reader.describe(include_icon=args.icon), indent=2, ensure_ascii=False))
    elif args.cmd == "list":
        with NupReader(args.file) as reader:
            rows = [{"index": fi, "path": rel, "size": f.size, "codec": f.codec_name, "sha256": f.sha256.hex()}
                    for fi, (rel, f) in enumerate(reader.walk(reader.primary_package()))]
            if args.search:
                needle = args.search.lower()
                rows = [r for r in rows if needle in r["path"].lower()]
            total = len(rows)
            rows = rows[:args.limit] if args.limit else rows
            print(json.dumps({"file": args.file, "files": total, "shown": len(rows), "entries": rows}, indent=2,
                             ensure_ascii=False))
    elif args.cmd == "extract":
        with NupReader(args.file) as reader:
            result = reader.extract(args.dest, mode=args.mode, package=args.package, subtree=args.subtree,
                                    verify=not args.no_verify, overwrite=args.overwrite)
            print(json.dumps(result, indent=2))
    elif args.cmd == "verify":
        with NupReader(args.file) as reader:
            report = reader.verify(deep=args.deep)
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1
    elif args.cmd == "materialize":
        with NupReader(args.file) as reader:
            result = reader.materialize(args.dest, verify=not args.no_verify, apply_updates=not args.no_updates)
            print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

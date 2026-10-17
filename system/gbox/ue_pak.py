"""Bounds-checked reader for Unreal Engine 4/5 .pak archives (pak versions 1-11) and IoStore table-of-contents headers.

Read-only by design: files are opened "rb", nothing in the install is written, and every length read from the archive
is checked against the bytes that actually exist before it is used.

What it does:
- Finds the FPakInfo footer for every known layout (44/61 bytes for v1-7, 189 bytes for UE 4.22's v8, 221 bytes for
  v8 (4.23-4.24), v10 and v11, 222 bytes for v9) and checks the index SHA-1.
- Reads the legacy index (v1-v9) and the v10/v11 primary index with its encoded entries, the non-encoded entry list and
  the full directory index (file names). Without a full directory index the entries are listed by number only.
- Extracts entries: stored, zlib and gzip in pure Python; Oodle only through an oo2core_*_win64.dll the game itself
  ships (loaded with ctypes from the game folder only, never from elsewhere); LZ4 only if the lz4 package is present.
- Stops with PakEncrypted when the index (or an entry) is AES-encrypted: gBox does not hold or guess keys.
- IoStore (.utoc/.ucas, UE 4.26+/UE5): reads the container header (entry count, flags, compression) and reports it;
  reading container chunks is the next stage.

Reference: Engine/Source/Runtime/PakFile/Public/IPlatformFilePak.h (FPakInfo, FPakEntry, FPakFile::DecodePakEntry)
and Engine/Source/Runtime/Core/Public/IO/IoStore.h (FIoStoreTocHeader).
"""
from __future__ import annotations

import fnmatch
import hashlib
import re
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PAK_MAGIC = 0x5A6F12E1
UTOC_MAGIC = b"-==--==--==--==-"
MAX_INDEX = 1 << 30            # 1 GiB: no shipped pak index comes close
MAX_STRING = 1 << 16           # longest FString we accept from an index (paths are < 1 KB)
MAX_ENTRY = 4 << 30            # refuse to inflate a single entry above 4 GiB
LEGACY_METHODS = {0: "None", 1: "Zlib", 2: "Gzip", 4: "Oodle"}   # COMPRESS_* before v8 (bias flags 0x10/0x20 masked)
VERSION_NAMES = {1: "Initial", 2: "NoTimestamps", 3: "CompressionEncryption", 4: "IndexEncryption",
                 5: "RelativeChunkOffsets", 6: "DeleteRecords", 7: "EncryptionKeyGuid",
                 8: "FNameBasedCompressionMethod", 9: "FrozenIndex", 10: "PathHashIndex", 11: "Fnv64BugFix"}
FLAG_ENCRYPTED, FLAG_DELETED = 0x01, 0x02


class PakError(Exception):
    """Malformed or unreadable archive (truncated, out-of-bounds, wrong magic)."""


class PakEncrypted(PakError):
    """AES-encrypted index or entry: needs the game's key, which gBox does not have."""


class PakUnsupported(PakError):
    """A valid archive feature this reader does not handle (frozen index, Oodle without the game's DLL, ...)."""


class Reader:
    """Little-endian cursor that refuses to read past `end`."""

    def __init__(self, data: bytes, pos: int = 0, end: int | None = None, what: str = "data"):
        self.data, self.pos, self.what = data, pos, what
        self.end = len(data) if end is None else min(end, len(data))

    def need(self, n: int):
        if n < 0 or self.pos + n > self.end:
            raise PakError(f"{self.what}: need {n} bytes at {self.pos}, only {self.end - self.pos} left")

    def take(self, n: int) -> bytes:
        self.need(n)
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def _s(self, fmt: str, n: int):
        self.need(n)
        v = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += n
        return v

    def u8(self): return self._s("<B", 1)
    def u16(self): return self._s("<H", 2)
    def i16(self): return self._s("<h", 2)
    def u32(self): return self._s("<I", 4)
    def i32(self): return self._s("<i", 4)
    def u64(self): return self._s("<Q", 8)
    def i64(self): return self._s("<q", 8)
    def f32(self): return self._s("<f", 4)
    def f64(self): return self._s("<d", 8)

    def bool32(self) -> bool:
        v = self.u32()
        if v > 1:
            raise PakError(f"{self.what}: bool at {self.pos - 4} is {v}")
        return bool(v)

    def count(self, elem_size: int, limit: int = 1 << 26) -> int:
        """An int32 element count that must fit in the remaining bytes (elem_size = minimum bytes per element)."""
        n = self.i32()
        if n < 0 or n > limit or n * max(elem_size, 0) > self.end - self.pos:
            raise PakError(f"{self.what}: implausible count {n} at {self.pos - 4}")
        return n

    def fstring(self) -> str:
        n = self.i32()
        if n == 0:
            return ""
        if n > 0:
            if n > MAX_STRING:
                raise PakError(f"{self.what}: string length {n} at {self.pos - 4}")
            return self.take(n).rstrip(b"\0").decode("latin-1")
        if -n > MAX_STRING:
            raise PakError(f"{self.what}: string length {n} at {self.pos - 4}")
        return self.take(-n * 2).decode("utf-16-le", "replace").rstrip("\0")

    def guid(self) -> bytes:
        return self.take(16)


@dataclass
class PakEntry:
    name: str
    offset: int
    size: int
    usize: int
    method: str = "None"
    encrypted: bool = False
    deleted: bool = False
    block_size: int = 0
    blocks: list[tuple[int, int]] = field(default_factory=list)

    def summary(self) -> dict:
        return {"path": self.name, "size": self.usize, "stored": self.size, "compression": self.method,
                "encrypted": self.encrypted}


def _clean_mount(mount: str) -> str:
    m = mount.replace("\\", "/")
    while m.startswith("../"):
        m = m[3:]
    return m.lstrip("/")


def _join(*parts: str) -> str:
    s = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
    return re.sub(r"/{2,}", "/", s)


@dataclass
class PakInfo:
    version: int
    index_offset: int
    index_size: int
    index_hash: bytes
    encrypted_index: bool
    key_guid: bytes
    methods: list[str]
    footer_size: int
    frozen: bool = False

    @property
    def method_u8(self) -> bool:
        """UE 4.22 wrote v8 with four method names and a one-byte method index per entry."""
        return self.version == 8 and self.footer_size == 189


def read_footer(f, file_size: int) -> PakInfo:
    """Locate and parse FPakInfo at the end of the file (tries every known footer size)."""
    tail_len = min(file_size, 512)
    f.seek(file_size - tail_len)
    tail = f.read(tail_len)
    # (footer size, number of compression-method names, has bIndexIsFrozen, allowed versions)
    layouts = [(221, 5, False, {8, 10, 11}), (222, 5, True, {9}), (189, 4, False, {8}), (61, 0, False, set(range(1, 8)))]
    for size, nmeth, frozen_byte, versions in layouts:
        if size > tail_len:
            continue
        r = Reader(tail, tail_len - size, what="pak footer")
        key_guid = r.guid()
        enc = r.u8()
        if r.u32() != PAK_MAGIC:
            continue
        version = r.u32()
        if version not in versions:
            continue
        index_offset, index_size, index_hash = r.i64(), r.i64(), r.take(20)
        frozen = bool(r.u8()) if frozen_byte else False
        methods = []
        for _ in range(nmeth):
            raw = r.take(32).split(b"\0", 1)[0]
            methods.append(raw.decode("latin-1"))
        if version < 4:          # bEncryptedIndex did not exist yet: the byte before the magic is index data
            enc = 0
        if version < 7:
            key_guid = b"\0" * 16
        if not (0 <= index_offset and 0 < index_size <= MAX_INDEX and index_offset + index_size <= file_size - 44):
            raise PakError(f"pak v{version}: index {index_offset}+{index_size} lies outside the {file_size}-byte file")
        if version < 8:
            methods = ["Zlib", "Gzip", "Oodle"]
        return PakInfo(version, index_offset, index_size, index_hash, bool(enc), key_guid,
                       [m for m in methods], size if version >= 7 else 44, frozen)
    raise PakError("no Unreal pak footer (magic 0x5A6F12E1) - not an Unreal Engine pak")


class Oodle:
    """OodleLZ_Decompress from the oo2core DLL that the game itself ships. Never loaded from outside the game folder."""

    PATTERN = re.compile(r"(?i)^oo2core_\d+_win64\.dll$")

    def __init__(self, dll: Path, game_dir: Path):
        if sys.platform != "win32":
            raise PakUnsupported("Oodle decompression needs the game's Windows DLL and runs on the Windows PC only")
        dll, game_dir = Path(dll).resolve(), Path(game_dir).resolve()
        if not dll.is_relative_to(game_dir) or not self.PATTERN.match(dll.name) or not dll.is_file():
            raise PakUnsupported(f"refusing to load {dll}: only an oo2core_*_win64.dll inside the game folder is used")
        import ctypes
        self._ct = ctypes
        self.path = dll
        lib = ctypes.WinDLL(str(dll))
        fn = lib.OodleLZ_Decompress
        fn.restype = ctypes.c_ssize_t
        fn.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_int]
        self._fn = fn

    @classmethod
    def find(cls, game_dir: Path) -> Path | None:
        """The game's own oo2core DLL: next to the shipping exe or under Engine/Binaries/ThirdParty/Oodle."""
        gd = Path(game_dir)
        pats = ["oo2core_*_win64.dll", "*/Binaries/Win64/oo2core_*_win64.dll", "Engine/Binaries/Win64/oo2core_*_win64.dll",
                "Engine/Binaries/ThirdParty/Oodle/*/oo2core_*_win64.dll", "Engine/Binaries/ThirdParty/Oodle/oo2core_*_win64.dll"]
        for pat in pats:
            for p in sorted(gd.glob(pat)):
                if p.is_file() and cls.PATTERN.match(p.name):
                    return p
        return None

    def decompress(self, data: bytes, raw_len: int) -> bytes:
        ct = self._ct
        src = ct.create_string_buffer(data, len(data))
        dst = ct.create_string_buffer(raw_len)
        n = self._fn(src, len(data), dst, raw_len, 1, 0, 0, None, 0, None, None, None, 0, 3)
        if n != raw_len:
            raise PakError(f"Oodle returned {n} bytes, expected {raw_len}")
        return dst.raw[:raw_len]


def decompress_block(method: str, data: bytes, raw_len: int, oodle: Oodle | None = None) -> bytes:
    m = method.lower()
    if m == "zlib":
        out = zlib.decompress(data)
    elif m == "gzip":
        out = zlib.decompress(data, 31)
    elif m == "oodle":
        if oodle is None:
            raise PakUnsupported("Oodle-compressed entry: the game ships no oo2core_*_win64.dll to decompress it "
                                 "(UE 4.27+/UE5 link Oodle statically; that path is not supported)")
        out = oodle.decompress(data, raw_len)
    elif m == "lz4":
        try:
            import lz4.block   # optional
        except ImportError:
            raise PakUnsupported("LZ4-compressed entry: install the lz4 package to read it") from None
        out = lz4.block.decompress(data, uncompressed_size=raw_len)
    else:
        raise PakUnsupported(f"compression method {method!r} is not supported")
    if len(out) != raw_len:
        raise PakError(f"{method} block inflated to {len(out)} bytes, expected {raw_len}")
    return out


class PakFile:
    """One .pak archive. `entries` maps the in-game path (mount point applied, ../../../ stripped) to a PakEntry."""

    def __init__(self, path: Path, oodle: Oodle | None = None):
        self.path = Path(path)
        self.oodle = oodle
        self.file_size = self.path.stat().st_size
        self._f = open(self.path, "rb")
        try:
            self.info = read_footer(self._f, self.file_size)
            self.mount_point = ""
            self.names_available = True
            self.index_hash_ok = None
            self.entries: dict[str, PakEntry] = {}
            self._load_index()
        except BaseException:
            self._f.close()
            raise

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    @property
    def version(self) -> int:
        return self.info.version

    def _read_at(self, offset: int, size: int, what: str) -> bytes:
        if offset < 0 or size < 0 or offset + size > self.file_size:
            raise PakError(f"{what}: {offset}+{size} lies outside the {self.file_size}-byte file")
        self._f.seek(offset)
        b = self._f.read(size)
        if len(b) != size:
            raise PakError(f"{what}: short read at {offset}")
        return b

    def _method(self, idx: int) -> str:
        if idx == 0:
            return "None"
        if 1 <= idx <= len(self.info.methods) and self.info.methods[idx - 1]:
            return self.info.methods[idx - 1]
        return f"method#{idx}"

    def _entry(self, r: Reader, name: str) -> PakEntry:
        """FPakEntry::Serialize for this archive's version."""
        v = self.info.version
        offset, size, usize = r.i64(), r.i64(), r.i64()
        if v >= 8:
            method = self._method(r.u8() if self.info.method_u8 else r.u32())
        else:
            method = LEGACY_METHODS.get(r.i32() & 0x0F, "unknown")
        if v < 2:
            r.i64()                      # FDateTime timestamp
        r.take(20)                       # SHA-1 of the stored bytes
        e = PakEntry(name, offset, size, usize, method)
        if v >= 3:
            if method != "None":
                n = r.count(16)
                e.blocks = [(r.i64(), r.i64()) for _ in range(n)]
            flags = r.u8()
            e.encrypted, e.deleted = bool(flags & FLAG_ENCRYPTED), bool(flags & FLAG_DELETED)
            e.block_size = r.u32()
        self._check_entry(e)
        return e

    def _check_entry(self, e: PakEntry):
        if not (0 <= e.offset < self.file_size) or e.size < 0 or e.usize < 0 or e.offset + e.size > self.file_size:
            if not e.deleted:
                raise PakError(f"entry {e.name!r}: {e.offset}+{e.size} lies outside the {self.file_size}-byte file")

    def _decode_entry(self, enc: bytes, off: int, name: str) -> PakEntry:
        """FPakFile::DecodePakEntry (v10+ bit-packed entries)."""
        r = Reader(enc, off, what="encoded pak entry")
        value = r.u32()
        block_size = r.u32() if (value & 0x3F) == 0x3F else (value & 0x3F) << 11
        method = self._method((value >> 23) & 0x3F)
        offset = r.u32() if value & (1 << 31) else r.i64()
        usize = r.u32() if value & (1 << 30) else r.i64()
        size = (r.u32() if value & (1 << 29) else r.i64()) if method != "None" else usize
        e = PakEntry(name, offset, size, usize, method, encrypted=bool(value & (1 << 22)))
        nblocks = (value >> 6) & 0xFFFF
        if nblocks:
            e.block_size = usize if nblocks == 1 else block_size
            hdr = 8 * 3 + 4 + 20 + 1 + 4 + (4 + 16 * nblocks if method != "None" else 0)
            align = 16 if e.encrypted else 1
            start = hdr                  # v10+ offsets are relative to the entry
            if nblocks == 1 and not e.encrypted:
                e.blocks = [(start, start + size)]
            else:
                for _ in range(nblocks):
                    bsz = r.u32()
                    e.blocks.append((start, start + bsz))
                    start += -(-bsz // align) * align
        self._check_entry(e)
        return e

    def _load_index(self):
        info = self.info
        if info.encrypted_index:
            raise PakEncrypted(f"pak index is AES-encrypted (key GUID {info.key_guid.hex()}): the game's AES key is needed; "
                               "gBox does not have it and stops here")
        if info.frozen:
            raise PakUnsupported("pak v9 frozen index (UE 4.25 bIndexIsFrozen) is a memory image; not supported")
        data = self._read_at(info.index_offset, info.index_size, "pak index")
        self.index_hash_ok = hashlib.sha1(data).digest() == info.index_hash or info.index_hash == b"\0" * 20
        r = Reader(data, what="pak index")
        try:
            self.mount_point = r.fstring()
        except PakError as e:
            raise PakError(f"pak index unreadable ({e}); if the index hash also fails it is probably encrypted") from None
        mount = _clean_mount(self.mount_point)
        if info.version < 10:
            n = r.count(40)
            for _ in range(n):
                name = _join(mount, r.fstring())
                self.entries[name] = self._entry(r, name)
            return
        n = r.count(0)
        r.u64()                                   # path hash seed
        path_hash = None
        if r.bool32():
            path_hash = (r.i64(), r.i64(), r.take(20))
        full_dir = None
        if r.bool32():
            full_dir = (r.i64(), r.i64(), r.take(20))
        enc = r.take(r.count(1, limit=MAX_INDEX))
        files = [self._entry(r, f"#{i}") for i in range(r.count(40))]
        if full_dir and full_dir[0] >= 0:
            d = self._read_at(full_dir[0], full_dir[1], "full directory index")
            dr = Reader(d, what="full directory index")
            for _ in range(dr.count(8)):
                dname = dr.fstring()
                for _ in range(dr.count(8)):
                    fname = dr.fstring()
                    loc = dr.i32()
                    name = _join(mount, dname, fname)
                    self.entries[name] = self._located(enc, files, loc, name)
            return
        # No full directory index: names are unknown (only FNV-64 path hashes). List the entries by number.
        self.names_available = False
        if path_hash and path_hash[0] >= 0:
            d = self._read_at(path_hash[0], path_hash[1], "path hash index")
            hr = Reader(d, what="path hash index")
            for i in range(hr.count(12)):
                h, loc = hr.u64(), hr.i32()
                name = f"#hash/{h:016x}"
                self.entries[name] = self._located(enc, files, loc, name)
        if n and not self.entries:
            raise PakUnsupported(f"pak v{info.version} has {n} entries but neither a full directory index nor a "
                                 "path hash index to locate them")

    def _located(self, enc: bytes, files: list[PakEntry], loc: int, name: str) -> PakEntry:
        """FPakEntryLocation: >= 0 is a byte offset into the encoded entries, < 0 is -(index+1) into the list."""
        if loc >= 0:
            if loc >= len(enc):
                raise PakError(f"entry {name!r}: encoded offset {loc} outside {len(enc)} bytes")
            return self._decode_entry(enc, loc, name)
        if loc == -(1 << 31):
            raise PakError(f"entry {name!r}: invalid location")
        i = -(loc + 1)
        if i >= len(files):
            raise PakError(f"entry {name!r}: list index {i} outside {len(files)} entries")
        e = files[i]
        return PakEntry(name, e.offset, e.size, e.usize, e.method, e.encrypted, e.deleted, e.block_size, list(e.blocks))

    # ------------------------------------------------------------------ data

    def read(self, e: PakEntry | str, max_size: int = MAX_ENTRY) -> bytes:
        """The entry's uncompressed bytes. Raises PakEncrypted / PakUnsupported / PakError."""
        if isinstance(e, str):
            e = self.entries[e]
        if e.deleted:
            raise PakError(f"{e.name}: delete record in a patch pak")
        if e.encrypted:
            raise PakEncrypted(f"{e.name}: entry is AES-encrypted; the game's key is needed")
        if e.usize > max_size:
            raise PakError(f"{e.name}: {e.usize} bytes is above the {max_size}-byte limit")
        # The data is preceded by a copy of its FPakEntry; parse it to learn its size and cross-check the index.
        window = min(self.file_size - e.offset, 128 + 16 * max(len(e.blocks), 1))
        r = Reader(self._read_at(e.offset, window, f"{e.name} header"), what=f"{e.name} header")
        inline = self._entry(r, e.name)
        hdr = r.pos
        if (inline.size, inline.usize) != (e.size, e.usize) or inline.method != e.method:
            raise PakError(f"{e.name}: inline header {inline.size}/{inline.usize}/{inline.method} disagrees with the "
                           f"index {e.size}/{e.usize}/{e.method}")
        if e.method == "None":
            return self._read_at(e.offset + hdr, e.usize, e.name)
        base = e.offset if self.info.version >= 5 else 0           # RelativeChunkOffsets
        blocks = inline.blocks or e.blocks
        bs = inline.block_size or e.block_size or e.usize
        out = bytearray()
        for i, (s, t) in enumerate(blocks):
            raw_len = min(bs, e.usize - i * bs)
            if raw_len <= 0 or t < s:
                raise PakError(f"{e.name}: block {i} is malformed")
            out += decompress_block(e.method, self._read_at(base + s, t - s, f"{e.name} block {i}"), raw_len, self.oodle)
        if len(out) != e.usize:
            raise PakError(f"{e.name}: inflated to {len(out)} bytes, expected {e.usize}")
        return bytes(out)

    def summary(self) -> dict:
        methods = sorted({e.method for e in self.entries.values()})
        return {"path": self.path.name, "size": self.file_size, "version": self.info.version,
                "version_name": VERSION_NAMES.get(self.info.version, "?"), "mount_point": self.mount_point,
                "entries": len(self.entries), "names_available": self.names_available,
                "index_hash_ok": self.index_hash_ok, "encrypted_index": self.info.encrypted_index,
                "encrypted_entries": sum(1 for e in self.entries.values() if e.encrypted),
                "compression_methods": methods}


def open_pak(path: Path, game_dir: Path | None = None) -> tuple[PakFile | None, dict]:
    """Open a pak and return (PakFile, summary) or (None, {path, error, status}) without raising.

    `status` is one of ok | encrypted | unsupported | not_unreal | error."""
    oodle = None
    try:
        pf = PakFile(path)
    except PakEncrypted as e:
        return None, {"path": Path(path).name, "status": "encrypted", "error": str(e)}
    except PakUnsupported as e:
        return None, {"path": Path(path).name, "status": "unsupported", "error": str(e)}
    except PakError as e:
        st = "not_unreal" if "no Unreal pak footer" in str(e) else "error"
        return None, {"path": Path(path).name, "status": st, "error": str(e)}
    except OSError as e:
        return None, {"path": Path(path).name, "status": "error", "error": str(e)}
    s = pf.summary()
    if "Oodle" in s["compression_methods"] and game_dir is not None:
        dll = Oodle.find(game_dir)
        s["oodle_dll"] = dll.name if dll else None
        if dll:
            try:
                oodle = Oodle(dll, game_dir)
                pf.oodle = oodle
            except (PakUnsupported, OSError, AttributeError) as e:
                s["oodle_error"] = str(e)
        else:
            s["oodle_error"] = "Oodle entries present but the game ships no oo2core DLL: those entries cannot be read"
    s["status"] = "ok"
    return pf, s


def pak_priority(p: Path) -> tuple:
    """Mount order: base paks first, patch paks (_P) last so their entries win."""
    stem = p.stem
    m = re.search(r"_(\d+)_P$", stem)
    return (1 if stem.endswith("_P") else 0, int(m.group(1)) if m else 0, stem.lower())


def safe_out_path(root: Path, name: str) -> Path:
    """Join an archive path under root, refusing absolute paths, drive letters and '..'."""
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or any(p in ("..", "") or ":" in p for p in parts) or name.startswith("/"):
        raise PakError(f"refusing unsafe archive path {name!r}")
    out = (root / Path(*parts)).resolve()
    if not out.is_relative_to(root.resolve()):
        raise PakError(f"refusing archive path {name!r}: escapes the work directory")
    return out


def match(name: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    low = name.lower()
    return any(fnmatch.fnmatch(low, p.lower()) or p.lower() in low for p in patterns)


# ---------------------------------------------------------------------- IoStore

UTOC_FLAGS = {1: "compressed", 2: "encrypted", 4: "signed", 8: "indexed"}


def read_utoc_header(path: Path) -> dict:
    """FIoStoreTocHeader: enough to list a container and say what reading it would need."""
    p = Path(path)
    with open(p, "rb") as f:
        head = f.read(144)
    r = Reader(head, what="utoc header")
    if r.take(16) != UTOC_MAGIC:
        raise PakError(f"{p.name}: not an IoStore table of contents")
    version = r.u8()
    r.u8(); r.u16()
    header_size, entry_count, block_count, block_entry_size = r.u32(), r.u32(), r.u32(), r.u32()
    method_count, method_len, block_size, dir_index_size, partition_count = r.u32(), r.u32(), r.u32(), r.u32(), r.u32()
    container_id = r.u64()
    key_guid = r.guid()
    flags = r.u8()
    ucas = p.with_suffix(".ucas")
    return {"path": p.name, "toc_version": version, "entries": entry_count, "compressed_blocks": block_count,
            "compression_methods": method_count, "block_size": block_size, "directory_index": dir_index_size > 0,
            "partitions": partition_count, "container_id": f"{container_id:016x}",
            "flags": [n for b, n in UTOC_FLAGS.items() if flags & b],
            "encrypted": bool(flags & 2), "key_guid": key_guid.hex() if flags & 2 else None,
            "ucas_size": ucas.stat().st_size if ucas.is_file() else None,
            "status": "listed (IoStore chunk reading is the next stage)"}


def list_iostore(game_dir: Path, limit: int = 500) -> list[dict]:
    out = []
    for p in sorted(Path(game_dir).rglob("*.utoc"))[:limit]:
        try:
            out.append(read_utoc_header(p) | {"path": p.relative_to(game_dir).as_posix()})
        except (PakError, OSError) as e:
            out.append({"path": p.relative_to(game_dir).as_posix(), "status": "error", "error": str(e)})
    return out

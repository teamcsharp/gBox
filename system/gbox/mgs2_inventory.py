"""Metal Gear Solid 2: Substance (USA, PS2 SLUS-20554): disc identity, the two-layer DVD, and the STAGE archives.

The catalog entry ``cb7aae71edb10cd3`` "Metal Gear Solid 2: Substance (USA)" was filed as windows_native because
HyperSpin's "Microsoft XBOX" emulator lists the PS2 rom folder; the file is the PS2 DVD-9
``collections/Sony Playstation 2/roms/USA/Metal Gear Solid 2 - Substance (USA).chd`` (CHD v5 createcd, one MODE1
track of 3,142,944 sectors, cdlz / cdzl / cdfl). Everything below was recovered from that disc and its executable
(no community notes were used):

* **two layers**: layer 0's ISO9660 volume is 1,167,824 sectors (``SYSTEM.CNF``, ``SLUS_205.54`` v1.00, ``MODULES``,
  the skateboarding game ``SKATE``, ``MGS2/STAGE2.DAT`` (VR / alternative missions), ``DEMO2`` / ``VOX2`` /
  ``MOVIEVR``); layer 1 starts at sector 1,167,808 (its primary volume descriptor sits at the layer break, sector
  1,167,824) with its own ISO9660 tree: ``MGS2/STAGE.DAT`` (the Tanker / Plant story), ``DEMO``, ``VOX``, ``MOVIE``,
  ``FACE``, ``CODEC``. The ELF opens them through ``cdrom0:\\MGS2\\%s;1`` (file table at ``0x180b08``).
* **STAGE.DAT / STAGE2.DAT** (loader ``0x100fa8``): sector 0 = ``u32 key`` (a build time stamp, clear) + 12 bytes
  and ``count`` x 12-byte rows ``{char name[8], u32 sector}`` encrypted with the word stream cipher (``Cipher``:
  ``x ^= k; k = k * 0x02e90edd + step`` from ``k = key, step = key ^ 0xf0f0``); header u16 [1] = TOC sectors,
  [2] = stage count.
* **a stage** (state machine ``0x101448``): its first sectors hold ``u32 n`` + n x ``{u32 type << 24 | name hash,
  u32 offset}``, encrypted with ``k = key + 129 h + 0xa78925d9, step = 129 h + 0x7a88fb59`` (h = ``name_hash`` of the
  stage name, function ``0x1424c8``). Rows group into pages: ``0x7f`` row (page id, decompressed size), ``0x7e`` row
  (compressed size in the low 24 bits, offset of the page's data from the end of the sector-aligned header), then the
  page's files ``(type, hash, offset in the page)``. A page's data is a zlib 1.1.3 stream encrypted with the same
  cipher seeded from its first u16 (``0x1007a8``: ``s = seed ^ 0x9385, k = s | (s ^ 0x6576) << 16, step = 0x116 s``),
  whose first u16 is stored minus 0x8f3 (``78 9c`` decrypts to ``85 93``). Page 0 (``0x7f010000``) is the stage
  program overlay (type 0x01, loaded at 0x1f6500).
* **names**: files are found by ``type << 24 | name_hash(base name)`` (24-bit rotate-5 hash); the overlay's strings
  name many of them (``sna_def``, ``rai_def``, ``gbs_def`` ...); ``names()`` holds the ones gBox uses.

    python -m gbox.mgs2_inventory <MGS2.chd | MGS2.iso> [stage ...] [--json out.json]
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
import zlib
from dataclasses import dataclass, field
import os
from pathlib import Path

GAME_ID = "cb7aae71edb10cd3"
GAME_IDS = {GAME_ID: "Metal Gear Solid 2: Substance (USA) - the PS2 DVD SLUS-20554 (HyperSpin CHD filed under Microsoft XBOX)"}
TITLE = "Metal Gear Solid 2: Substance (USA)"
SERIAL = "SLUS-20554"
ELF = "SLUS_205.54"
ELF_SIZE = 852772
ELF_SHA256 = "77de3383cb257a573e631f63fc373eb5eeb1090f9659ea37bb29e129814da2d5"
CHD_SHA1 = "5a69cb8b2d0354d80651ba4bfa7c859722994a70"
TOTAL_SECTORS = 3142944
LAYER0_SECTORS = 1167824
CATALOG_REL = "collections/Sony Playstation 2/roms/USA/Metal Gear Solid 2 - Substance (USA).chd"
STAGE_FILES = ("MGS2/STAGE.DAT", "MGS2/STAGE2.DAT")
SECTOR = 2048
PAGE_LOAD = 0x1F6500                 # where page 0 (the stage program) is loaded

# file types (the high byte of a stage row); what each holds, as far as gBox reads them
TYPES = {0x01: "stage program overlay", 0x02: "per-mesh hull (float vertices + u16 indices, 3 levels)",
         0x04: "unknown 0x04", 0x06: "unknown 0x06", 0x07: "stage geometry", 0x0A: "kms model (skinned, strips)",
         0x0B: "stage script", 0x0C: "motion data", 0x0E: "unknown 0x0e", 0x11: "unknown 0x11",
         0x12: "motion table", 0x13: "texture pack (GS pages + CLUTs)", 0x15: "unknown 0x15", 0x19: "unknown 0x19",
         0x7E: "page (compressed size, data offset)", 0x7F: "page marker (id, decompressed size)"}
T_KMS, T_HULL, T_TEX = 0x0A, 0x02, 0x13


def owned_disc_paths(cfg=None) -> list[Path]:
    """Candidate paths of the owned MGS2 disc: the GBOX_MGS2_PS2_DISC override, the configured HyperSpin
    library root for this host (per-OS path from gbox.toml, e.g. /mnt/gbox/hyperspin/Arcade on Linux), the
    Windows UNC share and the local modbase cache. The catalog-relative path is CATALOG_REL."""
    out: list[Path] = []
    if env := os.environ.get("GBOX_MGS2_PS2_DISC"):
        out.append(Path(env))
    try:
        try:
            from . import config as _config
        except ImportError:
            from gbox import config as _config
        cfg = cfg or _config.load()
        for lib in cfg.libraries:
            paths = dict(lib.paths or {})
            host = paths.pop(_config.HOST_OS, None)
            for p in ([host] if host else []) + list(paths.values()):
                out.append(Path(p) / CATALOG_REL)
    except Exception:
        pass
    out.append(Path("//10.89.1.125/HyperSpin Attraction/Arcade") / CATALOG_REL)
    out.append(Path("D:/gBox/cache/modbase") / GAME_ID / "Metal Gear Solid 2 - Substance (USA).iso")
    seen, uniq = set(), []
    for p in out:
        s = str(p)
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq


class FormatError(ValueError):
    pass


# ---------------------------------------------------------------- hash + cipher
def name_hash(s: str) -> int:
    """The 24-bit file / stage name hash (ELF 0x1424c8): h = rotl5(h) + c, 24 bits; 0 becomes 1."""
    h = 0
    for c in s.encode("latin-1"):
        h = (((h << 5) | (h >> 19)) + c) & 0xFFFFFF
    return h or 1


class Cipher:
    """The word stream cipher of the STAGE archives (ELF 0x1007d8): every u32 is xored with k, then
    k = k * 0x02e90edd + step. Symmetric: run() both encrypts and decrypts; the state carries over between calls."""

    MUL = 0x02E90EDD

    def __init__(self, k: int, step: int):
        self.k, self.step = k & 0xFFFFFFFF, step & 0xFFFFFFFF

    def run(self, data: bytes) -> bytes:
        n = len(data) // 4
        if n == 0:
            return bytes(data)
        import numpy as np
        A, C = _lcg_tables(self.step, n)                 # k_i = A_i k_0 + C_i (mod 2^32)
        ks = (A * np.uint64(self.k) + C) & np.uint64(0xFFFFFFFF)
        last = int(ks[-1])
        self.k = (last * self.MUL + self.step) & 0xFFFFFFFF
        w = np.frombuffer(bytes(data[:4 * n]), "<u4").astype(np.uint64)
        out = (w ^ ks).astype("<u4").tobytes()
        return out + bytes(data[4 * n:])

    @classmethod
    def for_toc(cls, key: int) -> "Cipher":
        return cls(key, key ^ 0xF0F0)

    @classmethod
    def for_stage(cls, key: int, name: str) -> "Cipher":
        h = name_hash(name)
        return cls(key + 129 * h + 0xA78925D9, 129 * h + 0x7A88FB59)

    @classmethod
    def for_page(cls, seed: int) -> "Cipher":
        s = (seed ^ 0x9385) & 0xFFFF
        return cls(s | ((s ^ 0x6576) << 16), s * 0x116)


_LCG: dict = {}


def _lcg_tables(step: int, n: int):
    """A_i = MUL^i, C_i = step (1 + MUL + ... + MUL^(i-1)) mod 2^32 for i < n, built by doubling (numpy, exact in
    uint64 because both factors stay below 2^32). Cached per step."""
    import numpy as np
    M = np.uint64(0xFFFFFFFF)
    A, C = _LCG.get(step, (None, None))
    if A is None or len(A) < n:
        A, C = np.array([1], np.uint64), np.array([0], np.uint64)
        aL, cL = np.uint64(Cipher.MUL), np.uint64(step & 0xFFFFFFFF)          # k_1 = MUL k_0 + step
        while len(A) < n:
            A2 = (A * aL) & M
            C2 = (A * cL + C) & M
            # the next doubling step: (aL, cL) for 2L
            aL, cL = (aL * aL) & M, (aL * cL + cL) & M
            A, C = np.concatenate([A, A2]), np.concatenate([C, C2])
        if len(_LCG) > 8:
            _LCG.clear()
        _LCG[step] = (A, C)
    return A[:n], C[:n]


def decode_page(raw: bytes, dsize: int | None = None) -> bytes:
    """One page's stored bytes -> its decompressed files block."""
    if len(raw) < 4:
        raise FormatError("page shorter than one word")
    seed = struct.unpack_from("<H", raw, 0)[0]
    raw = bytes(raw) + b"\0" * (-len(raw) % 4)          # the game decrypts whole words (the tail word too)
    plain = bytearray(Cipher.for_page(seed).run(raw))
    struct.pack_into("<H", plain, 0, (struct.unpack_from("<H", plain, 0)[0] + 0x8F3) & 0xFFFF)
    d = zlib.decompressobj()
    try:
        out = d.decompress(bytes(plain))
    except zlib.error as e:
        raise FormatError(f"page does not inflate: {e}") from None
    if dsize is not None and len(out) != dsize:
        raise FormatError(f"page inflated to {len(out)} bytes, the table says {dsize}")
    return out


def encode_page(data: bytes, seed: int = 0x5A5A, level: int = 9) -> bytes:
    """A files block -> stored page bytes (zlib, header forced to 78 9c, first u16 - 0x8f3, encrypted)."""
    z = bytearray(zlib.compress(bytes(data), level))
    z[0:2] = b"\x78\x9c"                                 # FLEVEL is informational; 0x789c keeps the header check
    struct.pack_into("<H", z, 0, (struct.unpack_from("<H", z, 0)[0] - 0x8F3) & 0xFFFF)
    z += b"\0" * (-len(z) % 4)
    # the seed is the stored first u16: its plain value is fixed (0x9385), so the key follows from the seed
    out = Cipher.for_page(seed).run(bytes(z))
    if struct.unpack_from("<H", out, 0)[0] != seed:
        raise FormatError("page seed did not round trip")
    return out


# ---------------------------------------------------------------- disc (CHD or ISO, both layers)
class Disc:
    """Both ISO9660 layers of the DVD-9 from the catalog CHD (read in place) or a plain ISO. ``files``: upper-case
    path -> (absolute sector, size)."""

    def __init__(self, path):
        self.path = Path(path)
        with open(self.path, "rb") as f:
            magic = f.read(8)
        self.chd = None
        if magic == b"MComprHD":
            from .chd import ChdDisc
            self.chd = ChdDisc(self.path)
            self.sectors_total = self.chd.frames
            self._f = None
        else:
            self._f = open(self.path, "rb")
            self.sectors_total = self.path.stat().st_size // SECTOR
        self.files: dict[str, tuple[int, int]] = {}
        self.pvd = self.sector(16)
        if self.pvd[1:6] != b"CD001":
            raise FormatError(f"{self.path.name}: no ISO9660 volume descriptor")
        self.layer0 = struct.unpack_from("<I", self.pvd, 80)[0]
        self._walk_root(self.pvd, 0)
        self.layer1_start = None
        if self.sectors_total > self.layer0 + 16:
            pvd1 = self.sector(self.layer0)
            if pvd1[1:6] == b"CD001":
                self.layer1_start = self.layer0 - 16
                self._walk_root(pvd1, self.layer1_start)

    def close(self):
        if self._f:
            self._f.close()
            self._f = None

    def sector(self, lba: int) -> bytes:
        return self.sectors(lba, 1)

    def sectors(self, lba: int, n: int) -> bytes:
        if lba < 0 or n < 0 or lba + n > self.sectors_total:
            raise FormatError(f"sectors {lba}+{n} outside the disc ({self.sectors_total})")
        if self.chd is not None:
            return b"".join(self.chd.sector(lba + i) for i in range(n))
        self._f.seek(lba * SECTOR)
        return self._f.read(n * SECTOR)

    def _walk_root(self, pvd: bytes, base: int):
        root = pvd[156:190]
        self._walk(struct.unpack_from("<I", root, 2)[0], max(struct.unpack_from("<I", root, 10)[0], SECTOR), "", 0,
                   base)

    def _walk(self, lba: int, size: int, prefix: str, depth: int, base: int):
        if depth > 8 or size > 1 << 20:
            return
        buf = self.sectors(base + lba, (size + SECTOR - 1) // SECTOR)
        o = 0
        while o < len(buf):
            n = buf[o]
            if n == 0:
                o = (o // SECTOR + 1) * SECTOR
                continue
            rec, o = buf[o:o + n], o + n
            if len(rec) < 34:
                break
            name = rec[33:33 + rec[32]]
            if name in (b"\0", b"\1"):
                continue
            path = prefix + name.decode("latin-1").split(";")[0]
            elba, esize = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
            if rec[25] & 2:
                self._walk(elba, esize, path + "/", depth + 1, base)
            else:
                self.files.setdefault(path.upper(), (base + elba, esize))

    def size(self, name: str) -> int:
        return self.files[name.upper()][1]

    def read(self, name: str, offset: int = 0, size: int | None = None) -> bytes:
        lba, n = self.files[name.upper()]
        size = n - offset if size is None else size
        if offset < 0 or size < 0 or offset + size > n:
            raise FormatError(f"{name}: read 0x{offset:x}+0x{size:x} outside 0x{n:x} bytes")
        first, last = offset // SECTOR, (offset + size + SECTOR - 1) // SECTOR
        buf = self.sectors(lba + first, last - first)
        s = offset - first * SECTOR
        return buf[s:s + size]


def system_cnf(disc: Disc) -> dict:
    out = {}
    for line in disc.read("SYSTEM.CNF").decode("latin-1").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().upper()] = v.strip()
    return out


def identify(disc: Disc) -> dict:
    cnf = system_cnf(disc)
    boot = re.sub(r"^cdrom0:\\?", "", cnf.get("BOOT2", "")).split(";")[0].upper()
    elf = disc.read(boot) if boot in disc.files else b""
    out = {"boot": boot, "version": cnf.get("VER"), "elf_size": len(elf),
           "elf_sha256": hashlib.sha256(elf).hexdigest() if elf else None, "sectors": disc.sectors_total,
           "layer0_sectors": disc.layer0, "layer1_start": disc.layer1_start,
           "stage_files": {n: disc.files.get(n) for n in STAGE_FILES}}
    if disc.chd is not None:
        out["chd_sha1"] = disc.chd.chd.h["sha1"]
    out["platform"] = "ps2"
    out["exact_build"] = bool(boot == ELF and out["elf_sha256"] == ELF_SHA256 and
                              all(n in disc.files for n in STAGE_FILES))
    return out


# ---------------------------------------------------------------- STAGE.DAT
@dataclass
class Page:
    marker: int                     # 0x7fXXXXXX row word
    dsize: int                      # decompressed size
    csize: int                      # stored (compressed) size
    coff: int                       # offset of the stored data after the header sectors
    files: list = field(default_factory=list)    # [type, hash, offset, size]
    rows: tuple = (0, 0)            # (marker row index, page row index)


@dataclass
class Stage:
    name: str
    index: int
    sector: int                     # first sector inside the .DAT
    sectors: int                    # span up to the next stage
    rows: list                      # [(word, offset)]
    header_bytes: int
    pages: list

    @property
    def data_sector(self) -> int:
        return (self.header_bytes + SECTOR - 1) // SECTOR

    def find(self, typ: int, h: int):
        for k, p in enumerate(self.pages):
            for f in p.files:
                if f[0] == typ and f[1] == h:
                    return k, f
        return None


def parse_rows(plain: bytes) -> list[tuple[int, int]]:
    n = struct.unpack_from("<I", plain, 0)[0]
    if n > 0x10000 or 4 + 8 * n > len(plain):
        raise FormatError(f"stage header claims {n} rows")
    return [struct.unpack_from("<2I", plain, 4 + 8 * i) for i in range(n)]


def pages_of(rows: list[tuple[int, int]]) -> list[Page]:
    out, cur = [], None
    for i, (w, off) in enumerate(rows):
        t = w >> 24
        if t == 0x7F:
            cur = Page(w, off, 0, 0, [], (i, -1))
            continue
        if t == 0x7E:
            if cur is None or cur.rows[1] >= 0:
                raise FormatError(f"page row {i} without its marker")
            cur.csize, cur.coff, cur.rows = w & 0xFFFFFF, off, (cur.rows[0], i)
            out.append(cur)
            continue
        if cur is not None and cur.rows[1] >= 0:
            cur.files.append([t, w & 0xFFFFFF, off, 0])
    for p in out:
        for k, f in enumerate(p.files):
            end = p.files[k + 1][2] if k + 1 < len(p.files) else p.dsize
            if not 0 <= f[2] <= end <= p.dsize:
                raise FormatError(f"file {f[0]:02x}:{f[1]:06x} at 0x{f[2]:x} outside its page (0x{p.dsize:x})")
            f[3] = end - f[2]
    return out


class StageArchive:
    """One of STAGE.DAT / STAGE2.DAT: TOC, stage headers, pages."""

    def __init__(self, disc: Disc, name: str = "MGS2/STAGE.DAT"):
        self.disc, self.name = disc, name
        self.lba, self.size = disc.files[name.upper()]
        head = disc.sectors(self.lba, 1)
        self.key = struct.unpack_from("<I", head, 0)[0]
        c = Cipher.for_toc(self.key)
        h = c.run(head[4:16])
        self.toc_sectors, self.count = struct.unpack_from("<hh", h, 2)
        if not 0 < self.count < 4096 or self.toc_sectors <= 0:
            raise FormatError(f"{name}: TOC header does not decrypt ({self.count} stages)")
        need = 16 + 12 * self.count
        if need > SECTOR:
            head = disc.sectors(self.lba, (need + SECTOR - 1) // SECTOR)
        rows = c.run(head[16:need])
        self.stages: list[tuple[str, int]] = []
        for i in range(self.count):
            r = rows[12 * i:12 * i + 12]
            self.stages.append((r[:8].split(b"\0")[0].decode("latin-1"), struct.unpack_from("<I", r, 8)[0]))
        self.end = self.size // SECTOR

    def names(self) -> list[str]:
        return [n for n, _s in self.stages]

    def span(self, i: int) -> tuple[int, int]:
        a = self.stages[i][1]
        b = self.stages[i + 1][1] if i + 1 < len(self.stages) else self.end
        return a, b - a

    def stage(self, name: str) -> Stage:
        i = self.names().index(name)
        a, n = self.span(i)
        c = Cipher.for_stage(self.key, name)
        first = c.run(self.disc.sectors(self.lba + a, 1))
        cnt = struct.unpack_from("<I", first, 0)[0]
        size = 4 + 8 * cnt
        if cnt > 0x10000 or size > n * SECTOR:
            raise FormatError(f"{name}: stage header does not decrypt ({cnt} rows)")
        if size > SECTOR:
            first += c.run(self.disc.sectors(self.lba + a + 1, (size - 1) // SECTOR))
        rows = parse_rows(first)
        return Stage(name, i, a, n, rows, size, pages_of(rows))

    def page_raw(self, st: Stage, k: int) -> bytes:
        p = st.pages[k]
        first = self.lba + st.sector + st.data_sector + p.coff // SECTOR
        return self.disc.sectors(first, (p.csize + SECTOR - 1) // SECTOR)[:(p.csize + 3) & ~3]

    def page(self, st: Stage, k: int) -> bytes:
        return decode_page(self.page_raw(st, k), st.pages[k].dsize)

    def file(self, st: Stage, typ: int, h: int) -> bytes | None:
        hit = st.find(typ, h)
        if hit is None:
            return None
        k, f = hit
        return self.page(st, k)[f[2]:f[2] + f[3]]


def encode_stage_header(rows: list[tuple[int, int]], key: int, name: str) -> bytes:
    """Stage rows -> the encrypted, sector-padded header."""
    plain = struct.pack("<I", len(rows)) + b"".join(struct.pack("<2I", w & 0xFFFFFFFF, o) for w, o in rows)
    plain += b"\0" * (-len(plain) % SECTOR)
    return Cipher.for_stage(key, name).run(plain)


def rebuild_stage(st: Stage, key: int, page_data: dict[int, bytes], old_raw: dict[int, bytes],
                  files: dict[int, list] | None = None, seed: int | None = None) -> bytes:
    """A stage's new stored bytes: pages in page_data are re-encoded (their file tables from `files` when given),
    the others are kept byte for byte (old_raw). Raises when the result is longer than the stage's span."""
    rows = list(st.rows)
    blobs = []
    coff = 0
    for k, p in enumerate(st.pages):
        if k in page_data:
            data = page_data[k]
            s = seed if seed is not None else (struct.unpack_from("<H", old_raw[k], 0)[0] if k in old_raw else 0x5A5A)
            raw = encode_page(data, s)
            mi, pi = p.rows
            rows[mi] = (p.marker, len(data))
            if files and k in files:
                fl = files[k]
                if len(fl) != len(p.files):
                    raise FormatError("a rebuilt page must keep its file count")
                for j, f in enumerate(fl):
                    rows[pi + 1 + j] = ((f[0] << 24) | f[1], f[2])
        else:
            raw = old_raw[k]
        rows[p.rows[1]] = ((0x7E << 24) | len(raw), coff)
        blobs.append((coff, raw))
        coff += (len(raw) + SECTOR - 1) // SECTOR * SECTOR
    head = encode_stage_header(rows, key, st.name)
    body = bytearray(coff)
    for o, raw in blobs:
        body[o:o + len(raw)] = raw
    out = head + bytes(body)
    if len(out) > st.sectors * SECTOR:
        raise FormatError(f"{st.name}: rebuilt stage is {len(out)} bytes, its span is {st.sectors * SECTOR}")
    return out + b"\0" * (st.sectors * SECTOR - len(out))


# ---------------------------------------------------------------- names
# names the overlay / executable spell out or gBox confirmed by hash (type 0x0a models, their 0x13 texture packs)
KNOWN = ["sna_def", "sna_def_mt", "sna_shadow", "sna_mugen_bdn1", "sna_mugen_bdn2", "rai_def", "rai_def_mt",
         "rai_shadow", "rai_mag", "rai_hlst", "rai_grip", "rai_hair_shadow_mt", "rai_hair_bounding",
         "rah_def_dummy", "gbs_def", "gbs_def_mt", "gbs_shadow", "gbs_hand_def", "gbs_nvg1", "gbs_nvg2",
         "gbs_sling", "gbs_kanagu", "gbs_mag", "gbs_knif", "gps_def", "gpa_def", "gba_def", "htc_def",
         "cbx_a_mt", "foot_shadow_cm", "usp", "m92", "socom", "aks", "psg", "stg", "nkt", "scm"]


def names(extra=()) -> dict[int, str]:
    out: dict[int, str] = {}
    for n in list(KNOWN) + list(extra):
        out.setdefault(name_hash(n), n)
    return out


def stage_files(arch: StageArchive, st: Stage, typ: int | None = None) -> list[dict]:
    nm = names()
    rows = []
    for k, p in enumerate(st.pages):
        for t, h, off, size in p.files:
            if typ is None or t == typ:
                rows.append({"page": k, "type": t, "hash": f"{h:06x}", "name": nm.get(h), "offset": off, "size": size})
    return rows


def inventory(path, stages=None) -> dict:
    disc = Disc(path)
    ident = identify(disc)
    out = {"identity": ident, "archives": {}}
    for fn in STAGE_FILES:
        a = StageArchive(disc, fn)
        rows = []
        for name, sec in a.stages:
            if stages and name not in stages:
                continue
            st = a.stage(name)
            types: dict[str, int] = {}
            for p in st.pages:
                for f in p.files:
                    types[f"{f[0]:02x}"] = types.get(f"{f[0]:02x}", 0) + 1
            rows.append({"stage": name, "sector": sec, "sectors": st.sectors, "pages": len(st.pages),
                         "files": sum(len(p.files) for p in st.pages), "types": types,
                         **({"file_list": stage_files(a, st)} if stages else {})})
        out["archives"][fn] = {"key": hex(a.key), "stages": a.count, "rows": rows}
    disc.close()
    return out


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    out = None
    if "--json" in a:
        i = a.index("--json")
        out = a[i + 1]
        del a[i:i + 2]
    if not a:
        print(__doc__)
        return 2
    inv = inventory(a[0], a[1:] or None)
    if out:
        Path(out).write_text(json.dumps(inv, indent=1, default=str))
    print(json.dumps(inv["identity"], indent=1, default=str))
    for fn, v in inv["archives"].items():
        print(fn, v["stages"], "stages")
        for r in v["rows"]:
            print(f"  {r['stage']:10s} {r['sector']:7d} {r['sectors']:6d} pages {r['pages']} files {r['files']} {r['types']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

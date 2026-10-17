"""Read-only PlayStation disc access: CHD v4/v5-zlib containers (as in the HyperSpin set) -> raw 2352-byte sectors ->
ISO9660 file listing + file reads (Mode 2 Form 1 user data). No external tools (chdman not needed)."""
from __future__ import annotations

import struct
import zlib
from functools import lru_cache


class CHD:
    """CHD v4 (zlib / zlib+ CD hunks). v5 raises (needs LZMA/FLAC + Huffman map)."""

    def __init__(self, path):
        self.f = open(path, "rb")
        try:
            h = self.f.read(0x6C)
            if h[:8] != b"MComprHD":
                raise ValueError("not a CHD")
            hlen, ver = struct.unpack_from(">II", h, 8)
            if ver != 4:
                raise NotImplementedError(f"CHD v{ver} not supported (v4 only)")
            _flags, self.comp, self.nhunks = struct.unpack_from(">III", h, 16)
            self.logical, _meta = struct.unpack_from(">QQ", h, 28)
            self.hunkbytes = struct.unpack_from(">I", h, 44)[0]
            self.f.seek(hlen)
            raw = self.f.read(16 * self.nhunks)
            self.map = [struct.unpack_from(">QIHBB", raw, 16 * i) for i in range(self.nhunks)]
            self.frame = 2448                                  # 2352 sector + 96 subcode
            self.frames_per_hunk = self.hunkbytes // self.frame
            self._hunk = lru_cache(64)(self._read_hunk)
        except BaseException:
            self.f.close()
            raise

    def close(self):
        self.f.close()

    def _read_hunk(self, i: int) -> bytes:
        off, crc, lo, hi, flags = self.map[i]
        ln = lo | (hi << 16)
        t = flags & 0xF
        if t == 1:                                         # compressed
            self.f.seek(off)
            d = self.f.read(ln)
            try:
                return zlib.decompress(d, -15)
            except zlib.error:
                return zlib.decompress(d)
        if t == 2:                                         # uncompressed
            self.f.seek(off)
            return self.f.read(self.hunkbytes)
        if t == 3:                                         # mini: 8-byte pattern repeated
            return struct.pack(">Q", off) * (self.hunkbytes // 8)
        if t == 4:                                         # same as another hunk
            return self._hunk(off)
        raise NotImplementedError(f"hunk type {t}")

    def sector(self, lba: int) -> bytes:
        """Raw 2352-byte sector by frame index (frame 0 = start of track 1)."""
        h, k = divmod(lba, self.frames_per_hunk)
        return self._hunk(h)[k * self.frame:k * self.frame + 2352]


class PSXDisc:
    def __init__(self, path):
        self.chd = CHD(path)
        try:
            pvd = self.data(16)
            assert pvd[1:6] == b"CD001", "no ISO9660 PVD"
            root = pvd[156:156 + 34]
            self.files: dict[str, tuple[int, int]] = {}
            self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")
        except BaseException:
            self.chd.close()
            raise

    def close(self):
        self.chd.close()

    def data(self, lba: int) -> bytes:
        s = self.chd.sector(lba)
        return s[24:24 + 2048] if s[15] == 2 else s[16:16 + 2048]

    def read(self, name: str, offset: int = 0, size: int | None = None) -> bytes:
        lba, length = self.files[name]
        size = length - offset if size is None else size
        if offset < 0 or size < 0 or offset + size > length:
            raise ValueError(f"{name}: read outside {length} bytes")
        first, last = offset // 2048, (offset + size + 2047) // 2048
        data = b"".join(self.data(lba + i) for i in range(first, last))
        start = offset - first * 2048
        return data[start:start + size]

    def _walk(self, lba, size, prefix):
        from .formats import iso9660                      # the shared ISO9660 walk (gbox.formats)
        for parts, rec, _d in iso9660.walk(iso9660.sector_reader(self.data), lba, size):
            if not rec.is_dir:
                self.files[prefix + "".join(p + "/" for p in parts) + rec.name] = (rec.lba, rec.size)


# ---------------------------------------------------------------- writing: raw MODE2/2352 .bin images (mods)
#
# A modded PSX disc is a copy of the raw single-track image with files rewritten sector by sector. Every touched
# Mode 2 Form 1 sector gets its EDC (CRC over subheader + data) and Reed-Solomon P/Q ECC recomputed (address bytes
# zeroed for Mode 2), so the image is valid for real drives and for emulators that check sectors.

def _luts():
    f, b, e = [0] * 256, [0] * 256, [0] * 256
    for i in range(256):
        j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
        f[i] = j
        b[i ^ j] = i
        c = i
        for _ in range(8):
            c = (c >> 1) ^ (0xD8018001 if c & 1 else 0)
        e[i] = c
    return f, b, e


_ECC_F, _ECC_B, _EDC = _luts()


def edc(data: bytes) -> int:
    c = 0
    for x in data:
        c = (c >> 8) ^ _EDC[(c ^ x) & 0xFF]
    return c


def _ecc_block(src: bytearray, major_count: int, minor_count: int, major_mult: int, minor_inc: int, dst: int):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = src[0xC + index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = _ECC_F[a]
        a = _ECC_B[_ECC_F[a] ^ b]
        src[dst + major] = a
        src[dst + major + major_count] = a ^ b


def fix_sector(s: bytearray) -> bytearray:
    """Recompute EDC + ECC of a raw 2352-byte Mode 2 Form 1 sector in place (Form 2 sectors: EDC only)."""
    if s[0x12] & 0x20:                                     # Form 2 (XA audio/video): EDC over 0x10..0x92C, no ECC
        struct.pack_into("<I", s, 0x92C, edc(s[0x10:0x92C]))
        return s
    struct.pack_into("<I", s, 0x818, edc(s[0x10:0x818]))
    addr = bytes(s[12:16])
    s[12:16] = b"\0\0\0\0"
    _ecc_block(s, 86, 24, 2, 86, 0x81C)
    _ecc_block(s, 52, 43, 86, 88, 0x8C8)
    s[12:16] = addr
    return s


class RawBin:
    """A single-track MODE2/2352 .bin opened for writing: ISO9660 listing + sector-exact file rewrites."""

    def __init__(self, path, writable: bool = True):
        self.f = open(path, "r+b" if writable else "rb")
        self.files: dict[str, tuple[int, int]] = {}
        pvd = self.data(16)
        assert pvd[1:6] == b"CD001", "no ISO9660 PVD"
        self._walk(struct.unpack_from("<I", pvd, 158)[0], struct.unpack_from("<I", pvd, 166)[0], "")

    _walk = PSXDisc._walk

    def raw(self, lba: int) -> bytearray:
        self.f.seek(lba * 2352)
        return bytearray(self.f.read(2352))

    def data(self, lba: int) -> bytes:
        s = self.raw(lba)
        return bytes(s[24:24 + 2048] if s[15] == 2 else s[16:16 + 2048])

    def read(self, name: str) -> bytes:
        lba, size = self.files[name]
        return b"".join(self.data(lba + i) for i in range((size + 2047) // 2048))[:size]

    def write_data(self, lba: int, data: bytes) -> int:
        """Overwrite the user data of consecutive Form 1 sectors from `lba` (data padded to whole sectors with the
        sectors' old bytes). Returns the number of sectors rewritten."""
        n = (len(data) + 2047) // 2048
        for i in range(n):
            s = self.raw(lba + i)
            if s[15] != 2 or s[0x12] & 0x20:
                raise ValueError(f"sector {lba + i} is not Mode 2 Form 1: refusing to write file data there")
            chunk = data[i * 2048:(i + 1) * 2048]
            s[24:24 + len(chunk)] = chunk
            fix_sector(s)
            self.f.seek((lba + i) * 2352)
            self.f.write(s)
        return n

    def write_file(self, name: str, offset: int, data: bytes) -> int:
        """Rewrite part of an existing file in place (offset must be sector-aligned; the file size never changes)."""
        lba, size = self.files[name]
        if offset % 2048:
            raise ValueError("offset must be a multiple of 2048")
        if offset + len(data) > (size + 2047) // 2048 * 2048:
            raise ValueError(f"{name}: {len(data)} bytes at {offset} run past the file's sectors")
        return self.write_data(lba + offset // 2048, data)

    def close(self):
        self.f.close()


def chd_to_bin(chd, out_bin, progress=None):
    """CHD (v4/v5, single data track) -> raw .bin + .cue: chdman when installed, else gbox.frame_rip's reader (v4)."""
    import shutil
    import subprocess
    from pathlib import Path
    out_bin = Path(out_bin)
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    cue = out_bin.with_suffix(".cue")
    if shutil.which("chdman"):
        tmp = out_bin.with_name(out_bin.stem + ".part.cue")
        subprocess.run(["chdman", "extractcd", "-f", "-i", str(chd), "-o", str(tmp), "-ob", str(out_bin)],
                       check=True, capture_output=True, timeout=3600)
        cue.write_text(f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        tmp.unlink(missing_ok=True)
        return cue
    from .frame_rip import psx_chd_to_bin
    return psx_chd_to_bin(Path(chd), out_bin)


def _selftest_ecc(path):
    """Recompute EDC/ECC of a few sectors of a real image: must match the mastered bytes."""
    d = PSXDisc(path)
    for lba in (16, 17, 24, 1000):
        s = bytearray(d.chd.sector(lba))
        if s[15] != 2:
            continue
        want = bytes(s)
        fix_sector(s)
        assert bytes(s) == want, f"EDC/ECC mismatch at sector {lba}"
    return True

"""Read-only Dreamcast GD-ROM filesystem (ISO9660 in the high-density area) from a .gdi + raw track files.

The .gdi lists tracks as: <n> <start_lba> <type 4=data/0=audio> <sector size> <file> 0. ISO9660 directory records
carry absolute LBAs, so each sector is found in whichever data track contains it.
"""
import struct
from pathlib import Path


class GDRom:
    def __init__(self, gdi: str | Path):
        gdi = Path(gdi)
        lines = gdi.read_text().split("\n")[1:]
        self.tracks = []                        # (start_lba, sector_size, path)
        for ln in lines:
            parts = ln.split()
            if len(parts) >= 6 and parts[2] == "4":
                self.tracks.append((int(parts[1]), int(parts[3]), gdi.parent / parts[4].strip('"')))
        self.tracks.sort()
        self._fh = {}
        # the first high-density data track (LBA 45000) holds the volume descriptor; games with audio tracks in
        # between (Shenmue) continue the filesystem in a later data track, which sector() also reads
        hd = min((t for t in self.tracks if t[0] >= 45000), default=max(self.tracks))
        pvd = self.sector(hd[0] + 16)
        if pvd[1:6] != b"CD001":
            raise ValueError("no ISO9660 volume in the high-density area")
        root = pvd[156:156 + 34]
        self.files: dict[str, tuple[int, int]] = {}
        self.records: dict[str, tuple[int, int]] = {}  # file -> (LBA of its directory sector, record offset there)
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")

    def sector(self, lba: int) -> bytes:
        for start, size, path in reversed(self.tracks):
            if lba >= start:
                f = self._fh.get(path) or self._fh.setdefault(path, open(path, "rb"))
                f.seek((lba - start) * size + (16 if size == 2352 else 0))
                return f.read(2048)
        raise ValueError(f"LBA {lba} not in a data track")

    def _walk(self, lba, size, prefix):
        data = b"".join(self.sector(lba + i) for i in range((size + 2047) // 2048))
        o = 0
        while o < len(data):
            n = data[o]
            if n == 0:
                o = (o // 2048 + 1) * 2048       # records never span sectors; skip padding
                continue
            ext, ln, flags, nl = struct.unpack_from("<I", data, o + 2)[0], struct.unpack_from("<I", data, o + 10)[0], data[o + 25], data[o + 32]
            name = data[o + 33:o + 33 + nl].decode("latin-1").split(";")[0]
            if name not in ("\x00", "\x01"):
                if flags & 2:
                    self._walk(ext, ln, f"{prefix}{name}/")
                else:
                    self.files[f"{prefix}{name}"] = (ext, ln)
                    self.records[f"{prefix}{name}"] = (lba + o // 2048, o % 2048)
            o += n

    def read(self, name: str) -> bytes:
        lba, size = self.files[name]
        out = bytearray()
        for i in range((size + 2047) // 2048):
            out += self.sector(lba + i)
        return bytes(out[:size])


# ---------------------------------------------------------------- writing: a modded copy of the disc (gBox file mods)

def _edc_lut():
    lut = []
    for i in range(256):
        e = i
        for _ in range(8):
            e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
        lut.append(e)
    return lut


_EDC = _edc_lut()
_ECC_F = [((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF for i in range(256)]
_ECC_B = [0] * 256
for _i in range(256):
    _ECC_B[_i ^ _ECC_F[_i]] = _i


def _ecc_block(s: bytearray, major_count, minor_count, major_mult, minor_inc, dest):
    size = major_count * minor_count
    src = 0xC
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = s[src + index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = _ECC_F[a]
        a = _ECC_B[_ECC_F[a] ^ b]
        s[dest + major] = a
        s[dest + major + major_count] = a ^ b


def mode1_sector(raw: bytes, data: bytes) -> bytes:
    """A raw 2352-byte Mode 1 sector with new user data: header kept, EDC and P/Q ECC recomputed."""
    s = bytearray(raw[:16]) + bytearray(data.ljust(2048, b"\0")) + bytearray(288)
    e = 0
    for c in s[:0x810]:
        e = (e >> 8) ^ _EDC[(e ^ c) & 0xFF]
    s[0x810:0x814] = struct.pack("<I", e)
    _ecc_block(s, 86, 24, 2, 86, 0x81C)
    _ecc_block(s, 52, 43, 86, 88, 0x8C8)
    return bytes(s)


def patch_gdi(src_gdi: str | Path, out_dir: str | Path, name: str, files: dict[str, bytes], progress=None) -> Path:
    """Copy a GDI to out_dir/<name>.gdi (unchanged tracks hard-linked, the last data track copied) with `files`
    rewritten in place: each must fit its old sectors plus the free sectors before the next file (a full GD-ROM
    has no room to move files). ISO9660 sizes updated; EDC/ECC recomputed. Only the last data track is patched."""
    import os
    import shutil
    src_gdi, out_dir = Path(src_gdi), Path(out_dir)
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)   # GDI lines are whitespace-separated
    disc = GDRom(src_gdi)
    order = sorted(l for l, _s in disc.files.values())
    start, ssz, tpath = max(disc.tracks)
    plan = []
    for key, data in files.items():
        if key not in disc.files:
            raise ValueError(f"{key} is not on this disc")
        lba, size = disc.files[key]
        if lba < start or disc.records[key][0] < start:
            raise ValueError(f"{key} isn't on the last data track; only that track is patched")
        nxt = next((l for l in order if l > lba), None)
        room = (nxt - lba) if nxt else (size + 2047) // 2048
        need = (len(data) + 2047) // 2048
        if need > room:
            raise ValueError(f"{key}: {len(data)} bytes need {need} sectors, only {room} free at LBA {lba} "
                             f"(the original is {size} bytes)")
        plan.append((key, lba, data))
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [ln for ln in src_gdi.read_text().splitlines() if ln.strip()]
    new_lines, dst_of = [lines[0]], {}
    for ln in lines[1:]:
        parts = ln.split()
        src = src_gdi.parent / parts[4].strip('"')
        dst = out_dir / f"{name}.track{int(parts[0]):02d}{src.suffix}"
        if dst.exists():
            dst.unlink()
        if src == tpath:
            if progress:
                progress(0, f"Copying {src.name} ({src.stat().st_size / 2**20:.0f} MB)")
            shutil.copyfile(src, dst)
        else:
            try:
                os.link(src, dst)
            except OSError:
                shutil.copyfile(src, dst)
        dst_of[src] = dst
        parts[4] = dst.name
        new_lines.append(" ".join(parts))
    with open(dst_of[tpath], "r+b") as f:
        def put(lba, data):
            f.seek((lba - start) * ssz)
            if ssz == 2352:
                raw = f.read(2352)
                f.seek((lba - start) * ssz)
                f.write(mode1_sector(raw, data))
            else:
                f.write(data.ljust(2048, b"\0"))
        for key, lba, data in plan:
            for i in range(0, max(len(data), 1), 2048):
                put(lba + i // 2048, data[i:i + 2048])
            dlba, doff = disc.records[key]
            f.seek((dlba - start) * ssz + (16 if ssz == 2352 else 0))
            sec = bytearray(f.read(2048))                  # this copy's sector (an earlier file may have changed it)
            sec[doff + 10:doff + 14] = struct.pack("<I", len(data))
            sec[doff + 14:doff + 18] = struct.pack(">I", len(data))
            put(dlba, bytes(sec))
    gdi = out_dir / f"{name}.gdi"
    gdi.write_text("\n".join(new_lines) + "\n")
    return gdi


if __name__ == "__main__":
    import sys
    g = GDRom(sys.argv[1])
    print(len(g.files), "files")
    for k, (lba, s) in sorted(g.files.items()):
        if len(sys.argv) < 3 or sys.argv[2].lower() in k.lower():
            print(f"{s:10d}  {k}")

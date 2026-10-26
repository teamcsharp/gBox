"""Read-only Dreamcast GD-ROM filesystem (ISO9660 in the high-density area) from a .gdi + raw track files.

The .gdi lists tracks as: <n> <start_lba> <type 4=data/0=audio> <sector size> <file> 0. ISO9660 directory records
carry absolute LBAs, so each sector is found in whichever data track contains it.
"""
import re
import struct
from pathlib import Path

_GDI_FIELD = re.compile(r'"[^"]*"|\S+')


def gdi_fields(line: str) -> list[str]:
    """Split one .gdi track line into fields. Redump/TOSEC sets quote file names that contain spaces
    (`3 45000 4 2352 "Game (USA) (Track 3).bin" 0`), which a plain str.split() cuts into pieces."""
    return [f[1:-1] if len(f) >= 2 and f[0] == f[-1] == '"' else f for f in _GDI_FIELD.findall(line)]


class CDIRom:
    """Read-only ISO9660 filesystem from a DiscJuggler .cdi image, including multi-session repacks (DCRES).

    A .cdi is every track's raw sectors back to back (pregap included) followed by a footer. The last 8 bytes
    are the format version (0x80000004 v2, 0x80000005 v3, 0x80000006 v3.5) and the footer offset (from the end
    of the file for v3.5, absolute otherwise). The footer lists sessions -> tracks with each track's pregap,
    length, mode, start LBA, total length (pregap + length) and sector size (layout as read by cdirip and
    libmirage). Each data track's LBAs [start_lba, start_lba + length) begin after its pregap; the 2048-byte
    user payload sits 0 (2048), 8 (Mode 2 2336), 16 (Mode 1 2352) or 24 (Mode 2 2352) bytes into a sector.

    Multi-session repacks keep a small decoy ISO in session 1 (DUMMY.DAT) and the real game filesystem in a
    later session, so every data track carrying a primary volume descriptor at start_lba + 16 is walked and
    their files merged. Images without a parsable footer fall back to locating the PVD and the next volume
    descriptor one sector later, whose distance is the stride and whose position is the LBA-0 base.
    """

    _SECTOR_SIZES = {0: 2048, 1: 2336, 2: 2352, 4: 2448}
    _TRACK_MARK = b"\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff"

    def __init__(self, cdi: str | Path):
        import mmap
        self.path = Path(cdi)
        self._fh = open(self.path, "rb")
        try:
            self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        except (ValueError, OSError) as e:
            self._fh.close()
            raise ValueError("cannot map CDI image") from e
        try:
            self._load()
        except BaseException:
            self.close()
            raise

    def close(self):
        mm = getattr(self, "_mm", None)
        if mm is not None:
            mm.close()
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _load(self):
        self._data_end = len(self._mm)
        # (start_lba, length, file offset of start_lba's user data, sector stride)
        self._track_map: list[tuple[int, int, int, int]] = []
        try:
            self.tracks_info = self._parse_footer()
        except (struct.error, ValueError, IndexError):
            self.tracks_info = []
            self._data_end = len(self._mm)
        pos = 0
        for t in self.tracks_info:
            if t["mode"] in (1, 2):
                user = {2048: 0, 2336: 8}.get(t["sector_size"], 16 if t["mode"] == 1 else 24)
                self._track_map.append((t["start_lba"], t["length"],
                                        pos + t["pregap"] * t["sector_size"] + user, t["sector_size"]))
            pos += t["total_length"] * t["sector_size"]
        if pos > self._data_end:
            raise ValueError("CDI tracks extend into the footer or beyond the image")
        self.files: dict[str, tuple[int, int]] = {}
        self.metadata_ranges = []
        self._active_directories = set()
        self.records: dict[str, tuple[int, int]] = {}
        if self._track_map:
            for start, _length, _off, _ss in self._track_map:
                pvd = self.sector(start + 16)
                if pvd[:6] == b"\x01CD001":
                    self._volume(pvd, start)
        if not self.files:
            self._track_map = []
            self._heuristic_layout()
        first = self._track_map[0]
        self.base = first[2] - first[0] * first[3]      # file offset of LBA 0's user data (first track)
        self.sector_size = first[3]

    def _heuristic_layout(self):
        pvd = self._mm.find(b"\x01CD001")
        if pvd < 0:
            raise ValueError("no ISO9660 volume descriptor in this CDI image")
        nxt = self._mm.find(b"CD001", pvd + 2)          # the next descriptor (terminator/supplementary)
        if nxt <= pvd:
            raise ValueError("no second ISO9660 volume descriptor in this CDI image")
        stride = nxt - (pvd + 1)                        # PVD "CD001" -> next "CD001" is one sector
        if stride not in (2048, 2336, 2352):
            raise ValueError(f"unexpected CDI sector stride {stride}")
        base = pvd - 16 * stride                        # the PVD is LBA 16: back up to LBA-0 user data
        self._track_map = [(0, (len(self._mm) - base) // stride + 1, base, stride)]
        self._volume(self.sector(16), 0)

    def _volume(self, pvd, start):
        self.metadata_ranges.append((start, start + 18))
        path_sectors = (struct.unpack_from("<I", pvd, 132)[0] + 2047) // 2048
        for offset, endian in ((140, "<"), (144, "<"), (148, ">"), (152, ">")):
            location = struct.unpack_from(endian + "I", pvd, offset)[0]
            if location and path_sectors:
                self.metadata_ranges.append((location, location + path_sectors))
        root = pvd[156:190]
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")

    def _parse_footer(self) -> list[dict]:
        mm, size = self._mm, len(self._mm)
        version, hoff = struct.unpack_from("<II", mm, size - 8)
        if version not in (0x80000004, 0x80000005, 0x80000006):
            raise ValueError(f"not a DiscJuggler image (version {version:#x})")
        off = size - hoff if version == 0x80000006 else hoff
        if not 0 <= off < size - 8:
            raise ValueError("CDI footer offset out of range")

        self._data_end = off

        def u(fmt):
            nonlocal off
            v = struct.unpack_from(fmt, mm, off)
            off += struct.calcsize(fmt)
            return v[0]

        tracks = []
        for _session in range(u("<H")):
            for _track in range(u("<H")):
                if u("<I"):
                    off += 8                            # extra data (DiscJuggler 3.00.780+)
                if mm[off:off + 10] != self._TRACK_MARK or mm[off + 10:off + 20] != self._TRACK_MARK:
                    raise ValueError("CDI track start mark missing")
                off += 20 + 4
                off += 1 + mm[off]                      # filename
                off += 11 + 4 + 4
                if u("<I") == 0x80000000:
                    off += 8                            # DiscJuggler 4
                off += 2
                pregap, length = u("<I"), u("<I")
                off += 6
                mode = u("<I")
                off += 12
                start_lba, total_length = u("<I"), u("<I")
                off += 16
                ss = self._SECTOR_SIZES.get(u("<I"))
                if ss is None or mode > 2 or not length or total_length < pregap + length:
                    raise ValueError("unsupported or inconsistent CDI track")
                off += 29
                if version != 0x80000004:
                    off += 5
                    if u("<I") == 0xFFFFFFFF:
                        off += 78                       # extra data (DiscJuggler 3.00.780+)
                tracks.append({"pregap": pregap, "length": length, "mode": mode, "start_lba": start_lba,
                               "total_length": total_length, "sector_size": ss})
            off += 4 + 8 + (1 if version != 0x80000004 else 0)     # end of session
        return tracks

    def _offset(self, lba: int) -> int:
        for start, length, file_off, ss in self._track_map:
            if start <= lba < start + length:
                off = file_off + (lba - start) * ss
                if off < 0 or off + 2048 > self._data_end:
                    raise ValueError("CDI user sector outside the image")
                return off
        raise ValueError(f"LBA {lba} not in any CDI data track")

    def sector(self, lba: int) -> bytes:
        off = self._offset(lba)
        return self._mm[off:off + 2048]

    def _walk(self, lba, size, prefix):
        if type(size) is not int or not 0 < size <= len(self._mm):
            raise ValueError("invalid CDI directory size")
        if lba in self._active_directories or len(self._active_directories) >= 128:
            raise ValueError("cyclic or excessive CDI directory depth")
        self.metadata_ranges.append((lba, lba + (size + 2047) // 2048))
        self._active_directories.add(lba)
        try:
            data = b"".join(self.sector(lba + i) for i in range((size + 2047) // 2048))[:size]
            o = 0
            while o < len(data):
                n = data[o]
                if n == 0:
                    o = (o // 2048 + 1) * 2048
                    continue
                if n < 34 or o + n > len(data) or o % 2048 + n > 2048:
                    raise ValueError("truncated CDI directory record")
                ext, ln = struct.unpack_from("<I", data, o + 2)[0], struct.unpack_from("<I", data, o + 10)[0]
                flags, nl = data[o + 25], data[o + 32]
                if not nl or nl > n - 33:
                    raise ValueError("invalid CDI directory filename")
                name = data[o + 33:o + 33 + nl].decode("latin-1").split(";")[0]
                if name not in ("\x00", "\x01"):
                    if flags & 2:
                        self._walk(ext, ln, f"{prefix}{name}/")
                    else:
                        self.files[f"{prefix}{name}"] = (ext, ln)
                        self.records[f"{prefix}{name}"] = (lba + o // 2048, o % 2048)
                o += n
        finally:
            self._active_directories.remove(lba)

    def read(self, name: str) -> bytes:
        lba, size = self.files[name]
        out = bytearray()
        for i in range((size + 2047) // 2048):
            out += self.sector(lba + i)
        return bytes(out[:size])


class GDRom:
    def __init__(self, gdi: str | Path):
        gdi = Path(gdi)
        if gdi.suffix.lower() == ".cdi":
            cdi = CDIRom(gdi)
            self.tracks = [(0, cdi.sector_size, gdi)]
            self._fh = {}
            self._mm = cdi._mm
            self.base = cdi.base
            self.sector_size = cdi.sector_size
            self.files, self.records = cdi.files, cdi.records
            self.metadata_ranges = cdi.metadata_ranges
            self._cdi = cdi
            return
        self._cdi = False
        lines = gdi.read_text().split("\n")[1:]
        self.tracks = []                        # (start_lba, sector_size, path)
        for ln in lines:
            parts = gdi_fields(ln)
            if len(parts) >= 6 and parts[2] == "4":
                self.tracks.append((int(parts[1]), int(parts[3]), gdi.parent / parts[4]))
        self.tracks.sort()
        self._fh = {}
        # the first high-density data track (LBA 45000) holds the volume descriptor; games with audio tracks in
        # between (Shenmue) continue the filesystem in a later data track, which sector() also reads
        hd = min((t for t in self.tracks if t[0] >= 45000), default=max(self.tracks))
        pvd = self.sector(hd[0] + 16)
        if pvd[1:6] != b"CD001":
            raise ValueError("no ISO9660 volume in the high-density area")
        root = pvd[156:156 + 34]
        self.metadata_ranges = [(hd[0], hd[0] + 18)]
        path_sectors = (struct.unpack_from('<I', pvd, 132)[0] + 2047) // 2048
        for offset, endian in ((140, '<'), (144, '<'), (148, '>'), (152, '>')):
            location = struct.unpack_from(endian + 'I', pvd, offset)[0]
            if location and path_sectors:
                self.metadata_ranges.append((location, location + path_sectors))
        self.files: dict[str, tuple[int, int]] = {}
        self.records: dict[str, tuple[int, int]] = {}  # file -> (LBA of its directory sector, record offset there)
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")

    def sector(self, lba: int) -> bytes:
        if self._cdi:
            off = self._cdi._offset(lba)
            return self._mm[off:off + 2048]
        for start, size, path in reversed(self.tracks):
            if lba >= start:
                f = self._fh.get(path) or self._fh.setdefault(path, open(path, "rb"))
                f.seek((lba - start) * size + (16 if size == 2352 else 0))
                return f.read(2048)
        raise ValueError(f"LBA {lba} not in a data track")

    def _walk(self, lba, size, prefix):
        self.metadata_ranges.append((lba, lba + (size + 2047) // 2048))
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


def patch_gdi(src_gdi: str | Path, out_dir: str | Path, name: str, files: dict[str, bytes], progress=None,
              donors: list[str] = (), *, reuse_modified_slack: bool = False) -> Path:
    """Copy a GDI to out_dir/<name>.gdi (unchanged tracks hard-linked, the last data track copied) with `files`
    rewritten in place when they fit their old sectors plus the free ones before the next file, else moved into
    the sectors of a `donors` file the mod gives up (its directory entry then points at the moved data too).
    Sectors after the last file are NOT used: Flycast crashes reading them. ISO9660 extent and size updated;
    EDC/ECC recomputed. Only the last data track is patched. With reuse_modified_slack,
    overflowing files relocate into shortened modified CHR/BIN tails, preserving
    all other files and ISO metadata. The complete plan is checked before copying."""
    import os
    import shutil
    src_gdi, out_dir = Path(src_gdi), Path(out_dir)
    if src_gdi.suffix.lower() != ".gdi":
        raise ValueError("Native disc writing requires a GDI with verified raw tracks; CDI support is read-only. "
                         "Supply an owned GDI extraction before building a replacement.")
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)   # GDI lines are whitespace-separated
    disc = GDRom(src_gdi)
    order = sorted(l for l, _s in disc.files.values())
    start, ssz, tpath = max(disc.tracks)
    plan = []
    spare = []                                                    # [lba, sectors] of donor files
    for dn in donors:
        l_, s_ = disc.files[dn]
        nxt = next((l for l in order if l > l_), None)
        spare.append([l_, (nxt - l_) if nxt else (s_ + 2047) // 2048])
    for key, data in files.items():
        if key not in disc.files:
            raise ValueError(f"{key} is not on this disc")
        lba, size = disc.files[key]
        if lba < start or disc.records[key][0] < start:
            raise ValueError(f"{key} isn't on the last data track; only that track is patched")
        if reuse_modified_slack:
            continue
        nxt = next((l for l in order if l > lba), None)
        room = (nxt - lba) if nxt else (size + 2047) // 2048
        need = (len(data) + 2047) // 2048
        if need > room:                                      # moved into a donor file's sectors
            sp = next((x for x in spare if x[1] >= need), None)
            if sp is None:
                raise ValueError(f"{key}: {len(data)} bytes need {need} sectors, only {room} free at LBA {lba} "
                                 f"(the original is {size} bytes)" + (" and no donor file is big enough" if donors else ""))
            lba, sp[0], sp[1] = sp[0], sp[0] + need, sp[1] - need
        plan.append((key, lba, data))
    if reuse_modified_slack:
        if donors:
            raise ValueError('Preserving modified slack cannot be combined with sacrificed donor files')
        from .gdrom_slack import plan_modified_slack
        planned = plan_modified_slack(disc.files, files, track_start=start,
                                     track_end=start + tpath.stat().st_size // ssz,
                                     reserved_ranges=disc.metadata_ranges)
        plan = [(row['file'], row['lba'], files[row['file']]) for row in planned['plan']]
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [ln for ln in src_gdi.read_text().splitlines() if ln.strip()]
    new_lines, dst_of = [lines[0]], {}
    for ln in lines[1:]:
        parts = gdi_fields(ln)
        src = src_gdi.parent / parts[4]
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
        parts[4] = f'"{dst.name}"' if any(c.isspace() for c in dst.name) else dst.name
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
            sec[doff + 2:doff + 6] = struct.pack("<I", lba)       # extent (moved files) + size, both byte orders
            sec[doff + 6:doff + 10] = struct.pack(">I", lba)
            sec[doff + 10:doff + 14] = struct.pack("<I", len(data))
            sec[doff + 14:doff + 18] = struct.pack(">I", len(data))
            put(dlba, bytes(sec))
        for dn in donors:                            # sacrificed donors: their sectors now hold moved data, so
            dlba, doff = disc.records[dn]            # zero their directory record so the mod no longer resolves them
            if dlba < start:
                continue
            f.seek((dlba - start) * ssz + (16 if ssz == 2352 else 0))
            sec = bytearray(f.read(2048))
            sec[doff:doff + sec[doff]] = b"\x00" * sec[doff]
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

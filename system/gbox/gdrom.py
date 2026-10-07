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
            o += n

    def read(self, name: str) -> bytes:
        lba, size = self.files[name]
        out = bytearray()
        for i in range((size + 2047) // 2048):
            out += self.sector(lba + i)
        return bytes(out[:size])


if __name__ == "__main__":
    import sys
    g = GDRom(sys.argv[1])
    print(len(g.files), "files")
    for k, (lba, s) in sorted(g.files.items()):
        if len(sys.argv) < 3 or sys.argv[2].lower() in k.lower():
            print(f"{s:10d}  {k}")

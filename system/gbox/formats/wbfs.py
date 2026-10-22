"""WBFS v1 reader: exposes the sparse WBFS container as a virtual, seekable Wii ISO (read-only).

Layout (big-endian): header at offset 0 = magic b"WBFS", u32 n_hd_sec, u8 hd_sec_shift, u8 wbfs_sec_shift,
2 pad bytes, disc_table[] (1 byte per disc, from 0x0C, nonzero = present). Disc 0 info lives at hd sector 1:
0x100-byte copy of the disc header, then u16 wlba_table[] mapping each wbfs sector of the ISO to a wbfs
sector in the container (0 = unallocated, reads as zeros). The whole file is never read into memory."""
from __future__ import annotations

import struct

WII_MAGIC = 0x5D1C9EA3


class WBFS:
    def __init__(self, path, disc: int = 0):
        self.path = str(path)
        self.fh = open(self.path, "rb")
        head = self.fh.read(0x200)
        if len(head) < 0x10 or head[:4] != b"WBFS":
            raise ValueError("not a WBFS image (magic 'WBFS' expected at offset 0)")
        self.n_hd_sec = struct.unpack_from(">I", head, 4)[0]
        self.hd_shift, self.sec_shift = head[8], head[9]
        if not (9 <= self.hd_shift <= 15) or not (15 <= self.sec_shift <= 30) or self.sec_shift < self.hd_shift:
            raise ValueError(f"implausible WBFS geometry hd_shift={self.hd_shift} sec_shift={self.sec_shift}")
        self.hd_sec = 1 << self.hd_shift
        self.sec_size = 1 << self.sec_shift
        self.n_sec = (self.n_hd_sec << self.hd_shift) >> self.sec_shift
        present = [i for i in range(min(self.hd_sec - 0x0C, 255)) if head[0x0C + i] and 0x0C + i < len(head)]
        if not present:
            raise ValueError("WBFS has no disc")
        if disc != 0:
            raise ValueError("only disc 0 of a WBFS image is supported")
        # a Wii disc spans at most 143432*2 sectors of 0x8000 bytes
        self.n_disc_sec = (143432 * 2 * 0x8000 + self.sec_size - 1) // self.sec_size
        self.fh.seek(self.hd_sec)
        info = self.fh.read(0x100 + self.n_disc_sec * 2)
        self.disc_header = info[:0x100]
        self.wlba = struct.unpack_from(f">{self.n_disc_sec}H", info, 0x100)
        if self.disc_header[0x18:0x1C] != struct.pack(">I", WII_MAGIC):
            raise ValueError("WBFS disc is not a Wii disc (0x5D1C9EA3 missing from the disc header copy)")
        self.game_id = self.disc_header[:6].decode("ascii", "replace")
        self.title = self.disc_header[0x20:0x60].split(b"\0")[0].decode("latin-1")
        used = [i for i, w in enumerate(self.wlba) if w]
        self.size = (used[-1] + 1) * self.sec_size if used else 0
        if any(w >= self.n_sec for w in self.wlba):
            raise ValueError("WBFS wlba entry beyond the container")

    def read(self, off: int, n: int) -> bytes:
        """Bytes [off, off+n) of the virtual ISO; unallocated sectors read as zeros."""
        if off < 0 or n < 0:
            raise ValueError("negative offset/length")
        out = bytearray()
        while n > 0:
            idx, inner = divmod(off, self.sec_size)
            take = min(n, self.sec_size - inner)
            w = self.wlba[idx] if idx < len(self.wlba) else 0
            if w:
                self.fh.seek(w * self.sec_size + inner)
                chunk = self.fh.read(take)
                chunk += b"\0" * (take - len(chunk))
            else:
                chunk = b"\0" * take
            out += chunk
            off += take
            n -= take
        return bytes(out)

    def partitions(self) -> list[dict]:
        """Wii partition table (groups at 0x40000): [{type, offset}] (type 0 data, 1 update, 2 channel)."""
        out = []
        groups = struct.unpack(">8I", self.read(0x40000, 32))
        for g in range(4):
            cnt, tab = groups[g * 2], groups[g * 2 + 1] << 2
            if not cnt or cnt > 32:
                continue
            for i in range(cnt):
                o, t = struct.unpack(">II", self.read(tab + i * 8, 8))
                out.append({"type": t, "offset": o << 2, "group": g})
        return out

    def close(self):
        self.fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def extract_iso(self, dest, chunk: int = 1 << 24) -> int:
        """Write the virtual ISO to dest (never the source dir). Returns bytes written."""
        done = 0
        with open(dest, "wb") as o:
            while done < self.size:
                b = self.read(done, min(chunk, self.size - done))
                o.write(b)
                done += len(b)
        return done

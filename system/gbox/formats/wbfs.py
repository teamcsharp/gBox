"""WBFS container (Wii backup file system) reader: header, sector map and logical disc reads, never writes.

Layout (big endian): 0 'WBFS', 4 u32 hd sector count, 8 u8 log2 hd sector size, 9 u8 log2 WBFS sector size,
0x0C disc table (1 byte per slot, non-zero = used). Disc slot 0 info sits at hd_sector_size: 0x100 bytes of the
disc header copy, then u16 wlba[] (WBFS sector index of each logical WBFS-sector; 0 = absent, reads as zeros).
The logical disc is the plain Wii disc (header with magic 0x5D1C9EA3 at 0x18, partition table at 0x40000);
partition data stays AES-encrypted, so this reader identifies the disc and its partitions but does not list files.
"""
from __future__ import annotations

import struct

WII_MAGIC = 0x5D1C9EA3
PART_TABLE_OFF = 0x40000
MAX_PARTITIONS = 16


class WBFS:
    def __init__(self, path, slot: int = 0):
        self.path = str(path)
        self._fh = open(path, "rb")
        try:
            self._parse(slot)
        except BaseException:
            self._fh.close()
            raise

    def close(self):
        self._fh.close()

    def _raw(self, off: int, n: int) -> bytes:
        self._fh.seek(off)
        return self._fh.read(n)

    def _parse(self, slot: int):
        h = self._raw(0, 0x0C)
        if len(h) < 0x0C or h[:4] != b"WBFS":
            raise ValueError("not a WBFS container (missing 'WBFS' magic)")
        self.hd_sectors = struct.unpack_from(">I", h, 4)[0]
        hd_s, wbfs_s = h[8], h[9]
        if not 9 <= hd_s <= 16 or not 15 <= wbfs_s <= 28:
            raise ValueError(f"implausible WBFS sector sizes 2^{hd_s} / 2^{wbfs_s}")
        self.hd_sector_size, self.wbfs_sector_size = 1 << hd_s, 1 << wbfs_s
        table = self._raw(0x0C, self.hd_sector_size - 0x0C)
        if not 0 <= slot < len(table) or not table[slot]:
            raise ValueError(f"WBFS disc slot {slot} is not in use")
        self.slot = slot
        self.used_slots = [i for i, b in enumerate(table) if b]
        # every slot's info block: header copy (0x100) + wlba table, sized to cover a dual-layer disc
        wii_secs = 143432 * 2
        n_wlba = -(-(wii_secs << 15) // self.wbfs_sector_size)
        info_size = 0x100 + n_wlba * 2
        info_sectors = -(-info_size // self.hd_sector_size)
        base = self.hd_sector_size * (1 + slot * info_sectors)
        blk = self._raw(base, info_size)
        if len(blk) < info_size:
            raise ValueError("truncated WBFS disc info block")
        self.header_copy = blk[:0x100]
        self.wlba = list(struct.unpack_from(f">{n_wlba}H", blk, 0x100))
        self.size = n_wlba * self.wbfs_sector_size
        if struct.unpack_from(">I", self.header_copy, 0x18)[0] != WII_MAGIC:
            raise ValueError("WBFS disc header copy lacks the Wii magic 0x5D1C9EA3")

    def read(self, off: int, n: int) -> bytes:
        """Logical disc bytes [off, off+n); absent WBFS sectors read as zeros; clamped to the disc extent."""
        if off < 0 or n < 0:
            raise ValueError("negative read")
        n = max(0, min(n, self.size - off))
        out = bytearray()
        s = self.wbfs_sector_size
        while n:
            idx, inner = divmod(off, s)
            take = min(n, s - inner)
            w = self.wlba[idx]
            out += self._raw(w * s + inner, take) if w else bytes(take)
            off += take
            n -= take
        return bytes(out)

    def disc_header(self) -> dict:
        h = self.read(0, 0x60)
        return {"game_id": h[:6].decode("ascii", "replace"), "disc_number": h[6], "revision": h[7],
                "title": h[0x20:0x60].split(b"\0")[0].decode("latin-1")}

    def partitions(self) -> list[dict]:
        """[{offset, type}] from the partition table groups at 0x40000 (offsets stored >>2). type 0 data, 1 update, 2 channel."""
        grp = self.read(PART_TABLE_OFF, 32)
        out = []
        for i in range(4):
            count, table_off = struct.unpack_from(">II", grp, i * 8)
            count = min(count, MAX_PARTITIONS)
            if not count or not table_off:
                continue
            ents = self.read(table_off << 2, count * 8)
            for j in range(count):
                off, typ = struct.unpack_from(">II", ents, j * 8)
                out.append({"offset": off << 2, "type": typ, "group": i})
        return out

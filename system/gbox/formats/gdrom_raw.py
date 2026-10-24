"""Reader for a raw 2352-byte-sector GD-ROM data image (chdman extractcd output of a Dreamcast CHD v5).

Sector s of the file holds 2048 user bytes at 2352*s+16. The low-density area is the first ``low_blocks`` file
sectors (its PVD sits at LBA 16 and declares the volume size); the high-density area starts at absolute LBA
45000 and its first file sector is ``low_blocks``. Verified on Jet Set Radio (Europe): 517085 sectors.
"""
from __future__ import annotations

import mmap
from typing import Callable

from . import iso9660

RAW = 2352
USER_OFFSET = 16
USER = 2048
HD_LBA = 45000


class RawGDRom:
    def __init__(self, path: str, low_blocks: int | None = None):
        self._fh = open(path, "rb")
        self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        if len(self._mm) % RAW:
            raise ValueError(f"{path}: size is not a multiple of {RAW}")
        self.sectors = len(self._mm) // RAW
        self.low_blocks = low_blocks if low_blocks is not None else iso9660.pvd_info(self.sector(16))["blocks"]

    def close(self) -> None:
        self._mm.close()
        self._fh.close()

    def file_sector(self, lba: int) -> int:
        return lba if lba < HD_LBA else self.low_blocks + (lba - HD_LBA)

    def sector(self, lba: int) -> bytes:
        s = self.file_sector(lba)
        if not 0 <= s < self.sectors:
            raise ValueError(f"LBA {lba} outside image")
        o = RAW * s + USER_OFFSET
        return self._mm[o:o + USER]

    def read(self, lba: int, size: int) -> bytes:
        return iso9660.sector_reader(self.sector)(lba, size)[:size]

    def hd_root(self) -> tuple[int, int]:
        return iso9660.pvd_root(self.sector(HD_LBA + 16))

    def files(self) -> dict[str, tuple[int, int]]:
        lba, size = self.hd_root()
        return iso9660.files(self.read, lba, size, max_depth=16, max_dir_size=1 << 22)

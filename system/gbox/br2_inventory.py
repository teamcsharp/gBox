"""Bloody Roar II (PSX, Raizing/Eighting) owned-disc inventory: MODE2/2352 .bin -> ISO9660 file table, SLPS EXE,
per-character container probe. Read-only; reuses gbox.formats.iso9660. Source identity is the streamed .bin SHA256.

Observed layout (JP SLPS_01842 build; one directory per character, e.g. LON/):
  <C>.ACT, <C>1P..4P.ANI (animation), <C>1P..4P.DAT (model/texture, 1P-4P = costume variants), <C>EFT.DAT,
  CHARA_nn.SND / GOVER_nn.SND. DAT header: u32 count(=9), u32 0, then 8 ascending u32 section offsets (<= file size; 0xFFFFFFFF = slot absent, e.g. ALI/JEN).
"""
from __future__ import annotations

import hashlib
import struct
from typing import Callable

from gbox.formats import iso9660

RAW, USER_OFF, SECTOR = 2352, 24, 2048   # MODE2/2352 Form1 user data at +24
CHAR_DIRS = {"ALI": "ALI", "BAK": "BAK", "BUS": "BUS", "GAD": "GAD", "JEN": "JEN", "LON": "LON", "MAR": "MAR",
             "RON": "RON", "ULI": "ULI", "YUG": "YUG"}


def raw_sector_reader(fh) -> Callable[[int], bytes]:
    def sec(lba: int) -> bytes:
        fh.seek(lba * RAW + USER_OFF)
        return fh.read(SECTOR)
    return sec


def file_table(sec: Callable[[int], bytes]) -> dict[str, tuple[int, int]]:
    pvd = sec(16)
    lba, size = iso9660.pvd_root(pvd)
    read = iso9660.sector_reader(sec)
    return iso9660.files(read, lba, size)


def read_file(sec, lba: int, size: int) -> bytes:
    return b"".join(sec(lba + i) for i in range((size + SECTOR - 1) // SECTOR))[:size]


def dat_offsets(buf: bytes) -> list[int | None]:
    """8 section offsets of a <C>nP.DAT (0xFFFFFFFF = absent slot -> None); present ones must ascend, be >= 0x34 and
    <= file size. Raises ValueError otherwise."""
    if len(buf) < 0x34:
        raise ValueError("too short")
    w = struct.unpack_from("<13I", buf, 0)
    if w[0] != 9 or w[1] != 0:
        raise ValueError("unexpected DAT header")
    offs = [None if x == 0xFFFFFFFF else x for x in w[2:10]]
    present = [x for x in offs if x is not None]
    if present != sorted(present) or not present or present[-1] > len(buf) or present[0] < 0x34:
        raise ValueError("DAT offsets not ascending/in range")
    return offs


def exe_info(exe: bytes) -> dict:
    if exe[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    pc, gp, dest, size = struct.unpack_from("<4I", exe, 0x10)
    return {"pc": pc, "dest": dest, "text_size": size, "sha256": hashlib.sha256(exe).hexdigest()}

"""Tetris (PSP, game 25da54968d78f816) EBOOT.BIN ~PSP header parser.

EBOOT.BIN is the real main executable on retail discs (BOOT.BIN is zeroed).
A 0x150-byte ~PSP v2 header (plaintext) wraps a KIRK-encrypted body.
Layout per sp00nznet/psprecomp docs/CONTAINERS.md + docs/DECRYPT.md (key tag
at 0xD0, NOT the misreported 0x130) and psdevwiki PRX_File_Format.

Decryption (mode 9) requires KIRK CMD1 plus the per-tag key set derived from
tag@0xD0 (psprecomp "phase 2b"); the body stays encrypted until that key
material is supplied.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import asdict, dataclass

from gbox.tetris_psp_inventory import CisoReader, SECTOR, walk_iso

HEADER_SIZE = 0x150
BODY_OFFSET = HEADER_SIZE
EBOOT_PATH = "/PSP_GAME/SYSDIR/EBOOT.BIN"


@dataclass
class EbootHeader:
    magic: str
    attrs: int
    compression: int
    name: str
    segments: int
    elf_size: int
    file_size: int
    entry: int
    module_info_off: int
    bss_size: int
    seg_addrs: tuple
    seg_sizes: tuple
    devkit: int
    decrypt_mode: int
    tag: int


def parse_eboot_header(data: bytes) -> EbootHeader:
    if len(data) < HEADER_SIZE:
        raise ValueError("EBOOT.BIN too small for ~PSP header: %d" % len(data))
    if data[:4] != b"~PSP":
        raise ValueError("bad ~PSP magic: %r" % (data[:4],))
    attrs, comp = struct.unpack_from("<HH", data, 4)
    name = data[0x0A:0x26].split(b"\0", 1)[0].decode("ascii", "replace")
    segments, elf_size, file_size = struct.unpack_from("<BII", data, 0x27)
    entry, info_off, bss = struct.unpack_from("<III", data, 0x30)
    seg_addrs = struct.unpack_from("<4I", data, 0x44)
    seg_sizes = struct.unpack_from("<4I", data, 0x54)
    (devkit,) = struct.unpack_from("<I", data, 0x78)
    (decrypt_mode,) = struct.unpack_from("<H", data, 0x7C)
    (tag,) = struct.unpack_from("<I", data, 0xD0)
    return EbootHeader(
        magic="~PSP", attrs=attrs, compression=comp, name=name,
        segments=segments, elf_size=elf_size, file_size=file_size,
        entry=entry, module_info_off=info_off, bss_size=bss,
        seg_addrs=seg_addrs, seg_sizes=seg_sizes,
        devkit=devkit, decrypt_mode=decrypt_mode, tag=tag,
    )


def extract_eboot(ciso_path, path=EBOOT_PATH) -> bytes:
    rd = CisoReader(ciso_path)
    try:
        by = {e.path: e for e in walk_iso(rd) if not e.is_dir}
        e = by[path]
        return rd.read(e.lba * SECTOR, e.size)
    finally:
        rd.close()


def eboot_report(ciso_path, path=EBOOT_PATH) -> dict:
    rd = CisoReader(ciso_path)
    try:
        by = {e.path: e for e in walk_iso(rd) if not e.is_dir}
        e = by[path]
        data = rd.read(e.lba * SECTOR, e.size)
    finally:
        rd.close()
    rep = asdict(parse_eboot_header(data))
    rep.update(
        path=e.path,
        lba=e.lba,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        body_offset=BODY_OFFSET,
        body_is_plaintext_elf=data[BODY_OFFSET:BODY_OFFSET + 4] == b"\x7fELF",
    )
    return rep

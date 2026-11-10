"""Bounded probe of the Dead or Alive (USA, PSX) boot-executable CD loader.

Evidence (SLUS_006.06, PS-X EXE, text 0x80010000 size 0x84800, pc0 0x80010e44),
derived by disassembling the text image (Ghidra raw import MIPS:LE:32 + capstone):
  * 0x8004c320 holds the C string "\\PS_DOA.BIN;1" (0x8004c321 is the byte after
    the backslash). BSS is cleared up to 0x8004c320 by the entry stub, so the
    string lies at the end of .data.
  * The only code that loads it is the loader FUN_8004c53c, called from the
    main startup routine 0x8004c480. It copies the 15-byte path to sp+0x10 and
    runs a 6-state machine (jump table 0x8004c330, state in halfword STATE_VAR):
      0 CdControl setup, 1 poll+advance, 2 CdSearchFile(0x80051578, path), 3 wait,
      4 sync, 5 CdRead(0x80-sector chunks -> 0x80067ab0) + CdReadSync (hypothesis: names of BIOS-wrapper calls inferred from arg shapes).
    Sector count = (CdlFILE.size + 0x7ff) >> 11 (CdlFILE at 0x80051578, size at +4).
"""
import struct

TEXT_BASE = 0x80010000
HEADER = 0x800
PATH_ADDR = 0x8004C320
LOADER_FUNC = 0x8004C53C
LOADER_CALLER = 0x8004C480
STATE_TABLE = 0x8004C330
STATE_VAR = 0x80068B1A  # lui 0x8007; sh v0,-0x74e6
CDLFILE_ADDR = 0x80051578
READ_BUF = 0x80067AB0
READ_CHUNK_SECTORS = 0x80


def parse_psx_exe(data: bytes) -> dict:
    if data[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    pc, gp, addr, size = struct.unpack_from("<4I", data, 0x10)
    return {"pc0": pc, "gp": gp, "text_addr": addr, "text_size": size}


def text_image(data: bytes) -> bytes:
    info = parse_psx_exe(data)
    return data[HEADER:HEADER + info["text_size"]]


def read_cstr(img: bytes, addr: int, base: int = TEXT_BASE) -> bytes:
    o = addr - base
    return img[o:img.index(b"\0", o)]


def loader_path(img: bytes) -> bytes:
    return read_cstr(img, PATH_ADDR)


def state_handlers(img: bytes) -> list:
    o = STATE_TABLE - TEXT_BASE
    return list(struct.unpack_from("<6I", img, o))


def data_refs(img: bytes, target: int, window: int = 8) -> list:
    """Return (lui_addr, use_addr) pairs materialising `target` via lui+addiu."""
    n = len(img) // 4
    w = struct.unpack("<%dI" % n, img[:n * 4])
    hi = (target + 0x8000) >> 16 & 0xFFFF
    lo = target & 0xFFFF
    lo_s = lo - 0x10000 if lo >= 0x8000 else lo
    out = []
    for i, x in enumerate(w):
        if x >> 26 == 0xF and (x & 0xFFFF) == hi:
            rt = (x >> 16) & 31
            for j in range(i + 1, min(i + window, n)):
                y = w[j]
                if y >> 26 == 9 and (y >> 21) & 31 == rt and (y & 0xFFFF) == lo:
                    out.append((TEXT_BASE + i * 4, TEXT_BASE + j * 4))
    return out


def sectors_for(size: int) -> int:
    return (size + 0x7FF) >> 11

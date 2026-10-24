"""WWF War Zone (USA) N64 boot loader + compressed main image (analysis stage 2).

CORRECTS gbox.warzone_analysis: the ROM is NOT mapped at 0x80000000 and the
"name bank refs" at 0x1D1E44.. etc. are coincidental bytes inside
high-entropy data, not code.  Real layout (exact owned build, normalized z64
sha256 ee4f5a036423b78449475fa09471de6148ff6972d0510098943bc83092f990b5):

* IPL3 copies ROM 0x1000.. to 0x80000400 (entry 0x80000400 = ``j 0x80000430``).
* The boot stub header lives at ROM 0x1010 (virtual 0x80000410):
  +0x00 ROM src start (cart 0xB0xxxxxx) +0x04 ROM src end +0x08 decompress dest
  +0x0C main entry +0x10 compressed flag +0x18/0x1C bss start/end.
  This build: src 0xB8E9E0..0xBF5031, dest 0x8003C400, entry 0x800E4050,
  flag 1, bss 0x8012A1C0..0x801A43E0.
* Stub: PI-DMA (0x800004D4) the blob to 0x80300000, then a Huffman+LZ
  decompressor (0x80000540 -> 0x80000608) expands it to the dest.
* Result: 0xEDDBC non-zero bytes of game code/data (real MIPS at the entry).
  Roster records live inside this image at 0x80109D80, stride 0x90:
  first name[14], last name[14], nickname at +0x1C (NUL padded).

The decompressor is run through a Unicorn MIPS emulator as a routine oracle
(no re-implementation, so output is exactly the game's own).
"""
from __future__ import annotations

import hashlib
import struct

STUB_HDR = 0x1010
STUB_CODE_END = 0x101000
SCRATCH = 0x80300000
ROSTER_BASE = 0x80109D80
ROSTER_STRIDE = 0x90


def boot_header(rom: bytes) -> dict:
    v = struct.unpack(">11I", rom[STUB_HDR:STUB_HDR + 44])
    return {
        "rom_start": v[0] & 0xFFFFFF, "rom_end": v[1] & 0xFFFFFF,
        "dest": v[2], "entry": v[3], "compressed": v[4],
        "bss_start": v[6], "bss_end": v[7],
    }


def decompress_main(rom: bytes) -> tuple[bytes, dict]:
    """Run the game's own decompressor; return (image, header)."""
    from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_BIG_ENDIAN
    from unicorn.mips_const import UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_RA, UC_MIPS_REG_SP
    h = boot_header(rom)
    mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_BIG_ENDIAN)
    mu.mem_map(0, 0x800000)           # kseg0 0x80000000 -> physical 0
    mu.mem_write(0x400, rom[0x1000:STUB_CODE_END])
    mu.mem_write(SCRATCH & 0xFFFFFF, rom[h["rom_start"]:h["rom_end"]])
    sent = 0x80000300
    mu.reg_write(UC_MIPS_REG_A0, SCRATCH)
    mu.reg_write(UC_MIPS_REG_A1, h["dest"])
    mu.reg_write(UC_MIPS_REG_SP, 0x803FFE00)
    mu.reg_write(UC_MIPS_REG_RA, sent)
    mu.emu_start(0x80000540, sent, count=400_000_000)
    lo = h["dest"] & 0xFFFFFF
    mem = bytes(mu.mem_read(lo, h["bss_start"] - h["dest"]))
    return mem.rstrip(b"\0"), h


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin-1")


def roster(image: bytes, dest: int, slots: int = 19) -> list[dict]:
    out = []
    for i in range(slots):
        o = ROSTER_BASE - dest + i * ROSTER_STRIDE
        r = image[o:o + ROSTER_STRIDE]
        if len(r) < ROSTER_STRIDE:
            break
        first, last, nick = _cstr(r[0:14]), _cstr(r[14:28]), _cstr(r[28:44])
        if (first or last or nick) and (first + last + nick).isprintable():
            out.append({"slot": i, "vaddr": ROSTER_BASE + i * ROSTER_STRIDE,
                        "first": first, "last": last, "nick": nick})
    return out


def probe(rom: bytes) -> dict:
    img, h = decompress_main(rom)
    return {"header": {k: hex(v) if k != "compressed" else v for k, v in h.items()},
            "image_len": len(img), "image_sha256": hashlib.sha256(img).hexdigest(),
            "roster": roster(img, h["dest"])}

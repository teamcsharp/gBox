"""WWF War Zone (USA, NWWE) N64 -- resource-handle / ROM asset table probe.

Evidence (decompressed main image, base 0x8003C400, see gbox.warzone_boot):
  * 0x80041944  handle -> pointer resolver.  Handle layout:
        bits 31..27  type   (2 = ROM table entry, 7 = name-keyed resource)
        bits 26..16  index  (11 bit, bound at [0x801132D0], cache at 0x8012D060)
        bits 15..9   sub-index (7 bit)
  * 0x80042AB8  type-2 loader.  A hard-coded compare chain maps 27 handles to
        (cart address, byte size); the data is DMA'd by 0x800420A0 into a
        buffer from 0x8003D0E0 (size rounded up to even).
  * 0x80042E8C  type-7 loader: walks a pointer table of lower-case/digit/'_'/'-'
        resource names, opens each via 0x8004237C.

Only the type-2 chain is decoded here (pure word-pattern scan, no
disassembler).  Cart address 0xB0xxxxxx -> ROM offset = addr & 0x0FFFFFFF.
Field meaning beyond (id, offset, size) is NOT claimed.
"""
from __future__ import annotations

import struct

IMAGE_BASE = 0x8003C400
TYPE2_LOADER = 0x80042AB8
TYPE2_LOADER_END = 0x80042E30   # shared DMA tail ("bnez s2")


def _s16(x: int) -> int:
    return x - 0x10000 if x & 0x8000 else x


def handle_fields(h: int) -> dict:
    return {"type": h >> 27, "index": (h >> 16) & 0x7FF, "sub": (h >> 9) & 0x7F}


def parse_type2_table(image: bytes, base: int = IMAGE_BASE) -> list[dict]:
    """Decode the compare chain in the type-2 loader.

    Per entry the compiler emitted (MIPS-BE):
        bne a0,v0,next ; lui v0,<next id hi>        (delay slot)
        lui v0,<cart hi> ; addiu s2,v0,<cart lo>
        lui v0,<size hi> ; j tail ; addiu s1,v0,<size lo>
        next: addiu v0,v0,<id lo>
    """
    lo, hi = TYPE2_LOADER - base, TYPE2_LOADER_END - base
    words = struct.unpack(f">{(hi - lo) // 4}I", image[lo:hi])
    ids: list[int] = []
    cart: list[int] = []
    size: list[int] = []
    last_lui_v0 = 0
    tgt_v0 = None            # v0 loaded in a bne delay slot (visible at the branch target)
    prev_bne = False
    for w in words:
        op = w >> 26
        rs, rt, imm = (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 0x0F and rt == 2:                       # lui v0
            last_lui_v0 = imm << 16
            if prev_bne:
                tgt_v0 = last_lui_v0
        elif op == 0x09 and rs == 2 and rt == 2:         # addiu v0,v0,lo -> next compare id
            base = tgt_v0 if tgt_v0 is not None else last_lui_v0
            ids.append((base + _s16(imm)) & 0xFFFFFFFF)
            tgt_v0 = None
        elif op == 0x09 and rs == 2 and rt == 18:        # addiu s2,v0 -> cart
            cart.append((last_lui_v0 + _s16(imm)) & 0xFFFFFFFF)
        elif op == 0x09 and rs == 2 and rt == 17:        # addiu s1,v0 -> size
            size.append((last_lui_v0 + _s16(imm)) & 0xFFFFFFFF)
        prev_bne = op == 0x05                            # bne
    n = min(len(cart), len(size))
    out = []
    for i in range(n):
        out.append({"handle": ids[i], **handle_fields(ids[i]),
                    "cart": cart[i], "rom_offset": cart[i] & 0x0FFFFFFF,
                    "size": size[i]})
    return out


def read_entry(rom: bytes, entry: dict) -> bytes:
    o = entry["rom_offset"]
    return rom[o:o + entry["size"]]

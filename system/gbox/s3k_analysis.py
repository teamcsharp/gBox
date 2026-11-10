"""Analysis-stage probe for the S3K+S&K (World) Tails loader, game_id ed2bef5be2826deb.

Reproducible, ROM-only: (1) scans the flat 68k image for absolute-long references to every table the inventory
manifest names and decodes the instruction that carries each reference (capstone M68K), (2) disassembles Tails'
Perform_Player_DPLC loader window and proves which DPLC table / art banks / bank-switch frame it uses, (3) derives
the writer constraints the coupled art+DPLC+mappings tables impose on a donor sprite set.
Hypotheses are labelled; only the decoded instructions and parsed tables are facts.
"""
from __future__ import annotations

import json
import struct
import sys

from . import s3k_inventory as inv
from . import sonic2d_sprites as s2d

SLOT = "tails"


def find_xrefs(d: bytes, value: int, limit: int = 32) -> list[int]:
    pat, out, i = struct.pack(">I", value), [], d.find(struct.pack(">I", value))
    while i >= 0 and len(out) < limit:
        out.append(i)
        i = d.find(pat, i + 1)
    return out


def disasm(d: bytes, start: int, length: int) -> list[dict]:
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000 | capstone.CS_MODE_BIG_ENDIAN)
    return [{"addr": i.address, "bytes": i.bytes.hex(), "text": f"{i.mnemonic} {i.op_str}".strip()}
            for i in md.disasm(d[start:start + length], start)]


def instr_at_xref(d: bytes, ref: int) -> dict | None:
    """The abs.l operand sits at the end of a 6-byte lea/move.l/pea; opcode word is at ref-2."""
    for back in (2, 4):
        ins = disasm(d, ref - back, 8)
        for i in ins:
            if i["addr"] + len(i["bytes"]) // 2 > ref + 3 and i["addr"] <= ref - 2:
                return i
    return None


def analyse(src=inv.DEFAULT_SRC, character: str = SLOT) -> dict:
    d, _ = s2d.read_rom(src)
    ident = inv.stream_hashes(src)
    ex = s2d.Extractor(d, {"member": ident["container"]["member"], "size": len(d)})
    ch = ex.chars[character]
    tables = {"dplc": ch.plc, "art_main": ch.art, "art_extra": ch.extra_art, "mappings": ch.maps_off, "anim": ch.anim}
    xrefs = {}
    for k, v in tables.items():
        if v is None:
            continue
        xrefs[k] = [{"ref_at": r, "insn": instr_at_xref(d, r)} for r in find_xrefs(d, v, 12)]
    code = disasm(d, ch.loader - 0x20, 0x90)
    tiles_per_frame = [sum(n for _, n in fr) for fr in ch.dplc]
    pieces = [len(m) for m in ch.maps]
    art_end_main = ch.art + 0x20 * (max(first + n for fr in ch.dplc[:ch.extra_from or len(ch.dplc)] for first, n in fr) if ch.dplc else 0)
    return {
        "game_id": inv.GAME_ID, "source_sha256": ident["sha256"], "character": character,
        "tables": tables, "loader_routine": ch.loader, "xrefs": xrefs, "loader_disasm": code,
        "dplc_frames": len(ch.dplc), "max_tiles_per_frame": max(tiles_per_frame),
        "max_pieces_per_frame": max(pieces), "bank_switch_frame": ch.extra_from,
        "main_bank_art_bytes_used": art_end_main - ch.art,
        "writer_constraints": {
            "coupled": ["art (4bpp 8x8, 32 B/tile)", "DPLC (per-frame (first,count) runs)", "mappings (pieces index VRAM tile = player art base + n)", "palette line"],
            "dma_budget_tiles_per_frame": max(tiles_per_frame),
            "hypothesis": "a donor frame must fit mapping pieces + DPLC runs of the slot's frame; art bank switch at frame index bank_switch_frame (hypothesis: cmpi.w on frame*2)",
        },
    }


if __name__ == "__main__":
    print(json.dumps(analyse(sys.argv[1] if len(sys.argv) > 1 else inv.DEFAULT_SRC), indent=1, default=str))

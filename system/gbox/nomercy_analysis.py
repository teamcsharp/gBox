"""WWF No Mercy (USA) Rev A (NW4E rev 1) analysis probe (#1329): the asset loaders, the decompressor and the
character texture rules that the reader and writer depend on, pinned to instruction words of the exact owned build.

Evidence: the Oct 7 RDRAM-image Ghidra project ~/gBox_alt/gbox-cache/aki_re/ghidra/proj.gpr (program nm_ram4.bin,
MIPS:BE:32:default, 2156 functions), re-read on Oct 12 with a read-only headless script (function entries, sizes,
callers, callees and disassembly). The 2530 instructions of the functions below that lie in the main code segment
are byte-identical to the owned ROM (RAM 0x80000400 = ROM 0x1000), so the project describes this build.

  * 0x80026888 (boot init) calls 0x80003AB0, which DMAs (0x8000062C) the 0x1300C-byte AkiFileTable from ROM
    0x16C31D8 into the heap (0x800007D4) and precomputes 0x4C02 file sizes (a packed file's size is its 4-byte LZSS
    header). 0x80003BD0 resolves a file id (it hangs on id 0 or > 0x4C02; 27 call sites). 0x80003C94 loads a file
    (38 call sites): a plain file is DMA'd, a packed one is DMA'd to a temp buffer and expanded by the Asmik LZSS
    decoder 0x80003D64 (only caller 0x80003C94).
  * 0x800148F0 (slot, costume) calls the part-list builder 0x80018A3C at 0x8001495C. The builder's neck entry
    (+0x20) is always model 0x14FF with texture 0x1F6A; its palette is 0x1F6B when the body class
    (u16 0x80048A48[body type]) is below 6, else 0x1F6D. The head-back entry (+0x28) takes texture 0x1F6C / 0x1F6E
    with the same palettes, and its model comes from the hair tables 0x8004913C (class < 6) / 0x80049148.
  * The model texture loaders 0x8000D688 and 0x8000E784 read texture header byte 2 (the high byte of the u16
    colour count): == 1 selects CI8 with a 256-colour LOADTLUT (0x073FC000) and SETTILE 0xF548; anything else
    selects CI4 with a 16-colour LOADTLUT (0x0703C000) from the palette file's first 16 entries and SETTILE 0xF540
    on palette 0. A CI4 header count of 32 (the neck 0x1F6A) is therefore not a bank selector.

  python -m gbox.nomercy_analysis ROM [--out probe.json]
"""
from __future__ import annotations

import argparse
import collections
import json
import struct
import zipfile
from pathlib import Path

import numpy as np

from . import aki_wrestling as A

FUNCTIONS = {                       # RAM entry -> (role, Ghidra body size in bytes)
    0x80026888: ("boot init; calls the file-table load", 812),
    0x80003AB0: ("AkiFileTable load: DMA 0x1300C B from ROM 0x16C31D8, precompute 0x4C02 sizes", 288),
    0x80003BD0: ("file id -> rom start, rom end, size, packed size", 196),
    0x80003C94: ("load a file: DMA, or DMA + LZSS 0x80003D64 + free", 208),
    0x80003D64: ("Asmik LZSS decompressor", 300),
    0x8000062C: ("PI DMA ROM -> RAM", 240),
    0x800007D4: ("heap alloc", 44),
    0x8000093C: ("heap free", 24),
    0x800148F0: ("(slot, costume) wrestler setup", 1164),
    0x80018A3C: ("costume -> 0x270-byte part list", 2836),
    0x800186D4: ("body-class part row + skin palettes", 220),
    0x8000D688: ("model texture + palette loader (CI8/CI4)", 1704),
    0x8000E784: ("second texture loader, same CI8/CI4 rule", 1708),
    0x8000C674: ("palette post-process when 0x80047EB0 == 1", 376),
}

SITES = [                           # (RAM address, instruction word, meaning)
    (0x80003ADC, 0x3C04016C, "lui a0,0x16c: file table ROM offset (high)"),
    (0x80003AE0, 0x248431D8, "addiu a0,a0,0x31d8: file table at ROM 0x16C31D8"),
    (0x80003B98, 0x2E424C02, "sltiu v0,s2,0x4c02: size precompute over 0x4C02 files"),
    (0x80003CF0, 0x0C000F59, "jal 0x80003d64: expand a packed file"),
    (0x8001495C, 0x0C00628F, "jal 0x80018a3c: build the slot's part list"),
    (0x8000D844, 0x90430002, "lbu v1,0x2(v0): texture header byte 2"),
    (0x8000D848, 0x24020001, "li v0,0x1"),
    (0x8000D84C, 0x10620092, "beq v1,v0,0x8000da98: == 1 -> CI8, else CI4"),
    (0x8000D884, 0x3C0C0703, "lui t4,0x703: CI4 LOADTLUT 0x0703C000 (16 colours)"),
    (0x8000D888, 0x358CC000, "ori t4,t4,0xc000"),
    (0x8000DA64, 0x3C02F540, "lui v0,0xf540: CI4 SETTILE, palette 0"),
    (0x8000DAC8, 0x3C0C073F, "lui t4,0x73f: CI8 LOADTLUT 0x073FC000 (256 colours)"),
    (0x8000DCA8, 0x3C02F548, "lui v0,0xf548: CI8 SETTILE"),
    (0x8000E928, 0x90430002, "lbu v1,0x2(v0): same rule in 0x8000E784"),
    (0x8000E92C, 0x24020001, "li v0,0x1"),
    (0x8000E930, 0x10620092, "beq v1,v0,0x8000eb7c"),
    (0x80018C7C, 0x240214FF, "li v0,0x14ff: neck model"),
    (0x80018C84, 0x24021F6A, "li v0,0x1f6a: neck texture"),
    (0x80018C88, 0x2A100006, "slti s0,s0,0x6: body class < 6"),
    (0x80018C98, 0x24021F6B, "li v0,0x1f6b: neck palette, class < 6"),
    (0x80018C9C, 0x24021F6D, "li v0,0x1f6d: neck palette, class >= 6"),
    (0x80018CAC, 0x28420006, "slti v0,v0,0x6"),
    (0x80018CB4, 0x24021F6B, "li v0,0x1f6b: head-back palette, class < 6"),
    (0x80018CC0, 0x24021F6C, "li v0,0x1f6c: head-back texture, class < 6"),
    (0x80018CC4, 0x24021F6D, "li v0,0x1f6d: head-back palette, class >= 6"),
    (0x80018CCC, 0x24021F6E, "li v0,0x1f6e: head-back texture, class >= 6"),
]

NECK_MODEL, NECK_TEX = 0x14FF, 0x1F6A
HEAD_BACK = {False: (0x1F6C, 0x1F6B), True: (0x1F6E, 0x1F6D)}      # class >= 6 -> (texture, palette)


def load_rom(path) -> bytes:
    """A z64/v64/n64 file, or a zip holding one, -> big-endian z64 bytes."""
    p = Path(path)
    if p.suffix.lower() != ".zip":
        return A.rom_bytes(p)
    with zipfile.ZipFile(p) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".z64", ".n64", ".v64"))]
        if len(names) != 1:
            raise ValueError(f"{p.name}: expected one N64 ROM member, found {names}")
        d = z.read(names[0])
    head = d[:4]
    if head == b"\x80\x37\x12\x40":
        return d
    if head == b"\x37\x80\x40\x12":                                      # v64: 16-bit byte swapped
        return np.frombuffer(d, np.uint16).byteswap().tobytes()
    if head == b"\x40\x12\x37\x80":                                      # n64: little-endian words
        return np.frombuffer(d, np.uint32).byteswap().tobytes()
    raise ValueError(f"{names[0]}: not an N64 ROM (first word {head.hex()})")


def check_sites(rom: bytes) -> dict:
    """Each pinned instruction word at its ROM offset -> {checked, mismatches [...]}; empty mismatches = this build."""
    bad = []
    for ram, word, what in SITES:
        got = struct.unpack_from(">I", rom, A._ram2rom(ram))[0]
        if got != word:
            bad.append({"ram": f"0x{ram:08X}", "expected": f"0x{word:08X}", "found": f"0x{got:08X}", "site": what})
    return {"checked": len(SITES), "mismatches": bad}


def body_class(rom: bytes, body_type: int) -> int:
    return A.body_parts(rom, body_type)[1]


def texture_survey(rom: bytes) -> dict:
    """Every texture the static part lists use (all 65 x 4 costumes) plus the head-back textures, classified by the
    game's own rule and decoded."""
    ft = A.FileTable(rom)
    pairs, classes = collections.Counter(), collections.Counter()
    for k, c in enumerate(A.costumes(rom, ft)):
        classes[body_class(rom, c[0]) >= 6] += 1
        for _o, (_m, t, p) in A.part_list_static(rom, k // 4 + 1, k % 4).items():
            if t and p:
                pairs[(t, p)] += 1
    for t, p in HEAD_BACK.values():
        pairs[(t, p)] += 0
    fmt, fails, ci4 = collections.Counter(), [], []
    for t, p in sorted(pairs):
        tex, pal = ft.get(t), ft.get(p)
        try:
            f = A.tex_format(tex)
            img = A.tex_decode(tex, pal)
        except ValueError as e:
            fails.append({"texture": f"0x{t:04X}", "palette": f"0x{p:04X}", "error": str(e)})
            continue
        fmt[f] += 1
        if f == "ci4":
            u = np.unique(img.reshape(-1, 4), axis=0)
            ci4.append({"texture": f"0x{t:04X}", "palette": f"0x{p:04X}", "size": [int(tex[0]) + 1, int(tex[1]) + 1],
                        "header_colours": struct.unpack_from(">H", tex, 2)[0], "bytes": len(tex),
                        "mirror": [tex[4], tex[5]], "colours_used": len(u), "first_colour": img[0, 0].tolist()})
    return {"pairs": len(pairs), "textures": len({t for t, _ in pairs}), "palettes": len({p for _, p in pairs}),
            "formats": dict(fmt), "decode_failures": fails, "ci4": ci4,
            "costumes_class_ge6": classes[True], "costumes_class_lt6": classes[False]}


def probe(rom: bytes) -> dict:
    return {"profile": {k: (f"0x{v:X}" if isinstance(v, int) and not isinstance(v, bool) else v)
                        for k, v in A.profile(rom).items()},
            "functions": {f"0x{a:08X}": {"role": r, "size": n} for a, (r, n) in FUNCTIONS.items()},
            "sites": check_sites(rom), "textures": texture_survey(rom),
            "rule": "texture header byte 2 == 1 -> CI8/256-colour TLUT, else CI4/16-colour TLUT (palette entries 0-15)"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.nomercy_analysis")
    ap.add_argument("rom")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res = probe(load_rom(a.rom))
    text = json.dumps(res, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps({"sites": res["sites"], "formats": res["textures"]["formats"], "ci4": res["textures"]["ci4"],
                      "decode_failures": len(res["textures"]["decode_failures"])}, indent=1))
    return 0 if not res["sites"]["mismatches"] and not res["textures"]["decode_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

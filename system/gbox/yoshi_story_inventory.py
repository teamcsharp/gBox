"""Owned-source inventory for Yoshi's Story (N64, USA "NYSE" rev 0).

The catalog entry is a zip holding a ``.n64`` (word-swapped) dump.  This
module never changes the owned file: it reads it through ``n64_rom.read``,
identifies the exact build and maps the cartridge layout that later
reader/writer stages need.

Facts established on the owned ROM (#1323):

* normalized z64 md5 ``586a092e22604840973b82dfaceac77a`` equals the
  decompals/yoshis-story ``baseroms/us/checksum.md5`` build, so that
  project's segment map (makerom 0x0-0x1070, ``main`` code at ROM 0x1070 /
  VRAM 0x80000470, unsplit ``unkbin`` from 0xB58B0) applies to this file;
* only bootproc and ``Overlay_Load`` call ``DmaMgr_RequestSync`` and only the
  DMA manager calls ``osPiStartDma``: asset requests go through the DMA
  manager message queue, not direct PI calls;
* characters are pre-rendered 2D sprites: each animation frame is a
  0x400-aligned record of quad vertices plus an F3DEX display list that
  loads a 16-bit TLUT and CI texture tiles from segment 3 (seg-3 offsets
  stay below 0x10000, i.e. one frame texture buffer per draw).
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
import struct
from pathlib import Path

from . import n64_rom

GAME_ID = "14da9d54679e0100"
GAME_CODE = b"NYSE"
DECOMP_US_MD5 = "586a092e22604840973b82dfaceac77a"  # decompals/yoshis-story baseroms/us
ROM_SIZE = 0x1000000

# decompals/yoshis-story yamls/us (verified for the md5 above)
SEGMENTS = (
    {"name": "header", "rom": 0x0, "end": 0x40},
    {"name": "ipl3", "rom": 0x40, "end": 0x1000},
    {"name": "entry", "rom": 0x1000, "end": 0x1070, "vram": 0x80000400},
    {"name": "main", "rom": 0x1070, "end": 0xB58B0, "vram": 0x80000470, "bss_size": 0x5DFF0},
    {"name": "unkbin", "rom": 0xB58B0, "end": None, "vram": 0x80112CA0},
)
CODE_SYMBOLS = {
    "DmaMgr_RequestSync": 0x8007DF0C,
    "Overlay_Load": 0x8008169C,
    "osPiStartDma": 0x800891D0,
    "eepmgr_Create": 0x8007D488,
}
MAIN_ROM_TO_VRAM = 0x80000470 - 0x1070

G_SETTIMG, G_SETTILE, G_LOADBLOCK, G_LOADTLUT = 0xFD, 0xF5, 0xF3, 0xF0
G_TRI1, G_TRI2, G_VTX = 0xBF, 0xB1, 0x04
FRAME_ALIGN = 0x400
SEG3_LIMIT = 0x10000
FMT = {0: "RGBA", 1: "YUV", 2: "CI", 3: "IA", 4: "I"}
SIZ = {0: 4, 1: 8, 2: 16, 3: 32}


def header(rom: bytes) -> dict:
    """Return the cartridge header fields of a big-endian ROM."""
    if rom[:4] != b"\x80\x37\x12\x40":
        raise ValueError("ROM is not normalized big-endian z64 data")
    return {
        "title": rom[0x20:0x34].decode("ascii", "replace").rstrip(),
        "game_code": rom[0x3B:0x3F].decode("ascii", "replace"),
        "version": rom[0x3F],
        "entry": rom[8:12].hex(),
        "crc1": rom[0x10:0x14].hex(),
        "crc2": rom[0x14:0x18].hex(),
    }


def _entropy(block: bytes) -> float:
    n = len(block)
    if not n:
        return 0.0
    return -sum(v / n * math.log2(v / n) for v in collections.Counter(block).values())


def regions(rom: bytes, start: int = 0xB58B0, block: int = 0x10000) -> list[dict]:
    """Classify 64 KiB blocks after code into compressed/structured/padding runs."""
    kinds = []
    for off in range(start - start % block, len(rom), block):
        data = rom[off:off + block]
        if data.count(0) + data.count(0xFF) == len(data):
            kind = "padding"
        elif _entropy(data) >= 6.9:
            kind = "high_entropy"
        else:
            kind = "structured"
        kinds.append((off, kind))
    out: list[dict] = []
    for off, kind in kinds:
        if out and out[-1]["kind"] == kind:
            out[-1]["end"] = off + block
        else:
            out.append({"rom": off, "end": off + block, "kind": kind})
    return out


def _cmds(rom: bytes, off: int, end: int):
    for i in range(off, end, 8):
        yield i, rom[i], struct.unpack_from(">I", rom, i)[0], struct.unpack_from(">I", rom, i + 4)[0]


def parse_frame(rom: bytes, off: int) -> dict | None:
    """Decode one 0x400 sprite record: seg-3 TLUT/tiles and triangle count."""
    tiles, tlut, tris, vtx = [], None, 0, 0
    pending = None
    for _, op, w0, w1 in _cmds(rom, off, off + FRAME_ALIGN):
        if op == G_SETTIMG and w1 >> 24 == 3:
            pending = {"seg3": w1 & 0xFFFFFF, "fmt": FMT.get((w0 >> 21) & 7, "?"), "bpp": SIZ[(w0 >> 19) & 3]}
        elif op == G_LOADTLUT and pending:
            tlut = {"seg3": pending["seg3"], "colors": ((w1 >> 14) & 0x3FF) + 1}
            pending = None
        elif op == G_LOADBLOCK and pending:
            texels = ((w1 >> 12) & 0xFFF) + 1
            tiles.append({**pending, "texels": texels})
            pending = None
        elif op == G_SETTILE and (w1 >> 24) & 7 != 7 and tiles and "render" not in tiles[-1]:
            tiles[-1]["render"] = f"{FMT.get((w0 >> 21) & 7, '?')}{SIZ[(w0 >> 19) & 3]}"
        elif op == G_TRI2:
            tris += 2
        elif op == G_TRI1:
            tris += 1
        elif op == G_VTX:
            vtx += (w0 >> 10) & 0x3F
    # A real sprite record loads a TLUT and keeps every seg-3 tile inside one
    # 64 KiB frame texture buffer; random data that happens to hold 0xFD fails.
    if not tiles or tlut is None or any(t["seg3"] >= SEG3_LIMIT for t in tiles):
        return None
    return {"rom": off, "tlut": tlut, "tiles": tiles, "tris": tris, "vtx": vtx,
            "seg3_end": max(t["seg3"] + t["texels"] * t["bpp"] // 8 for t in tiles)}


def sprite_frames(rom: bytes, start: int = 0xB58B0) -> list[dict]:
    """Return every 0x400-aligned record that draws seg-3 CI sprite tiles."""
    frames = []
    for off in range(start - start % FRAME_ALIGN, len(rom) - FRAME_ALIGN + 1, FRAME_ALIGN):
        block = rom[off:off + FRAME_ALIGN]
        if block.count(b"\xfd") == 0:
            continue
        frame = parse_frame(rom, off)
        if frame:
            frames.append(frame)
    return frames


def frame_banks(frames: list[dict]) -> list[dict]:
    """Group consecutive frame records into banks (a gap > one record splits)."""
    banks: list[dict] = []
    for f in frames:
        if banks and f["rom"] - banks[-1]["end"] <= FRAME_ALIGN:
            b = banks[-1]
            b["end"] = f["rom"] + FRAME_ALIGN
            b["frames"] += 1
            b["tiles"] += len(f["tiles"])
            b["seg3_max"] = max(b["seg3_max"], f["seg3_end"])
        else:
            banks.append({"rom": f["rom"], "end": f["rom"] + FRAME_ALIGN, "frames": 1,
                          "tiles": len(f["tiles"]), "seg3_max": f["seg3_end"]})
    return banks


def _jal(target: int) -> int:
    return 0x0C000000 | ((target & 0x3FFFFFF) >> 2)


def callers(rom: bytes, target: int, start: int = 0x1070, end: int = 0xB58B0) -> list[int]:
    """VRAM addresses of ``jal target`` in the main code segment."""
    op = _jal(target)
    words = struct.unpack_from(f">{(end - start) // 4}I", rom, start)
    return [start + 4 * i + MAIN_ROM_TO_VRAM for i, w in enumerate(words) if w == op]


def inventory(path: str | Path) -> dict:
    path = Path(path)
    raw = path.read_bytes()
    rom = n64_rom.read(path)
    hdr = header(rom)
    if rom[0x3B:0x3F] != GAME_CODE:
        raise ValueError(f"not Yoshi's Story: game code {hdr['game_code']!r}")
    md5 = hashlib.md5(rom).hexdigest()
    frames = sprite_frames(rom)
    banks = frame_banks(frames)
    used = len(rom.rstrip(b"\xff").rstrip(b"\x00"))
    return {
        "game_id": GAME_ID,
        "source": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
        "rom": {"sha256": hashlib.sha256(rom).hexdigest(), "md5": md5, "bytes": len(rom),
                "used_bytes": used, "header": hdr,
                "decomp_us_build": md5 == DECOMP_US_MD5,
                "byte_order": {b"\x80\x37": "z64", b"\x37\x80": "v64", b"\x40\x12": "n64"}.get(raw[:2], "container")},
        "platform": "n64",
        "launch": {"core": "parallel_n64", "save": "EEPROM (eepmgr in main code)",
                   "expansion_pak": False, "region": "NTSC-U"},
        "segments": [dict(s) for s in SEGMENTS],
        "loader_evidence": {name: {"vram": hex(addr), "callers": [hex(c) for c in callers(rom, addr)]}
                            for name, addr in CODE_SYMBOLS.items()},
        "regions": regions(rom),
        "sprites": {"frames": len(frames), "tiles": sum(len(f["tiles"]) for f in frames),
                    "banks": banks,
                    "formats": dict(collections.Counter(t.get("render", f"{t['fmt']}{t['bpp']}") for f in frames for t in f["tiles"])),
                    "seg3_max": max((f["seg3_end"] for f in frames), default=0)},
        "characters": {"status": "unmapped",
                       "note": "frame banks are not yet tied to actor IDs; analysis must locate the seg-3 texture source and the per-actor frame tables"},
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Yoshi's Story owned-source inventory")
    p.add_argument("rom")
    p.add_argument("--out")
    a = p.parse_args(argv)
    inv = inventory(a.rom)
    text = json.dumps(inv, indent=1, default=lambda v: hex(v) if isinstance(v, int) else str(v))
    if a.out:
        Path(a.out).write_text(text)
    s = inv["sprites"]
    print(inv["rom"]["header"], inv["rom"]["md5"], "decomp build" if inv["rom"]["decomp_us_build"] else "UNKNOWN build")
    print(f"sprite frames {s['frames']} tiles {s['tiles']} banks {len(s['banks'])} formats {s['formats']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""ClayFighter: Sculptor's Cut (USA) — N64 character-asset inventory and reader.

Game: f87ec3e2f6b266a1 (request #487, Cloud Strife -> ClayFighter SC player).
Engine: CF3 ("Clay Fighter 3") + MPF framework on libultra. The player is a
2D sprite fighter: each of the 17 characters is a CHAR_<CODE> asset containing
sequence tables, frame rects (CF3_FrameRect*), move tables and N64BMP-style
bitmap frames, with MPFCOMP (Huffman) compression on the packed asset blobs.

Everything in this module is verified against the owned USA build:
    source zip sha256 6fcd1244f390bd42c3dc2c7b1984af450f5a89a513f1acaac33c8bb0293106f7
    normalized z64 sha256 9ccebc317b7ee892be3bdc0d1c8ae46687995908ed51ebd58d6855e5e25abd7f
    z64 md5 30e7e083b978408d5b7760d0ce4dc61d  (No-Intro USA)
The owned zip member is a v64 word-swapped image; always read through
`n64_rom.read`.

Memory map (MIPS VR4300, big-endian):
    ROM offset X >= 0x1000   <->  RDRAM 0x7FFFF400 + X   (IPL3 puts ROM 0x1000
    at 0x80000400).  Code region: ROM 0x1000..0xB0000.  Data segment image:
    ROM 0x0B0C00..0x0D10A0 <-> RAM 0x800B0000..0x800D04A0.  BSS:
    0x800D04A0..0x800FFBE0.  Stack at boot: 0x800F4E30.

Verified tables (ROM offsets):
    ROSTER_NAME_TABLE  0x0AB2E8  RAM 0x800AA6E8  17 u32 name pointers
    CHAR_HOOK_TABLE    0x0AB370  RAM 0x800AA770  17 x 16-byte records of
                                                 {u32 fn1, u32 fn2, 0, 0}
    CHAR_NAME_STRINGS  0x0C5ED0  RAM 0x800C52D0  17 CHAR_<CODE> ASCIIZ names
    DISPLAY_NAMES      0x0C5FB0  RAM 0x800C5FB0  17 display names, descending
                                                 character index (ZAPPA..BMF)
    BMF_BIO_RECORD     0x15C2B0  plaintext CHARBIO record for index 0 (BMF)

Character index order (0 = the default player-1 character):
    0 CHAR_BMF "Bad Mr. Frosty"  1 CHAR_BLOB "Blob"  2 CHAR_BONKER "Bonker"
    3 CHAR_BOOGER "Booger Man"   4 CHAR_KILN "Dr. Kiln"  5 CHAR_EWJ "E. W. Jim"
    6 CHAR_HIGHFIVE "High Five"  7 CHAR_HOBO "Hobo Cop"  8 CHAR_HOUNGAN "Houngan"
    9 CHAR_ICKY "Ickybod Clay"  10 CHAR_KUNGPOW "Kung Pow" 11 CHAR_LIBERTY "Lady Liberty"
    12 CHAR_LOCKJAW "Lockjaw"   13 CHAR_SUMO "Sumo Santa" 14 CHAR_TAFFY "Taffy"
    15 CHAR_THOPPY "T-Hoppy"    16 CHAR_ZAPPA "Zappa Boys"

Formats (from the game's own debug strings, ROM 0x0C4xxx-0x0D1xxx):
    CF3_CharDefHeader / CF3_SequenceTableEntry / CF3_FrameRectTableEntry /
    CF3_FrameRectHeader / CF3_FrameRect / CF3_MoveTableEntry /
    CF3_MoveTriggerEntry   (CF3CDEF.H)
    CF3_Stage / CF3_BkgBoundingLineSegment / CF3_CameraBarLineSegment /
    CF3_Breakthrough / CF3_BkgDefHeader   (CF3BDEF.H)
    MPF_CompressedDataHeader (MPFCOMP.H); codec is Huffman (see below).
    Sprite frames are N64BMP.C bitmaps replayed by the CHARFRAM.C command
    player ("*** %d commands over/under (should have been %d)").

MPFCOMP Huffman codec (partially reversed): mpDataDecompress at
RAM 0x8008FAE0-0x8008FE00 (ROM 0x906C0) reads, from its source cursor:
    u32 table_size (sanity limit 0x3D41)
    table_size bytes of a code-length/symbol table (skipped, then histogrammed)
    u32 symbol_count
    u32 output_size(?)
then builds a 257-entry symbol histogram and a canonical Huffman table
(prefix sums at a second table) and emits bytes while the cursor is below the
end pointer.  Bit extraction goes through MPFBSTRM mpReadBits
(RAM 0x80092Dxx).  TODO(next): finish the tree construction and the exact
header layout, then decompress the CHAR_ asset blobs and locate the
name->(offset,size) directory (fopen family around RAM 0x8008BDE0).
"""

from __future__ import annotations

import struct
from pathlib import Path

from . import n64_rom

GAME_ID = "f87ec3e2f6b266a1"

SOURCE_ZIP_SHA256 = "6fcd1244f390bd42c3dc2c7b1984af450f5a89a513f1acaac33c8bb0293106f7"
ROM_SHA256 = "9ccebc317b7ee892be3bdc0d1c8ae46687995908ed51ebd58d6855e5e25abd7f"
ROM_MD5 = "30e7e083b978408d5b7760d0ce4dc61d"
ROM_SIZE = 0x1000000

ROM_TO_RAM_DELTA = 0x7FFFF400  # RAM = ROM + delta for ROM >= 0x1000

ROSTER_NAME_TABLE = 0x0AB2E8
CHAR_HOOK_TABLE = 0x0AB370
CHAR_NAME_STRINGS = 0x0C5ED0
DISPLAY_NAMES = 0x0C5FB0
BMF_BIO_RECORD = 0x15C2B0

CHARACTER_COUNT = 17

# index -> (code, display name)
ROSTER = [
    ("CHAR_BMF", "Frosty"),
    ("CHAR_BLOB", "Blob"),
    ("CHAR_BONKER", "Bonker"),
    ("CHAR_BOOGER", "Booger Man"),
    ("CHAR_KILN", "Dr. Kiln"),
    ("CHAR_EWJ", "E. W. Jim"),
    ("CHAR_HIGHFIVE", "High Five"),
    ("CHAR_HOBO", "Hobo Cop"),
    ("CHAR_HOUNGAN", "Houngan"),
    ("CHAR_ICKY", "Ickybod Clay"),
    ("CHAR_KUNGPOW", "Kung Pow"),
    ("CHAR_LIBERTY", "Lady Liberty"),
    ("CHAR_LOCKJAW", "Lockjaw"),
    ("CHAR_SUMO", "Sumo Santa"),
    ("CHAR_TAFFY", "Taffy"),
    ("CHAR_THOPPY", "T-Hoppy"),
    ("CHAR_ZAPPA", "Zappa Boys"),
]


def load_rom(src: str | Path) -> bytes:
    """Normalize the owned v64 zip member to a z64 image (see n64_rom)."""
    data = n64_rom.read(Path(src))
    if len(data) != ROM_SIZE:
        raise ValueError(f"unexpected ROM size {len(data)}")
    return data


def _cstr(data: bytes, off: int, limit: int = 64) -> str:
    end = data.find(b"\x00", off, off + limit)
    if end < 0:
        end = off + limit
    return data[off:end].decode("latin1")


def roster(rom: bytes) -> list[dict]:
    """17 entries, index order, from the verified name-pointer table."""
    out = []
    for i in range(CHARACTER_COUNT):
        ptr = struct.unpack_from(">I", rom, ROSTER_NAME_TABLE + 4 * i)[0]
        ro = ptr - ROM_TO_RAM_DELTA
        code = _cstr(rom, ro, 16)
        out.append({"index": i, "code": code, "name_ptr": ptr,
                    "name_rom": ro, "display": ROSTER[i][1]})
    return out


def display_names(rom: bytes) -> list[str]:
    """Parse the display-name string run (descending index: ZAPPA..BMF)."""
    names, off = [], DISPLAY_NAMES
    while len(names) < CHARACTER_COUNT:
        name = _cstr(rom, off, 32)
        if not name:
            raise ValueError("display-name run ended early")
        names.append(name)
        off += (len(name) + 1 + 3) & ~3
    return names


def char_hooks(rom: bytes) -> list[dict]:
    """17 x 16-byte records {u32 fn1, u32 fn2, 0, 0}; fn pointers into code."""
    out = []
    for i in range(CHARACTER_COUNT):
        rec = struct.unpack_from(">4I", rom, CHAR_HOOK_TABLE + 16 * i)
        out.append({"index": i, "code": ROSTER[i][0], "fn1": rec[0], "fn2": rec[1]})
    return out


def parse_bmf_bio(rom: bytes) -> dict:
    """Parse the plaintext CHARBIO record for index 0 (Bad Mr. Frosty).

    Layout observed at ROM 0x15C2B0: display name, then encoded fields
    (0x89/0x88 opcodes), the plaintext code "BMF", ten f32 stats, then one or
    more u16 frame-offset tables separated by a 0x7F marker byte.
    """
    off = BMF_BIO_RECORD
    end = off
    while end < len(rom) and 0x20 <= rom[end] < 0x7F:
        end += 1
    name = rom[off:end].decode("latin1")
    off = (end + 1 + 3) & ~3  # name terminator is the 0x89 opcode byte
    tail = rom[off:off + 0x120]
    code_pos = tail.find(b"BMF")
    code = tail[code_pos:code_pos + 3].decode("latin1") if code_pos >= 0 else ""
    stats_off = off + code_pos + 3 + 3  # skip code + 0x88 00 marker observed
    stats = [struct.unpack_from(">f", rom, stats_off + 4 * i)[0]
             for i in range(10)]
    frames = []
    cursor = stats_off + 40
    while len(frames) < 256:
        if cursor + 2 > len(rom):
            break
        if rom[cursor] == 0x7F:  # table separator marker byte
            cursor += 1
            continue
        val = struct.unpack_from(">H", rom, cursor)[0]
        if not (0x3000 <= val <= 0x8000):  # frame offsets live in this band
            break
        frames.append(val)
        cursor += 2
    return {"name": name, "code": code, "stats": stats,
            "frame_offsets": frames, "record_rom": BMF_BIO_RECORD}


def validate(rom: bytes) -> dict:
    """Run the reader's checks against a normalized ROM image."""
    import hashlib
    problems = []
    if hashlib.sha256(rom).hexdigest() != ROM_SHA256:
        problems.append("rom sha256 mismatch")
    if rom[0x8:0xC] != b"\x80\x00\x04\x00":
        problems.append("entry point is not 0x80000400")
    ro = roster(rom)
    if [e["code"] for e in ro] != [c for c, _ in ROSTER]:
        problems.append("roster code order mismatch")
    dn = display_names(rom)
    if dn != [d for _, d in ROSTER][::-1]:
        problems.append("display names do not match descending roster")
    hooks = char_hooks(rom)
    if any(not (0x80004000 <= h["fn2"] <= 0x800A0000) for h in hooks):
        problems.append("hook fn2 outside code range")
    bio = parse_bmf_bio(rom)
    if bio["name"] != "Bad Mr. Frosty" or bio["code"] != "BMF":
        problems.append("BMF bio record identity mismatch")
    if len(bio["frame_offsets"]) < 16:
        problems.append("BMF bio frame table too short")
    return {"ok": not problems, "problems": problems, "bio": bio,
            "roster": ro, "display_names": dn, "hooks": hooks}

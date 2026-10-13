"""Sonic 2D (Mega Drive) player sprite animations straight from the ROM, frame-exact, as collection ``sprites`` clips.

Owned titles (catalog, HyperSpin share): Sonic the Hedgehog (Japan, Korea) REV01 f82de5b1456da0ce, Sonic the
Hedgehog 2 (World) REV01 938e4ca5b120e344 / 764582c25053f662, Sonic the Hedgehog 3 (USA) 1936eeee6b541ca3,
Sonic & Knuckles + Sonic the Hedgehog 3 (World) ed2bef5be2826deb (the locked-on S3K image), Sonic & Knuckles (World)
668e74c15d61a9a7. (The catalog's 117cd862c2e9dbaf "Sonic the Hedgehog (USA, Europe)" zip holds Sonic Spinball; it is
refused by serial.)

What a player character is in these engines (Sonic Retro SCHG / s1disasm, s2disasm, skdisasm):

* art: uncompressed 4bpp 8x8 tiles, streamed per mapping frame into the player's VRAM slot by a DPLC
  ("dynamic pattern load cue") table: per frame a count then entries ``(tiles-1) << 12 | first_tile`` (S1: byte
  count; S2/S3K: word count). S3K Sonic/Tails switch to a second art bank above a frame number.
* mappings: per frame a piece count then pieces ``y, size, tile word, x`` (S1 5-byte, S2 8-byte with a 2P tile
  word, S3K 6-byte); the tile word indexes the tiles the DPLC just streamed and carries palette line / flips.
* animation scripts (Ani_Sonic / SonicAniData / AniSonic...): u16 offset table; a script is a frame delay byte, mapping
  frame numbers, and an end command: $FF loop, $FE n go back n, $FD a switch to animation a ($FC.. stop). A first
  byte with bit 7 set marks the speed-driven walk/run ($FF), roll ($FE) and push ($FD) scripts, whose delay comes
  from the ground speed (walk/run: (0x800 - |v|) >> 8, roll: (0x400 - |v|) >> 8, push: (0x800 - |v|) >> 6).
  Every frame is shown delay+1 game frames.
* palette: the palette pointer table (Pal_Index / PalPointers / PalPoint) entry 3 = Sonic (and Tails) line 0; S3K
  entry 5 = Knuckles.

Nothing comes from a table of guessed ROM offsets: the DPLC loaders, ``Animate`` routines (their ``lea (Ani).l,a1``)
and ``move.l #Map,mappings(a0)`` sites are found by their 68k instruction shapes (S3K characters by the
``Perform_Player_DPLC`` dispatch, gbox.sk_sprites), each mapping table is the one whose frames fit that character's
DPLC frame for frame, and the signpost scripts are found by their own bytes. The owned-ROM tests pin what that finds.

Output per character: a collection ``sprites`` entry (``<game>_<char>``, e.g. ``sonic2_sonic``) whose
``meta.animations[]`` are clips: ``clips/<clip>/`` with ``frames/frame_NNNN.png`` (RGBA, one canvas per clip, the
sprite origin at the same pixel in every frame), ``sheet.png`` + ``sheet.json`` (per-frame duration in game frames
and ms, mapping frame, origin/hotspot, loop start/length), ``preview.apng`` (+ ``preview.webp``) and ``clip.mp4``
(ffmpeg, 4x nearest-neighbour). The collage helper (gbox.sprite_collage) tiles chosen clips onto a timeline.

CLI: ``python -m gbox.sonic2d_sprites inventory ROM`` | ``extract ROM --out DIR [--char sonic] [--clips a,b]``
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import struct
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .formats import sega_md

VERSION = "1.0"
READER_VERSION = 1
FPS = 60.0                 # NTSC Mega Drive vertical blank (the scripts count these)
MP4_SCALE = 4
MAX_SIM = 1800             # game frames a clip simulation may run before it must have looped or stopped


class Sonic2DError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ engine layouts

@dataclass(frozen=True)
class Layout:
    name: str
    piece: int             # mapping piece bytes
    map_count: int         # mapping frame header bytes (1 or 2)
    dplc_count: int        # DPLC frame header bytes (1 or 2)
    map_field: int         # mappings(a0) SST offset
    anim_field: int        # anim(a0); prev_anim is the next byte
    player_cmd: int        # player scripts: bytes >= this are commands
    obj_mask: int          # AnimateSprite frame mask (S1 keeps flip flags in bits 5/6)


LAYOUTS = {
    "s1": Layout("s1", 5, 1, 1, 0x04, 0x1C, 0x80, 0x1F),
    "s2": Layout("s2", 8, 2, 2, 0x04, 0x1C, 0xF0, 0x7F),
    "s3k": Layout("s3k", 6, 2, 2, 0x0C, 0x20, 0xFC, 0x7F),
}

# Animation names (sonicretro disassembly labels; S3K ids named by their use in skdisasm).
S1_SONIC = ["walk", "run", "roll", "roll_fast", "push", "wait", "balance", "look_up", "duck", "warp1", "warp2",
            "warp3", "warp4", "skid", "float1", "float2", "spring", "hang", "leap1", "leap2", "surf", "get_air",
            "burnt", "drown", "death", "shrink", "hurt", "slide", "null", "float3", "float4"]
S2_SONIC = ["walk", "run", "roll", "roll_fast", "push", "wait", "balance", "look_up", "duck", "spindash", "blink",
            "get_up", "balance2", "skid", "float", "float2", "spring", "hang", "dash2", "dash3", "hang2", "bubble",
            "death_bw", "drown", "death", "hurt", "hurt2", "slide", "blank", "balance3", "balance4",
            "super_transform", "lying", "lie_down"]
S2_TAILS = ["walk", "run", "roll", "roll_fast", "push", "wait", "balance", "look_up", "duck", "spindash", "dummy1",
            "dummy2", "dummy3", "skid", "float", "float2", "spring", "hang", "blink", "blink2", "hang2", "bubble",
            "death_bw", "drown", "death", "hurt", "hurt2", "slide", "blank", "dummy4", "dummy5", "run_fast", "fly"]
S3K_COMMON = ["walk", "run", "roll", "roll_fast", "push", "wait", "balance", "look_up", "duck", "spindash",
              "wait_end", "get_up", "balance2", "skid", "float", "float2", "spring", "hang", "dash2", "victory",
              "hang2", "bubble", "burnt", "drown", "death", "hurt2", "hurt", "slide", "blank", "balance3",
              "balance4", "super_transform", "lying", "lie_down", "carried", "carried_end"]
S3K_TAILS = S3K_COMMON[:10] + ["dummy_0a", "dummy_0b", "dummy_0c", "skid", "float", "float2", "spring", "hang",
                               "anim_12", "victory", "hang2", "bubble", "burnt", "drown", "death", "slide2", "hurt",
                               "slide", "blank", "dummy_1d", "dummy_1e", "run_fast", "fly", "fly2", "carry",
                               "ascend", "tired", "swim", "swim2", "tired2", "tired3", "anim_29"]
S3K_KNUCKLES = S3K_COMMON[:32] + ["glide", "glide_fall", "glide_slide", "glide_get_up", "sphere_victory"]

# Speed (|ground speed| in 1/256 px) a speed-driven script is shown at: walk, run, the fast run and the fast roll at
# the speed the game switches to them; push at a slow shove.
NOMINAL_SPEED = {"walk": 0x400, "run": 0x600, "run_fast": 0x700, "roll": 0, "roll_fast": 0x600, "push": 0x80}


@dataclass
class Game:
    key: str
    title: str
    layout: str
    chars: list[str]
    names: dict[str, list[str]]
    pal_index: dict[str, int]          # palette pointer entry per character (line 0)
    zone_pal: int | None               # entry holding lines 1-3 for objects (signpost)
    signpost: str | None               # 's1' | 's2' | 's3k'
    clips: dict[str, list[dict]] = field(default_factory=dict)


def _clip(name, *seq, note="", what=""):
    return {"name": name, "seq": list(seq), "note": note, "what": what or name.replace("_", " ")}


def _a(anim, frames=None, speed=None):
    return {"anim": anim, "frames": frames, "speed": speed}


S1_CLIPS = [
    _clip("jump", _a(2, speed=0), what="jump / roll ball (standing jump: the roll script at speed 0)"),
    _clip("roll", _a(3, speed=0x600), what="roll at running speed (Roll2, picked at |v| >= $600)"),
    _clip("level_complete", _a(None), what="act clear: the signpost spins (Eggman -> Sonic) while Sonic is forced "
          "right", note="Sonic 1 has no player victory pose; this is the signpost (object 0D) sequence"),
]
S2_CLIPS = [
    _clip("spindash_charge", _a(9), what="spin dash charge (revving loop)"),
    _clip("spindash_release", _a(9, frames=12), _a(2, speed=0x800),
          what="spin dash release: last revs, then the roll at the minimum release speed $800"),
    _clip("jump", _a(2, speed=0), what="jump / roll ball (standing jump)"),
    _clip("roll", _a(3, speed=0x600), what="roll at running speed"),
    _clip("level_complete", _a(None), what="act clear: the signpost spins and lands on the character's face",
          note="Sonic 2 has no player victory pose; this is the signpost (object 0D) sequence"),
]
S3K_CLIPS = [
    _clip("spindash_charge", _a(9), what="spin dash charge (revving loop)"),
    _clip("spindash_release", _a(9, frames=12), _a(2, speed=0x800),
          what="spin dash release: last revs, then the roll at the minimum release speed $800"),
    _clip("jump", _a(2, speed=0), what="jump / roll ball (standing jump)"),
    _clip("roll", _a(3, speed=0x600), what="roll at running speed"),
    _clip("level_complete", _a(0x13), what="act clear victory pose (Set_PlayerEndingPose, anim $13)"),
    _clip("signpost", _a(None), what="end-of-act signpost: spins while falling, lands on the character's face"),
]

GAMES = {
    "sonic1": Game("sonic1", "Sonic the Hedgehog", "s1", ["sonic"], {"sonic": S1_SONIC}, {"sonic": 3}, 4, "s1",
                   {"sonic": S1_CLIPS}),
    "sonic2": Game("sonic2", "Sonic the Hedgehog 2", "s2", ["sonic", "tails"], {"sonic": S2_SONIC, "tails": S2_TAILS},
                   {"sonic": 3, "tails": 3}, 4, "s2", {"sonic": S2_CLIPS, "tails": S2_CLIPS}),
    "sonic3": Game("sonic3", "Sonic the Hedgehog 3", "s3k", ["sonic", "tails"],
                   {"sonic": S3K_COMMON, "tails": S3K_TAILS}, {"sonic": 3, "tails": 3}, None, None,
                   {"sonic": S3K_CLIPS[:5], "tails": S3K_CLIPS[:5]}),
    "s3k": Game("s3k", "Sonic 3 & Knuckles", "s3k", ["sonic", "tails", "knuckles"],
                {"sonic": S3K_COMMON, "tails": S3K_TAILS, "knuckles": S3K_KNUCKLES},
                {"sonic": 3, "tails": 3, "knuckles": 5}, 0x0C, "s3k",
                {"sonic": S3K_CLIPS, "tails": S3K_CLIPS, "knuckles": S3K_CLIPS}),
    "sk": Game("sk", "Sonic & Knuckles", "s3k", ["sonic", "knuckles"],
               {"sonic": S3K_COMMON, "knuckles": S3K_KNUCKLES}, {"sonic": 3, "knuckles": 5}, 0x0C, "s3k",
               {"sonic": S3K_CLIPS, "knuckles": S3K_CLIPS}),
}
CHAR_NAMES = {"sonic": "Sonic", "tails": "Tails", "knuckles": "Knuckles"}
SIGN_FACE = {"s2": {"sonic": 3, "tails": 4}, "s3k": {"sonic": 0, "tails": 1, "knuckles": 2}}


# ------------------------------------------------------------------------------------------------ ROM + identity

def _u16(d, o):
    return struct.unpack_from(">H", d, o)[0]


def _u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def read_rom(src) -> tuple[bytes, dict]:
    """A flat Mega Drive image from a .zip (one ROM member, save files ignored) / .md / .bin / .gen, or bytes."""
    if isinstance(src, (bytes, bytearray)):
        d, name = bytes(src), "<bytes>"
    else:
        p = Path(src)
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                members = [i for i in zf.infolist() if not i.is_dir()
                           and Path(i.filename).suffix.lower() in (".md", ".bin", ".gen", ".smd")]
                if len(members) != 1:
                    raise Sonic2DError(f"expected one ROM member in {p.name}, found {len(members)}")
                name, d = members[0].filename, zf.read(members[0])
        else:
            name, d = p.name, p.read_bytes()
    if d[0x100:0x104] != b"SEGA" and d[0x100:0x105] != b" SEGA":
        raise Sonic2DError("no Mega Drive header at 0x100 (interleaved SMD dumps are not handled)")
    return d, {"member": name, "size": len(d)}


def header(d: bytes) -> dict:
    h = d[0x100:0x200]
    return {"console": h[0:16].decode("latin1").strip(), "domestic": h[32:80].decode("latin1").strip(),
            "overseas": h[80:128].decode("latin1").strip(), "serial": h[128:142].decode("latin1").strip(),
            "checksum": h[142:144].hex(), "region": h[240:243].decode("latin1").strip()}


def identify(d: bytes) -> Game:
    h = header(d)
    title = re.sub(r"\s+", " ", (h["overseas"] or h["domestic"]).upper())
    serial = h["serial"]
    if "MK-1563" in serial:                                    # Sonic & Knuckles cart
        lock = d[0x200100:0x200200] if len(d) >= 0x200200 else b""
        if b"HEDGEHOG 3" in re.sub(rb"\s+", b" ", lock):
            return GAMES["s3k"]
        if lock[:4] == b"SEGA":
            raise Sonic2DError("Sonic & Knuckles locked on to a cartridge other than Sonic 3 is not handled")
        return GAMES["sk"]
    if not title.startswith("SONIC THE HEDGEHOG"):
        raise Sonic2DError(f"not a Sonic 1/2/3/S&K ROM: {title!r} ({serial})")
    rest = title[len("SONIC THE HEDGEHOG"):].strip()
    if rest == "":
        return GAMES["sonic1"]
    if rest == "2":
        return GAMES["sonic2"]
    if rest == "3":
        return GAMES["sonic3"]
    raise Sonic2DError(f"unhandled Sonic title {title!r}")


# ------------------------------------------------------------------------------------------------ tables

def offsets(d: bytes, off: int, count: int | None = None, limit: int = 0x2000) -> list[int]:
    """A u16 offset table's entries (count = first offset / 2 unless given)."""
    first = _u16(d, off)
    if first == 0 or first & 1 or first > limit:
        raise Sonic2DError(f"bad offset table at 0x{off:x}")
    n = first // 2 if count is None else count
    if n > first // 2 and count is not None and count > 0x200:
        raise Sonic2DError(f"table at 0x{off:x} too long")
    return [_u16(d, off + 2 * i) for i in range(n)]


def parse_dplc(d: bytes, off: int, lay: Layout, count: int | None = None,
               obj: bool = False) -> list[list[tuple[int, int]]]:
    """Per frame: [(first_tile, tiles)]. ``obj``: the S3K object format read by Perform_DPLC (count-1 word, entries
    ``first_tile << 4 | tiles-1``)."""
    frames = []
    for rel in offsets(d, off, count):
        p = off + rel
        if obj:
            n = _u16(d, p) + 1
            if n > 0x40:
                raise Sonic2DError(f"DPLC frame at 0x{p:x} claims {n} entries")
            frames.append([(w >> 4, (w & 0xF) + 1) for w in struct.unpack_from(f">{n}H", d, p + 2)])
            continue
        if lay.dplc_count == 1:
            n, p = d[p], p + 1
        else:
            n, p = _u16(d, p), p + 2
        if n > 0x40:
            raise Sonic2DError(f"DPLC frame at 0x{p:x} claims {n} entries")
        frames.append([(w & 0xFFF, (w >> 12) + 1) for w in struct.unpack_from(f">{n}H", d, p)])
    return frames


def parse_mappings(d: bytes, off: int, lay: Layout, count: int | None = None) -> list[list[dict]]:
    """Per frame: pieces {x, y, w, h (tiles), tile, pal, pri, hf, vf}."""
    frames = []
    for rel in offsets(d, off, count):
        p = off + rel
        if lay.map_count == 1:
            n, p = d[p], p + 1
        else:
            n, p = _u16(d, p), p + 2
        if n > 0x50:
            raise Sonic2DError(f"mapping frame at 0x{p:x} claims {n} pieces")
        ps = []
        for k in range(n):
            q = p + lay.piece * k
            if lay.piece == 5:
                y, size, tile, x = struct.unpack_from(">bBHb", d, q)
            elif lay.piece == 8:
                y, size, tile, _t2, x = struct.unpack_from(">bBHHh", d, q)
            else:
                y, size, tile, x = struct.unpack_from(">bBHh", d, q)
            ps.append({"x": x, "y": y, "w": ((size >> 2) & 3) + 1, "h": (size & 3) + 1, "tile": tile & 0x7FF,
                       "pal": (tile >> 13) & 3, "pri": tile >> 15, "hf": (tile >> 11) & 1, "vf": (tile >> 12) & 1})
        frames.append(ps)
    return frames


def mapping_fits(maps, dplc) -> bool:
    if len(maps) != len(dplc):
        return False
    for ps, ents in zip(maps, dplc):
        have = sum(n for _, n in ents)
        if max((pc["tile"] + pc["w"] * pc["h"] for pc in ps), default=0) > have:
            return False
    return True


# ------------------------------------------------------------------------------------------------ discovery

# add.w d0,d0; adda.w (a2,d0.w),a2; then the entry count: S1 moveq #0,d1; move.b (a2)+,d1; subq.b #1,d1; bmi.s
# S2/S3K move.w (a2)+,d5; subq.w #1,d5; bmi.s
_DPLC_CORE = {
    "s1": re.compile(rb"\xd0\x40\xd4\xf2\x00\x00\x72\x00\x12\x1a\x53\x01\x6b", re.S),
    "s2": re.compile(rb"\xd0\x40\xd4\xf2\x00\x00\x3a\x1a\x53\x45\x6b", re.S),
}
_DPLC_CORE["s3k"] = _DPLC_CORE["s2"]


def find_loaders(d: bytes, lay: Layout) -> list[dict]:
    """Player-style DPLC loaders: {code, plc, alt_plc?, art, extra_art?, extra_from?}. The table is the first
    ``lea (PLC).l,a2`` in the 24 bytes before the table walk (a later one is a flag-selected override such as
    PLC_SuperSonic); the art base is the ``lea (Art).l,a1`` (S1), ``addi.l #Art,d1`` (S2) or ``move.l #Art,d6``
    (S3K) next to it."""
    out = []
    for m in _DPLC_CORE[lay.name].finditer(d):
        c = m.start()
        if c & 1:
            continue
        back24 = d[max(0, c - 24):c]
        leas = [x for x in range(0, len(back24) - 5, 2) if back24[x:x + 2] == b"\x45\xf9"]
        if not leas or leas[-1] != len(back24) - 6:        # the last lea leads straight into the walk
            continue
        plc = _u32(back24, leas[0] + 2)
        alts = [_u32(back24, x + 2) for x in leas[1:]]
        fwd = d[m.end():m.end() + 48]
        back = d[max(0, c - 40):c]
        art = None
        rec = {"code": c, "plc": plc}
        if alts:
            rec["alt_plc"] = alts
        if lay.name == "s1":
            j = fwd.find(b"\x43\xf9")
            art = _u32(fwd, j + 2) if j >= 0 else None
        else:
            j = fwd.find(b"\x06\x81")
            k = fwd.find(b"\x2c\x3c")
            if j >= 0 and (k < 0 or j < k):
                art = _u32(fwd, j + 2)
            elif k >= 0:
                art = _u32(fwd, k + 2)
                tail = fwd[k + 6:k + 18]
                if tail[:2] == b"\x0c\x40" and tail[4:5] == b"\x65" and tail[6:8] == b"\x2c\x3c":
                    rec["extra_art"], rec["extra_from"] = _u32(tail, 8), _u16(tail, 2) // 2
            else:
                k = back.rfind(b"\x2c\x3c")
                if k >= 0:
                    art = _u32(back, k + 2)
        if art is None or art >= len(d) or plc >= len(d):
            continue
        rec["art"] = art
        out.append(rec)
    return out


def find_anim_leas(d: bytes, lay: Layout) -> list[dict]:
    """``lea (Ani).l,a1`` that start an Animate routine (moveq #0,d0; move.b anim(a0),d0; cmp.b prev_anim(a0),d0
    within the next 20 bytes). The first lea of a run wins (S2/S3K load a Super table after a flag test)."""
    tail = b"\x70\x00\x10\x28\x00" + bytes([lay.anim_field]) + b"\xb0\x28\x00" + bytes([lay.anim_field + 1])
    out, seen = [], set()
    for m in re.finditer(re.escape(tail), d):
        t = m.start()
        for back in range(20, 5, -2):
            s = t - back
            if s >= 0 and d[s:s + 2] == b"\x43\xf9":
                if t not in seen:
                    seen.add(t)
                    out.append({"lea": s, "table": _u32(d, s + 2), "animate": t})
                break
    return out


def map_targets(d: bytes, lay: Layout) -> dict[int, list[int]]:
    """``move.l #Map,mappings(a0|a1)`` immediates -> sites."""
    out: dict[int, list[int]] = {}
    pat = rb"[\x21\x23]\x7c(....)\x00" + re.escape(bytes([lay.map_field]))
    for m in re.finditer(pat, d, re.S):
        v = _u32(m.group(1), 0)
        if 0x200 <= v < len(d) - 2 and not v & 1 and not m.start() & 1:
            out.setdefault(v, []).append(m.start())
    return out


def find_palette_table(d: bytes) -> int:
    """The palette pointer table (lea (PalPointers).l,a1; lsl.w #3,d0; adda.w d0,a1; movea.l (a1)+,a2; ...)."""
    hits = [_u32(d, m.start() + 2) for m in re.finditer(rb"\x43\xf9....\xe7\x48\xd2\xc0\x24\x59\x36\x59", d, re.S)
            if not m.start() & 1]
    if not hits:
        raise Sonic2DError("palette pointer table not found")
    return max(set(hits), key=hits.count)


def palette_entry(d: bytes, table: int, i: int) -> dict:
    ptr, ram, cnt = struct.unpack_from(">IHH", d, table + 8 * i)
    n = (cnt + 1) * 4
    if ptr + n > len(d) or cnt > 0x3F:
        raise Sonic2DError(f"bad palette entry {i} at 0x{table + 8 * i:x}")
    line = (ram & 0x7F) // 0x20
    return {"index": i, "ptr": ptr, "ram": ram, "bytes": n, "line": line, "data": d[ptr:ptr + n]}


def script_bytes(d: bytes, table: int, i: int, n: int = 256) -> bytes:
    return d[table + _u16(d, table + 2 * i):table + _u16(d, table + 2 * i) + n]


def anim_count(d: bytes, table: int) -> int:
    return _u16(d, table) // 2


def anim_frames_used(d: bytes, table: int, cmd: int) -> set[int]:
    used = set()
    for i in range(anim_count(d, table)):
        s = script_bytes(d, table, i)
        k = 1
        while k < len(s) and s[k] < cmd:
            used.add(s[k])
            k += 1
    return used


def dplc_count(d: bytes, ld: dict) -> int:
    """Frames in a loader's DPLC table: its first offset / 2, cut where a flag-selected table (PLC_SuperSonic) that
    shares its frame data starts."""
    first = _u16(d, ld["plc"]) // 2
    stops = [a for a in ld.get("alt_plc", []) if a > ld["plc"]]
    return min([first] + [(a - ld["plc"]) // 2 for a in stops])


def _fit_maps(d, lay, dplc, near) -> tuple[int, list]:
    fits = []
    for t, refs in map_targets(d, lay).items():
        try:
            maps = parse_mappings(d, t, lay, len(dplc))
        except (Sonic2DError, struct.error, IndexError):
            continue
        if mapping_fits(maps, dplc):
            fits.append((min(abs(r - near) for r in refs), t, maps))
    if not fits:
        raise Sonic2DError("no mapping table fits the DPLC")
    fits.sort(key=lambda f: f[0])
    return fits[0][1], fits[0][2]


@dataclass
class Character:
    key: str
    plc: int
    art: int
    maps_off: int
    anim: int
    dplc: list
    maps: list
    palette: bytes
    pal_entry: int
    loader: int
    extra_art: int | None = None
    extra_from: int | None = None
    tails: dict | None = None              # Tails' tails overlay object (S2/S3K)

    def tiles(self, d: bytes, frame: int) -> bytes:
        base = self.extra_art if self.extra_art is not None and frame >= (self.extra_from or 0) else self.art
        out = bytearray()
        for first, n in self.dplc[frame]:
            out += d[base + 32 * first:base + 32 * (first + n)]
        return bytes(out)


def _player_loaders_generic(d, lay, game) -> dict[str, dict]:
    """S1/S2/S3: per Animate routine the loader(s) after it (before the next Animate routine, within 0x800 bytes);
    the one with the most DPLC frames is the character's (S2/S3 also stream Tails' tails from the same code area).
    Characters are named in code order (Sonic's object precedes Tails')."""
    leas = sorted(find_anim_leas(d, lay), key=lambda a: a["lea"])
    loaders = find_loaders(d, lay)
    groups = []
    for i, a in enumerate(leas):
        stop = min(leas[i + 1]["lea"] if i + 1 < len(leas) else len(d), a["lea"] + 0x800)
        cand = []
        for ld in loaders:
            if a["lea"] < ld["code"] < stop:
                try:
                    n = len(parse_dplc(d, ld["plc"], lay, dplc_count(d, ld)))
                except (Sonic2DError, struct.error, IndexError):
                    continue
                if n >= 0x40:
                    cand.append((n, ld))
        if cand:
            cand.sort(key=lambda c: -c[0])
            groups.append({**cand[0][1], "anim": a["table"], "anim_lea": a["lea"]})
    if len(groups) < len(game.chars):
        raise Sonic2DError(f"found {len(groups)} player loaders, expected {len(game.chars)}")
    return dict(zip(game.chars, groups))


def _player_loaders_s3k(d, lay, game) -> dict[str, dict]:
    """S&K / S3K: Perform_Player_DPLC's dispatch names the loaders (gbox.sk_sprites); each character's Animate
    routine is the closest one before its loader."""
    from . import sk_sprites
    disp = sk_sprites.player_dispatch(d)
    leas = sorted(find_anim_leas(d, lay), key=lambda a: a["lea"])
    loaders = find_loaders(d, lay)
    out = {}
    for name in game.chars:
        entry = disp[name]
        ld = min((x for x in loaders if 0 <= x["code"] - entry <= 0x40), key=lambda x: x["code"], default=None)
        if ld is None or ld["plc"] >= len(d) or ld["art"] >= len(d):
            continue
        before = [a for a in leas if a["lea"] < ld["code"]]
        if not before:
            continue
        a = before[-1]
        out[name] = {**ld, "anim": a["table"], "anim_lea": a["lea"]}
    return out


def find_characters(d: bytes, game: Game | None = None) -> dict[str, Character]:
    game = game or identify(d)
    lay = LAYOUTS[game.layout]
    found = _player_loaders_s3k(d, lay, game) if game.key in ("s3k", "sk") else _player_loaders_generic(d, lay, game)
    pal_table = find_palette_table(d)
    chars = {}
    for name in game.chars:
        ld = found.get(name)
        if ld is None:
            continue
        dplc = parse_dplc(d, ld["plc"], lay, dplc_count(d, ld))
        maps_off, maps = _fit_maps(d, lay, dplc, ld["code"])
        used = anim_frames_used(d, ld["anim"], lay.player_cmd)
        if used and max(used) >= len(maps):
            raise Sonic2DError(f"{name}: animation table 0x{ld['anim']:x} uses frame {max(used):#x} "
                               f"beyond the {len(maps)} mapping frames")
        pe = palette_entry(d, pal_table, game.pal_index[name])
        chars[name] = Character(name, ld["plc"], ld["art"], maps_off, ld["anim"], dplc, maps, pe["data"][:32],
                                game.pal_index[name], ld["code"], ld.get("extra_art"), ld.get("extra_from"))
    if game.key in ("sonic2", "s3k", "sonic3") and "tails" in chars:
        try:
            chars["tails"].tails = find_tails_overlay(d, lay, chars["tails"])
        except (Sonic2DError, struct.error, IndexError):
            chars["tails"].tails = None
    return chars


def find_tails_overlay(d: bytes, lay: Layout, tails: Character) -> dict:
    """Tails' two tails are their own object (S2 Obj05, S3K Obj_Tails_Tail): an animation picked from Tails' anim
    through a byte table (``move.b Sel(pc,d0.w),anim(a0)``) followed by ``lea (TailAni).l,a1``. S2 draws them from
    Tails' own mappings/DPLC; S3K has a separate map/DPLC/art set (``move.l #Map,mappings(a0)`` just before)."""
    pat = rb"\x11\x7b\x00(.)\x00" + re.escape(bytes([lay.anim_field])) + rb"\x43\xf9(....)"
    best = None
    for m in re.finditer(pat, d, re.S):
        if m.start() & 1 or not 0 < m.start() - tails.loader < 0x2000 and not 0 < tails.loader - m.start() < 0x2000:
            continue
        sel = m.start() + 2 + struct.unpack("b", m.group(1))[0]
        best = {"select": sel, "anim": _u32(m.group(2), 0), "site": m.start()}
        break
    if best is None:
        raise Sonic2DError("Tails' tails object not found")
    if lay.name == "s2":
        best.update({"maps": tails.maps_off, "plc": tails.plc, "art": tails.art, "own_set": False})
        return best
    # S3K: the tails object sets its own mappings a few dozen bytes before; its DPLC loader is the one with the
    # matching table right after the Tails loader group
    tgt = map_targets(d, lay)
    maps_off = max((t for t, refs in tgt.items() for r in refs if 0 < best["site"] - r < 0x100), default=None,
                   key=lambda t: max(r for r in tgt[t] if 0 < best["site"] - r < 0x100))
    if maps_off is None:
        raise Sonic2DError("Tails' tails mappings not found")
    for ld in find_loaders(d, lay):
        if ld["plc"] == tails.plc or ld["plc"] >= len(d):
            continue
        try:
            dp = parse_dplc(d, ld["plc"], lay)
            mp = parse_mappings(d, maps_off, lay, len(dp))
        except (Sonic2DError, struct.error, IndexError):
            continue
        if mapping_fits(mp, dp) and abs(ld["code"] - tails.loader) < 0x400:
            best.update({"maps": maps_off, "plc": ld["plc"], "art": ld["art"], "own_set": True})
            return best
    raise Sonic2DError("Tails' tails DPLC not found")


# ------------------------------------------------------------------------------------------------ signposts

def _find_table_for_script(d: bytes, script: bytes, index: int, entries: int) -> int | None:
    for m in re.finditer(re.escape(script), d):
        p = m.start()
        for t in range(max(0, p - 2 * entries - 64) & ~1, p, 2):
            try:
                if t + 2 * index + 2 <= len(d) and t + _u16(d, t + 2 * index) == p and _u16(d, t) == 2 * entries:
                    return t
            except struct.error:
                continue
    return None


def _plc_art_for_vram(d: bytes, vram: int, need_tiles: int = 1) -> int | None:
    """The Nemesis art a PLC entry (u32 art, u16 vram) loads at ``vram`` for an object whose mappings use
    ``need_tiles`` tiles: of the pointers PLC-looking records give for that VRAM address, the tightest fit."""
    votes: dict[int, int] = {}
    for m in re.finditer(re.escape(struct.pack(">H", vram)), d):
        p = m.start()
        if p & 1 or p < 4 or p + 6 > len(d):
            continue
        art = _u32(d, p - 4)
        if 0x200 <= art < len(d) - 2 and not art & 1:
            # the neighbouring record must look like a PLC entry too (another art pointer + VRAM word)
            nxt = _u32(d, p + 2)
            prv = _u32(d, p - 10) if p >= 10 else 0
            if 0x200 <= nxt < len(d) or 0x200 <= prv < len(d):
                votes[art] = votes.get(art, 0) + 1
    # the tightest art that still covers every tile the mappings use (other zones' art at the same address is
    # bigger or smaller), then the one most PLC records name
    cands = [(t - need_tiles, -n, art) for art, n in votes.items() if (t := _u16(d, art) & 0x7FFF) >= need_tiles]
    for _slack, _n, art in sorted(cands):
        try:
            sega_md.nemesis_decompress(d, art)
            return art
        except sega_md.CodecError:
            continue
    return None


def find_signpost(d: bytes, game: Game) -> dict | None:
    """The end-of-act signpost: its animation table (found by its spin script), mappings + art tile (the
    ``move.l #Map,mappings(a0)`` / ``move.w #tile,art_tile(a0)`` pair of the object that animates with it), and art
    (Nemesis through the PLC entry for that tile, S1/S2; uncompressed + DPLC through PLCPtr_EndSigns, S3K)."""
    lay = LAYOUTS[game.layout]
    if game.signpost == "s3k":
        raw = bytes([1, 0, 4, 5, 6, 1, 4, 5, 6, 3, 4, 5, 6, 0xFC])
        p = d.find(raw)
        if p < 8:
            return None
        art, plc = _u32(d, p - 8), _u32(d, p - 4)
        raw2 = d[p + 14:p + 28] if d[p + 14:p + 15] == b"\x01" else None
        # ObjSlot_EndSigns: dc.w 0, tile, $C, 0; dc.l Map; dc.w $300 ...
        maps_off = None
        for q in range(p - 0x80, p - 8, 2):
            if d[q:q + 4] == b"\x00\x0c\x00\x00" and d[q + 8:q + 10] == b"\x03\x00":
                maps_off = _u32(d, q + 4)
                tile = _u16(d, q - 2)
        if maps_off is None:
            return None
        dplc = parse_dplc(d, plc, lay, obj=True)
        maps = parse_mappings(d, maps_off, lay, len(dplc))
        if not mapping_fits(maps, dplc):
            return None
        return {"kind": "s3k", "raw": d[p:p + 14], "raw_knuckles": raw2, "raw_at": p, "art": art, "plc": plc,
                "maps_off": maps_off, "maps": maps, "dplc": dplc, "art_tile": tile}
    if game.signpost == "s1":
        table = _find_table_for_script(d, bytes([1, 0, 1, 2, 3, 0xFF]), 1, 4)
    else:
        table = _find_table_for_script(d, bytes([1, 2, 3, 4, 5, 1, 3, 4, 5, 0, 3, 4, 5, 0xFF]), 1, 5)
    if table is None:
        return None
    pairs = []
    for m in re.finditer(rb"\x43\xf9" + re.escape(struct.pack(">I", table)), d):
        lo, hi = max(0, m.start() - 0x40), m.start() + 0x100
        for n in re.finditer(rb"\x21\x7c(....)\x00\x04\x31\x7c(..)\x00\x02", d[lo:hi], re.S):
            pairs.append((_u32(n.group(1), 0), _u16(n.group(2), 0)))
    best = None
    for maps_off, tile in pairs:
        try:
            maps = parse_mappings(d, maps_off, lay)
        except (Sonic2DError, struct.error):
            continue
        need = max((pc["tile"] + pc["w"] * pc["h"] for f in maps for pc in f), default=1)
        art = _plc_art_for_vram(d, (tile & 0x7FF) * 32, need)
        if art is None:
            continue
        # prefer the table stored right after the animation script (S2's one-player Obj0D_MapUnc_195BE)
        key = abs(maps_off - table)
        if best is None or key < best[0]:
            best = (key, maps_off, maps, tile, art)
    if best is None:
        return None
    _, maps_off, maps, tile, art = best
    return {"kind": game.signpost, "anim": table, "maps_off": maps_off, "maps": maps, "art_tile": tile,
            "art": art, "tiles": sega_md.nemesis_decompress(d, art)}


# ------------------------------------------------------------------------------------------------ rendering

def piece_rects(pieces: list[dict], xflip: bool = False, yflip: bool = False) -> list[dict]:
    """Pieces in object space after the object's own flips (the VDP mirrors each piece around the origin)."""
    out = []
    for pc in pieces:
        w, h = pc["w"] * 8, pc["h"] * 8
        x = -pc["x"] - w if xflip else pc["x"]
        y = -pc["y"] - h if yflip else pc["y"]
        out.append({**pc, "x": x, "y": y, "hf": pc["hf"] ^ int(xflip), "vf": pc["vf"] ^ int(yflip), "pw": w, "ph": h})
    return out


def frame_bbox(pieces: list[dict]) -> tuple[int, int, int, int] | None:
    if not pieces:
        return None
    return (min(p["x"] for p in pieces), min(p["y"] for p in pieces),
            max(p["x"] + p["pw"] for p in pieces), max(p["y"] + p["ph"] for p in pieces))


def draw(canvas: np.ndarray, origin: tuple[int, int], pieces: list[dict], tiles: np.ndarray,
         palette: np.ndarray) -> None:
    """Draw pieces (already flipped by piece_rects) onto an RGBA canvas; the first piece ends up on top, as the VDP
    gives the lower sprite index priority. Tile indices past the streamed tiles draw nothing."""
    ox, oy = origin
    for pc in reversed(pieces):
        w, h = pc["w"], pc["h"]
        block = np.zeros((h * 8, w * 8), np.int16)
        for cx in range(w):
            for cy in range(h):
                t = pc["tile"] + cx * h + cy
                if t < len(tiles):
                    block[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8] = tiles[t]
        if pc["hf"]:
            block = block[:, ::-1]
        if pc["vf"]:
            block = block[::-1, :]
        idx = block + 16 * pc["pal"]
        rgba = palette[np.clip(idx, 0, len(palette) - 1)]
        mask = block != 0
        x0, y0 = ox + pc["x"], oy + pc["y"]
        region = canvas[y0:y0 + h * 8, x0:x0 + w * 8]
        region[mask] = rgba[mask]


def full_palette(char_line: bytes, zone: bytes | None = None, zone_line: int = 1) -> np.ndarray:
    """64 RGBA entries: line 0 = the character's, lines 1-3 from the zone palette when given (else grey ramps so a
    stray piece is visible, not black)."""
    words = list(struct.unpack(">16H", char_line[:32].ljust(32, b"\x00")))
    rest = []
    if zone:
        zw = list(struct.unpack(f">{len(zone) // 2}H", zone[:len(zone) // 2 * 2]))
        lines = [zw[i:i + 16] for i in range(0, len(zw), 16)]
        start = zone_line - 1
        for k in range(3):
            j = k - start
            rest += (lines[j] if 0 <= j < len(lines) else [0x0EEE - 0x0222 * (i // 3) for i in range(16)])[:16]
    else:
        for _ in range(3):
            rest += [(min(7, i // 2) * 0x0222) & 0x0EEE for i in range(16)]
    return sega_md.palette_rgba(words + rest)


# ------------------------------------------------------------------------------------------------ animation engines

def _sb(v: int) -> int:
    """A 68k byte counter: signed after wrap."""
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


class PlayerAnimator:
    """Sonic_Animate / Tails_Animate / Animate_Knuckles, one call per game frame.

    Normal scripts: on expiry the delay byte is reloaded and the next byte is read; bytes >= ``cmd`` are commands
    ($FF restart, $FE n back n, $FD a switch animation, anything else stops). Speed-driven scripts (first byte has
    bit 7 set) are shown at a given ground speed: $FF walk/run (mapping updated every frame, delay
    (0x800-|v|)>>8), $FE roll ((0x400-|v|)>>8), $FD push ((0x800-|v|)>>6), $FC the Tails'-tails directional script
    (delay 3). Ground angle 0, facing right: walk/run frames get no slope offset."""

    def __init__(self, d: bytes, table: int, cmd: int):
        self.d, self.table, self.cmd = d, table, cmd
        self.anim, self.prev, self.af, self.timer, self.mapping = 0, -1, 0, 0, 0
        self.speed = 0
        self.ended: str | None = None

    def script(self, i: int) -> bytes:
        return script_bytes(self.d, self.table, i)

    def state(self):
        return (self.anim, self.prev, self.af, self.timer, self.mapping)

    def set(self, anim: int, speed: int | None = None):
        self.anim, self.ended = anim, None
        if speed is not None:
            self.speed = abs(speed)

    def _do2(self, s: bytes):
        b = s[1 + self.af]
        if b >= self.cmd:
            if b == 0xFF:
                self.af, b = 0, s[1]
            elif b == 0xFE:
                self.af -= s[2 + self.af]
                b = s[1 + self.af]
            elif b == 0xFD:
                self.anim = s[2 + self.af]
                self.ended = "goto"
                return
            else:
                self.ended = "stop"
                return
        self.mapping = b
        self.af += 1

    def step(self):
        if self.anim != self.prev:
            self.prev, self.af, self.timer = self.anim, 0, 0
        s = self.script(self.anim)
        d0 = s[0]
        sp = self.speed
        if d0 & 0x80:
            if d0 == 0xFF:                                   # walk / run
                b = s[1 + self.af]
                if b == 0xFF:
                    self.af, b = 0, s[1]
                self.mapping = b
                self.timer = _sb(self.timer - 1)
                if self.timer < 0:
                    self.timer = max(0, 0x800 - sp) >> 8
                    self.af += 1
                return
            self.timer = _sb(self.timer - 1)
            if self.timer >= 0:
                return
            if d0 == 0xFE:
                self.timer = max(0, 0x400 - sp) >> 8
            elif d0 == 0xFD:
                self.timer = max(0, 0x800 - sp) >> 6
            else:
                self.timer = 3
            self._do2(s)
            return
        self.timer = _sb(self.timer - 1)
        if self.timer >= 0:
            return
        self.timer = d0
        self._do2(s)


class ObjectAnimator(PlayerAnimator):
    """AnimateSprite (generic objects): the frame byte is masked (S1 keeps x/y flip in bits 5/6), commands are the
    bytes with bit 7 set."""

    def __init__(self, d: bytes, table: int, mask: int, flip_bits: bool):
        super().__init__(d, table, 0x80)
        self.mask, self.flip_bits, self.flips = mask, flip_bits, (False, False)

    def state(self):
        return super().state() + self.flips

    def step(self):
        if self.anim != self.prev:
            self.prev, self.af, self.timer = self.anim, 0, 0
        self.timer = _sb(self.timer - 1)
        if self.timer >= 0:
            return
        s = self.script(self.anim)
        self.timer = s[0]
        b = s[1 + self.af]
        if b & 0x80:
            if b == 0xFF:
                self.af, b = 0, s[1]
            elif b == 0xFE:
                self.af -= s[2 + self.af]
                b = s[1 + self.af]
            elif b == 0xFD:
                self.anim, self.ended = s[2 + self.af], "goto"
                return
            else:
                self.ended = "stop"
                return
        self.mapping = b & self.mask
        if self.flip_bits:
            self.flips = (bool(b & 0x20), bool(b & 0x40))
        self.af += 1


class RawAnimator:
    """S3K Animate_Raw: delay byte, frames, a command byte (bit 7; $FC loops). anim_frame is pre-incremented, so the
    first frame byte is only the object's initial frame."""

    def __init__(self, raw: bytes):
        self.raw, self.af, self.timer, self.mapping, self.ended = raw, 0, 0, raw[1], None
        self.anim = None

    def set(self, anim, speed=None):
        pass

    def state(self):
        return (self.af, self.timer, self.mapping)

    def step(self):
        self.timer = _sb(self.timer - 1)
        if self.timer >= 0:
            return
        self.af += 1
        b = self.raw[1 + self.af]
        if b & 0x80:
            self.af = 0
            return
        self.timer = self.raw[0]
        self.mapping = b


@dataclass
class Tick:
    frame: int
    xflip: bool = False
    yflip: bool = False
    anim: int | None = None
    overlay: int | None = None             # Tails' tails mapping frame drawn behind

    def key(self):
        return (self.frame, self.xflip, self.yflip, self.overlay)


class TailsOverlay:
    """Tails' tails: the animation picked from Tails' current one through the selection table, re-picked when it
    changes (Obj05 / Obj_Tails_Tail)."""

    def __init__(self, d: bytes, info: dict, cmd: int):
        self.d, self.info = d, info
        self.anim = PlayerAnimator(d, info["anim"], cmd)
        self.parent_prev = -1

    def step(self, parent_anim: int):
        if parent_anim != self.parent_prev:
            self.parent_prev = parent_anim
            self.anim.set(self.d[self.info["select"] + parent_anim])
        self.anim.step()
        return self.anim.mapping

    def state(self):
        return (self.parent_prev,) + self.anim.state()


def simulate(seq: list[dict], animator, overlay: TailsOverlay | None = None, max_frames: int = MAX_SIM,
             final_hold: int = 0) -> dict:
    """Run a clip one game frame at a time: every item but the last for its ``frames``; the last until its state
    repeats (the loop), its script switches animation or stops (then ``final_hold`` more frames of the frame it ended
    on), or ``max_frames``. Items are {anim, frames, speed} for ``animator``, {animator, frames} for another engine
    (the S3K signpost's raw script) or {static: mapping frame, frames} (a held frame; the last one loops)."""
    ticks: list[Tick] = []
    loop_start, end = None, None
    for i, item in enumerate(seq):
        last = i == len(seq) - 1
        if "static" in item:
            n = item.get("frames") or 1
            ticks += [Tick(item["static"])] * n
            if last:
                loop_start, end = len(ticks) - n, "loop"
            continue
        a = item.get("animator") or animator
        if item.get("anim") is not None:
            a.set(item["anim"], item.get("speed"))
        seen: dict = {}
        count = item.get("frames")
        k = 0
        while True:
            if not last and count is not None and k >= count:
                break
            if last:
                st = a.state() + ((overlay.state(),) if overlay else ())
                if st in seen:
                    loop_start, end = seen[st], "loop"
                    break
                seen[st] = len(ticks)
                if len(ticks) >= max_frames:
                    end = "cut"
                    break
            cur_anim = getattr(a, "anim", None)
            a.step()
            ov = overlay.step(cur_anim if isinstance(cur_anim, int) else 0) if overlay else None
            fl = getattr(a, "flips", (False, False))
            ticks.append(Tick(a.mapping, fl[0], fl[1], cur_anim, ov))
            k += 1
            if getattr(a, "ended", None):
                if last:
                    end = a.ended
                    ticks += [ticks[-1]] * final_hold
                    break
                a.ended = None
    # The loop found is the first repeated engine state; the picture may repeat earlier (a reset animation shows its
    # first frame for one tick before the delay counter settles): pull the loop start back while it does.
    if loop_start is not None and loop_start < len(ticks):
        while loop_start > 0 and ticks[loop_start - 1].key() == ticks[-1].key() and len(ticks) - loop_start > 1:
            ticks.pop()
            loop_start -= 1
    return {"ticks": ticks, "loop_start": loop_start, "end": end}


def runs_of(ticks: list[Tick], loop_start: int | None) -> list[dict]:
    """Consecutive identical ticks -> frames with durations (game frames); a run never spans the loop point."""
    out: list[dict] = []
    for i, t in enumerate(ticks):
        if out and out[-1]["tick"].key() == t.key() and i != loop_start:
            out[-1]["frames"] += 1
        else:
            out.append({"tick": t, "frames": 1, "start": i})
    return out


# ------------------------------------------------------------------------------------------------ sprite sources

@dataclass
class SpriteSet:
    """Something drawable by mapping frame: pieces + the tiles each frame sees + a palette."""
    maps: list
    tiles_for: object                      # frame -> np.ndarray (n, 8, 8)
    palette: np.ndarray
    pal_base: int = 0                      # art_tile palette line

    def layer(self, frame: int, xflip=False, yflip=False):
        if frame >= len(self.maps):
            return []
        ps = piece_rects(self.maps[frame], xflip, yflip)
        if self.pal_base:
            ps = [{**p, "pal": (p["pal"] + self.pal_base) & 3} for p in ps]
        return ps


def player_set(d: bytes, ch: Character, palette: np.ndarray) -> SpriteSet:
    cache: dict[int, np.ndarray] = {}

    def tiles(f):
        if f not in cache:
            cache[f] = sega_md.tiles_to_indices(ch.tiles(d, f))
        return cache[f]
    return SpriteSet(ch.maps, tiles, palette)


def tails_overlay_set(d: bytes, lay: Layout, info: dict, tails: Character, palette: np.ndarray) -> SpriteSet:
    if not info.get("own_set"):
        return player_set(d, tails, palette)
    dplc = parse_dplc(d, info["plc"], lay)
    maps = parse_mappings(d, info["maps"], lay, len(dplc))
    cache: dict[int, np.ndarray] = {}

    def tiles(f):
        if f not in cache:
            raw = b"".join(d[info["art"] + 32 * a:info["art"] + 32 * (a + n)] for a, n in dplc[f])
            cache[f] = sega_md.tiles_to_indices(raw)
        return cache[f]
    return SpriteSet(maps, tiles, palette)


def signpost_set(d: bytes, sp: dict, palette: np.ndarray) -> SpriteSet:
    pal_base = (sp["art_tile"] >> 13) & 3
    if sp["kind"] == "s3k":
        cache: dict[int, np.ndarray] = {}

        def tiles(f):
            if f not in cache:
                raw = b"".join(d[sp["art"] + 32 * a:sp["art"] + 32 * (a + n)] for a, n in sp["dplc"][f])
                cache[f] = sega_md.tiles_to_indices(raw)
            return cache[f]
        return SpriteSet(sp["maps"], tiles, palette, pal_base)
    t = sega_md.tiles_to_indices(sp["tiles"])
    return SpriteSet(sp["maps"], lambda f: t, palette, pal_base)


def render_clip(ticks_runs: list[dict], main: SpriteSet, behind: SpriteSet | None = None, margin: int = 2):
    """Every run's picture on one canvas: (images per run, origin (x, y) on the canvas, canvas (w, h), bboxes)."""
    layers = []
    for r in ticks_runs:
        t = r["tick"]
        ls = []
        if behind is not None and t.overlay is not None:
            ls.append((behind, behind.layer(t.overlay, t.xflip, t.yflip), t.overlay))
        ls.append((main, main.layer(t.frame, t.xflip, t.yflip), t.frame))
        layers.append(ls)
    boxes = [frame_bbox([p for _, ps, _ in ls for p in ps]) for ls in layers]
    real = [b for b in boxes if b]
    if real:
        x0, y0 = min(b[0] for b in real), min(b[1] for b in real)
        x1, y1 = max(b[2] for b in real), max(b[3] for b in real)
    else:
        x0 = y0 = -8
        x1 = y1 = 8
    ox, oy = margin - x0, margin - y0
    w, h = x1 - x0 + 2 * margin, y1 - y0 + 2 * margin
    images = []
    for ls in layers:
        im = np.zeros((h, w, 4), np.uint8)
        for ss, ps, f in ls:
            draw(im, (ox, oy), ps, ss.tiles_for(f), ss.palette)
        images.append(im)
    return images, (ox, oy), (w, h), boxes


# ------------------------------------------------------------------------------------------------ clips

def seq_is_signpost(plan: dict) -> bool:
    """A clip drawn from the signpost object instead of the player (anim None)."""
    return plan["name"] == "signpost" or plan["seq"][0].get("anim", 0) is None


class Extractor:
    """One ROM: its game profile, characters, palettes and signpost, and the clips each character can give."""

    def __init__(self, d: bytes, meta: dict | None = None):
        self.d, self.meta = d, meta or {}
        self.game = identify(d)
        self.lay = LAYOUTS[self.game.layout]
        self.chars = find_characters(d, self.game)
        self.pal_table = find_palette_table(d)
        zone = None
        if self.game.zone_pal is not None:
            try:
                zone = palette_entry(d, self.pal_table, self.game.zone_pal)
            except (Sonic2DError, struct.error):
                zone = None
        self.zone = zone
        self.signpost = None
        if self.game.signpost:
            try:
                self.signpost = find_signpost(d, self.game)
            except (Sonic2DError, struct.error, sega_md.CodecError):
                self.signpost = None

    # -- identity
    def rom_info(self) -> dict:
        d = self.d
        return {"title": self.game.title, "game": self.game.key, "header": header(d), "size": len(d),
                "crc32": f"{zlib.crc32(d) & 0xFFFFFFFF:08x}", "sha1": hashlib.sha1(d).hexdigest(), **self.meta}

    def palette(self, char: str) -> np.ndarray:
        ch = self.chars[char]
        z = self.zone
        return full_palette(ch.palette, z["data"] if z else None, z["line"] if z else 1)

    def anim_name(self, char: str, i: int) -> str:
        names = self.game.names.get(char, [])
        return names[i] if i < len(names) else f"anim_{i:02x}"

    # -- clip plans
    def plans(self, char: str) -> list[dict]:
        """The requested clips (spin dash, jump, level complete, ...) then every other named animation."""
        ch = self.chars[char]
        out = []
        for spec in self.game.clips.get(char, []):
            if seq_is_signpost(spec):
                if self.signpost is None:
                    continue
            out.append(dict(spec, kind="requested"))
        names_used = {p["name"] for p in out}
        n = anim_count(self.d, ch.anim)
        for i in range(n):
            name = self.anim_name(char, i)
            if name in names_used or name.startswith(("dummy", "blank", "null")):
                continue
            s = script_bytes(self.d, ch.anim, i)
            frames = [b for b in s[1:16] if b < self.lay.player_cmd]
            if not frames or all(f == 0 for f in frames):
                continue
            names_used.add(name)
            speed = NOMINAL_SPEED.get(name, 0) if s[0] & 0x80 else None
            out.append({"name": name, "seq": [_a(i, speed=speed)], "what": f"animation {i:#04x} ({name})",
                        "note": "", "kind": "animation"})
        return out

    def simulate(self, char: str, plan: dict) -> dict:
        ch = self.chars[char]
        seq = plan["seq"]
        if seq_is_signpost(plan):
            return self._simulate_signpost(char)
        a = PlayerAnimator(self.d, ch.anim, self.lay.player_cmd)
        ov = TailsOverlay(self.d, ch.tails, 0xF0 if self.lay.name == "s2" else 0xFC) if ch.tails else None
        items = [dict(x) for x in seq]
        for x in items:
            if x.get("speed") is None and x.get("anim") is not None:
                s = script_bytes(self.d, ch.anim, x["anim"])
                if s[0] & 0x80:
                    x["speed"] = NOMINAL_SPEED.get(self.anim_name(char, x["anim"]), 0)
        sim = simulate(items, a, ov, final_hold=0)
        sim["sets"] = (player_set(self.d, ch, self.palette(char)),
                       tails_overlay_set(self.d, self.lay, ch.tails, ch, self.palette(char)) if ch.tails else None)
        return sim

    def _simulate_signpost(self, char: str) -> dict:
        sp = self.signpost
        pal = self.palette(char)
        if sp["kind"] == "s3k":
            raw = sp["raw_knuckles"] if char == "knuckles" and sp.get("raw_knuckles") else sp["raw"]
            face = SIGN_FACE["s3k"].get(char, 0)
            # falls spinning (Animate_Raw) until it lands, keeps spinning $40 frames, then shows the player's face
            seq = [{"animator": RawAnimator(raw), "frames": 96}, {"static": face, "frames": 60}]
            sim = simulate(seq, None)
        else:
            a = ObjectAnimator(self.d, sp["anim"], self.lay.obj_mask, self.lay.name == "s1")
            if sp["kind"] == "s1":            # Sign_Spin: 3 spin cycles of 60+1 frames, then the Sonic face
                seq = [_a(1, 61), _a(2, 61), _a(3)]
            else:                             # Obj0D: anim 1 for a frame, anim 2 for 61, then the player's face
                seq = [_a(1, 1), _a(2, 61), _a(SIGN_FACE["s2"].get(char, 3))]
            sim = simulate(seq, a)
        sim["sets"] = (signpost_set(self.d, sp, pal), None)
        return sim

    def clip(self, char: str, plan: dict) -> dict:
        """Render one clip: {'images', 'runs', 'origin', 'canvas', 'index'} (index = sheet.json minus file cells)."""
        sim = self.simulate(char, plan)
        main, behind = sim["sets"]
        runs = runs_of(sim["ticks"], sim["loop_start"])
        images, origin, canvas, boxes = render_clip(runs, main, behind)
        loop_run = None
        if sim["loop_start"] is not None:
            loop_run = next(k for k, r in enumerate(runs) if r["start"] == sim["loop_start"])
        sign = seq_is_signpost(plan)
        frames = []
        for k, r in enumerate(runs):
            t = r["tick"]
            named = isinstance(t.anim, int) and not sign
            frames.append({"index": k, "duration_frames": r["frames"],
                           "duration_ms": round(r["frames"] * 1000 / FPS, 3),
                           "start_frame": r["start"], "mapping_frame": t.frame, "xflip": t.xflip, "yflip": t.yflip,
                           "anim": t.anim if isinstance(t.anim, int) else None,
                           "anim_name": self.anim_name(char, t.anim) if named else None,
                           "overlay_frame": t.overlay, "origin": list(origin), "hotspot": list(origin),
                           "bbox": list(boxes[k]) if boxes[k] else None})
        total = sum(f["duration_frames"] for f in frames)
        loop = None
        if loop_run is not None:
            loop = {"start": loop_run, "length": len(frames) - loop_run, "frames": list(range(loop_run, len(frames))),
                    "start_game_frame": sim["loop_start"], "length_game_frames": total - sim["loop_start"]}
        ch = self.chars[char]
        anims = []
        for x in plan["seq"]:
            if x.get("anim") is None:
                continue
            off = ch.anim + _u16(self.d, ch.anim + 2 * x["anim"])
            s = script_bytes(self.d, ch.anim, x["anim"], 64)
            end = next((j for j in range(1, len(s)) if s[j] >= self.lay.player_cmd), len(s) - 1)
            arg = 1 if s[end] in (0xFE, 0xFD) else 0
            anims.append({"id": x["anim"], "name": self.anim_name(char, x["anim"]), "script": f"0x{off:x}",
                          "bytes": s[:end + 1 + arg].hex(), "game_frames": x.get("frames"), "speed": x.get("speed")})
        index = {"tool": f"gbox.sonic2d_sprites {VERSION}", "game": self.game.key, "title": self.game.title,
                 "character": char, "clip": plan["name"], "what": plan.get("what", ""), "note": plan.get("note", ""),
                 "kind": plan.get("kind", ""), "fps": FPS, "frame_unit": "game frames (NTSC 60 Hz vblanks)",
                 "canvas": list(canvas), "origin": list(origin), "hotspot": list(origin),
                 "origin_meaning": "the object's x_pos/y_pos (sprite origin) on the canvas, the same pixel in every "
                                   "frame: place the clip by putting this pixel on the spot",
                 "loop": loop, "end": sim["end"], "total_game_frames": total,
                 "total_ms": round(total * 1000 / FPS, 3), "animations": anims, "frames": frames,
                 "source": self._source(char, plan)}
        return {"images": images, "runs": runs, "origin": origin, "canvas": canvas, "index": index}

    def _source(self, char: str, plan: dict) -> dict:
        ch = self.chars[char]
        if seq_is_signpost(plan):
            sp = self.signpost
            src = {"object": "signpost", "mappings": f"0x{sp['maps_off']:x}", "art": f"0x{sp['art']:x}",
                   "art_tile": f"0x{sp['art_tile']:x}",
                   "art_format": "uncompressed + object DPLC" if sp["kind"] == "s3k" else "Nemesis (PLC entry)"}
            if sp["kind"] == "s3k":
                src.update({"dplc": f"0x{sp['plc']:x}", "raw_script": f"0x{sp['raw_at']:x}"})
            else:
                src["anim_table"] = f"0x{sp['anim']:x}"
            return src
        src = {"art": f"0x{ch.art:x}", "dplc": f"0x{ch.plc:x}", "mappings": f"0x{ch.maps_off:x}",
               "anim_table": f"0x{ch.anim:x}", "palette_entry": ch.pal_entry, "palette": ch.palette.hex()}
        if ch.extra_art is not None:
            src["extra_art"] = {"offset": f"0x{ch.extra_art:x}", "from_frame": ch.extra_from}
        if ch.tails:
            src["tails_overlay"] = {k: (f"0x{v:x}" if isinstance(v, int) and k != "own_set" else v)
                                    for k, v in ch.tails.items()}
        return src


# ------------------------------------------------------------------------------------------------ files

def _scale(img: np.ndarray, k: int) -> np.ndarray:
    return img.repeat(k, axis=0).repeat(k, axis=1) if k > 1 else img


def package_clip(clip: dict, want_mp4: bool = True) -> tuple[dict, dict[str, bytes], str | None]:
    """Files of one clip: frames/frame_NNNN.png (timeline order), sheet.png (unique pictures) + sheet.json,
    preview.apng (+ preview.webp), clip.mp4 (4x, over the collection grey; ffmpeg when present)."""
    from . import sprite_capture as SC
    images, index = clip["images"], dict(clip["index"])
    files: dict[str, bytes] = {}
    uniq, which = [], []
    digests: dict[bytes, int] = {}
    for im in images:
        h = hashlib.sha1(im.tobytes()).digest()
        if h not in digests:
            digests[h] = len(uniq)
            uniq.append(im)
        which.append(digests[h])
    sheet, cells, cols, rows = SC.build_sheet(uniq)
    files["sheet.png"] = SC.png_bytes(sheet)
    frames = []
    for k, (im, f) in enumerate(zip(images, index["frames"])):
        name = f"frames/frame_{k:04d}.png"
        files[name] = SC.png_bytes(im)
        frames.append({**f, "file": name, "image": which[k], "sheet": cells[which[k]]})
    index.update({"frames": frames, "images": len(uniq), "columns": cols, "rows": rows})
    durs = [max(1, int(round(f["duration_ms"]))) for f in frames]
    files["preview.apng"] = SC.preview_bytes(images, durs, "apng")
    try:
        from PIL import features
        if features.check("webp_anim"):
            files["preview.webp"] = SC.preview_bytes(images, durs, "webp")
    except Exception:                                          # noqa: BLE001 - the WebP preview is a bonus
        pass
    reason = None
    if want_mp4:
        try:
            files["clip.mp4"] = SC.mp4_bytes([_scale(i, MP4_SCALE) for i in images], [f["duration_ms"] for f in frames],
                                             FPS, loops=3 if index["loop"] else 1,
                                             loop=index["loop"], background=(38, 40, 48))
            index["mp4"] = {"scale": MP4_SCALE, "loops": 3 if index["loop"] else 1}
        except Exception as e:                                 # noqa: BLE001 - ffmpeg missing / failing is reported
            reason = str(e)
    else:
        reason = "not requested"
    index["mp4_unavailable"] = reason
    files["sheet.json"] = json.dumps(index, indent=1).encode()
    return index, files, reason


def write_clip(dest: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        p = Path(dest) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def animation_entry(clip_slug: str, index: dict, files: dict[str, bytes]) -> dict:
    """The meta.animations[] row of a clip (the same shape sprite_capture writes, plus game-frame timing)."""
    base = f"clips/{clip_slug}"
    return {"clip": clip_slug, "name": index["clip"], "what": index.get("what", ""), "dir": base,
            "sheet": f"{base}/sheet.png", "index": f"{base}/sheet.json", "preview": f"{base}/preview.apng",
            "webp": f"{base}/preview.webp" if "preview.webp" in files else None,
            "mp4": f"{base}/clip.mp4" if "clip.mp4" in files else None,
            "frames": len(index["frames"]), "fps": FPS, "game_frames": index["total_game_frames"],
            "duration_s": round(index["total_game_frames"] / FPS, 3), "loop": index["loop"],
            "canvas": index["canvas"], "origin": index["origin"], "kind": index.get("kind", "")}


def overview(clips: list[tuple[str, np.ndarray]], cell: int = 0) -> np.ndarray:
    """A contact sheet of each clip's first picture (the entry's model image), origins aligned per row."""
    pics = [im for _, im in clips if im is not None]
    if not pics:
        return np.zeros((8, 8, 4), np.uint8)
    cw = cell or max(p.shape[1] for p in pics)
    ch = max(p.shape[0] for p in pics)
    cols = max(1, min(8, math.ceil(math.sqrt(len(pics)))))
    rows = math.ceil(len(pics) / cols)
    out = np.zeros((rows * ch, cols * cw, 4), np.uint8)
    for k, p in enumerate(pics):
        y, x = (k // cols) * ch + (ch - p.shape[0]), (k % cols) * cw + (cw - p.shape[1]) // 2
        out[y:y + p.shape[0], x:x + p.shape[1]] = p
    return out


def extract_character(ex: Extractor, char: str, out: Path, only: list[str] | None = None, want_mp4: bool = True,
                      progress=lambda pct, msg: None) -> dict:
    """Every clip of one character under ``out/clips/<clip>/`` + ``out/overview.png``: {animations, overview, ...}."""
    from . import sprite_capture as SC
    out = Path(out)
    plans = [p for p in ex.plans(char) if not only or p["name"] in only]
    anims, firsts, mp4_missing = [], [], None
    for k, plan in enumerate(plans):
        progress(100 * k / max(1, len(plans)), f"{CHAR_NAMES.get(char, char)}: {plan['name']}")
        clip = ex.clip(char, plan)
        slug = re.sub(r"[^a-z0-9_]+", "_", plan["name"].lower()).strip("_")
        index, files, reason = package_clip(clip, want_mp4)
        mp4_missing = mp4_missing or reason
        write_clip(out / "clips" / slug, files)
        anims.append(animation_entry(slug, index, files))
        if plan.get("kind") == "requested":
            firsts.append((slug, clip["images"][0]))
    ov = overview(firsts or [(None, None)])
    (out / "overview.png").write_bytes(SC.png_bytes(ov))
    return {"animations": anims, "overview": str(out / "overview.png"), "clips": len(anims),
            "requested": [a["clip"] for a in anims if a["kind"] == "requested"], "mp4_unavailable": mp4_missing}


def inventory(src) -> dict:
    d, meta = read_rom(src)
    ex = Extractor(d, meta)
    chars = {}
    for name, ch in ex.chars.items():
        chars[name] = {"art": f"0x{ch.art:x}", "extra_art": f"0x{ch.extra_art:x}" if ch.extra_art else None,
                       "extra_from": ch.extra_from, "dplc": f"0x{ch.plc:x}", "mappings": f"0x{ch.maps_off:x}",
                       "frames": len(ch.maps), "anim_table": f"0x{ch.anim:x}", "animations": anim_count(d, ch.anim),
                       "palette_entry": ch.pal_entry, "palette": ch.palette.hex(),
                       "tails_overlay": bool(ch.tails),
                       "clips": [p["name"] for p in ex.plans(name)]}
    sp = ex.signpost
    return {"rom": ex.rom_info(), "layout": ex.lay.name, "palette_table": f"0x{ex.pal_table:x}",
            "zone_palette": ex.zone and {"entry": ex.zone["index"], "line": ex.zone["line"]},
            "signpost": sp and {"kind": sp["kind"], "mappings": f"0x{sp['maps_off']:x}", "art": f"0x{sp['art']:x}",
                                "art_tile": f"0x{sp['art_tile']:x}", "frames": len(sp["maps"])},
            "characters": chars}


# ------------------------------------------------------------------------------------------------ collection reader

# (dedicated reader name, game key, title test) -- registered in gbox.characters.DEDICATED
TITLE_TESTS = {
    "sonic1": re.compile(r"^sonic the hedgehog( \((usa|europe|japan|world|korea|usa, europe|japan, korea)[^)]*\))*"
                         r"( \(rev [a-z0-9]+\))?$"),
    "sonic2": re.compile(r"^sonic the hedgehog 2( \([^)]*\))*$"),
    "sonic3": re.compile(r"^sonic the hedgehog 3( \([^)]*\))*$"),
    "s3k": re.compile(r"^sonic (&|and) knuckles \+ sonic the hedgehog 3( \([^)]*\))*$"),
    "sk": re.compile(r"^sonic (&|and) knuckles( \([^)]*\))*$"),
}


def title_test(key: str):
    rx = TITLE_TESTS[key]
    return lambda t, p: p == "genesis" and rx.match((t or "").strip().lower()) is not None


def roster(key: str) -> list[dict]:
    g = GAMES[key]
    return [{"key": c, "slug": f"{key}_{c}", "name": f"{CHAR_NAMES[c]} ({g.title})", "char": c, "game": key,
             "aliases": [CHAR_NAMES[c], f"{g.title} {CHAR_NAMES[c]}", f"{key}_{c}"], "kind": "character"}
            for c in g.chars]


def extract_run(ctx, game: dict, entry: dict, work) -> dict:
    """characters op=collect / extract: one character's clips from the catalog ROM."""
    from .models import CatalogEntry
    from .tools import rom_path
    src = rom_path(CatalogEntry.model_validate(game), ctx.config)
    d, meta = read_rom(src)
    ex = Extractor(d, meta)
    want = entry.get("game") or entry["slug"].split("_")[0]
    if ex.game.key != want:
        raise Sonic2DError(f"{Path(src).name} is {ex.game.title} ({header(d)['serial']}), not {GAMES[want].title}")
    char = entry.get("char") or entry["key"]
    if char not in ex.chars:
        raise Sonic2DError(f"{CHAR_NAMES.get(char, char)} is not in this ROM (found {sorted(ex.chars)})")
    work = Path(work)
    prog = getattr(ctx, "progress", lambda p, m: None)
    res = extract_character(ex, char, work, progress=lambda p, m: prog(20 + 0.6 * p, m))
    ch = ex.chars[char]
    req = ", ".join(res["requested"])
    return {"files": [work / "overview.png", work / "clips"], "roles": {}, "kind": "sprites",
            "tool": f"gbox.sonic2d_sprites {VERSION}",
            "source_files": [f"{Path(src).name}: art 0x{ch.art:x}, DPLC 0x{ch.plc:x}, mappings 0x{ch.maps_off:x}, "
                             f"animations 0x{ch.anim:x}"],
            "notes": f"{res['clips']} animation clips decoded from the ROM ({req} + every named animation), "
                     f"frame-exact at 60 fps; MP4: {res['mp4_unavailable'] or 'yes'}",
            "extra": {"picture": "2d", "animations": res["animations"], "sonic2d_reader": READER_VERSION,
                      "sonic2d": {"game": ex.game.key, "character": char, "rom": ex.rom_info()}}}


# ------------------------------------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sonic 1/2/3/S&K player sprite animations from the ROM")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("inventory")
    a.add_argument("rom")
    b = sub.add_parser("extract")
    b.add_argument("rom")
    b.add_argument("--out", required=True)
    b.add_argument("--char", action="append")
    b.add_argument("--clips", help="comma-separated clip names (default: all)")
    b.add_argument("--no-mp4", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "inventory":
        print(json.dumps(inventory(args.rom), indent=1))
        return 0
    d, meta = read_rom(args.rom)
    ex = Extractor(d, meta)
    only = [c.strip() for c in args.clips.split(",")] if args.clips else None
    t0 = time.time()
    for char in args.char or list(ex.chars):
        r = extract_character(ex, char, Path(args.out) / f"{ex.game.key}_{char}", only, not args.no_mp4)
        print(f"{ex.game.key}_{char}: {r['clips']} clips ({', '.join(r['requested'])}) mp4: "
              f"{r['mp4_unavailable'] or 'yes'}")
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

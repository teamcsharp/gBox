"""Sonic 2D (Mega Drive) sprite animation extractor + collage (gbox.sonic2d_sprites, gbox.sprite_collage,
gbox.formats.sega_md).

Synthetic tests build the codecs' streams, the three engines' mapping/DPLC/script formats and a small Sonic 2 shaped
ROM (loader / Animate / palette code shapes) so discovery, the frame-exact simulation, canvas alignment and the clip
files are checked without a cartridge. The owned-ROM tests pin what discovery finds in the operator's dumps (cached at
~/gBox_alt/gbox-cache/<game_id>/source.zip, identified by the ROM's SHA-1) and skip when a dump is not on this machine.
"""
from __future__ import annotations

import json
import os
import random
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import sonic2d_sprites as S
from gbox import sprite_collage as SC
from gbox.formats import sega_md as M


# ------------------------------------------------------------------------------------------------ codecs

@pytest.mark.parametrize("xor", [False, True])
def test_nemesis_round_trip(xor):
    rng = random.Random(5)
    tiles = bytes(rng.choice([0x00, 0x11, 0x12, 0x21, 0xFF, 0x3C]) for _ in range(32 * 24))
    assert M.nemesis_decompress(M.nemesis_compress(tiles, xor)) == tiles
    noise = bytes(rng.randrange(256) for _ in range(32 * 3))
    assert M.nemesis_decompress(M.nemesis_compress(noise, xor)) == noise


def test_nemesis_short_codes_and_inline_escape():
    # one tile; code table: nybble 0 run 8 = code "0" (1 bit), nybble 1 run 8 = code "10" (2 bits)
    stream = bytes([0x00, 0x01, 0x80, 0x71, 0x00, 0x81, 0x72, 0x02, 0xFF])
    # rows: 0,0,1,1,0,0, then two inline rows of nybble 5 run 8: 111111 111 0101 each
    bits = "0" "0" "10" "10" "0" "0" + "111111" + "1110101" + "111111" + "1110101"
    bits += "0" * (-len(bits) % 8)
    stream += int(bits, 2).to_bytes(len(bits) // 8, "big")
    out, end = M.nemesis_decompress(stream, 0, with_end=True)
    rows = [out[i:i + 4] for i in range(0, 32, 4)]
    assert rows == [b"\x00" * 4] * 2 + [b"\x11" * 4] * 2 + [b"\x00" * 4] * 2 + [b"\x55" * 4] * 2
    assert end == len(stream)
    with pytest.raises(M.CodecError):
        M.nemesis_decompress(b"\x00\x00\xff")              # zero tiles


def test_kosinski_known_stream_and_round_trip():
    # literal 'A' (bit 1), then the end marker (bits 0,1 + 00 F0 00); description field 0b101 little-endian
    assert M.kosinski_decompress(bytes([0x05, 0x00, 0x41, 0x00, 0xF0, 0x00])) == b"A"
    rng = random.Random(7)
    for n in (0, 1, 15, 16, 17, 300, 2500):
        data = bytes(rng.choice(b"abcab\x00\x00\xff") for _ in range(n)) + bytes(rng.randrange(256) for _ in range(n // 9))
        packed = M.kosinski_compress(data)
        assert M.kosinski_decompress(packed) == data
    long_run = b"\x07" * 700 + b"xyz" * 90
    assert len(M.kosinski_compress(long_run)) < len(long_run) // 4
    assert M.kosinski_decompress(M.kosinski_compress(long_run)) == long_run


def test_tiles_and_palette():
    tile = bytes([0x12, 0x34, 0x56, 0x78] + [0] * 28)
    a = M.tiles_to_indices(tile)
    assert a.shape == (1, 8, 8) and list(a[0, 0]) == [1, 2, 3, 4, 5, 6, 7, 8]
    pal = M.palette_rgba([0x0000, 0x000E, 0x00E0, 0x0E00] + [0x0EEE] * 12)
    assert pal[0, 3] == 0 and tuple(pal[1]) == (255, 0, 0, 255) and tuple(pal[2][:3]) == (0, 255, 0)
    assert tuple(pal[3][:3]) == (0, 0, 255) and M.md_color(0x0444) == (73, 73, 73)


# ------------------------------------------------------------------------------------------------ tables

def _table(frames: list[bytes]) -> bytes:
    head = 2 * len(frames)
    offs, body = [], b""
    for f in frames:
        offs.append(head + len(body))
        body += f
        if len(body) % 2:
            body += b"\x00"
    return b"".join(struct.pack(">H", o) for o in offs) + body


def _map_frame(layout, pieces):
    lay = S.LAYOUTS[layout]
    out = struct.pack(">B" if lay.map_count == 1 else ">H", len(pieces))
    for y, w, h, tile, x in pieces:
        size = ((w - 1) << 2) | (h - 1)
        if lay.piece == 5:
            out += struct.pack(">bBHb", y, size, tile, x)
        elif lay.piece == 8:
            out += struct.pack(">bBHHh", y, size, tile, tile >> 1, x)
        else:
            out += struct.pack(">bBHh", y, size, tile, x)
    return out


def _dplc_frame(layout, entries):
    lay = S.LAYOUTS[layout]
    head = struct.pack(">B" if lay.dplc_count == 1 else ">H", len(entries))
    return head + b"".join(struct.pack(">H", ((n - 1) << 12) | t) for t, n in entries)


@pytest.mark.parametrize("layout", ["s1", "s2", "s3k"])
def test_mappings_and_dplc_decode(layout):
    lay = S.LAYOUTS[layout]
    maps = _table([_map_frame(layout, [(-16, 2, 4, 0x2000 | 0x0800 | 3, -8), (0, 1, 1, 0x1000 | 11, 4)]),
                   _map_frame(layout, [])])
    m = S.parse_mappings(maps, 0, lay)
    assert len(m) == 2 and m[1] == []
    a, b = m[0]
    assert (a["x"], a["y"], a["w"], a["h"], a["tile"], a["pal"], a["hf"], a["vf"]) == (-8, -16, 2, 4, 3, 1, 1, 0)
    assert (b["x"], b["tile"], b["vf"], b["w"], b["h"]) == (4, 11, 1, 1, 1)
    dplc = _table([_dplc_frame(layout, [(0x10, 8), (0x200, 4)]), _dplc_frame(layout, [])])
    assert S.parse_dplc(dplc, 0, lay) == [[(0x10, 8), (0x200, 4)], []]
    assert S.mapping_fits(m, [[(0, 12)], []]) and not S.mapping_fits(m, [[(0, 11)], []])


def test_s3k_object_dplc_format():
    # Perform_DPLC: count-1, then first_tile << 4 | tiles-1
    t = _table([struct.pack(">HH", 0, (0x20 << 4) | 11), struct.pack(">HHH", 1, (0x3 << 4) | 0, (0x8 << 4) | 15)])
    assert S.parse_dplc(t, 0, S.LAYOUTS["s3k"], obj=True) == [[(0x20, 12)], [(3, 1), (8, 16)]]


# ------------------------------------------------------------------------------------------------ animation engines

def _anim_rom(scripts: list[bytes]) -> bytes:
    return _table(scripts)


def _frames(sim):
    return [(t.frame) for t in sim["ticks"]]


def test_player_script_durations_loop_back_and_switch():
    d = _anim_rom([bytes([2, 10, 11, 12, 0xFF]),            # 0: loop, each frame 3 ticks
                   bytes([0, 20, 21, 22, 0xFE, 2]),          # 1: back 2 -> loops 21, 22
                   bytes([1, 30, 0xFD, 0]),                  # 2: switch to 0
                   bytes([0xFF, 40, 41, 0xFF]),              # 3: walk-style speed script
                   bytes([0xFE, 50, 51, 0xFF])])             # 4: roll-style
    a = S.PlayerAnimator(d, 0, 0xF0)
    sim = S.simulate([S._a(0)], a)
    runs = S.runs_of(sim["ticks"], sim["loop_start"])
    assert [(r["tick"].frame, r["frames"]) for r in runs] == [(10, 3), (11, 3), (12, 3)]
    assert sim["loop_start"] == 0 and sim["end"] == "loop"
    sim = S.simulate([S._a(1)], S.PlayerAnimator(d, 0, 0xF0))
    runs = S.runs_of(sim["ticks"], sim["loop_start"])
    assert [r["tick"].frame for r in runs] == [20, 21, 22] and runs[1]["start"] == sim["loop_start"] == 1
    sim = S.simulate([S._a(2)], S.PlayerAnimator(d, 0, 0xF0))
    assert sim["end"] == "goto" and _frames(sim) == [30, 30, 30]       # shown 2 ticks + the tick the $FD is read
    # walk at $400: (0x800 - 0x400) >> 8 = 4 -> 5 ticks per frame; at $700: 1 -> 2 ticks
    for speed, ticks in ((0x400, 5), (0x700, 2), (0x900, 1)):
        sim = S.simulate([S._a(3, speed=speed)], S.PlayerAnimator(d, 0, 0xF0))
        runs = S.runs_of(sim["ticks"], sim["loop_start"])
        assert sorted((r["tick"].frame, r["frames"]) for r in runs) == [(40, ticks), (41, ticks)]
        assert sim["loop_start"] == 0                       # a whole-clip loop, rotated to start on a frame
    # roll at 0: (0x400 - 0) >> 8 = 4 -> 5 ticks
    sim = S.simulate([S._a(4, speed=0)], S.PlayerAnimator(d, 0, 0xF0))
    assert [r["frames"] for r in S.runs_of(sim["ticks"], sim["loop_start"])] == [5, 5]


def test_sequence_then_loop_and_command_threshold():
    d = _anim_rom([bytes([0, 1, 2, 0xFF]), bytes([0, 5, 6, 0xFF])])
    sim = S.simulate([S._a(0, frames=3), S._a(1)], S.PlayerAnimator(d, 0, 0xF0))
    assert _frames(sim)[:3] == [1, 2, 1] and sim["loop_start"] == 3 and _frames(sim)[3:] == [5, 6]
    # S1's Sonic treats every byte >= $80 as a command; S3K only >= $FC
    d = _anim_rom([bytes([0, 0x90, 0xFF])])
    assert _frames(S.simulate([S._a(0)], S.PlayerAnimator(d, 0, 0xFC))) == [0x90]
    sim = S.simulate([S._a(0)], S.PlayerAnimator(d, 0, 0x80), max_frames=10)
    assert sim["end"] == "stop"


def test_object_animator_s1_flip_bits_and_raw():
    d = _anim_rom([bytes([0, 0x21, 0x42, 0x03, 0xFF])])
    a = S.ObjectAnimator(d, 0, 0x1F, True)
    sim = S.simulate([S._a(0)], a)
    assert [(t.frame, t.xflip, t.yflip) for t in sim["ticks"]] == [(1, True, False), (2, False, True), (3, False, False)]
    r = S.RawAnimator(bytes([1, 0, 4, 5, 0xFC]))
    sim = S.simulate([{"animator": r, "frames": 8}, {"static": 9, "frames": 2}], None)
    assert _frames(sim) == [4, 4, 5, 5, 5, 4, 4, 5, 9, 9] and sim["loop_start"] == 8


# ------------------------------------------------------------------------------------------------ rendering

def _tileset(n):
    """n tiles, tile k filled with colour index (k % 15) + 1."""
    return np.stack([np.full((8, 8), (k % 15) + 1, np.uint8) for k in range(n)])


def test_render_alignment_and_flip():
    pal = M.palette_rgba([0x000] + [0x0E00 - 0x0100 * i for i in range(15)] + [0x0EEE] * 48)
    maps = [[{"x": -8, "y": -16, "w": 1, "h": 2, "tile": 0, "pal": 0, "pri": 0, "hf": 0, "vf": 0}],
            [{"x": 0, "y": -8, "w": 2, "h": 1, "tile": 2, "pal": 0, "pri": 0, "hf": 0, "vf": 0}]]
    ss = S.SpriteSet(maps, lambda f: _tileset(4), pal)
    runs = [{"tick": S.Tick(0), "frames": 2, "start": 0}, {"tick": S.Tick(1), "frames": 1, "start": 2},
            {"tick": S.Tick(1, xflip=True), "frames": 1, "start": 3}]
    images, origin, canvas, boxes = S.render_clip(runs, ss, margin=0)
    assert origin == (16, 16) and canvas == (32, 16)
    assert all(im.shape == (16, 32, 4) for im in images)
    ox, oy = origin
    # frame 0: column x -8..-1, rows -16..-1 -> tiles 0 (top) and 1 (bottom, column-major)
    assert tuple(images[0][oy - 16, ox - 8][:3]) == tuple(pal[1][:3]) and tuple(images[0][oy - 1, ox - 1][:3]) == tuple(pal[2][:3])
    assert images[0][oy - 1, ox][3] == 0
    # frame 1: tiles 2, 3 left to right at x 0..15; flipped: mirrored around the origin, x -16..-1, order reversed
    assert tuple(images[1][oy - 8, ox][:3]) == tuple(pal[3][:3]) and tuple(images[1][oy - 8, ox + 8][:3]) == tuple(pal[4][:3])
    assert tuple(images[2][oy - 8, ox - 1][:3]) == tuple(pal[3][:3]) and tuple(images[2][oy - 8, ox - 16][:3]) == tuple(pal[4][:3])
    assert boxes[2] == (-16, -8, 0, 0)


def test_first_piece_draws_on_top():
    pal = M.palette_rgba([0x000, 0x00E, 0x0E0] + [0] * 61)
    pieces = [{"x": 0, "y": 0, "w": 1, "h": 1, "tile": 0, "pal": 0, "pri": 0, "hf": 0, "vf": 0},
              {"x": 0, "y": 0, "w": 1, "h": 1, "tile": 1, "pal": 0, "pri": 0, "hf": 0, "vf": 0}]
    canvas = np.zeros((8, 8, 4), np.uint8)
    S.draw(canvas, (0, 0), S.piece_rects(pieces), _tileset(2), pal)
    assert tuple(canvas[0, 0][:3]) == tuple(pal[1][:3])


# ------------------------------------------------------------------------------------------------ synthetic ROM

def _synthetic_s2_rom(frames: int = 64) -> bytes:
    d = bytearray(0x40000)
    d[0x100:0x110] = b"SEGA GENESIS    "
    d[0x150:0x180] = b"SONIC THE             HEDGEHOG 2".ljust(48)
    d[0x180:0x18E] = b"GM 00001051-01"
    art, plc, maps, ani, paltab = 0x20000, 0x10000, 0x12000, 0x14000, 0x16000
    # art: tile k = colour (k % 15) + 1; every frame streams 4 tiles starting at 4*f
    for k in range(frames * 4):
        d[art + 32 * k:art + 32 * k + 32] = bytes([((k % 15) + 1) * 0x11]) * 32
    dp = _table([_dplc_frame("s2", [(4 * f, 4)]) for f in range(frames)])
    mp = _table([_map_frame("s2", [(-16 - f % 3, 2, 2, 0, -8)]) for f in range(frames)])
    scripts = [bytes([0xFF, 1, 2, 3, 0xFF]), bytes([0xFF, 4, 5, 0xFF]), bytes([0xFE, 6, 7, 8, 0xFF]),
               bytes([0xFE, 6, 8, 0xFF]), bytes([0xFD, 9, 10, 0xFF]), bytes([5, 11, 0xFF]),
               bytes([3, 12, 0xFF]), bytes([3, 13, 0xFE, 1]), bytes([3, 14, 0xFE, 1]),
               bytes([0, 20, 21, 20, 22, 0xFF])]
    an = _table(scripts)
    d[plc:plc + len(dp)], d[maps:maps + len(mp)], d[ani:ani + len(an)] = dp, mp, an
    pals = [0x0000, 0x0EEE, 0x0E00, 0x00E0, 0x000E] + [0x0888] * 11
    d[0x17000:0x17020] = struct.pack(">16H", *pals)
    for i in range(6):
        d[paltab + 8 * i:paltab + 8 * i + 8] = struct.pack(">IHH", 0x17000, 0xFB00 + (0x20 if i == 4 else 0), 7)
    code = 0x1000
    # Sonic_Animate: lea (Ani).l,a1; moveq #0,d0; move.b anim(a0),d0; cmp.b prev_anim(a0),d0
    d[code:code + 16] = b"\x43\xf9" + struct.pack(">I", ani) + b"\x70\x00\x10\x28\x00\x1c\xb0\x28\x00\x1d"
    # LoadSonicDynPLC: lea (PLC).l,a2; add.w d0,d0; adda.w (a2,d0.w),a2; move.w (a2)+,d5; subq.w #1,d5; bmi.s ..
    #                  move.w #vram,d4; ... addi.l #Art,d1
    ld = code + 0x100
    d[ld:ld + 40] = (b"\x45\xf9" + struct.pack(">I", plc) + b"\xd0\x40\xd4\xf2\x00\x00\x3a\x1a\x53\x45\x6b\x30"
                     + b"\x38\x3c\xf0\x00\x72\x00\x32\x1a\x36\x01\xe0\x4b\x02\x43\x00\xf0\x06\x81"
                     + struct.pack(">I", art))
    # move.l #Map,mappings(a0) near the loader
    d[code + 0x200:code + 0x208] = b"\x21\x7c" + struct.pack(">I", maps) + b"\x00\x04"
    # PalLoad: lea (PalPointers).l,a1; lsl.w #3,d0; adda.w d0,a1; movea.l (a1)+,a2; movea.w (a1)+,a3
    d[0x800:0x80E] = b"\x43\xf9" + struct.pack(">I", paltab) + b"\xe7\x48\xd2\xc0\x24\x59\x36\x59"
    return bytes(d)


def test_synthetic_rom_discovery_and_clips(tmp_path):
    rom = _synthetic_s2_rom()
    game = S.identify(rom)
    assert game.key == "sonic2"
    game = S.Game(**{**game.__dict__, "chars": ["sonic"]})
    chars = S.find_characters(rom, game)
    c = chars["sonic"]
    assert (c.art, c.plc, c.maps_off, c.anim) == (0x20000, 0x10000, 0x12000, 0x14000)
    assert len(c.maps) == 64 and c.palette[2:4] == b"\x0e\xee"
    S.GAMES["_test"] = game
    try:
        ex = S.Extractor.__new__(S.Extractor)
        ex.d, ex.meta, ex.game, ex.lay = rom, {}, game, S.LAYOUTS["s2"]
        ex.chars, ex.pal_table = chars, S.find_palette_table(rom)
        ex.zone, ex.signpost = S.palette_entry(rom, ex.pal_table, 4), None
        names = [p["name"] for p in ex.plans("sonic")]
        assert names[:4] == ["spindash_charge", "spindash_release", "jump", "roll"] and "level_complete" not in names
        assert "walk" in names and "wait" in names
        res = S.extract_character(ex, "sonic", tmp_path / "sonic2_sonic", want_mp4=False)
    finally:
        S.GAMES.pop("_test")
    assert (tmp_path / "sonic2_sonic" / "overview.png").is_file()
    sd = tmp_path / "sonic2_sonic" / "clips" / "spindash_charge"
    idx = json.loads((sd / "sheet.json").read_text())
    assert [f["mapping_frame"] for f in idx["frames"]] == [20, 21, 20, 22]
    assert all(f["duration_frames"] == 1 and f["duration_ms"] == pytest.approx(16.667, abs=0.01) for f in idx["frames"])
    assert idx["loop"]["start"] == 0 and idx["loop"]["length"] == 4 and idx["images"] == 3
    assert idx["origin"] == idx["frames"][0]["origin"] and all(f["origin"] == idx["origin"] for f in idx["frames"])
    assert (sd / "frames" / "frame_0003.png").is_file() and (sd / "sheet.png").is_file() and (sd / "preview.apng").is_file()
    rel = json.loads((tmp_path / "sonic2_sonic" / "clips" / "spindash_release" / "sheet.json").read_text())
    assert rel["animations"][0]["game_frames"] == 12 and rel["loop"]["start_game_frame"] == 12
    jump = json.loads((tmp_path / "sonic2_sonic" / "clips" / "jump" / "sheet.json").read_text())
    assert [(f["mapping_frame"], f["duration_frames"]) for f in jump["frames"]] == [(6, 5), (7, 5), (8, 5)]
    # every frame's sprite sits at the same origin: frame k draws its piece from y = -16 - (k % 3)
    from PIL import Image
    for f in jump["frames"]:
        im = np.asarray(Image.open(tmp_path / "sonic2_sonic" / "clips" / "jump" / f["file"]))
        ys = np.nonzero(im[..., 3])[0]
        assert ys.min() == jump["origin"][1] - 16 - f["mapping_frame"] % 3
    rows = {a["clip"]: a for a in res["animations"]}
    assert rows["jump"]["sheet"] == "clips/jump/sheet.png" and rows["spindash_charge"]["loop"]["length"] == 4
    assert res["requested"] == ["spindash_charge", "spindash_release", "jump", "roll"]


def test_identify_titles_and_registration():
    def rom(title, serial=b"GM 00000000-00", size=0x80000):
        d = bytearray(size)
        d[0x100:0x110] = b"SEGA MEGA DRIVE "
        d[0x150:0x180] = title.ljust(48)
        d[0x180:0x18E] = serial
        return bytes(d)
    assert S.identify(rom(b"SONIC THE               HEDGEHOG")).key == "sonic1"
    assert S.identify(rom(b"SONIC THE             HEDGEHOG 3")).key == "sonic3"
    assert S.identify(rom(b"SONIC & KNUCKLES", b"GM MK-1563 -00", 0x200000)).key == "sk"
    with pytest.raises(S.Sonic2DError):
        S.identify(rom(b"SONIC SPINBALL", b"GM MK-1537 -00"))
    lock = bytearray(rom(b"SONIC & KNUCKLES", b"GM MK-1563 -00", 0x400000))
    lock[0x200100:0x200110] = b"SEGA GENESIS    "
    lock[0x200150:0x200170] = b"SONIC THE             HEDGEHOG 3"
    assert S.identify(bytes(lock)).key == "s3k"
    t = S.title_test
    assert t("sonic1")("sonic the hedgehog (usa, europe)", "genesis") and not t("sonic1")("sonic the hedgehog", "sms")
    assert t("sonic2")("sonic the hedgehog 2 (world) (rev a)", "genesis") and not t("sonic2")("sonic 2 delta", "genesis")
    assert t("s3k")("sonic & knuckles + sonic the hedgehog 3 (world)", "genesis")
    assert t("sk")("sonic & knuckles (world)", "genesis") and not t("sk")("sonic & knuckles + sonic the hedgehog", "genesis")
    from gbox import characters as C, character_collection as CC
    names = {n for n, *_ in C.DEDICATED}
    assert {"sonic2d_sonic1", "sonic2d_sonic2", "sonic2d_sonic3", "sonic2d_s3k", "sonic2d_sk"} <= names
    assert CC.registered({"title": "Sonic the Hedgehog 2 (World)", "platform": "genesis"})
    assert [r["slug"] for r in S.roster("s3k")] == ["s3k_sonic", "s3k_tails", "s3k_knuckles"]


# ------------------------------------------------------------------------------------------------ collage

def _clip(name, colours, durations, loop=None, w=8, h=8, origin=(4, 8)):
    imgs = []
    for c in colours:
        im = np.zeros((h, w, 4), np.uint8)
        im[..., :3], im[..., 3] = c, 255
        imgs.append(im)
    return SC.Clip(name, imgs, durations, 60.0, [origin] * len(imgs), loop, name)


def test_collage_timeline_loops_hold_flip_and_z(tmp_path):
    red, green, blue = (255, 0, 0), (0, 255, 0), (0, 0, 255)
    a = _clip("a", [red, green], [2, 2], loop={"start": 1, "length": 1})
    b = _clip("b", [blue], [3])
    layout = {"canvas": [32, 16], "fps": 60, "frames": 8, "background": "transparent",
              "items": [{"clip": "a", "x": 8, "y": 12, "loops": 2, "hold": "hide"},
                        {"clip": "b", "x": 10, "y": 12, "start": 1, "z": -1, "hold": "last"},
                        {"clip": "a", "x": 24, "y": 12, "flip": True}]}
    r = SC.render(layout, clips={"a": a, "b": b})
    fr = r["frames"]
    assert len(fr) == 8 and r["size"] == [32, 16]
    px = lambda t, x, y: tuple(fr[t][y, x][:3]) if fr[t][y, x][3] else None
    # item a: origin (4, 8) at (8, 12) -> covers x 4..11, y 4..11; red 2 ticks, then green for 2 loop passes, then hides
    assert [px(t, 5, 6) for t in range(8)] == [red, red, green, green, green, green, None, None]
    # item b (behind a): on from frame 1, visible where a is not (x 12..13), held after its 3 ticks
    assert px(0, 13, 6) is None and px(1, 13, 6) == blue and px(7, 13, 6) == blue and px(1, 10, 6) == red
    # flipped item: origin mirrored (8 - 4 = 4), covers x 20..27; loops on forever (green at the end)
    assert px(7, 20, 6) == green and px(7, 27, 6) == green and px(7, 28, 6) is None
    s = SC.export(layout, tmp_path / "c", mp4=False, clips={"a": a, "b": b})
    assert s["frames"] == 8 and (tmp_path / "c" / "frames" / "collage_0007.png").is_file()
    assert json.loads((tmp_path / "c" / "collage.json").read_text())["items"][0]["clip"] == "a"
    assert (tmp_path / "c" / "preview.apng").is_file()


def test_collage_reads_clip_folders(tmp_path):
    from gbox import sprite_capture as SCap
    clip = {"images": [np.full((4, 4, 4), 200, np.uint8), np.full((4, 4, 4), 90, np.uint8)],
            "index": {"clip": "x", "canvas": [4, 4], "origin": [2, 4], "loop": {"start": 0, "length": 2},
                      "fps": 60.0, "total_game_frames": 3,
                      "frames": [{"index": 0, "duration_frames": 1, "duration_ms": 16.667, "origin": [2, 4]},
                                 {"index": 1, "duration_frames": 2, "duration_ms": 33.333, "origin": [2, 4]}]}}
    index, files, _ = S.package_clip(clip, want_mp4=False)
    S.write_clip(tmp_path / "ent" / "clips" / "x", files)
    c = SC.load_clip("ent/x", tmp_path)
    assert c.durations == [1, 2] and c.origins == [(2, 4), (2, 4)] and c.loop["length"] == 2
    assert [c.frame_at(t) for t in range(6)] == [0, 1, 1, 0, 1, 1]
    assert index["frames"][1]["sheet"][2:] == [4, 4] and "file" in index["frames"][0]
    with pytest.raises(SC.CollageError):
        SC.load_clip("ent/missing", tmp_path)
    assert SCap.png_bytes  # the shared PNG writer is what both use


# ------------------------------------------------------------------------------------------------ owned ROMs

CACHE = Path(os.environ.get("GBOX_ROM_CACHE", Path.home() / "gBox_alt/gbox-cache"))
OWNED = {  # game_id: ROM sha1
    "sonic1": ("f82de5b1456da0ce", "69e102855d4389c3fd1a8f3dc7d193f8eee5fe5b"),
    "sonic2": ("938e4ca5b120e344", "14dd06fc3aa19a59a818ea1f6de150c9061b14d4"),
    "sonic3": ("1936eeee6b541ca3", "75e9c4705259d84112b3e697a6c00a0813d47d71"),
    "s3k": ("ed2bef5be2826deb", "cfbf98c36c776677290a872547ac47c53d2761d6"),
    "sk": ("668e74c15d61a9a7", "88d6499d874dcb5721ff58d76fe1b9af811192e3"),
}


def _owned(key):
    gid, sha1 = OWNED[key]
    p = CACHE / gid / "source.zip"
    if not p.is_file():
        pytest.skip(f"owned ROM {gid} not cached at {p}")
    import hashlib
    d, meta = S.read_rom(p)
    if hashlib.sha1(d).hexdigest() != sha1:
        pytest.skip(f"{p} is not the owned build")
    return S.Extractor(d, meta)


def _seq(ex, char, clip):
    plan = next(p for p in ex.plans(char) if p["name"] == clip)
    c = ex.clip(char, plan)
    return [(f["mapping_frame"], f["duration_frames"]) for f in c["index"]["frames"]], c


def test_owned_sonic2():
    ex = _owned("sonic2")
    s, t = ex.chars["sonic"], ex.chars["tails"]
    assert (s.art, s.plc, s.maps_off, s.anim, len(s.maps)) == (0x50000, 0x714E0, 0x6FBE0, 0x1B624, 214)
    assert (t.art, t.plc, t.maps_off, t.anim) == (0x64320, 0x7446C, 0x739E2, 0x1D028)
    assert t.tails and not t.tails["own_set"]
    assert ex.signpost["art"] == 0x79BDE and len(ex.signpost["tiles"]) == 78 * 32
    seq, _ = _seq(ex, "sonic", "spindash_charge")         # SonAni_Spindash: 0, $42,$43,$42,$44,...,$47, $FF
    assert seq == [(f, 1) for f in (0x42, 0x43, 0x42, 0x44, 0x42, 0x45, 0x42, 0x46, 0x42, 0x47)]
    seq, c = _seq(ex, "sonic", "level_complete")
    assert seq[-1][0] == 0 and c["index"]["loop"]["length"] == 1 and sum(n for _, n in seq[:-1]) == 62
    seq, _ = _seq(ex, "tails", "level_complete")
    assert seq[-1][0] == 1                               # anim 4: the sign lands on Tails' face


def test_owned_sonic1():
    ex = _owned("sonic1")
    s = ex.chars["sonic"]
    assert (s.art, s.plc, s.maps_off, s.anim, len(s.maps)) == (0x22610, 0x22310, 0x21CF4, 0x1421C, 88)
    assert ex.signpost["art"] == 0x3A9E8 and ex.signpost["art_tile"] == 0x680
    seq, _ = _seq(ex, "sonic", "jump")                   # SonAni_Roll ($FE): Roll1..Roll5 at speed 0 -> 5 ticks
    assert seq == [(f, 5) for f in (0x2E, 0x2F, 0x30, 0x31, 0x32)]
    seq, _ = _seq(ex, "sonic", "level_complete")          # Eggman, 2 x 61 spin ticks, Sonic face
    assert seq[0][0] == 0 and seq[-1][0] == 4 and sum(n for _, n in seq[:-1]) == 122


def test_owned_s3k_matches_sk_sprites_and_victory():
    from gbox import sk_sprites as sk
    ex = _owned("s3k")
    assert set(ex.chars) == {"sonic", "tails", "knuckles"}
    for name in ("sonic", "tails", "knuckles"):
        assert ex.chars[name].anim == sk.AUX[name]["anim"][0]
        off = sk.AUX[name]["palette"][0]
        assert ex.chars[name].palette == ex.d[off:off + 32]
    assert ex.chars["sonic"].extra_from == 0xDA and ex.chars["tails"].extra_from == 0xD1
    assert ex.chars["tails"].tails["own_set"]
    seq, _ = _seq(ex, "sonic", "level_complete")         # AniSonic13: 7, $B0, $B2 x6, $B1, $B2, $B3, $B2, $FE 4
    assert [f for f, _ in seq][:4] == [0xB0, 0xB2, 0xB1, 0xB2] and seq[0][1] == 8 and seq[1][1] == 48
    seq, _ = _seq(ex, "knuckles", "spindash_charge")
    assert [f for f, _ in seq] == [0x86, 0x87, 0x86, 0x88, 0x86, 0x89, 0x86, 0x8A, 0x86, 0x8B]
    seq, _ = _seq(ex, "knuckles", "signpost")
    assert seq[-1][0] == 2


def test_owned_collect_into_collection(tmp_path, monkeypatch):
    """characters.extract_dedicated with the sonic2d reader: a verified sprites entry whose animations list the clips."""
    ex = _owned("sonic1")
    from types import SimpleNamespace
    from gbox import characters as C, tools
    gid = OWNED["sonic1"][0]
    monkeypatch.setattr(tools, "rom_path", lambda entry, cfg: CACHE / gid / "source.zip")
    real_plans = S.Extractor.plans
    monkeypatch.setattr(S.Extractor, "plans",
                        lambda self, char: [p for p in real_plans(self, char) if p.get("kind") == "requested"])
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path / "cache"), progress=lambda p, m: None)
    game = {"game_id": gid, "title": "Sonic The Hedgehog", "platform": "genesis", "source_paths": ["x.zip"],
            "format": "zip", "profile_id": "genesis"}
    root = tmp_path / "characters"
    res = C.extract_dedicated(ctx, game, "sonic1_sonic", root)
    assert res["status"] == "extracted" and res["extractor"] == "sonic2d_sonic1"
    meta = C.get(root, "sonic1_sonic")
    assert meta["kind"] == "sprites" and meta["model"] == "overview.png" and meta["picture"] == "2d"
    assert [a["clip"] for a in meta["animations"]] == ["jump", "roll", "level_complete"]
    assert C.verify_entry(root, meta)["ok"]
    assert (root / "sonic1_sonic" / "clips" / "jump" / "sheet.json").is_file()
    assert meta["sonic2d"]["game"] == ex.game.key == "sonic1"


def test_owned_sonic3_and_sk():
    ex = _owned("sonic3")
    assert set(ex.chars) == {"sonic", "tails"} and ex.signpost is None
    names = [p["name"] for p in ex.plans("sonic")]
    assert names[:5] == ["spindash_charge", "spindash_release", "jump", "roll", "level_complete"]
    ex = _owned("sk")
    assert set(ex.chars) == {"sonic", "knuckles"}        # Tails' art is on the Sonic 3 cart (lock-on only)
    assert ex.signpost is not None

"""Tests for gbox.sk_lockon_analysis (#1333, S&K + Sonic 1 lock-on / Blue Spheres)."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from gbox import sk_lockon_analysis as ska
from gbox.sk_sprites import SkError

CACHE = Path.home() / "gBox_alt/gbox-cache" / "286b3fae79e33f17"
SRC = CACHE / "source.zip"
REF = CACHE / "sk_world.zip"
SOURCE_SHA256 = "4526806489260bb6dbc5d2342d85bfdf6a476034e58d7ac3f39988d37b46ffe1"


def _w(*v: int) -> bytes:
    return struct.pack(f">{len(v)}H", *v)


def _l(v: int) -> bytes:
    return struct.pack(">I", v)


def _fake_rom(serial: bytes | None, console: bytes = b"SEGA MEGA DRIVE ") -> bytes:
    sk = bytearray(ska.SK_SIZE)
    sk[0x100:0x110] = b"SEGA MEGA DRIVE "
    sk[0x400:0x400 + 56] = b"".join(ska.LOCKON_SERIALS)
    sk[0x300:0x306] = b"\x43\xf9" + _l(0x400)
    sk[0x306:0x30C] = b"\x41\xf9" + _l(ska.SERIAL_AT)
    if serial is None:
        return bytes(sk)
    cart = bytearray(0x1000)
    cart[0x100:0x110] = console
    cart[0x180:0x18E] = serial
    return bytes(sk + cart)


def test_lockon_mode_follows_attached_serial():
    assert ska.lockon_mode(_fake_rom(b"GM 00001009-00"))["mode"] == "blue_spheres"
    assert ska.lockon_mode(_fake_rom(b"GM MK-1079 -00"))["mode"] == "sonic3_and_knuckles"
    assert ska.lockon_mode(_fake_rom(b"GM 00001051-01"))["mode"] == "knuckles_in_sonic2"
    assert ska.lockon_mode(_fake_rom(None))["mode"] == "sonic_and_knuckles"
    r = ska.lockon_mode(_fake_rom(b"GM 00001009-00"))
    assert r["serial_table"] == 0x400 and r["serial_table_xrefs"] == [0x300] and r["serial_read_xrefs"] == [0x306]


def _sstage_image() -> tuple[bytes, dict]:
    """A miniature special-stage player: init sites, guarded loader groups, core, tables, palette."""
    d = bytearray(0x4000)
    map_s, map_k, art_s, art_k = 0x1000, 0x1400, 0x2000, 0x3000
    # one block per character: map head, PLC head, then interleaved frames (like the real files)
    maps = [[{"y": -16, "w": 2, "h": 2, "tile": 0, "pal": 0, "pri": 0, "hf": 0, "vf": 0, "x": -8}],
            [{"y": -8, "w": 1, "h": 2, "tile": 0, "pal": 0, "pri": 1, "hf": 1, "vf": 0, "x": 0},
             {"y": 8, "w": 1, "h": 1, "tile": 2, "pal": 0, "pri": 0, "hf": 0, "vf": 1, "x": 4}]]
    dplc = [[(0, 4)], [(4, 2), (10, 1)]]
    for base in (map_s, map_k):
        # DPLC frame 0 directly follows the PLC head, as in the ROM's SStage files
        f = [ska.encode_dplc_frame(dplc[0]), ska.encode_map_frame(maps[0]),
             ska.encode_dplc_frame(dplc[1]), ska.encode_map_frame(maps[1])]
        pos = base + 8
        addr = []
        for b in f:
            addr.append(pos)
            pos += len(b)
        plc = base + 4
        head = _w(addr[1] - base, addr[3] - base) + _w(addr[0] - plc, addr[2] - plc)
        d[base:base + 8] = head
        d[base + 8:pos] = b"".join(f)
    guard = lambda n, disp: b"\x0c\x78" + _w(n, 0xFF08) + bytes([0x66, disp])  # noqa: E731
    init = (b"\x21\x7c" + _l(map_s) + _w(0x000C) + b"\x31\x7c" + _w(0x87D4, 0x000A)
            + guard(2, 0x0E) + b"\x21\x7c" + _l(0x301FE8) + _w(0x000C) + b"\x31\x7c" + _w(0xA7EB, 0x000A)
            + guard(3, 0x0C) + b"\x21\x7c" + _l(map_k) + _w(0x000C) + b"\x31\x7c" + _w(0x87D4, 0x000A))
    d[0x200:0x200 + len(init)] = init
    grp = lambda plc, art, vram: b"\x45\xf9" + _l(plc) + b"\x2c\x3c" + _l(art) + b"\x38\x3c" + _w(vram)  # noqa: E731
    loader = (grp(map_s + 4, art_s, 0xFA80) + guard(2, 0x12) + grp(0x302000, 0x301000, 0xFD60) + b"\x60\x18"
              + guard(3, 0x10) + grp(map_k + 4, art_k, 0xFA80)
              + _w(0x7000, 0x1028, 0x0022, 0xB028, 0x003A, 0x6728, 0x1140, 0x003A)
              + _w(0xD040, 0xD4F2, 0x0000, 0x3A1A, 0x5345, 0x6B10))
    d[0x400:0x400 + len(loader)] = loader
    pal = (b"\x43\xf9" + _l(0x3800) + b"\x45\xf8" + _w(0xFC80) + b"\x30\x3c" + _w(0x3F) + _w(0x34D9, 0x51C8, 0xFFFC)
           + guard(3, 0x0E) + b"\x43\xf9" + _l(0x3880) + b"\x45\xf8" + _w(0xFC90) + b"\x30\x3c" + _w(7)
           + _w(0x34D9, 0x51C8, 0xFFFC))
    d[0x600:0x600 + len(pal)] = pal
    return bytes(d), {"map_s": map_s, "map_k": map_k, "art_s": art_s, "art_k": art_k}


def test_sstage_players_pins_guarded_groups_and_roundtrips():
    d, a = _sstage_image()
    r = ska.sstage_players(d)
    assert r["player_mode_ram"] == [0xFF08] and r["vram_bases"] == [0xFA80, 0xFD60]
    s, t, k = r["characters"]["sonic"], r["characters"]["tails"], r["characters"]["knuckles"]
    assert t["status"] == "lock_on_only" and t["plc"]["offset"] == 0x302000
    assert s["status"] == k["status"] == "in_cart"
    assert s["mappings"]["offset"] == a["map_s"] and s["plc"]["offset"] == a["map_s"] + 4
    assert k["mappings"]["offset"] == a["map_k"] and k["art"]["offset"] == a["art_k"]
    assert s["art"]["tiles"] == 11 and s["plc"]["max_tiles_per_frame"] == 4
    assert s["art_tile"] == {"word": 0x87D4, "tile": 0x7D4, "palette_line": 0, "priority": 1}
    assert s["vram_budget_tiles"] == 23 and k["vram_budget_tiles"] is None  # no Tails in mode 3
    for c in (s, k):
        assert c["roundtrip"]["ok"] and c["roundtrip"]["gaps"] == []
        assert [h[2] for h in c["roundtrip"]["heads"]] == [6, 2]
    p = ska.sstage_palette(d)
    assert p["main"]["offset"] == 0x3800 and p["main"]["words"] == 64
    assert p["knuckles_override"]["words"] == 8 and p["knuckles_from_colour"] == 8


def test_rebuild_keeps_dead_bytes_and_rejects_overlap():
    frames = [[(0, 4)], [(4, 3)]]
    body = ska.encode_dplc_frame(frames[0]) + b"\x00\x01\x30\x09" + ska.encode_dplc_frame(frames[1])
    d = bytearray(0x100)
    d[0x40:0x44] = _w(4, 4 + 4 + 4)
    d[0x44:0x44 + len(body)] = body
    r = ska.roundtrip(bytes(d), [(0x40, 2, 2)])
    assert r["ok"] and r["gaps"] == [[0x48, 4]]
    d[0x40:0x44] = _w(4, 6)  # second frame starts inside the first
    assert not ska.roundtrip(bytes(d), [(0x40, 2, 2)])["ok"]
    with pytest.raises(SkError):
        ska.encode_dplc_frame([(0x1000, 1)])
    with pytest.raises(SkError):
        ska.encode_dplc_frame([(0, 17)])


@pytest.mark.skipif(not SRC.exists(), reason="owned #1333 build is not cached on this host")
def test_real_build_blue_spheres_player_tables():
    r = ska.analyze(SRC, REF if REF.exists() else None)
    assert r["source"]["sha256"] == SOURCE_SHA256
    assert r["rom"]["sk_segment_sha256"].startswith("2542b446")
    lk = r["lockon"]
    assert lk["mode"] == "blue_spheres" and lk["attached_serial"] == "GM 00001009-00"
    assert lk["serial_table"] == 0x3C0 and lk["serial_table_xrefs"] == [0x384]
    ss = r["special_stage"]
    assert ss["loader_core"] == 0x91B2 and ss["player_mode_ram"] == [0xFF08]
    s, k, t = (ss["characters"][n] for n in ("sonic", "knuckles", "tails"))
    assert (s["setup"], s["mappings"]["offset"], s["plc"]["offset"], s["art"]["offset"]) == \
        (0x9160, 0xABDFC, 0xABE14, 0xAAA7C)
    assert (k["setup"], k["mappings"]["offset"], k["plc"]["offset"], k["art"]["offset"]) == \
        (0x9192, 0xAD302, 0xAD31A, 0xABF22)
    assert s["mappings"]["init_xref"] == 0x8FC2 and k["mappings"]["init_xref"] == 0x9002
    assert s["plc"]["frames"] == k["plc"]["frames"] == 12
    assert s["art"]["tiles"] == 156 and s["art"]["end"] == 0xABDFC and k["art"]["end"] == 0xAD302
    assert s["vram_byte"] == 0xFA80 and s["vram_budget_tiles"] == 23 and s["plc"]["max_tiles_per_frame"] == 23
    assert s["art_tile"]["palette_line"] == 0 and s["dma_bank_crossings"] == 0
    assert t["status"] == "lock_on_only" and (t["plc"]["offset"], t["art"]["offset"]) == (0x202000, 0x201000)
    for c in (s, k):
        assert c["roundtrip"]["ok"] and c["roundtrip"]["gaps"] == []
    pal = ss["palette"]
    assert (pal["main"]["offset"], pal["main"]["xref"], pal["knuckles_override"]["offset"]) == (0x896E, 0x8276, 0x89EE)
    assert any(w["at"] == 0x4D01E and w["from_ram"] == 0xFF0A for w in ss["player_mode_writes"]["copy"])
    mg = r["main_game"]
    assert mg["dispatch"] == 0x12D22 and mg["stock_pins"]["knuckles"]["matches_stock_pins"]
    assert mg["characters"]["sonic"]["art"]["offset"] == 0x200000  # patched away from stock 0x100000
    for n in ("sonic", "knuckles"):
        assert all(v["ok"] for v in mg["characters"][n]["roundtrip"].values())
    if REF.exists():
        cp = r["compat"]
        assert cp["reference_sha256"].startswith("6e12e6b3") and cp["diff_bytes"] == 918
        assert cp["touched"] == []
        kinds = {(c["site"], c["kind"]) for c in cp["pointer_changes"]}
        assert (0x9178, "sstage.tails.plc") in kinds and (0x9178, "sstage.tails.art") in kinds
        assert any(c["kind"] == "dplc_loader.art" and c["ours"] == 0x200000 for c in cp["pointer_changes"])


def test_truncated_image_raises_valueerror():
    d, _ = _sstage_image()
    cut = ska.sstage_players(d[:0x1005])     # tables past the cut are reported, not read
    assert cut["characters"]["sonic"]["status"] == "lock_on_only"
    with pytest.raises(ValueError):
        ska.sstage_players(d[:0x400])         # no loader at all
    with pytest.raises(ValueError):
        ska.sstage_palette(d[:0x600])
    with pytest.raises(ValueError):
        ska.lockon_mode(bytes(0x100))

"""Sonic & Knuckles (World) player sprite inventory (#1365).

The synthetic tests build a tiny ROM with the same 68k loader/dispatch shapes, so the
discovery logic is exercised without the owned cartridge. The real-ROM test pins the
owned build (HyperSpin zip sha256 77788157...) and the byte ranges that match the
sonicretro/skdisasm sources; it skips when the ROM is not cached on this machine.
"""
from __future__ import annotations

import hashlib
import os
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import sk_sprites as sk

OWNED = Path(os.environ.get("GBOX_SK_ZIP", Path.home() / "gBox_alt/gbox-cache/668e74c15d61a9a7/source.zip"))
OWNED_SHA = "777881572e72f50c9868335bddafbdcc140c8772699b266cbcee7f4c3e68b26b"


def _table(frames: list[bytes]) -> bytes:
    head = 2 * len(frames)
    offs, body = [], b""
    for f in frames:
        offs.append(head + len(body))
        body += f
    return b"".join(struct.pack(">H", o) for o in offs) + body


def _dplc_frame(entries):
    return struct.pack(">H", len(entries)) + b"".join(struct.pack(">H", ((n - 1) << 12) | t) for t, n in entries)


def _map_frame(pieces):
    out = struct.pack(">H", len(pieces))
    for y, w, h, tile, x in pieces:
        out += struct.pack(">bBHh", y, ((w - 1) << 2) | (h - 1), tile, x)
    return out


def _loader(plc: int, art: int, vram: int) -> bytes:
    return (b"\x45\xf9" + struct.pack(">I", plc) + b"\xd0\x40\xd4\xf2\x00\x00\x3a\x1a\x53\x45\x6b\x30"
            + b"\x38\x3c" + struct.pack(">H", vram) + b"\x2c\x3c" + struct.pack(">I", art))


def _synthetic() -> tuple[bytearray, dict]:
    d = bytearray(0x10000)
    d[0x100:0x110] = b"SEGA GENESIS    "
    d[0x180:0x18E] = b"GM MK-1563 -00"
    # Perform_Player_DPLC at 0x1000 -> sonic 0x1040, tails 0x1200, knuckles 0x1300
    at = 0x1000
    d[at:at + 22] = (b"\x4a\x29\x00\x38\x67" + struct.pack("b", 0x1040 - (at + 6)) + b"\x0c\x29\x00\x01\x00\x38"
                     + b"\x67\x00" + struct.pack(">h", 0x1200 - (at + 14)) + b"\x60\x00"
                     + struct.pack(">h", 0x1300 - (at + 18)) + b"\x4e\x75\x4e\x75")
    plcs = {"sonic": 0x4000, "tails": 0x5000, "knuckles": 0x6000}
    maps = {"sonic": 0x7000, "tails": 0x8000, "knuckles": 0x9000}
    arts = {"sonic": 0xA000, "tails": 0x300000, "knuckles": 0xB000}
    for name, entry in (("sonic", 0x1040), ("tails", 0x1200), ("knuckles", 0x1300)):
        code = _loader(plcs[name], arts[name], 0xD000)
        d[entry + 4:entry + 4 + len(code)] = code
        dp = _table([_dplc_frame([]), _dplc_frame([(0, 4), (10, 2)]), _dplc_frame([(20, 6)])])
        d[plcs[name]:plcs[name] + len(dp)] = dp
        mp = _table([_map_frame([]), _map_frame([(-16, 2, 2, 0, -8), (0, 1, 2, 4, -8)]),
                     _map_frame([(-8, 3, 2, 0, -12)])])
        d[maps[name]:maps[name] + len(mp)] = mp
        # a decoy mapping table whose second frame needs more tiles than the DPLC streams
        dec = _table([_map_frame([]), _map_frame([(0, 4, 4, 0, 0)]), _map_frame([])])
        d[maps[name] + 0x400:maps[name] + 0x400 + len(dec)] = dec
        for i, t in enumerate((maps[name], maps[name] + 0x400)):
            ref = entry + 0x30 + 8 * i
            d[ref:ref + 8] = b"\x21\x7c" + struct.pack(">I", t) + b"\x00\x0c"
    return d, {"plcs": plcs, "maps": maps, "arts": arts}


def test_loaders_dispatch_and_mapping_choice():
    d, ex = _synthetic()
    lds = sk.find_dplc_loaders(bytes(d))
    assert sorted(x["plc"] for x in lds) == sorted(ex["plcs"].values())
    assert {x["vram"] for x in lds} == {0xD000}
    disp = sk.player_dispatch(bytes(d))
    assert (disp["sonic"], disp["tails"], disp["knuckles"]) == (0x1040, 0x1200, 0x1300)
    inv = sk.player_inventory(bytes(d))["characters"]
    for name in ("sonic", "knuckles"):
        c = inv[name]
        assert c["status"] == "in_cart"
        assert c["plc"]["offset"] == ex["plcs"][name] and c["plc"]["frames"] == 3
        assert c["mappings"]["offset"] == ex["maps"][name]  # the decoy does not fit
        assert c["mappings"]["fitting_tables"] == 3  # identical tables: nearest set-up wins
        assert c["art"]["tiles"] == 26 and c["art"]["size"] == 26 * 32
        assert c["plc"]["max_tiles_per_frame"] == 6
    assert inv["tails"]["status"] == "lock_on_only" and inv["tails"]["art"]["in_cart"] is False


def test_mapping_fit_rejects_overreach():
    dplc = [[(0, 4)]]
    ok = [[{"tile": 0, "w": 2, "h": 2}]]
    bad = [[{"tile": 2, "w": 2, "h": 2}]]
    assert sk.mapping_fits(ok, dplc)
    assert not sk.mapping_fits(bad, dplc)
    assert not sk.mapping_fits(ok + ok, dplc)


def test_table_bounds():
    d, ex = _synthetic()
    with pytest.raises(sk.SkError):
        sk.parse_mappings(bytes(d), ex["maps"]["sonic"], count=9)
    assert len(sk.parse_dplc(bytes(d), ex["plcs"]["sonic"], count=2)) == 2


def test_read_rom_rejects_bad_sources(tmp_path):
    z = tmp_path / "two.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.md", b"x")
        zf.writestr("b.md", b"y")
    with pytest.raises(sk.SkError):
        sk.read_rom(z)
    smd = tmp_path / "x.bin"
    smd.write_bytes(b"\0" * 0x400)
    with pytest.raises(sk.SkError):
        sk.read_rom(smd)


@pytest.mark.skipif(not OWNED.exists(), reason="owned S&K zip not cached")
def test_owned_build_inventory():
    assert hashlib.sha256(OWNED.read_bytes()).hexdigest() == OWNED_SHA
    m = sk.inventory(OWNED)
    r = m["rom"]
    assert r["no_intro_match"] and r["checksum_ok"] and r["header"]["serial"] == "GM MK-1563 -00"
    assert r["sha256"] == "6e12e6b33c26ebfcd0be433251d21cf6284eafe9f71b027bda3767ae59affec1"
    c = m["characters"]
    # offsets + sha256 equal to the skdisasm sources assembled byte-for-byte
    pins = {
        ("sonic", "mappings"): (0x146620, 7010, "9e095328f14b970c"),
        ("sonic", "plc"): (0x148182, 3382, "255202163612edda"),
        ("sonic", "anim"): (0x12AA6, 526, "aecec369d9720251"),
        ("tails", "mappings"): (0x148EB8, 4562, "8c5265807922b80c"),
        ("tails", "plc"): (0x14A08A, 2124, "c796eee4b4bd47ae"),
        ("tails", "anim"): (0x15AB0, 398, "0b85694a42dfa863"),
        ("knuckles", "mappings"): (0x14A8D6, 5172, "2507b7782c5bc145"),
        ("knuckles", "plc"): (0x14BD0A, 2376, "5eb879b37c9ab20a"),
        ("knuckles", "anim"): (0x17EF4, 538, "dc421620ff3048cb"),
        ("knuckles", "palette"): (0xA8AFC, 32, "a8b339a9dfafbbf8"),
    }
    for (name, key), (off, size, sha) in pins.items():
        rec = c[name][key]
        assert (rec["offset"], rec["size"], rec["sha256"][:16]) == (off, size, sha), (name, key)
    for name in ("sonic", "tails", "knuckles"):
        assert c[name]["plc"]["frames"] == c[name]["mappings"]["frames"] == 251
        for key in ("anim", "palette"):
            assert c[name][key]["xref_ok"], (name, key)
    assert c["sonic"]["art"]["offset"] == 0x100000 and c["knuckles"]["art"]["offset"] == 0x1200E0
    assert c["sonic"]["extra_art"]["offset"] == 0x140060 and c["sonic"]["extra_art"]["from_frame"] == 0xDA
    assert c["sonic"]["extra_art"]["sha256"].startswith("3b17d9e1dc8f9208")  # Sonic Extra.unc, whole file
    assert c["tails"]["status"] == "lock_on_only" and c["tails"]["art"]["offset"] == 0x3200E0
    assert c["sonic"]["vram_tile"] == 0x680 and c["knuckles"]["vram_tile"] == 0x680

"""Focused tests for gbox.nfl2k2_inventory (NFL 2K2 USA Dreamcast, #1338)."""
import hashlib
import json
import struct
from pathlib import Path

import pytest

from gbox import nfl2k2_inventory as nfl

CACHE = Path.home() / "gbox-cache" / "dc" / nfl.GAME_ID
HAVE_DISC = (CACHE / "disc.gdi").exists()
CHD_SHA256 = "7d4b3c49bbcc4e2be49f5f4a1476a9ce7929806aba69e618d9b27839cd7fc7ee"


# ---- pure functions ---------------------------------------------------------

def test_gd_dir_v0_with_names():
    recs = [(847392, 5472, 3104), (845312, 5464, 2080)]
    data = struct.pack("<2I", 0, 2) + b"".join(struct.pack("<3I", *r) for r in recs)
    data += b"\x00\x00\x000099.vq\x000096.vq\x00"
    d = nfl.gd_dir(data)
    assert d["version"] == 0 and d["count"] == 2
    assert d["records"] == [{"off": r[0], "x": r[1], "size": r[2]} for r in recs]
    assert d["names"] == ["0099.vq", "0096.vq"]


def test_gd_dir_nameless_versions():
    data = struct.pack("<2I", 2, 3) + b"".join(struct.pack("<3I", i, 0, 10) for i in range(3))
    d = nfl.gd_dir(data)
    assert d["version"] == 2 and d["names"] == [] and len(d["records"]) == 3


def test_iff_kind_and_header():
    assert nfl.iff_kind(b"SCNE\x00\x00") == "SCNE"
    assert nfl.iff_kind(b"VQCB\x00\x00") == "VQCB"
    assert nfl.iff_kind(b"FORM\x00\x00") is None
    h = nfl.iff_header(b"SCNE" + struct.pack("<3I", 1, 2, 3))
    assert h == {"kind": "SCNE", "desc": nfl.IFF_TYPES["SCNE"], "h0": 1, "h1": 2, "h2": 3}


def test_ip_bin_info():
    data = bytearray(0xC0)
    data[0x00:0x10] = b"SEGA SEGAKATANA "
    data[0x20:0x28] = b"A9BF GD-"
    data[0x30:0x38] = b"U       "
    data[0x40:0x4A] = b"MK-51168  "
    data[0x4A:0x50] = b"V1.004"
    data[0x60:0x70] = b"1ST_READ.BIN    "
    data[0x80:0xC0] = b"NFL2K2" + b"\x00" * (0x40 - 6)
    info = nfl.ip_bin_info(bytes(data))
    assert info["hardware_id"] == "SEGA SEGAKATANA"
    assert info["area_symbols"] == "U"
    assert info["product_number"] == "MK-51168"
    assert info["boot_file"] == "1ST_READ.BIN"
    assert info["title"] == "NFL2K2"
    assert info["layout"] == "standard"


def test_ip_bin_info_vc_shifted_variant():
    # VC discs drop the hardware field: maker sits at 0x00, all fields -16.
    data = bytearray(32768)
    data[0x00:0x10] = b"SEGA ENTERPRISES"
    data[0x10:0x20] = b"A9BF GD-ROM1/1  "
    data[0x20:0x28] = b"  U     "
    data[0x28:0x30] = b"2799A10 "
    data[0x30:0x3A] = b"MK-51168  "
    data[0x3A:0x40] = b"V1.004"
    data[0x40:0x48] = b"20010829"
    data[0x50:0x60] = b"1ST_READ.BIN    "
    data[0x70:0x76] = b"NFL2K2"
    data[0x800:0x810] = b"SEGA SEGAKATANA "  # hardware string lives elsewhere in the sector
    info = nfl.ip_bin_info(bytes(data))
    assert info["layout"] == "vc-shifted"
    assert info["hardware_id"] == "SEGA SEGAKATANA"
    assert info["maker_id"] == "SEGA ENTERPRISES"
    assert info["device_info"] == "A9BF GD-ROM1/1"
    assert info["area_symbols"] == "U"
    assert info["peripherals"] == "2799A10"
    assert info["product_number"] == "MK-51168"
    assert info["product_version"] == "V1.004"
    assert info["release_date"] == "20010829"
    assert info["boot_file"] == "1ST_READ.BIN"
    assert info["title"] == "NFL2K2"


def test_iff_tag_family_completeness():
    # every tag registered in IFF_TYPES must classify
    for tag in nfl.IFF_TYPES:
        assert nfl.iff_kind(tag.encode() + b"\x00\x00\x00\x00") == tag


# ---- integration against the owned, unpacked disc ---------------------------

@pytest.mark.skipif(not HAVE_DISC, reason="owned disc not unpacked on this node")
def test_disc_read_fast_path_matches_gdrom():
    disc = nfl.Disc(CACHE / "disc.gdi")
    for name in ("FACES.DIR", "FACES.DAT", "PLAYERS.DIR"):
        assert disc.read(name) == disc.g.read(name)
    fast = disc.read("PLAYERS.DAT")
    assert len(fast) == disc.g.files["PLAYERS.DAT"][1]


@pytest.mark.skipif(not HAVE_DISC, reason="owned disc not unpacked on this node")
def test_real_manifest_landmarks():
    disc = nfl.Disc(CACHE / "disc.gdi")
    m = nfl.inventory(CACHE / "disc.gdi", chd_sha256=CHD_SHA256)
    assert m["source"]["sha256"] == CHD_SHA256
    assert m["ip_bin"]["product_number"] == "MK-51168"       # USA V1.004
    assert m["ip_bin"]["area_symbols"] == "U"
    exes = {f["name"]: f for f in m["files"] if f["role"] == "sh4_binary"}
    assert set(exes) == {"1ST_READ.BIN", "MAIN.BIN"}
    assert hashlib.sha256(disc.read("1ST_READ.BIN")).hexdigest() == exes["1ST_READ.BIN"]["sha256"]
    faces = next(f for f in m["files"] if f["name"] == "FACES.DIR")
    assert faces["dir"]["count"] == 274 and len(faces["dir"]["names"]) == 274
    assert all(n.endswith(".vq") for n in faces["dir"]["names"])
    players = next(f for f in m["files"] if f["name"] == "PLAYERS.DIR")
    assert players["dir"]["count"] == 5941 and players["dir"]["names"] == []
    # character asset families present
    for group in ("stadiums", "uniforms", "player_geometry", "coaches", "sounds"):
        assert m["groups"][group]["count"] > 0
    kinds = {f["iff"]["kind"] for f in m["files"] if f["role"] == "iff"}
    assert kinds >= {"SCNE", "SPRT", "VQCB", "SOUN", "TXTR", "ROST"}


if __name__ == "__main__":
    m = nfl.inventory(CACHE / "disc.gdi", chd_sha256=CHD_SHA256)
    print(json.dumps({"source": m["source"], "groups": m["groups"]}, indent=2))

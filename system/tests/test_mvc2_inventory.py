"""MVC2 Dreamcast inventory (#1315) and quoted .gdi track names (Redump sets such as the owned MVC2 7z)."""
import hashlib
import struct
from pathlib import Path

import pytest

from gbox import mvc2_inventory as inv
from gbox.gdrom import GDRom, gdi_fields

START = 45000
# The owned USA disc wherever this node unpacked it: the #1417 favorite's cache dir (the characters._dc_gdi
# convention), the #1315 unpack test_mvc2_dat.py reads, or the ad-hoc CHD extract. First that exists; none -> skip.
_OWNED_DIRS = ("86184244a61f816e", "02db6d37c0e20375", "mvc2_usa_chd")
OWNED = next((p for p in (Path.home() / "gBox_alt/gbox-cache/dc" / d / "disc.gdi" for d in _OWNED_DIRS) if p.exists()),
             Path.home() / "gBox_alt/gbox-cache/dc" / _OWNED_DIRS[0] / "disc.gdi")


def _rec(extent: int, size: int, flags: int, name: bytes) -> bytes:
    n = 33 + len(name)
    n += n % 2
    r = bytearray(n)
    r[0] = n
    struct.pack_into("<I", r, 2, extent)
    struct.pack_into(">I", r, 6, extent)
    struct.pack_into("<I", r, 10, size)
    struct.pack_into(">I", r, 14, size)
    r[25], r[32] = flags, len(name)
    r[33:33 + len(name)] = name
    return bytes(r)


def _ip() -> bytes:
    s = bytearray(b" " * 0x100)
    for off, text in ((0, b"SEGA SEGAKATANA "), (0x10, b"SEGA ENTERPRISES"), (0x20, b"009B GD-ROM1/1  "),
                      (0x30, b" U      "), (0x38, b"27BBA10 "), (0x40, b"T1212N    "), (0x4A, b"V1.001"),
                      (0x50, b"20000529        "), (0x60, b"1ST_READ.BIN    "), (0x70, b"SEGA LC-T-12    "),
                      (0x80, b"MARVEL VS CAPCOM 2")):
        s[off:off + len(text)] = text
    return bytes(s).ljust(2048, b"\0")


def _dat() -> bytes:
    table = [0x40, 0x100, 0, 0x140] + [0] * 12          # slot 2 empty; sizes 0xc0, 0x40, 0x20
    return struct.pack("<16I", *table) + bytes(0x140 - 0x40) + b"\x11" * 0x20


def make_disc(tmp_path: Path, files: dict) -> Path:
    """A GDI whose quoted track names contain spaces; track 3 = IP.BIN, PVD at +16, root dir at +18, files."""
    lba, recs, blobs = START + 19, [_rec(START + 18, 2048, 2, b"\0"), _rec(START + 18, 2048, 2, b"\1")], []
    for name in sorted(files):
        data = files[name]
        recs.append(_rec(lba, len(data), 0, name.encode() + b";1"))
        blobs.append(data.ljust(max(1, -(-len(data) // 2048)) * 2048, b"\0"))
        lba += len(blobs[-1]) // 2048
    pvd = bytearray(2048)
    pvd[0], pvd[1:6] = 1, b"CD001"
    pvd[156:190] = _rec(START + 18, 2048, 2, b"\0")
    track = b"".join([_ip()] + [bytes(2048)] * 15 + [bytes(pvd), bytes(2048), b"".join(recs).ljust(2048, b"\0")])
    (tmp_path / "Fake Game (Track 1).bin").write_bytes(b"")
    (tmp_path / "Fake Game (Track 3).bin").write_bytes(track + b"".join(blobs))
    gdi = tmp_path / "Fake Game.gdi"
    gdi.write_text('2\n1 0 4 2352 "Fake Game (Track 1).bin" 0\n3 45000 4 2048 "Fake Game (Track 3).bin" 0\n')
    return gdi


def test_gdi_fields_keeps_quoted_names_whole():
    assert gdi_fields('3 45000 4 2352 "Marvel vs. Capcom 2 (USA) (Track 3).bin" 0') == [
        "3", "45000", "4", "2352", "Marvel vs. Capcom 2 (USA) (Track 3).bin", "0"]
    assert gdi_fields("1 0 4 2352 track01.bin 0") == ["1", "0", "4", "2352", "track01.bin", "0"]


def test_gdrom_opens_quoted_track_names(tmp_path):
    gdi = make_disc(tmp_path, {"1ST_READ.BIN": b"\x09\x00" * 8})
    assert GDRom(gdi).read("1ST_READ.BIN") == b"\x09\x00" * 8


def test_dat_sections_sizes_and_empty_slots():
    assert inv.dat_sections(_dat()) == [{"slot": 0, "offset": 0x40, "size": 0xC0},
                                        {"slot": 1, "offset": 0x100, "size": 0x40},
                                        {"slot": 3, "offset": 0x140, "size": 0x20}]


@pytest.mark.parametrize("data", [b"\x03\x00\x00\x00" + bytes(12), struct.pack("<4I", 16, 0x999, 0, 0), b"\x10"])
def test_dat_sections_rejects_non_tables(data):
    with pytest.raises(ValueError):
        inv.dat_sections(data)


def test_ip_header_identity_and_region():
    ip = inv.ip_header(_ip())
    assert (ip["product"], ip["version"], ip["regions"], ip["boot"]) == ("T1212N", "V1.001", ["USA"], "1ST_READ.BIN")
    with pytest.raises(ValueError):
        inv.ip_header(bytes(256))


def test_roster_has_59_ids_with_abyss_forms():
    assert len(inv.ROSTER) == 59 and all(n.startswith("Abyss") for n in inv.ROSTER[0x18:0x1B])


def test_inventory_on_a_synthetic_disc(tmp_path):
    boot = b"\x09\x00" * 64
    gdi = make_disc(tmp_path, {"1ST_READ.BIN": boot, "PL00_DAT.BIN": _dat(), "PL00_FAC.BIN": b"face",
                               "PL00_VOI.BIN": b"DTPK", "S_PL00A.BIN": b"code", "STG00TEX.BIN": b"tex"})
    man = inv.inventory(gdi)
    ryu = man["characters"][0]
    assert man["ip"]["product"] == "T1212N" and man["platform_check"] == "dreamcast"
    assert man["boot"] == {"name": "1ST_READ.BIN", "size": len(boot), "sha256": hashlib.sha256(boot).hexdigest()}
    assert ryu["name"] == "Ryu" and "PL00_WIN.BIN" in ryu["missing"] and ryu["dat_sections"][2]["size"] == 0x20
    assert ryu["files"]["dat"]["sha256"] == hashlib.sha256(_dat()).hexdigest()
    assert man["groups"]["character"]["files"] == 4 and man["groups"]["3D stage textures/polygons"]["files"] == 1
    assert len(man["characters"]) == 59 and man["characters"][0x3A]["missing"]


@pytest.mark.skipif(not OWNED.exists(), reason="owned MVC2 USA disc not unpacked on this node")
def test_owned_usa_disc():
    man = inv.inventory(OWNED, hash_files=False)
    assert (man["ip"]["product"], man["ip"]["version"], man["ip"]["regions"]) == ("T1212N", "V1.001", ["USA"])
    assert man["boot"]["sha256"] == "862e43cdd42fab395e2d71c8f1d9435f41af79380fe3b2820cb9ba25fe1f234f"
    chars = man["characters"]
    assert all(c["dat_sections"][0]["offset"] == 0x40 for c in chars)
    assert [c["hex"] for c in chars if any("_WIN" in m for m in c["missing"])] == ["18", "19", "1A"]

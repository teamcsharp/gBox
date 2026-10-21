import hashlib
import json
from pathlib import Path

import pytest

from gbox import doa2_inventory as inv

GDI = Path.home() / "gBox_alt/gbox-cache/dc/1de2e7634f3161ff/disc.gdi"


def _ip(product=b"T3601M    ", version=b"V1.002", area=b"J       "):
    s = bytearray(b" " * 0x100)
    s[0:16] = b"SEGA SEGAKATANA "
    s[0x10:0x20] = b"SEGA ENTERPRISES"
    s[0x30:0x38] = area
    s[0x40:0x4A] = product
    s[0x4A:0x50] = version
    s[0x50:0x58] = b"20000829"
    s[0x60:0x6C] = b"1ST_READ.BIN"
    s[0x80:0x8F] = b"DEAD OR ALIVE 2"
    return bytes(s)


def test_parse_ip_fields():
    ip = inv.parse_ip(_ip())
    assert (ip["product"], ip["version"], ip["date"], ip["area"]) == ("T3601M", "V1.002", "20000829", "J")
    assert ip["boot"] == "1ST_READ.BIN" and ip["title"] == "DEAD OR ALIVE 2"


def test_parse_ip_rejects_non_dreamcast():
    with pytest.raises(ValueError):
        inv.parse_ip(b"\0" * 0x100)


def test_file_room_runs_to_next_lba_and_rounds_the_last_file():
    files = {"A": (100, 5000), "B": (110, 10), "C": (110, 0), "D": (120, 2049)}
    room = inv.file_room(files)
    assert room["A"] == 10 * 2048          # padding up to B is usable
    assert room["B"] == 10 * 2048          # C shares B's LBA (empty file); next distinct LBA is D
    assert room["D"] == 2 * 2048     # last file: its own sector-rounded size
    # a file never gets less than its own rounded size, even with overlapping LBAs
    assert inv.file_room({"X": (10, 9000), "Y": (11, 1)})["X"] == 5 * 2048


def test_families_skip_stages_and_effects():
    names = ["DOA2/KAS00.CHR", "DOA2/KAS10.BIN", "DOA2/KAS04.MDL", "DOA2/STAGE01.CHR",
             "DOA2/EFC00.BIN", "DOA2/KASUMI.MOT", "DOA2/LOR00.SUP", "1ST_READ.BIN"]
    assert inv.families(names) == {"KAS": ["00", "04", "10"], "LOR": ["00"]}


@pytest.mark.skipif(not GDI.exists(), reason="owned DOA2 LE disc not unpacked on this node")
def test_owned_disc_inventory_matches_exact_build(tmp_path):
    m = inv.build(GDI, hash_tracks=False)
    json.dumps(m)                                       # manifest is plain JSON
    assert m["ip"]["product"] == "T3601M" and m["ip"]["version"] == "V1.002" and m["ip"]["area"] == "J"
    assert m["executable"]["matches"] and m["build_matches"]
    s = inv.summary(m)
    assert s["files"] == 960 and s["families"] == 19 and s["costumes"] == 80
    assert s["chr_files"] == 80 and s["chr_decoded"] == 80 and s["models"] == 3800
    assert s["motion_files"] == 149 and s["stages"] == 92
    kas = next(r for r in m["characters"] if r["key"] == "KAS")
    c0 = next(c for c in kas["costumes"] if c["costume"] == "00")
    assert c0["chr"]["decoded"] and c0["chr"]["models"] > 0 and c0["chr"]["textures"] > 0
    assert c0["chr"]["room"] >= c0["chr"]["bytes"] and c0["bin"]["bytes"] > 0
    assert {mm["file"] for mm in kas["motion"]} == {"DOA2/KASUMI.MOT", "DOA2/C_KASUMI.MOT"}
    # read-only: hashing the CHR again gives the recorded value
    from gbox.gdrom import GDRom
    assert hashlib.sha256(GDRom(GDI).read("DOA2/KAS00.CHR")).hexdigest() == c0["chr"]["sha256"]

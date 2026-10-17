"""WCW/nWo Revenge (Europe, NW2P) profile and owned-build inventory (#1317)."""
from pathlib import Path

import numpy as np
import pytest

from gbox import aki_wcw as W
from gbox import aki_wcw_inventory as I

ROMS = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms")
EU_ZIP = ROMS / "Europe/WCW-nWo Revenge (Europe).zip"
US_ZIP = ROMS / "USA/WCW-nWo Revenge (USA).zip"


def test_pal_header_selects_revenge_profile():
    rom = bytearray(0x1000)
    rom[0x3B:0x3F], rom[0x3F] = b"NW2P", 0
    p = W.profile(bytes(rom))
    assert p["layout"] == "rv" and (p["first"], p["ft"]) == (0xD81E0, 0xCDFCE2)
    us = W.PROFILES[("NW2E", 0)]
    # same asset set and the same writer patch kinds, in the same order, so Writer.build patches every site
    assert (p["nfiles"], p["nmodels"], p["groups"], p["sets"], p["bodies"]) == \
           (us["nfiles"], us["nmodels"], us["groups"], us["sets"], us["bodies"])
    assert [k for _r, _i, k in p["patch"]] == [k for _r, _i, k in us["patch"]]
    assert p["ft"] - p["first"] == us["ft"] - us["first"]


def test_masked_match_and_xrefs_follow_moved_code():
    # base: addiu sp; sw ra; lui at,0x8003; lw v0,0x17f0(at) (-> 0x800317f0); sll; addu; jr ra; addiu sp; filler
    body = [0x27BDFFE8, 0xAFBF0014, 0x3C018003, 0x8C2217F0, 0x00021080, 0x00441021, 0x03E00008, 0x27BD0018]
    filler = [0x00851021 + (k << 11) for k in range(24)]
    base = np.array(body + filler, np.uint32)
    moved = list(body)
    moved[3] = 0x8C22EF40                                   # PAL: lw v0,-0x10c0(at) -> 0x8002ef40
    target = np.array([0x00000000, 0x24020001, 0x00000000] + moved + filler, np.uint32)
    mb, mt = I.masked(base), I.masked(target)
    assert I.match(mb, mt, 3) == 6
    refs = I.lui_refs(base, {0x800317F0})
    assert refs == {0x800317F0: [(2, 3)]}
    i, j = refs[0x800317F0][0]
    ti = I.match(mb, mt, i)
    assert ti is not None
    assert I.imm_addr(int(target[ti]), int(target[ti + j - i])) == 0x8002EF40
    assert I.match(mb, I.masked(np.array(filler, np.uint32)), 3) is None


def test_header_and_container_report_actual_byte_order(tmp_path):
    import zipfile
    rom = bytearray(0x1000)
    rom[0:4] = b"\x80\x37\x12\x40"
    rom[0x20:0x34] = b"WCW / nWo  REVENGE  "
    rom[0x3B:0x3F] = b"NW2P"
    h = I.header(bytes(rom))
    assert (h["code"], h["region"], h["rev"]) == ("NW2P", "Europe", 0)
    v64 = bytearray(rom)
    v64[0::2], v64[1::2] = rom[1::2], rom[0::2]
    z = tmp_path / "rv.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("WCW-nWo Revenge (Europe).z64", bytes(v64))
    c = I.container(z)
    assert c["members"][0]["byte_order"].startswith("v64") and c["members"][0]["extension_matches"] is False


@pytest.mark.skipif(not (EU_ZIP.exists() and US_ZIP.exists()), reason="owned Revenge ROMs not mounted")
def test_owned_pal_build_rederives_profile_and_matches_usa_assets():
    from gbox import n64_rom
    eu, us = n64_rom.read(EU_ZIP), n64_rom.read(US_ZIP)
    assert I.header(eu)["sha256_z64"] == "e4bd4f49d6e2217294cd2f9178488349eabd44155e4ad0436a9d1ddef58c53da"
    assert I._norm(I.derive_profile(us, eu)) == I._norm(W.PROFILES[("NW2P", 0)])
    m = I.inventory(eu, None, us)
    assert m["roster"]["wrestlers"] == 92 and m["roster"]["costumes"] == 736
    assert m["vs_base"] == m["vs_base"] | {"file_table_equal": True, "files_differing": [527], "names_equal": True,
                                           "costume_parts_equal": True, "profile_rederived": True}
    sting = next(w for w in m["wrestlers"] if w["name"] == "Sting")
    assert len(sting["costumes"]) >= 1 and len(sting["costumes"][0]["parts"]) >= 15
    # every writer patch site holds the instruction the profile expects (Writer.build's put() check)
    for ram, ins, _k in W.PROFILES[("NW2P", 0)]["patch"]:
        assert int.from_bytes(eu[W.Rom.r2r(ram):W.Rom.r2r(ram) + 4], "big") == ins

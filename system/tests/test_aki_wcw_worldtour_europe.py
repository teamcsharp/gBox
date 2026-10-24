"""WCW vs. nWo: World Tour (Europe, NWNP rev 0) profile and owned-build manifest (#1778)."""
from pathlib import Path

import pytest

from gbox import aki_wcw as W
from gbox import aki_wcw_inventory as I

OWNED = Path(__file__).resolve().parents[1] / "owned"
EU_Z64 = OWNED / "eu.z64"
US_Z64 = OWNED / "usa.z64"
EU_SHA256 = "177b179b78c86b97ac5ee21d7eed543ddd1a1a71a41d74adcb4c7bbdfff5f479"
US_SHA256 = "3711c8838b18374d1c7be0192ad824082d33978f00b886d145bc55a782325d4d"
NW = 45
COSTUMES = 180
TARGET_NAME = 'Hulk Hogan'
TARGET_PARTS = 21


def _wrestlers(man):
    """The manifest's wrestler list (roster["wrestlers"] is only a count)."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list) and node and isinstance(node[0], dict) and "name" in node[0]:
            found.append(node)
    walk(man)
    assert found, "manifest has no wrestler list"
    return found[0]


def test_pal_header_selects_worldtour_europe_profile():
    rom = bytearray(0x1000)
    rom[0x3B:0x3F], rom[0x3F] = b"NWNP", 0
    p = W.profile(bytes(rom))
    assert p["layout"] == "wt" and p["game"] == "worldtour"
    us = W.PROFILES[("NWNE", 1)]
    # same asset set and the same writer patch kinds, in the same order, so Writer.build patches every site
    for k in ("nfiles", "nmodels", "groups", "bodies"):
        assert p[k] == us[k]
    assert [k for _r, _i, k in p["patch"]] == [k for _r, _i, k in us["patch"]]
    assert p["ft"] - p["first"] == us["ft"] - us["first"]
    assert p["profile_area"][0] < p["profile_area"][1]
    # the USA build still selects its own profile
    assert W.profile(bytearray(b"\x00" * 0x3B + b"NWNE\x01"))["layout"] == "wt"


@pytest.mark.skipif(not (EU_Z64.exists() and US_Z64.exists()), reason="owned World Tour ROMs not mounted")
def test_owned_europe_build_rederives_profile_and_manifest():
    import hashlib
    from gbox import n64_rom

    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                h.update(c)
        return h.hexdigest()

    assert sha(EU_Z64) == EU_SHA256 and sha(US_Z64) == US_SHA256
    eu, us = n64_rom.read(EU_Z64), n64_rom.read(US_Z64)
    h = I.header(eu)
    assert (h["code"], h["region"], h["rev"]) == ("NWNP", "Europe", 0)
    assert h["sha256_z64"] == EU_SHA256
    # the Europe profile re-derives from the owned bytes, not from a copied hash
    assert I._norm(I.derive_profile(us, eu, ("NWNE", 1))) == I._norm(W.PROFILES[("NWNP", 0)])
    m = I.inventory(eu, None, us)
    wres = _wrestlers(m)
    assert len(wres) == NW
    assert m["roster"]["wrestlers"] == NW and m["roster"]["costumes"] == COSTUMES
    # one identified native target asset: the first roster wrestler's costume 0 parts
    tgt = next((w for w in wres if w.get("name") == TARGET_NAME), wres[0])
    parts = tgt["costumes"][0]["parts"]
    assert len(parts) == TARGET_PARTS
    nfiles = W.PROFILES[("NWNP", 0)]["nfiles"]
    for _part, v in parts.items():
        assert isinstance(v, list) and v
        assert 0 <= v[0] < nfiles          # the part's file id is inside the NWNP file table
    # every writer patch site holds the instruction the profile expects (Writer.build's put() check)
    for ram, ins, _k in W.PROFILES[("NWNP", 0)]["patch"]:
        assert int.from_bytes(eu[W.Rom.r2r(ram):W.Rom.r2r(ram) + 4], "big") == ins

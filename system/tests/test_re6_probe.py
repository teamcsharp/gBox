"""Focused tests for gbox.re6_probe (synthetic header check always; owned-ISO probe when present)."""

import os
import struct
from pathlib import Path

import pytest

from gbox.re6_models import HEADER
from gbox.re6_probe import DEFAULT_ARC, header_check, probe_iso

ISO = Path(os.environ.get("RE6_ISO", "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Resident Evil 6.iso"))
LEON_MOD_SHA = "ecfd8ad529b56a8300572dabe40ccbd28865824aaced38e51d66289d5178d356"


def _hdr(**kw):
    f = dict(nb=1, nm=1, nmat=1, nv=3, ni=3, ntri=1, vbs=16, ntex=0, ng=1, ob=0x80, og=0xA0, omat=0xC0,
             omesh=0xD0, ovb=0x100, oib=0x110, oend=0x118)
    f.update(kw)
    d = bytearray(0x120)
    struct.pack_into(HEADER, d, 0, b"\0DOM", 0xD3, f["nb"], f["nm"], f["nmat"], f["nv"], f["ni"], f["ntri"], f["vbs"],
                     f["ntex"], f["ng"], f["ob"], f["og"], f["omat"], f["omesh"], f["ovb"], f["oib"], f["oend"])
    return bytes(d)


def test_header_check_consistent():
    h = header_check(_hdr())
    assert h["magic"] == "\0DOM" and h["version"] == "0xd3" and h["offsets_consistent"] is True


def test_header_check_rejects_bad_offsets():
    assert header_check(_hdr(oib=0x90))["offsets_consistent"] is False      # unordered
    assert header_check(_hdr(ntri=2))["offsets_consistent"] is False        # tris*3 != indices
    assert header_check(_hdr(oend=0x400))["offsets_consistent"] is False    # past end


@pytest.mark.skipif(not ISO.exists(), reason="owned RE6 ISO not mounted")
def test_leon_usa_exact_build():
    r = probe_iso(str(ISO), DEFAULT_ARC)
    m = r["mod"]
    assert (m["bones"], m["prims"], m["verts"], m["indices"], m["tris"]) == (54, 103, 25784, 97929, 32643)
    assert m["mod_sha256"] == LEON_MOD_SHA and m["header"]["offsets_consistent"]
    assert m["noop_roundtrip"]["byte_identical"] and m["changed_bone"]["applied"] and m["changed_bone"]["others_unchanged"]
    assert r["arc_rebuild"]["mod_roundtrip_identical"]

"""Focused tests for the .zzz / UE3 package probe (Too Human analysis stage)."""
import gzip
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import toohuman_inventory as inv

ISO = "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Too Human.iso"


def _ue3_block(ver=1500):
    return (inv.UE3_PACKAGE_MAGIC + ver.to_bytes(4, "big") + b"\x00\x00\x00\x01"
            + b"\x00\x00\x00\x02" + b"\x00\x00\x00\x03" + b"\x00\x00\x00\x04")


def test_magic_constants():
    assert inv.ZZZ_MAGIC == b"\xf0\x0d\xca\xfe"
    assert inv.UE3_PACKAGE_MAGIC == b"FACB"


def test_find_ue3_packages_synthetic():
    payload = inv.ZZZ_MAGIC + b"\x00" * 32 + _ue3_block() + b"\x00" * 16
    pkgs = inv.find_ue3_packages(payload)
    assert len(pkgs) == 1
    assert pkgs[0]["offset"] == 36
    assert pkgs[0]["header_u32"] == [1500, 1, 2, 3]


def test_zzz_probe_synthetic():
    payload = inv.ZZZ_MAGIC + b"\x00" * 32 + _ue3_block()
    out = inv.zzz_probe(payload)
    assert out["size"] == len(payload)
    assert out["ue3_count"] == 1
    assert out["ue3_packages"][0]["offset"] == 36


def test_zzz_probe_rejects_bad_magic():
    with pytest.raises(ValueError):
        inv.zzz_probe(b"\x00\x01\x02\x03" + b"\x00" * 32)


@pytest.mark.skipif(not os.path.exists(ISO), reason="owned Too Human disc not mounted")
def test_pla001_zzz_embeds_ue3_packages():
    from gbox import re6
    d = re6.XDVD(ISO)
    try:
        off, size = d.files["/pla001.zzz.gz"]
        d.f.seek(off)
        payload = gzip.decompress(d.f.read(size))
    finally:
        d.close()
    assert payload[:4] == inv.ZZZ_MAGIC
    out = inv.zzz_probe(payload)
    assert out["ue3_count"] >= 1
    assert out["ue3_packages"][0]["offset"] > 0

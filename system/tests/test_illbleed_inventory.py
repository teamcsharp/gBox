"""Pinned checks for gbox.illbleed_inventory: NJTL header/chunk parsing on synthetic data, plus the
full-disc inventory pinned to the owned Illbleed (USA) GD-ROM when its cache is present
(GBOX_ILLBLEED_GDI, default ~/gBox_alt/gbox-cache/dc/81a90290abc15a37/disc.gdi)."""
import json
import os
import struct
from pathlib import Path

import pytest

from gbox import illbleed_inventory as iv

CHD_SHA = "cc63a6ba7d9b918a5969a39df3f24af0486fe0f9a998d5ca62f717fb454edaf7"
EXE_SHA = "af9686e11df9efc02bcf97b7e5e744a4d981cfebdab7e1fe8a0281396461cee7"
DEFAULT_GDI = "~/gBox_alt/gbox-cache/dc/81a90290abc15a37/disc.gdi"


def synth_nj(names, chunks=()):
    """A minimal NJTL file: header, 12-byte entries, names, then an 8-byte-header chunk stream."""
    base = 8
    head = b"NJTL" + struct.pack("<III", 0, base, len(names))
    name_table_start = len(head) + len(names) * 12
    entries = b""
    name_blob = b""
    for n in names:
        off = (name_table_start - base) + len(name_blob)
        entries += struct.pack("<III", off, 0, 0)
        name_blob += n.encode() + b"\0"
    body = b""
    for typ, payload in chunks:
        body += typ.encode() + struct.pack("<I", len(payload)) + payload
    blob = head + entries + name_blob
    blob += b"\0" * ((4 - len(blob) % 4) % 4)
    blob += body
    return blob


def test_njtl_parses_names_and_start():
    d = synth_nj(["vkev001z", "vkev002z"])
    head = iv.njtl(d)
    assert head["names"] == ["vkev001z", "vkev002z"]
    assert head["chunk_start"] == 60  # 16-byte header + 2*12-byte entries + 18-byte names, aligned
    assert head["name_base"] == 8


def test_chunks_walk_and_must_consume_exactly():
    d = synth_nj(["a"], (("POF0", b"\x40\x42\x43\x43"), ("NJCM", b"\x01" * 16)))
    head = iv.njtl(d)
    walk = iv.chunks(d, head["chunk_start"])
    assert [(c["type"], c["size"]) for c in walk] == [("POF0", 4), ("NJCM", 16)]


def test_chunks_reject_truncated():
    d = synth_nj(["a"], (("POF0", b"\x40\x42\x43\x43"),))
    d = d[:-1]
    with pytest.raises(ValueError):
        iv.chunks(d, iv.njtl(d)["chunk_start"])


def test_njtl_rejects_garbage():
    with pytest.raises(ValueError):
        iv.njtl(b"\x00" * 64)


def test_njtl_rejects_entry_count_past_the_file():
    with pytest.raises(ValueError, match="overrun"):
        iv.njtl(b"NJTL" + struct.pack("<III", 0, 8, 0x10000000) + b"\0" * 16)



def test_afs_and_cgam_and_cglc_headers():
    afs = b"AFS\0" + struct.pack("<I", 1) + struct.pack("<II", 0x80000, 0x1464)
    assert iv.afs(afs)["count"] == 1
    assert iv.cgam(b"CGAM" + struct.pack("<II", 0x10, 1) + b"\0" * 8) == {"size": 0x10, "count": 1}
    assert iv.cglc(b"CGLC" + struct.pack("<II", 0x30, 2) + b"\0" * 0x24) == {"size": 0x30, "count": 2}
    with pytest.raises(ValueError):
        iv.cgam(b"CGAM" + struct.pack("<II", 0xFFFF, 1) + b"\0" * 8)


@pytest.fixture(scope="module")
def disc_gdi():
    p = Path(os.environ.get("GBOX_ILLBLEED_GDI", DEFAULT_GDI)).expanduser()
    if not p.exists():
        pytest.skip("Illbleed disc cache not present")
    return str(p)


@pytest.mark.skipif(not Path(os.environ.get("GBOX_ILLBLEED_GDI", DEFAULT_GDI)).expanduser().exists(),
                    reason="disc cache")
def test_full_inventory_pins(disc_gdi):
    m = iv.inventory(disc_gdi, CHD_SHA)
    assert m["source_sha256"] == CHD_SHA
    assert m["problems"] == []
    assert m["ip"]["product"] == "T46001N" and m["ip"]["version"] == "V1.002"
    assert m["ip"]["area"] == "U" and m["ip"]["date"] == "20010321"
    assert m["executable"]["sha256"] == EXE_SHA
    assert m["containers"]["nj"]["all_walk_ok"] is True
    assert m["containers"]["nj"]["count"] == 79
    assert m["containers"]["afs"]["count"] == 669 and m["containers"]["afs"]["parsed"] == 669
    assert len(m["characters"]) == 5
    names = [c["textures"] for c in m["characters"] if "textures" in c]
    assert any("vkev001z" in n for n in names) and any("vmic000z" in n for n in names)
    chars = {c["stem"]: c for c in m["characters"]}
    assert chars["C00"]["main_sha256"] == "3ba3b57b613b7de4375f4ebc5d2ca107006ac18bd635da1ef4e44638dd301145"
    assert chars["C01"]["main_sha256"] == "f7abf84aa9dc92ff638527c7160e9bb8b22a4e7aa89623136f6893535ecc316f"
    assert len(m["enemies"]) == 50 and len(m["effect_sprites"]) == 10
    assert "CMCK" in chars["C00"]["chunks"]  # embedded animation chunk present

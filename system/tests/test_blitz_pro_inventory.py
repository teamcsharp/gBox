import os
import re
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox.blitz_pro_inventory import (  # noqa: E402
    PAK_PART_MARKER,
    FormatError,
    pak_header,
    pak_id_records,
    pak_inventory,
    pak_part_entries,
    part_names,
)

GCZ = os.environ.get(
    "BLITZPRO_GCZ",
    "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/NFL Blitz Pro (USA).gcz",
)


def fixture_pak(*, part_names_in=(b"c0130_1", b"c0130_2"), ids=(b"1000", b"1002")) -> bytes:
    """Synthetic container shaped like the owned blitz04.mpk header and directory records."""
    buf = bytearray(b"\0" * 0x200)
    buf[0:4] = b"PAK "
    struct.pack_into(">5I", buf, 4, 0x200, 0x170E3D40, 0x6C10, 0x4F1C, 0x200000)
    off = 0x40
    for ident in ids:
        buf[off:off + 16] = ident + b"\0" * 12
        off += 0x20
        for name in part_names_in:
            buf[off:off + 8] = PAK_PART_MARKER
            buf[off + 8:off + 16] = name + b"\0" * (8 - len(name))
            off += 0x34
    return bytes(buf)


def test_header_fields():
    hdr = pak_header(fixture_pak())
    assert hdr["version"] == 0x200
    assert hdr["size_field"] == 0x170E3D40
    assert hdr["field_0c"] == 0x6C10
    assert hdr["field_10"] == 0x4F1C
    assert hdr["field_14"] == 0x200000


def test_rejects_non_pak():
    with pytest.raises(FormatError):
        pak_header(b"NOPE" + b"\0" * 32)
    with pytest.raises(FormatError):
        pak_header(b"PAK ")


def test_id_records_and_part_entries():
    b = fixture_pak()
    ids = pak_id_records(b)
    assert [i["id"] for i in ids] == ["1000", "1002"]
    assert ids[0]["offset"] == 0x40
    parts = pak_part_entries(b)
    assert [p["name"] for p in parts] == ["c0130_1", "c0130_2"] * 2
    inv = pak_inventory(b)
    assert inv["id_count"] == 2
    assert inv["part_count"] == 4
    assert inv["parts"][0]["id"] == "1000"
    assert inv["parts"][2]["id"] == "1002"
    assert part_names(b, len(b)) == ["c0130_1", "c0130_2"]


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned NFL Blitz Pro (USA).gcz not present")
def test_owned_build_blitz04_mpk():
    """Byte-verified facts about the owned build's PAK directory (see module docstring)."""
    from gbox.gcdisc import GCDisc

    data = GCDisc(GCZ).read("blitz04.mpk")
    assert data[:4] == b"PAK "
    hdr = pak_header(data)
    assert hdr["version"] == 0x200
    assert hdr["size_field"] == 0x170E3D40
    assert hdr["field_0c"] == 0x6C10
    assert hdr["field_10"] == 0x4F1C
    assert hdr["field_14"] == 0x200000

    inv = pak_inventory(data, 1 << 22)
    # directory id records: "1000" at 0x40, "1002" at 0x220, "1003" at 0x540 ...
    assert inv["ids"][:3] == ["1000", "1002", "1003"]
    assert [i["offset"] for i in pak_id_records(data, 1 << 22)][:3] == [0x40, 0x220, 0x540]
    assert inv["id_count"] >= 200

    # part entries: 0x5622/0xcdcdcdcd marker then an 8-byte name
    first = [(p["offset"], p["name"], p["id"]) for p in inv["parts"][:3]]
    assert first == [
        (0xFC, "c0130_1", "1000"),
        (0x130, "c0130_2", "1000"),
        (0x2F4, "c0132_1", "1002"),
    ]
    assert inv["part_count"] >= 100
    assert len(inv["part_names"]) >= 100
    matched = [n for n in inv["part_names"] if re.fullmatch(r"c\d{4}_\d", n)]
    assert len(matched) >= 100
    assert all(p["id"] for p in inv["parts"][:50])

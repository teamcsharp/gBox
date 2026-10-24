import struct
import pytest
from gbox import mugen_sff as m


def _pcx(w, h):
    hdr = bytearray(128)
    hdr[0], hdr[1], hdr[2], hdr[3] = 0x0A, 5, 1, 8
    struct.pack_into("<HHHH", hdr, 4, 0, 0, w - 1, h - 1)
    hdr[65] = 1
    return bytes(hdr) + b"\x00" * (w * h) + b"\x0c" + bytes(range(256)) * 3


def _sff(items):
    """items: list of (group, image, pcx_bytes|None(linked->0), link)"""
    body, off = bytearray(), m.HEADER
    for i, (g, im, pcx, link) in enumerate(items):
        data = pcx or b""
        nxt = 0 if i == len(items) - 1 else off + m.SUB + len(data)
        body += struct.pack("<IIhhHHHB13s", nxt, len(data), 3, 4, g, im, link, 0, b"")
        body += data
        off += m.SUB + len(data)
    head = m.SIG + bytes([0, 1, 0, 1]) + struct.pack("<IIII", 2, len(items), m.HEADER, m.SUB)
    head += b"\x01" + b"\x00" * 3
    return head.ljust(m.HEADER, b"\x00") + bytes(body)


def test_sprite_table_and_link():
    d = m.parse_sff1(_sff([(0, 0, _pcx(4, 5), 0), (0, 1, None, 0)]))
    s = d["sprites"]
    assert d["images"] == 2 and s[0]["width"] == 4 and s[0]["height"] == 5 and s[0]["axis"] == (3, 4)
    assert s[0]["palette_offset"] and s[1]["linked"] == 0 and s[1]["kind"] == "linked"


def test_rejects_bad_input():
    with pytest.raises(m.MugenError):
        m.parse_sff1(b"x" * 600)
    good = bytearray(_sff([(0, 0, _pcx(2, 2), 0), (0, 1, _pcx(2, 2), 0)]))
    struct.pack_into("<I", good, m.HEADER, m.HEADER)  # next pointer cycles back
    with pytest.raises(m.MugenError):
        m.parse_sff1(bytes(good))
    fwd = bytearray(_sff([(0, 0, None, 0)]))
    with pytest.raises(m.MugenError):
        m.parse_sff1(bytes(fwd))  # first sprite cannot be linked


def test_select_and_def():
    r = m.parse_select_def("[Characters]\nKFM, stages/a.def ; c\nrandomselect\n[ExtraStages]\nx\n")
    assert [e["name"] for e in r] == ["KFM", "randomselect"] and r[1]["random"]
    c = m.parse_char_def('[Info]\ndisplayname = "Kung Fu Man"\n[Files]\nsprite = kfm.sff\n')
    assert c == {"name": "Kung Fu Man", "files": {"sprite": "kfm.sff"}}


def test_inventory(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "chars" / "KFM").mkdir(parents=True)
    (tmp_path / "mugen.exe").write_bytes(b"MZ")
    (tmp_path / "data" / "select.def").write_text("[Characters]\nkfm\nrandomselect\n")
    (tmp_path / "chars" / "KFM" / "KFM.def").write_text("[Info]\nname=K\n[Files]\nsprite=KFM.SFF\n")
    (tmp_path / "chars" / "KFM" / "KFM.SFF").write_bytes(_sff([(0, 0, _pcx(2, 2), 0)]))
    inv = m.inventory(str(tmp_path))
    assert inv["roster_count"] == 1 and inv["characters"][0]["sff_images"] == 1 and inv["characters"][0]["error"] is None
    assert len(inv["engine_sha256"]) == 64

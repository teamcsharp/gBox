import os, struct, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gbox.wm19_probe import parse_tex, parse_ymg_header

ISO = os.environ.get("WM19_ISO", "/home/ehm_eckx/gBox_alt/gbox-cache/0afbb206f442bb11/source.iso")


def _synth():
    blob = struct.pack(">IIII", 0x20AF30, 1, 0xC, 0x14) + b"\0" * 0x30
    idx = b"hhh_body".ljust(16, b"\0") + b"tpl\0" + struct.pack("<BBHI", 64, 64, 0, 0x230) + b"\0" * 4
    return struct.pack("<I", 1) + b"\0" * 12 + idx + b"\0" * (0x230 - 0x30) + blob


def test_tex_synthetic():
    e = parse_tex(_synth())
    assert e[0]["name"] == "hhh_body" and e[0]["w"] == 64 and e[0]["size"] == 0x40


def test_ymg_synthetic():
    h = parse_ymg_header(b"YOBJ" + struct.pack(">15I", 0x40, *range(14)) + b"\0" * 8)
    assert h["layout"] == "flat" and h["extra"] == len(b"YOBJ") + 60 + 8 - 0x40


@pytest.mark.skipif(not os.path.exists(ISO), reason="owned disc not present")
def test_real_disc_wrestler_tex_all_parse():
    from gbox.gcdisc import GCDisc
    d = GCDisc(ISO)
    assert d.game_id == "GW9E78"
    names = [k for k in d.files if k.startswith("model/wrestler/") and k.endswith(".tex")]
    assert len(names) == 162
    for k in names:
        ents = parse_tex(d.read(k))
        assert ents and sum(e["size"] for e in ents) <= d.files[k][1]
    first = parse_tex(d.read("model/wrestler/000_0.tex"))
    assert len(first) == 25 and first[0]["name"] == "hhh_body"
    assert parse_ymg_header(d.read("model/wrestler/000_0.ymg"))["payload_len"] == 0x10D80

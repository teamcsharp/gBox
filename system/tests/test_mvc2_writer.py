"""MVC2 DC writer: lossless slot round trip, donor visual swap, single-part edit, routing."""
import hashlib
import struct
from pathlib import Path

import pytest

from gbox import mvc2_dat as M
from gbox import mvc2_writer as W

GDI = Path.home() / "gbox-cache/dc/02db6d37c0e20375/disc.gdi"
needs = pytest.mark.skipif(not GDI.exists(), reason="unpacked MVC2 disc cache not present")
_C = {}


def dat(cid):
    if cid not in _C:
        from gbox.gdrom import GDRom
        _C[cid] = GDRom(str(GDI)).read(W.DAT_NAME.format(id=cid))
    return _C[cid]


def _synthetic():
    s0, s1, s5 = b"A" * 12, b"B" * 8, b"C" * 20
    tab = [0] * 16
    tab[0], tab[1], tab[5] = 0x40, 0x4C, 0x54
    return struct.pack("<16I", *tab) + s0 + s1 + s5


def test_synthetic_roundtrip_and_swap():
    d = _synthetic()
    assert W.rebuild_dat(d) == d
    donor = bytearray(d)
    donor[0x40:0x4C] = b"Z" * 12
    out = W.swap_slots(d, bytes(donor), (0,))
    assert out == bytes(donor)[:0x40] + b"Z" * 12 + d[0x4C:] or out[0x40:0x4C] == b"Z" * 12
    assert W.split_dat(out)["slots"][1] == b"B" * 8


def test_slot_presence_mismatch_refused():
    d = _synthetic()
    other = W.rebuild_dat(d)
    t = bytearray(d)
    struct.pack_into("<I", t, 4 * 5, 0)       # drop slot 5 from the donor
    t = bytes(t)
    with pytest.raises(ValueError):
        W.swap_slots(d, t[:0x54], (5,))


def test_parse_cid():
    assert W.parse_cid("player") == 0 and W.parse_cid("fighter:1A") == 0x1A and W.parse_cid("Ryu") == 0


@needs
def test_noop_roundtrip_all_59():
    for cid in range(0x3B):
        d = dat(cid)
        assert W.rebuild_dat(d) == d, f"PL{cid:02X}"


@needs
def test_ryu_noop_hash():
    d = dat(0)
    assert hashlib.sha256(W.rebuild_dat(d)).hexdigest() == \
        "751165ed1fc9f001961a8ed02ec437c5171c7712bf9718694e6a09b97667597b"


@needs
def test_donor_swap_ryu_gets_zangief():
    t, dn = dat(0), dat(1)
    new = W.swap_slots(t, dn)
    ts, ns, ds = W.split_dat(t), W.split_dat(new), W.split_dat(dn)
    for i in W.VISUAL_SLOTS:
        assert ns["slots"][i] == ds["slots"][i]
    for i in set(ts["slots"]) - set(W.VISUAL_SLOTS):      # unrelated members intact
        assert ns["slots"][i] == ts["slots"][i]
    assert ns["pre"] == ts["pre"]
    rb, rd = W.read_back(new), W.read_back(dn)
    assert rb["parts_sha256"] == rd["parts_sha256"] != W.read_back(t)["parts_sha256"]
    assert rb["parts"] == rd["parts"] and rb["anim_groups"] == rd["anim_groups"]
    w, h, rgba = M.render_sprite(new, 5)
    w2, h2, rgba2 = M.render_sprite(dn, 5)
    assert (w, h, rgba) == (w2, h2, rgba2)
    assert rgba != M.render_sprite(t, 5)[2]


@needs
def test_part_replace_readback():
    t = dat(0)
    idx, w, h = M.part_indices(t, 3)
    new_idx = bytes((i + 1) % 16 for i in idx)
    new = W.replace_part(t, 3, new_idx)
    assert M.part_indices(new, 3)[0] == new_idx
    for sel in (0, 2, 4, 1532):                              # unrelated parts byte-exact
        assert M.part_indices(new, sel)[0] == M.part_indices(t, sel)[0]
    assert W.split_dat(new)["slots"][5] == W.split_dat(t)["slots"][5]
    assert W.rebuild_dat(new) == new
    assert M.part_count(new) == 1533


def test_registered_and_routed():
    from gbox import char_coverage as CC, characters as C
    assert any(n == "mvc2_writer" for n, *_ in CC.WRITERS)
    import inspect
    src = inspect.getsource(C.characters_tool)
    assert "mvc2_writer.use(" in src

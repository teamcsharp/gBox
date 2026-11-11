import collections
import pytest
from gbox import madden2005_comp as comp, madden2005_terf as terf
from gbox.gcdisc import GCDisc

DISC = None


def _disc():
    global DISC
    if DISC is None:
        DISC = GCDisc("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/"
                      "Madden NFL 2005 (USA).gcz")
    return DISC


@pytest.mark.parametrize("name,codecs", [
    ("PLADATA.DAT", {0: 70, 5: 365}),
    ("ANIMDATA.DAT", {0: 695, 5: 15}),
])
def test_owned_comp_table_matches_members(name, codecs):
    buf = _disc().read(name)
    idx = terf.parse_terf(buf)
    entries, total = comp.parse_comp(buf, [m.size for m in idx.members])
    got = collections.Counter(e.codec for e in entries[:len(idx.members)])
    assert got[5] == codecs[5]
    assert got[0] == len(idx.members) - codecs[5]
    assert total > 0


def test_synthetic_comp_rejects_missing_terminator():
    import struct
    blob = b"COMP" + struct.pack(">3I", 16, 0, 0) + struct.pack(">II", 0, 0)
    with pytest.raises(ValueError):
        comp.parse_comp(blob)


def test_owned_dol_codec_registry_names_slot5_lzh1():
    dol = _disc().dol
    dol = dol() if callable(dol) else dol
    reg = comp.registry_from_dol(dol)
    assert reg == comp.CODEC_NAMES
    assert reg[comp.CODEC_PACKED] == b"LZH1"


def _synth_stream(literals):
    """Encode literals + EOB with flat 9-bit lit codes? use lengths: 257 syms."""
    bits = "0"
    lit_len = [0] * 285
    for s in set(literals) | {256}:
        lit_len[s] = 9
    # canonical codes (all len 9, assigned in symbol order)
    syms = sorted(set(literals) | {256})
    code = {s: format(k, "09b") for k, s in enumerate(syms)}
    # canonical start for len 9 is count-derived: with only len-9 codes start is 0
    bits += "".join(format(l, "04b") for l in lit_len)
    dist_len = [0] * 30
    dist_len[0] = 1
    bits += "".join(format(l, "04b") for l in dist_len)
    bits += "".join(code[s] for s in literals) + code[256]
    bits += "1" + "0" * 32
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


def test_synthetic_lzh1_literals_roundtrip():
    from gbox import madden2005_lzh1 as lzh1
    data = b"TMdl\x00\x01madden"
    assert lzh1.decode(_synth_stream(list(data)), len(data)) == data


def test_owned_codec5_members_decode_to_tmdl():
    buf = _disc().read("PLADATA.DAT")
    idx = terf.parse_terf(buf)
    entries, _ = comp.parse_comp(buf, [m.size for m in idx.members])
    small = sorted((m.size, m.index) for m, e in zip(idx.members, entries)
                   if e.codec == comp.CODEC_PACKED and 0 < m.size < 30000)[:3]
    assert small
    for _, i in small:
        out = comp.decode_member(buf, i)
        assert len(out) == entries[i].decoded_size
    big = comp.decode_member(buf, 0)
    assert big[:4] == b"TMdl" and len(big) == 115456

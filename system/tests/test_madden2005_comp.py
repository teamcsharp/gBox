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

import glob, json, os, struct
import pytest
EV = json.load(open(os.path.join(os.path.dirname(__file__), "ct_usa_shape_tables.json")))
def _dol():
    for p in [os.environ.get("GBOX_CT_DOL", "")] + glob.glob(os.path.expanduser("~/gBox_alt/gbox-cache/modbase/*/main.dol")):
        if p and os.path.exists(p) and os.path.getsize(p) == EV["main_dol_size"]:
            return open(p, "rb").read()
    gcz = os.path.expanduser("~/gBox_alt/gbox-cache/bc02bb68790ce2e7/Crazy Taxi (USA).gcz")
    if os.path.exists(gcz):
        import sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from gbox.gcdisc import GCDisc
        d = GCDisc(gcz).dol()
        if len(d) == EV["main_dol_size"]:
            return d
    pytest.skip("owned main.dol not present")
def _off(d, va):
    o = struct.unpack_from(">18I", d, 0); a = struct.unpack_from(">18I", d, 0x48); s = struct.unpack_from(">18I", d, 0x90)
    for i in range(18):
        if s[i] and a[i] <= va < a[i] + s[i]:
            return o[i] + va - a[i]
def _table(d, t):
    out = []
    while True:
        p = struct.unpack_from(">I", d, _off(d, t + 16 * len(out)))[0]
        if not 0x80100000 <= p < 0x80200000: return out
        o = _off(d, p); out.append(d[o:d.index(b"\0", o)].decode("latin1"))
def test_tables():
    d = _dol()
    assert len(_table(d, 0x801ff67c)) == EV["tables"]["0x801ff67c"]["entries"]
    s = _table(d, 0x80203d8c)
    assert len(s) == EV["tables"]["0x80203d8c"]["entries"]
    assert [n for n in s if n.startswith("MP_YH_plyrA_")] == EV["tables"]["0x80203d8c"]["plyrA_names"]

def test_0x80135158_is_name_string_not_bone_list():
    d = _dol()
    o = _off(d, 0x80135158)
    assert d[o:d.index(b"\0", o)] == b"MP_YH_plyrA_koshi.shp"
    assert struct.unpack_from(">I", d, _off(d, 0x80203d8c + 16 * 26))[0] == 0x80135158
    assert struct.unpack_from(">3I", d, _off(d, 0x80203d8c + 16 * 26 + 4)) == (0, 0, 0)


def _w(d, va):
    return struct.unpack_from(">I", d, _off(d, va))[0]

def test_shape_loader_loop_0x800866fc():
    """Registry 0x801ff67c is the master shape table (16B entries [name, shape*, ...]).
    Loop at 0x800866fc..0x80086764 calls 0x800062d0(name, 0, "sShape") per entry for 0x647
    entries and stores the result in word1; 0x80006c88 resolves names in the .all archives."""
    d = _dol()
    assert _w(d, 0x800866fc) == 0x3d20 << 16 | 0x8020           # lis r9,-0x7fe0
    assert _w(d, 0x80086704) & 0xffff == 0xf67c                  # addi r28,r9,-0x984
    assert _w(d, 0x80086728) == 0x48000001 | ((0x800062d0 - 0x80086728) & 0x3fffffc)  # bl 0x800062d0
    assert _w(d, 0x80086730) >> 16 == 0x7c1d                     # stwx r0,r29,r31 -> word1
    assert _w(d, 0x80086760) == 0x281e0646                       # cmplwi r30,0x646
    o = _off(d, 0x8012cc70); assert d[o:o + 7] == b"sShape\0"
    assert (0x80203d8c - 0x801ff67c) // 16 == 0x471 <= 0x646   # plyrA names are in the first loop

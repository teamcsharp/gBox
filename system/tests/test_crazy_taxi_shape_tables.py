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


def _bank():
    """ct/polDC0.all of the owned disc: GBOX_CT_BANK, else streamed out of the GCZ."""
    import hashlib, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import gbox.crazy_taxi as ct
    p = os.environ.get("GBOX_CT_BANK", "")
    if p and os.path.exists(p):
        b = open(p, "rb").read()
    else:
        gcz = os.path.expanduser("~/gBox_alt/gbox-cache/bc02bb68790ce2e7/Crazy Taxi (USA).gcz")
        if not os.path.exists(gcz):
            pytest.skip("owned disc not present")
        from gbox.gcdisc import GCDisc
        b = GCDisc(gcz).read("ct/polDC0.all")
    assert hashlib.sha256(b).hexdigest() == ct.BANK_SHA256
    return ct, b


def test_plyrA_name_table_maps_onto_polDC0_bank():
    """All 54 MP_YH_plyrA_* names of the main.dol table 0x80203d8c resolve in polDC0.all, at the
    contiguous bank positions 1110..1163 and in the table's own order (loader 0x80006c88 matches by
    name, so the bank is the archive that carries driver A's rig)."""
    ct, bank = _bank()
    names = [n for n, _, _ in ct.read_bank(bank)]
    assert len(names) == 1586
    plyr = EV["tables"]["0x80203d8c"]["plyrA_names"]
    assert len(plyr) == 54
    idx = [names.index(n) for n in plyr]
    assert idx == list(range(1110, 1164))
    assert names[1136] == "MP_YH_plyrA_koshi.shp"


def test_driver_pose_callers():
    import sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from gbox import crazy_taxi as ct
    d = _dol()
    assert ct.DRIVER_POSE_FN == 0x8005cd18
    calls = ct.driver_pose_callers_from_dol(d)
    assert [c["call"] for c in calls] == [0x8004c96c, 0x8004c9c4, 0x8004ca7c, 0x80050370, 0x800568d4,
                                         0x80056938, 0x8006a808, 0x8006d4a0, 0x8007684c]
    by = {c["call"]: c for c in calls}
    assert by[0x8004c96c]["variant"] == 22 and by[0x8004c96c]["r3_global"] == 0x801fefa0
    assert by[0x8004c9c4]["variant"] == 36 and by[0x8004c9c4]["r3_global"] == 0x801ff0c0
    assert by[0x8007684c]["variant"] == 21 and by[0x8007684c]["r3_global"] == 0x801ff0d8


def test_dol_pose_fn_confirms_motion_group_kinds():
    """The DOL pose fn 0x8005cd18 reads all 17 motDC groups and applies the position evaluator exactly to
    ct.POSITION_GROUPS - an independent (code-side) proof of the motDC.bin group layout."""
    import sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import gbox.crazy_taxi as ct
    kinds = ct.driver_pose_group_kinds_from_dol(_dol())
    assert sorted(kinds) == list(range(1, ct.MOTION_GROUPS + 1))
    assert {g for g, k in kinds.items() if k == "pos"} == set(ct.POSITION_GROUPS)
    assert {g for g, k in kinds.items() if k == "ang"} == set(range(1, 18)) - set(ct.POSITION_GROUPS)

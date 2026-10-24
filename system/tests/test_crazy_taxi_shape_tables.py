import glob, json, os, struct
import pytest
EV = json.load(open(os.path.join(os.path.dirname(__file__), "ct_usa_shape_tables.json")))
def _dol():
    for p in [os.environ.get("GBOX_CT_DOL", "")] + glob.glob(os.path.expanduser("~/gBox_alt/gbox-cache/modbase/*/main.dol")):
        if p and os.path.exists(p) and os.path.getsize(p) == EV["main_dol_size"]:
            return open(p, "rb").read()
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

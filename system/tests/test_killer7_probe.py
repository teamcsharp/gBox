import struct
from gbox.killer7_probe import probe


def _hsd():
    # data: 0 sd->arr ptr@0 ; arr@0x10 [ms,0]; ms@0x20 [jobj,..]; jobj@0x30 (0x40 bytes), child jobj@0x80
    d = bytearray(0xE0)
    def P(o, v): struct.pack_into(">I", d, o, v)
    P(0, 0x10); P(0x10, 0x20); P(0x20, 0x30)
    P(0x30 + 8, 0x80)            # root child
    P(0x30 + 0x10, 0xC0)         # root dobj
    P(0xC0 + 0xC, 0xD0)          # dobj->pobj stub at 0xD0
    rel = [0, 0x10, 0x20, 0x38, 0x40, 0xCC]
    strs = b"scene_data\0"
    hdr = struct.pack(">5I", 0x20 + len(d) + 4 * len(rel) + 8 + len(strs), len(d), len(rel), 1, 0) + b"\0" * 12
    return hdr + bytes(d) + struct.pack(f">{len(rel)}I", *rel) + struct.pack(">II", 0, 0) + strs


def test_probe_synthetic():
    r = probe(_hsd())
    ms = r["modelsets"]
    assert len(ms) == 1 and ms[0]["jobj_root"] == 0x30
    assert ms[0]["joints"] == 2 and ms[0]["dobjs"] == 1 and ms[0]["pobjs"] == 1

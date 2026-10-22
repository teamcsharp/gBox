import os, pytest
from gbox import blitz2001_loader_evidence as ev

EXE = os.environ.get("BLITZ2001_1ST_READ")

def test_constants_consistent():
    assert len(ev.BODY_NAMES) == 3 and ev.BONE_MATRIX_STRIDE == 48
    assert ev.MODEL_READY_FLAG == 1 << 27

def test_pool_loaders_synthetic():
    import struct
    x = bytearray(0x40)
    struct.pack_into("<H", x, 0, 0xD100 | 1)          # mov.l @(4,pc),r1 at BASE
    struct.pack_into("<I", x, 8, 0x8C0E0000)           # pool at ((BASE+4)&~3)+4
    assert ev.pool_loaders(bytes(x), {ev.BASE + 8}) == [(ev.BASE, ev.BASE + 8)]

@pytest.mark.skipif(not EXE, reason="set BLITZ2001_1ST_READ to owned 1ST_READ.BIN")
def test_real_executable():
    r = ev.verify_executable(EXE)
    assert r["sha_ok"] and r["body_names_ok"]
    assert r["table_loader_insns"] == ["0x8c0e1b2e", "0x8c0e1b90"]
    assert r["flag_const_ok"] and r["load_fn_ok"] and r["fixup_fn_ok"]

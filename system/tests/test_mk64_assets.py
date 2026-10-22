import os
import struct
import pytest
from gbox import mk64_assets as m

def test_synthetic_tkmk00():
    blob = b"\0" * 8 + m.TKMK_MAGIC + struct.pack(">HHH", 0x60F, 64, 32) + struct.pack(">III", 24, 40, 80) + b"\0" * 16
    t = m.tkmk00_streams(blob)
    assert len(t) == 1 and t[0]["offset"] == 8 and (t[0]["width"], t[0]["height"]) == (64, 32)
    assert t[0]["table_len"] >= 3 and t[0]["plausible"]

def test_synthetic_mio0_hist():
    blob = b"MIO0" + struct.pack(">III", 4096, 16, 20) + b"\0" * 8
    assert m.mio0_size_histogram(blob) == {4096: 1}

def test_owned_rom():
    from gbox import n64_rom
    p = os.path.expanduser("~/gBox_alt/gbox-cache/n64/7f5c674909d63b5f/Mario Kart 64 (USA).n64")
    if not os.path.exists(p):
        pytest.skip("owned ROM absent")
    r = m.probe(n64_rom.read(p))
    assert r["tkmk00_count"] == 63 and r["tkmk00_plausible"] == 63
    assert r["mio0_top_sizes"][4096] == 2684

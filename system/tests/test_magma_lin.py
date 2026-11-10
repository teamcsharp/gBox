import os
import struct
import zlib

import pytest

from gbox.formats import magma_lin as m

OWNED = os.path.join(os.path.dirname(__file__), "..", "artifacts",
                     "splinter_cell_da_gc", "extract", "common.lin")


def _entry(name, off, size):
    raw = name.encode() + b"\0"
    return bytes([len(raw)]) + raw + struct.pack(">III", off, size, 0)


def _lin(payload, chunk=32768):
    out = b""
    for i in range(0, len(payload), chunk):
        z = zlib.compress(payload[i:i + chunk])
        out += struct.pack(">I", len(z)) + z
    return out


def test_synthetic_roundtrip():
    toc = b"\x11" * m.TOC_HEADER + _entry("System\\Core.ugx", 0, 100) + \
        _entry("System\\Echelon.ugx", 104, 5)
    ents = m.parse_lin(_lin(toc + b"\0" * 40000))
    assert [(e.name, e.offset, e.size) for e in ents] == [
        ("System\\Core.ugx", 0, 100), ("System\\Echelon.ugx", 104, 5)]


def test_multi_chunk_and_exactness():
    p = bytes(range(256)) * 400
    assert m.inflate(_lin(p)) == p
    with pytest.raises(ValueError):
        m.inflate(_lin(p)[:-3])


def test_stops_at_garbage():
    toc = b"\0" * m.TOC_HEADER + _entry("a.ugx", 0, 1) + b"\x05ab\x01\x02xxxxxxxxxxxxxx"
    assert len(m.parse_toc(toc)) == 1


@pytest.mark.skipif(not os.path.exists(OWNED), reason="owned build not extracted")
def test_owned_build_common_lin():
    ents = m.parse_lin(open(OWNED, "rb").read())
    by = {e.name: e for e in ents}
    assert len(ents) == 932
    c = by["System\\EchelonCharacter.ugx"]
    assert (c.offset, c.size) == (3810960, 67496)
    assert by["System\\Core.ugx"].offset == 0
    assert sum(1 for e in ents if e.name.endswith(".ugx")) == 13
    assert "DataGCN\\Maps\\x01_iceland_a.unr" in by

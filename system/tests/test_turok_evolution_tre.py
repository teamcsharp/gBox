import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox import turok_evolution_tre as t  # noqa: E402

PATHS = [r"y:\data\actors\players\talset\talset.mtf",
         r"y:\data\textures\particle\glows\lgt001.tgax"]


def _synth():
    keys = sorted((t.path_crc(p), i) for i, p in enumerate(PATHS))
    body = b"".join(struct.pack(">4I", 0x220, c, 1 + i, 2) for c, i in keys)
    txt = "".join('*PR = "%s"\r\n' % p for p in PATHS).encode()
    return struct.pack(">2I", len(keys), 0) + body + txt


def test_synthetic_roundtrip():
    buf = _synth()
    recs = t.parse_index(buf)
    assert len(recs) == 2 and t.index_is_sorted(recs)
    assert set(t.resolve_pr_paths(buf)) == set(PATHS)


def test_crc_known_value():
    assert t.path_crc(r"y:\data\textures\particle\glows\streak001.tgax") == 0x3877CA6D


ROM = os.environ.get("TUROK_EVO_TRE_HEAD")


@pytest.mark.skipif(not ROM or not os.path.exists(ROM), reason="owned tre head not provided")
def test_real_build_head():
    buf = open(ROM, "rb").read()
    recs = t.parse_index(buf)
    assert len(recs) == 9879 and t.index_is_sorted(recs)
    assert len(t.resolve_pr_paths(buf)) == len(t.pr_paths(buf)) == 1488


def test_entry_spans_synthetic():
    R = t.TreRecord
    recs = [R(0, 1, 0, 100), R(0, 2, 0, 130), R(0, 3, 0, 130), R(0, 4, 0, 200)]
    assert t.entry_spans(recs) == {100: 30, 130: 70}
    assert t.entry_spans(recs, 250)[200] == 50


def test_atr_header():
    assert t.atr_body_size(b"\x01atr\x82\x00\x0e\x60rest") == 3680
    assert t.atr_body_size(b"SWAP0000") is None


@pytest.mark.skipif(not ROM or not os.path.exists(ROM), reason="owned tre head not provided")
def test_real_build_atr_spans():
    buf = open(ROM, "rb").read()
    recs = t.parse_index(buf)
    spans = t.entry_spans(recs)
    n = 0
    for o, s in spans.items():
        if o + 8 <= len(buf) and o + s <= len(buf):
            b = t.atr_body_size(buf[o:o + 8])
            if b is not None:
                assert s == b + t.ATR_OVERHEAD
                n += 1
    assert n >= 500

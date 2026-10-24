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

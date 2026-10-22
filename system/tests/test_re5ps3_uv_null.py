"""Regression tests for the RE5 PS3 MOD texcoord slot.

Meshes whose UV slot holds the 32-bit null-attribute sentinel (0xFFFFFFFF)
declare no UV channel; read as f16 that sentinel is NaN, which used to abort
the whole model parse. The reader now reports such meshes as uv_null and
emits a finite (0, 0) channel.
"""
import os
import struct
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import re5ps3_models as M

PACKS = os.environ.get(
    "RE5PS3_PACKS",
    "/home/ehm_eckx/gBox_alt/gbox-pr-audit-20261017/re-export-evidence/re5-expanded-cast-v1/packs",
)

FIXTURES = [
    ("uPl05ExcellaNormal.arc", r"pawn\pl\pl1e\model\pl1e00"),
    ("uPl02JillCos1.arc", r"pawn\pl\pl02\model\Pl0200"),
    ("uPl03WeskerCos1.arc", r"pawn\pl\pl15\model\pl1500"),
]


def test_decode_texcoord_null_sentinel():
    block = np.full((4, 4), 0xFF, dtype=np.uint8)
    uv, null = M.decode_texcoord(block)
    assert null is True
    assert uv.shape == (4, 2)
    assert np.all(np.isfinite(uv))
    assert np.all(uv == 0.0)


def test_decode_texcoord_real_values():
    block = np.frombuffer(
        struct.pack('>ee', 0.25, 0.5) + struct.pack('>ee', 0.75, 1.0), dtype=np.uint8
    ).reshape(2, 4)
    uv, null = M.decode_texcoord(block)
    assert null is False
    assert uv.tolist() == [[0.25, 0.5], [0.75, 1.0]]


def test_decode_texcoord_partial_null_is_rejected():
    block = np.zeros((2, 4), dtype=np.uint8)
    block[0] = np.frombuffer(struct.pack('>ee', 0.25, 0.5), dtype=np.uint8)
    block[1] = 0xFF
    with pytest.raises(ValueError):
        M.decode_texcoord(block)


@pytest.mark.skipif(not os.path.isdir(PACKS), reason="RE5PS3 pack fixtures unavailable")
def test_models_with_null_uv_slots_parse():
    from gbox.re5ps3_arc import Arc
    for arcname, modname in FIXTURES:
        path = os.path.join(PACKS, arcname)
        if not os.path.exists(path):
            continue
        arc = Arc(open(path, "rb").read())
        entry = next(e for e in arc.entries if e.name == modname)
        model = M.Model(arc.read(entry))
        assert model.meshes, arcname
        for mesh in model.meshes:
            assert np.all(np.isfinite(mesh["uv"])), (arcname, mesh["index"])
        assert [m for m in model.meshes if m.get("uv_null")], arcname

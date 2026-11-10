"""Owned-build reader regression: SLUS-201.44 (Sons of Liberty), stage r_tnk0.

Fixtures are real kms + texture-pack bytes extracted from the owned ISO
(/mnt/gbox/.../Metal Gear Solid 2 - Sons of Liberty (USA).iso) via
gbox.mgs2_sol.probe_stage. They pin the READER against the owned build so it
cannot silently drift into Substance (SLUS-205.54) assumptions.
"""
import hashlib
import json
from pathlib import Path

import pytest

from gbox import mgs2_models as mm

FIX = Path(__file__).parent / "fixtures" / "mgs2_sol"


def _hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture(scope="module")
def owned_kms():
    b = (FIX / "r_tnk0_0x31792f.kms").read_bytes()
    assert _hex(b) == "112c2782773ebe645e30134079c3cf334b22bc8c51089f39adb42eca28012a85"
    return b


@pytest.fixture(scope="module")
def owned_texpack():
    b = (FIX / "r_tnk0_0xa2cb54.texpack").read_bytes()
    assert _hex(b) == "4351807a673f6079c523cf494d4b6cb1cc57587a7a05e04b819fe6377ea035fd"
    return b


def test_owned_kms_parses(owned_kms):
    k = mm.parse_kms(owned_kms)
    assert k["bones"] == 3
    assert len(k["meshes"]) == 3
    assert k["tex"] == 0xA2CB54  # matches the model's texture-pack name hash


def test_owned_texpack_parses(owned_texpack):
    tp = mm.TexturePack(owned_texpack)
    assert tp.count == 38


def test_owned_kms_matches_texpack(owned_kms, owned_texpack):
    """The kms names its pack (<model>_mt) and the pack has every texture it references."""
    k = mm.parse_kms(owned_kms)
    tp = mm.TexturePack(owned_texpack)
    assert k["tex"] == 0xA2CB54
    used = {t for mesh in k["meshes"] for part in mesh["parts"] for t in part["tex"] if t}
    assert used <= set(tp.entries)


def test_owned_roundtrip_glb(owned_kms, owned_texpack, tmp_path):
    k = mm.parse_kms(owned_kms)
    tp = mm.TexturePack(owned_texpack)
    out = tmp_path / "r_tnk0_0x31792f.glb"
    r = mm.write_glb(out, k, [tp], "r_tnk0_0x31792f")
    assert out.stat().st_size > 0
    assert r["triangles"] == 391
    assert r["bones"] == 3
    assert r["missing_textures"] == []
    assert _hex(out.read_bytes()) == "8b5fd2c205f0dcb4b85c0a16a63159a360d237daa55bab16cc6285dd567ef6f1"

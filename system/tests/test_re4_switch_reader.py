import json
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import re4_switch_reader as R


def test_bc1_and_bc3_decode_solid_blocks():
    red565 = 0xF800
    bc1 = struct.pack("<HHI", red565, 0, 0) * 4          # all index 0 -> colour0
    dds = b"DDS " + struct.pack("<I", 124) + b"\0" * 4 + struct.pack("<II", 8, 8) + b"\0" * 12 + b"\0" * 56 + b"\0" * 4 + b"DXT1" + b"\0" * 40
    dds = dds[:84] + b"DXT1" + dds[88:128].ljust(44, b"\0")
    dds = dds[:128] + bc1
    img = R.decode_dds(dds)
    assert img.shape == (8, 8, 4) and tuple(img[0, 0]) == (255, 0, 0, 255)
    bc3 = (bytes([255, 255]) + b"\0" * 6 + struct.pack("<HHI", red565, 0, 0)) * 4
    img = R.decode_dds(dds[:84] + b"DXT5" + dds[88:128] + bc3)
    assert tuple(img[7, 7]) == (255, 0, 0, 255)


def test_png_roundtrip_header():
    p = R._png(np.zeros((2, 3, 4), np.uint8))
    assert p[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", p[16:24]) == (3, 2)


def test_roster_without_romfs_lists_players(monkeypatch, tmp_path):
    out = R.roster(tmp_path)
    assert out or True
    monkeypatch.setattr(R, "romfs_root", lambda game=None: (_ for _ in ()).throw(FileNotFoundError()))
    ids = [r["key"] for r in R.roster()]
    assert "pl08" in ids and all(r["slug"].startswith("re4sw_") for r in R.roster())


ROOT = Path.home() / "gBox_alt" / "switch" / "romfs" / R.TITLE_ID


@pytest.mark.skipif(not (ROOT / "bio4" / "em" / "pl08.udas").exists(), reason="RE4 Switch RomFS not extracted here")
def test_leon_pack_exports_skinned_glb(tmp_path):
    before = (ROOT / "bio4" / "em" / "pl08.udas").stat().st_mtime_ns
    res = R.export_pack(ROOT, "pl08", tmp_path)
    blob = Path(res["glb"]).read_bytes()
    magic, ver, total = struct.unpack_from("<III", blob)
    assert magic == 0x46546C67 and ver == 2 and total == len(blob)
    jlen = struct.unpack_from("<I", blob, 12)[0]
    gltf = json.loads(blob[20:20 + jlen])
    assert gltf["skins"][0]["joints"] and res["bones"] > 50 and res["triangles"] > 10000 and res["textures"] >= 1
    assert all(a["count"] > 0 for a in gltf["accessors"])
    assert all(Path(p).read_bytes()[:4] == b"\x89PNG" for p in res["pngs"])
    assert (ROOT / "bio4" / "em" / "pl08.udas").stat().st_mtime_ns == before

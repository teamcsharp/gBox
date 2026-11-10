"""Reader-stage tests: RE Survivor 2 MDL -> GLB."""
import json
import os
import struct
from pathlib import Path

import pytest

from gbox.gs2_mesh import extract_parts, to_glb

DISC = Path(os.environ.get("GBOX_GS2_DISC", "/home/ehm_eckx/gbox-cache/ps2/5ec1d297cb44b3ea/disc.iso"))
MANIFEST = Path("/home/ehm_eckx/gbox-cache/ps2/5ec1d297cb44b3ea/gs2_manifest.json")


def _synthetic():
    n = 3
    recs = b"".join(struct.pack("<3ff3ff", x, 0, 0, 1.0, 0, 0, 1, 1.0) for x in (0.0, 1.0, 2.0))
    pad = b"\x00" * 8
    size = (4 + len(pad) + len(recs)) // 4
    head = struct.pack("<I", 0x33 | (size << 16)) + struct.pack("<HH", 0, n)
    verts = head + pad + recs
    vstream = b"\x00" * 0x84 + verts + b"\xff\x00\x00\x00"
    strip = struct.pack("<hhh", 0, 0, 0)  # placeholder replaced below
    strip = struct.pack("<h", 3) + b"".join(struct.pack("<Hhh", i, i * 100, 5) for i in range(3))
    chunk = struct.pack("<BBHH", 0x42, 0, (2 + len(strip)) // 2, 1) + strip
    return vstream + chunk + b"\xff\x00\x00\x00"


def test_synthetic_roundtrip_glb():
    parts = extract_parts(_synthetic())
    assert len(parts) == 1 and len(parts[0]["pos"]) == 3 and len(parts[0]["tris"]) == 1
    g = to_glb(parts)
    assert g[:4] == b"glTF"
    assert struct.unpack_from("<I", g, 8)[0] == len(g)


def _claire():
    from gbox import gs2_inventory as G
    if not DISC.exists() or not MANIFEST.exists():
        pytest.skip("disc/manifest not staged")
    lba = json.load(open(MANIFEST))["containers"]["afs"]["SYSTEM.AFS"][0]
    with open(DISC, "rb") as f:
        f.seek(lba * 2048)
        pairs = G.afs_pairs(f.read(0x2000))
        f.seek(lba * 2048 + pairs[20][0])
        return f.read(pairs[20][1])


def test_real_claire_cl02_mesh():
    d = _claire()
    parts = extract_parts(d)
    assert len(parts) == 1
    p = parts[0]
    assert len(p["pos"]) == 43 and len(p["tris"]) == 82      # matches walk_ninja_polys census
    assert max(max(t) for t in p["tris"]) == 42 and len(p["uv"]) == 43
    import math
    assert all(abs(math.sqrt(sum(c * c for c in n)) - 1) < 1e-2 for n in p["nrm"][1:])
    g = to_glb(parts)
    jl = struct.unpack_from("<I", g, 12)[0]
    gl = json.loads(g[20:20 + jl])
    assert gl["accessors"][3]["count"] == 82 * 3

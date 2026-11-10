"""Player KMD -> GLB export is read-only, structurally valid and covers every face/texture."""
import hashlib, json, os, struct
from pathlib import Path

import pytest

from gbox import mgs_disc2_glb as g
from gbox import mgs_disc2_inventory as inv
from gbox import mgs_disc2_player as pl

CACHE = Path(os.environ.get("TMPDIR", "/tmp")) / "mgs_disc2" / "STAGE.DIR"


@pytest.fixture(scope="module")
def stage():
    if CACHE.is_file():
        data = CACHE.read_bytes()
    elif Path(inv.CHD_PATH).is_file():
        data = inv.stage_bytes()
    else:
        pytest.skip("owned MGS disc 2 CHD is not reachable")
    assert hashlib.sha256(data).hexdigest() == pl.STAGE_SHA256
    return data


def _parse(glb):
    assert glb[:4] == b"glTF" and struct.unpack_from("<I", glb, 8)[0] == len(glb)
    n = struct.unpack_from("<I", glb, 12)[0]
    return json.loads(glb[20:20 + n])


def test_export_init(stage):
    before = hashlib.sha256(stage).hexdigest()
    glb, st = g.export_player(stage, "init")
    assert hashlib.sha256(stage).hexdigest() == before
    j = _parse(glb)
    assert (st["objects"], st["faces"]) == (16, 341)
    assert st["images"] == 28 and len(j["materials"]) == 28
    assert len(j["nodes"]) == 17 and len(j["meshes"]) <= 16
    for a in j["accessors"]:
        assert a["count"] % 3 == 0 or a["type"] == "VEC2"
    assert g.export_player(stage, "init")[0] == glb  # deterministic


def test_export_tux(stage):
    glb, st = g.export_player(stage, "init_tux")
    assert st["size"] == 13112 and _parse(glb)["meshes"]

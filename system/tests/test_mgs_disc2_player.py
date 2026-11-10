"""Player KMD slot resolution + no-op roundtrip on the owned MGS disc 2 STAGE.DIR (skips if the disc is unreachable)."""
import hashlib
import os
from pathlib import Path

import pytest

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


def test_player_site(stage):
    init = next(s for s in pl.player_sites(stage) if s["stage"] == "init")
    assert (init["offset"], init["size"], init["dar"]) == (5760508, 13608, 5677056)
    r = pl.resolve(stage, init)
    assert r["sha256"].startswith("5dda0c64dfef")
    assert (r["objects"], r["faces"], r["verts"]) == (16, 341, 369)
    assert len(r["textures"]) == 28 and not r["missing_textures"]
    assert r["raw"]["sector"] == 103613 and r["raw"]["in_sector"] == 1532


def test_extract_is_read_only(stage):
    before = hashlib.sha256(stage).hexdigest()
    for s in pl.player_sites(stage):
        kmd, tex = pl.extract(stage, s)
        assert len(kmd) == s["size"] and tex
    assert hashlib.sha256(stage).hexdigest() == before


def test_noop_roundtrip(stage):
    for s in pl.player_sites(stage):
        rt = pl.noop_roundtrip(stage, s)
        assert rt["identical"] and rt["changed_sectors"] == 0

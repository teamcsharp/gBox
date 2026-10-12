"""Focused tests for the GTA Vice City (PS2) native character reader.

Requires the owned Vice City disc image to be staged in the gBox cache
(gbox-cache/modbase/<game_id>/<image>.iso), which the first extraction job creates.
Tests are skipped when the image is absent.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from gbox import config, filemods
from gbox import gta_vc_models
from gbox.gta_vc_swap import VC_ROLES

GAME = {"game_id": "0000000000000000", "title": "Grand Theft Auto - Vice City", "platform": "ps2"}


def test_roster_includes_tommy():
    slugs = {e["slug"] for e in gta_vc_models.roster()}
    assert "gtavc_tommy" in slugs


def test_roles_exported_with_entry():
    # The reader must report the same body roles the Vice City writer consumes.
    assert set(VC_ROLES) == {"pelvis", "hip", "chest", "neck", "head",
                               "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                               "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}
    assert "extract_run" in dir(gta_vc_models)


def _iso_path() -> pathlib.Path | None:
    cfg = config.load(pathlib.Path(__file__).parent.parent / "gbox.toml")
    p = filemods.base_dir(cfg, GAME["game_id"]) / "Grand Theft Auto - Vice City (USA).iso"
    return p if p.exists() else None


@pytest.mark.skipif(_iso_path() is None, reason="Vice City base ISO not staged")
def test_extract_player_glb():
    from gbox import characters as C

    # Look for the owned ROM in the usual libraries
    rom = pathlib.Path("/mnt/gbox/quickswap2/Emulation/PS2/Grand Theft Auto - Vice City (USA).7z")
    cfg = config.load(pathlib.Path(__file__).parent.parent / "gbox.toml")

    class FakeCtx:
        config = cfg
        def progress(self, _p, _m):
            pass

    C._rom = lambda _ctx, _game: rom
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td)
        entry = next(e for e in gta_vc_models.roster() if e["key"] == "player")
        result = gta_vc_models.extract_run(FakeCtx(), GAME, entry, work)
        assert result["tool"] == "gbox.gta_vc_models"
        assert result["files"][0].exists()
        assert result["files"][0].stat().st_size > 0
        assert "MODELS/GTA3.IMG" in result["source_files"][0]
        assert set(result["roles"]) == set(VC_ROLES)

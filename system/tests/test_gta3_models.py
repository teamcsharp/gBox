"""Focused tests for the GTA III (PS2) native character reader.

Requires the owned GTA III disc image to be staged in the gBox cache
(gbox-cache/modbase/265819390074bb4e/Grand Theft Auto III (USA, Canada).iso),
which the first extraction job creates. Tests are skipped when the image is absent.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from gbox import config, filemods
from gbox import gta3_models
from gbox.gta3_swap import GTA3_ROLES

GAME = {"game_id": "265819390074bb4e", "title": "Grand Theft Auto III", "platform": "ps2"}


def test_roster_includes_claude():
    slugs = {e["slug"] for e in gta3_models.roster()}
    assert "gta3_claude" in slugs


def test_roles_exported_with_entry():
    # The reader must report the same body roles the GTA III writer consumes.
    assert set(GTA3_ROLES) == {"pelvis", "hip", "chest", "neck", "head",
                               "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                               "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}
    assert "extract_run" in dir(gta3_models)


def _iso_path() -> pathlib.Path | None:
    cfg = config.load(pathlib.Path(__file__).parent.parent / "gbox.toml")
    p = filemods.base_dir(cfg, GAME["game_id"]) / "Grand Theft Auto III (USA, Canada).iso"
    return p if p.exists() else None


@pytest.mark.skipif(_iso_path() is None, reason="GTA III base ISO not staged")
def test_extract_player_glb():
    from gbox import characters as C
    from gbox.gta3_swap import iso_from_rom

    rom = pathlib.Path("/mnt/gbox/quickswap2/Emulation/PS2/Grand Theft Auto III (USA, Canada).7z")
    cfg = config.load(pathlib.Path(__file__).parent.parent / "gbox.toml")

    class FakeCtx:
        config = cfg
        def progress(self, _p, _m):
            pass

    C._rom = lambda _ctx, _game: rom
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td)
        entry = next(e for e in gta3_models.roster() if e["key"] == "player")
        result = gta3_models.extract_run(FakeCtx(), GAME, entry, work)
        assert result["tool"] == "gbox.gta3_models"
        assert result["files"][0].exists()
        assert result["files"][0].stat().st_size > 0
        assert "MODELS/GTA3.IMG" in result["source_files"][0]
        assert set(result["roles"]) == set(GTA3_ROLES)

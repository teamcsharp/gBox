"""Tests for gbox.auf_chars (AUF character-tool integration)."""
import os

import pytest

from gbox import auf_chars


def test_module_constants():
    assert auf_chars.GAME_IDS == {"65b7187589166b26"}
    assert auf_chars.DEFAULT_LEVEL == "maps/dm1.ngc"


GCZ = os.environ.get("GBOX_AUF_GCZ",
                     os.path.expanduser("~/gbox-cache/gc/65b7187589166b26/source.gcz"))


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_read_level_lists_actor_gcms():
    from gbox import auf_ngc_writer as W
    from gbox.tools import rom_path
    from pathlib import Path
    from gbox.models import CatalogEntry
    game = {"game_id": "65b7187589166b26", "title": "007: Agent Under Fire",
             "platform": "gamecube"}
    # Use the catalog entry if available, else skip via the GCZ path
    gcz = Path(GCZ) if os.path.exists(GCZ) else Path(rom_path(CatalogEntry.model_validate(game)))
    pkg = auf_chars._read_level(gcz, "maps/dm1.ngc")
    actors = W.actor_gcms(pkg)
    assert "models/actors/bond/bond_combat_l.gcm" in actors
    assert len(actors) >= 30

"""EU Jet Set Radio changed-donor swap into archive slot 6, written to a separate GDI (skipped without owned assets)."""
import json, os, hashlib
from pathlib import Path
import pytest

CACHE = Path("/home/ehm_eckx/gBox_alt/gbox-cache")
GDI = CACHE / "dc/bd43233f27d78508/disc.gdi"
DONOR = CACHE / "characters/sc2_cassandra"
BLENDER = "/usr/bin/blender"
EU_AFS_SHA = "406d4ec877eb6c69d4a217534992ea3e280fdeb5cf6b0130bcc29821a6f07113"

@pytest.mark.skipif(not (GDI.exists() and (DONOR / "meta.json").exists() and os.path.exists(BLENDER)),
                    reason="owned EU GDI / donor / arm64 blender absent")
def test_eu_slot6_changed_donor_to_separate_gdi(tmp_path):
    from gbox import jgr
    from gbox.gdrom import GDRom, patch_gdi
    meta = json.load(open(DONOR / "meta.json"))
    orig = GDRom(str(GDI)).read(jgr.PLAYER_AFS)
    assert hashlib.sha256(orig).hexdigest() == EU_AFS_SHA
    b = jgr.build_swap(GDI, DONOR / meta["model"], meta["rig"]["roles"], tmp_path / "w", meta["name"], 6, BLENDER)
    new = b["files"][jgr.PLAYER_AFS]
    assert len(new) == len(orig) and new != orig and b["report"]["archive_index"] == 6
    img = patch_gdi(GDI, tmp_path / "mod", "eu_gum_swap", b["files"])
    assert GDRom(str(img)).read(jgr.PLAYER_AFS) == new
    assert GDRom(str(GDI)).read(jgr.PLAYER_AFS) == orig            # original untouched
    # only slot 6's PLAY/PTEX entries changed
    p6, t6 = jgr.character_pair(orig, 6)
    _, offs, _ = jgr.afs_entries(orig)
    changed = [j for j, o in enumerate(offs) if orig[o:o + jgr.entry_room(orig, o)] != new[o:o + jgr.entry_room(orig, o)]]
    assert changed == sorted([offs.index(p6), offs.index(t6)])

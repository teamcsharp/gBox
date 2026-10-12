"""#1153: the operator's pick whip (x=0.50, y=0.56, Jet Grind Radio USA, donor sa2_amy_rose) must land on the
native actor it picked, not on archive 00 or an assumed player.

The pick frame (artifact a47c2a1b…, timer 92.37 at first control) shows Beat, the new-game player. In the USA
build Beat is native character ID 0 = PLAYER.AFS character slot 04 (`ereki`) = AFS entries 8/9
(erekidat.bin / erekitxr.bin). The disc and staged-mod checks skip when those owned files are absent
(JGR_GDI / JGR_1153_MOD override the default cache paths)."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from gbox import jgr

STOCK_GDI = Path(os.environ.get("JGR_GDI", "/home/ehm_eckx/gbox-cache/dc/4187aeab4d67638c/disc.gdi"))
MOD_NAME = "jgr_sa2_amy_rose_04_a80947d49d022a3a"
MOD_DIR = Path(os.environ.get("JGR_1153_MOD", f"/home/ehm_eckx/gbox-cache/mods/4187aeab4d67638c/{MOD_NAME}"))
# Preserved source hash: PLAYER.AFS on the owned USA disc.
STOCK_AFS_SHA256 = "406d4ec877eb6c69d4a217534992ea3e280fdeb5cf6b0130bcc29821a6f07113"
BEAT_BODIES = (0x8da4, 0x13cf4, 0x19ba8, 0x2039c)   # every textured 20-node body of Beat's PLAY


def _afs(gdi):
    from gbox.gdrom import GDRom
    return GDRom(str(gdi)).read("JETRADIO/PLAYER.AFS")


def test_picked_player_beat_resolves_to_archive_slot_04_not_archive_00():
    # Beat's verified names and the active-player route all reach archive slot 04 (USA table, no disc read).
    for slot in ("beat", "ereki", "erekidat.bin", "04"):
        assert jgr.swap_index(slot) == 4
    assert jgr.USA_NATIVE_IDS[4] == 0 and jgr.ARCHIVE_NAMES[4] == "ereki"
    assert jgr.NATIVE_DEBUG_NAMES[0] == "BEAT(EREKI)"
    # 'player' is never guessed: archive 00 is native ID 7 (bis), so an unknown active ID must fail.
    assert jgr.USA_NATIVE_IDS[0] == 7
    with pytest.raises(ValueError, match="active native character ID is unknown"):
        jgr.swap_index("player")


def test_owned_disc_binds_beat_to_native_id_0_at_afs_entries_8_and_9():
    if not STOCK_GDI.is_file():
        pytest.skip("JGR disc not present")
    data = _afs(STOCK_GDI)
    assert hashlib.sha256(data).hexdigest() == STOCK_AFS_SHA256
    assert jgr.native_ids(data) == jgr.USA_NATIVE_IDS
    assert jgr.swap_index("player", data, active_id=0) == 4 == jgr.swap_index("id:0", data)
    assert jgr.character_names(data)[4] == "ereki"
    _, offsets, _ = jgr.afs_entries(data)
    assert jgr.character_pair(data, 4) == (offsets[8], offsets[9])
    assert jgr.afs_names(data)[8:10] == ["erekidat.bin", "erekitxr.bin"]


def test_staged_mod_round_trip_changes_only_beats_entries_and_writes_amy_on_every_body():
    if not STOCK_GDI.is_file() or not (MOD_DIR / f"{MOD_NAME}.gdi").is_file():
        pytest.skip("JGR disc or staged #1153 mod not present")
    manifest = json.loads((MOD_DIR / ".gbox-mod.json").read_text())
    ident = manifest["cache_identity"]
    assert manifest["character"] == "sa2_amy_rose" and manifest["files"] == ["JETRADIO/PLAYER.AFS"]
    assert ident["source_afs_sha256"] == STOCK_AFS_SHA256
    assert (ident["archive_index"], ident["native_id"]) == (4, 0)
    stock, mod = _afs(STOCK_GDI), _afs(MOD_DIR / f"{MOD_NAME}.gdi")
    assert len(mod) == len(stock)
    n, so, ss = jgr.afs_entries(stock)
    n2, mo, ms = jgr.afs_entries(mod)
    assert n == n2 == 34 and so == mo                     # archive layout and every offset preserved
    changed = [i for i in range(n) if ss[i] != ms[i] or stock[so[i]:so[i] + ss[i]] != mod[mo[i]:mo[i] + ms[i]]]
    assert changed == [8, 9]                               # Beat's PLAY + PTEX only; other 15 actors untouched
    assert jgr.native_ids(mod) == jgr.USA_NATIVE_IDS       # native ID binding survives the rewrite
    before = {r["root"]: r for r in jgr.play_summary(stock, so[8])}
    after = {r["root"]: r for r in jgr.play_summary(mod, mo[8])}
    assert set(before) == set(after)
    for root in BEAT_BODIES:
        assert before[root]["nodes"] == after[root]["nodes"] == 20
        assert before[root]["triangles"] in (838, 942, 1588, 1796)
        assert after[root]["triangles"] == 500 and after[root]["texture_ids"] == [0]

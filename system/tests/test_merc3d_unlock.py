"""Resident Evil: The Mercenaries 3D unlock research profile must never write."""
from __future__ import annotations

import hashlib
from pathlib import Path

from gbox import merc3d_unlock


def test_profile_is_unverified_and_states_a_reason():
    prof = merc3d_unlock.profile()
    assert prof['verified'] is False
    assert prof['status'] == 'research_pending'
    assert prof['game_id'] == merc3d_unlock.CATALOG_GAME_ID
    assert prof['reason']
    assert prof['exclusions']
    assert len(merc3d_unlock.CODE_SHA256) == 64
    assert prof['evidence']['code_sha256'] == merc3d_unlock.CODE_SHA256


def test_unlock_ops_empty_until_layout_is_verified():
    assert merc3d_unlock.unlock_ops() == []


def test_apply_unlock_refuses_and_leaves_the_save_untouched(tmp_path):
    save = tmp_path / 'sav'
    original = bytes(range(256)) * 4
    save.write_bytes(original)
    before = hashlib.sha256(save.read_bytes()).hexdigest()
    result = merc3d_unlock.apply_unlock(save)
    assert result['applied'] is False
    assert result['state'] == 'refused'
    assert hashlib.sha256(save.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob('*' + merc3d_unlock.BACKUP_SUFFIX))


def test_backup_save_copies_and_keeps_the_original(tmp_path):
    save = tmp_path / 'sav'
    save.write_bytes(b'mercenaries')
    backup = Path(merc3d_unlock.backup_save(save))
    assert backup.read_bytes() == b'mercenaries'
    assert save.read_bytes() == b'mercenaries'
    assert backup != save


def test_find_save_files_locates_the_title_tree(tmp_path):
    title_dir = tmp_path / 'Resident Evil - The Mercenaries'
    title_dir.mkdir()
    (title_dir / 'sav').write_bytes(b'x' * 32)
    found = merc3d_unlock.find_save_files(tmp_path)
    assert any(f['path'].endswith('sav') and f['size'] == 32 for f in found)
    assert all(len(f['sha256']) == 64 for f in found)

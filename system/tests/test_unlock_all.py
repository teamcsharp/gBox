import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from gbox import game_unlocks as G, re3_gc_unlock as R

ROOT = Path(__file__).resolve().parent.parent
GAME = {'game_id': R.RE3_GC_ID, 'platform': 'gamecube', 'title': 'Resident Evil 3 - Nemesis (USA)'}


def elf_path():
    return ROOT / R.RE3_GC_ANALYSIS_ELF


def test_exact_build_membership_probe_passes():
    data = elf_path().read_bytes()
    assert len(data) <= 4 * 1024 * 1024
    result = R.re3_gc_lock_targets(data)
    assert result['matches'] is True and not result['missing']
    assert [x['offset'] for x in result['found']][:3] == ['0x2059b4', '0x2059ce', '0x205ad9']


def test_tampered_elf_fails_the_membership_probe():
    data = bytearray(elf_path().read_bytes())
    off = 0x20d46b
    assert data[off:off + 8] == b'mercenar'
    data[off] = ord('M')
    result = R.re3_gc_lock_targets(bytes(data))
    assert result['matches'] is False
    assert result['missing'] == [{'offset': '0x20d46b', 'string': 'mercenaries only'}]


def test_elf_profile_gates_on_exact_identity(tmp_path):
    assert R.re3_gc_elf_profile({'game_id': R.RE3_GC_ID, 'platform': 'ps2'}, ROOT)['verified'] is False
    assert R.re3_gc_elf_profile({'game_id': '0' * 16, 'platform': 'gamecube'}, ROOT)['verified'] is False
    assert R.re3_gc_elf_profile(GAME, tmp_path)['verified'] is False
    assert 'unavailable' in R.re3_gc_elf_profile(GAME, tmp_path)['reason'].lower()
    profile = R.re3_gc_elf_profile(GAME, ROOT)
    assert profile['verified'] is True
    assert profile['disc_id'] == R.RE3_GC_DISC_ID
    assert profile['source_sha256'] == R.RE3_GC_DOL_SHA256
    assert profile['elf_sha256'] == hashlib.sha256(elf_path().read_bytes()).hexdigest()
    assert len(profile['routine_table']) == len(R.RE3_GC_REQUIRED_STRINGS)
    assert profile['requires_save_upgrade_opt_in'] is True
    assert any('runtime' in x.lower() for x in profile['exclusions'])


def test_pre_launch_never_writes_for_re3_gc(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError('pre_launch must not invoke a writer before native verification')
    monkeypatch.setattr(G, 're3_gc_elf_profile', boom, raising=False)
    result = G.pre_launch(GAME, SimpleNamespace())
    assert result['applied'] is False


def test_unknown_games_stay_research_pending():
    for game in ({'game_id': 'doa3', 'platform': 'xbox'}, {'game_id': G.RE6_ID, 'platform': 'ps3'}):
        assert G.pre_launch(game, SimpleNamespace())['applied'] is False

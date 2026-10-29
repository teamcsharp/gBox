import hashlib

from gbox import game_unlocks
from gbox import pso_gc_unlocks as u

GAME = {'game_id': u.GAME_ID, 'platform': u.PLATFORM, 'title': u.TITLE}


def test_profile_is_honest_and_unverified():
    prof = u.profile()
    assert prof['verified'] is False
    assert prof['status'] == 'pending_research'
    assert prof['game_id'] == u.GAME_ID
    assert prof['platform'] == u.PLATFORM
    assert prof['reason']
    assert set(prof['categories']) == set(u.CATEGORIES)
    for name, row in prof['categories'].items():
        assert row['state'] == 'unknown'
        assert row['entries'] == []
    assert prof['evidence']['executable']['sha256'] == u.DOL_SHA256


def test_plan_carries_no_unproven_edits():
    plan = u.plan()
    assert plan['edits'] == []
    assert plan['state'] == 'layout_unresolved'


def test_game_unlocks_registers_profile_without_reaching_a_writer():
    prof = game_unlocks.profile_for(GAME)
    assert prof['status'] == 'pending_research'
    assert prof['verified'] is False
    assert prof['reason']
    result = game_unlocks.pre_launch(GAME, ctx=None)
    assert result['applied'] is False
    assert result['state'] == 'research_pending'
    assert result['writer']['edits'] == []


def test_revision_guard_accepts_only_the_owned_revision():
    assert u.revision_guard(u.REVISION_STAMP) is True
    assert u.revision_guard(b'GPOE8P\x00\x01') is False
    assert u.revision_guard(b'') is False


def test_apply_overlay_backs_up_and_rolls_back(tmp_path):
    save = tmp_path / 'card.bin'
    save.write_bytes(b'\x00\x00\x00\x05' + b'\xff' * 8)
    before = save.read_bytes()
    edits = [{'offset': 0, 'expected': b'\x00\x00\x00\x05',
              'value': b'\x00\x00\x00\x09', 'kind': 'progress'}]
    report = u.apply_overlay(save, edits)
    assert report['applied'] is True
    assert save.read_bytes()[:4] == b'\x00\x00\x00\x09'
    assert report['sha256_before'] == hashlib.sha256(before).hexdigest()
    backup = tmp_path / ('card.bin' + u.BACKUP_SUFFIX)
    assert backup.read_bytes() == before
    u.rollback(save, backup)
    assert save.read_bytes() == before


def test_apply_overlay_refuses_mismatched_expectation(tmp_path):
    save = tmp_path / 'card.bin'
    save.write_bytes(b'\x00' * 8)
    before = save.read_bytes()
    report = u.apply_overlay(save, [{'offset': 0, 'expected': b'\x01\x02',
                                     'value': b'\x03\x04', 'kind': 'flag'}])
    assert report['applied'] is False
    assert report['failed']
    assert save.read_bytes() == before
    assert not (tmp_path / ('card.bin' + u.BACKUP_SUFFIX)).exists()


def test_progress_edits_only_move_forward(tmp_path):
    save = tmp_path / 'card.bin'
    save.write_bytes(b'\x00\x00\x00\x09')
    before = save.read_bytes()
    report = u.apply_overlay(save, [{'offset': 0, 'expected': b'\x00\x00\x00\x09',
                                     'value': b'\x00\x00\x00\x02', 'kind': 'progress'}])
    assert report['applied'] is False
    assert save.read_bytes() == before


def test_dry_run_does_not_write(tmp_path):
    save = tmp_path / 'card.bin'
    save.write_bytes(b'\x00\x00\x00\x01')
    before = save.read_bytes()
    report = u.apply_overlay(save, [{'offset': 0, 'expected': b'\x00\x00\x00\x01',
                                     'value': b'\x00\x00\x00\x02', 'kind': 'progress'}],
                             dry_run=True)
    assert report['applied'] is True
    assert save.read_bytes() == before

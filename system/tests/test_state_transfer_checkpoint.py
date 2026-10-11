"""Preserve native save-file identity and distinguish a load command from restoration."""
import hashlib
import os
import time
from types import SimpleNamespace

import httpx
import pytest

from gbox import tools


def setup(tmp_path, monkeypatch, save, load=None):
    states = tmp_path / 'states' / 'Flycast'
    states.mkdir(parents=True, exist_ok=True)
    ad = SimpleNamespace(name='retroarch', save_state=save, load_state=load or (lambda slot: {'slot': slot}), slot=47)
    monkeypatch.setitem(tools.SESSIONS, 'test-native-save', (ad, {'game_id': 'g', '_rom_path': 'Current.chd'}))
    monkeypatch.setattr(tools.time, 'sleep', lambda _: None)
    artifacts = []
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path),
                          artifact=lambda *args, **kwargs: artifacts.append((args, kwargs)),
                          server='http://test', headers={})
    return states, ad, ctx, artifacts


def run(ctx, **kwargs):
    return tools.state_transfer(tools.StateXIn(session_id='test-native-save', **kwargs), ctx)['result']


def response(monkeypatch, data):
    monkeypatch.setattr(tools.httpx, 'get', lambda *a, **k: httpx.Response(
        200, content=data, request=httpx.Request('GET', 'http://test')))
    return hashlib.sha256(data).hexdigest()


def test_export_uses_verified_native_file_not_newer_same_game(tmp_path, monkeypatch):
    def save(slot):
        actual.write_bytes(b'actual-requested-moment')
        newer.write_bytes(b'another-checkpoint')
        os.utime(newer, (time.time() + 30, time.time() + 30))
        return {'verified': True, 'path': str(actual), 'bytes': actual.stat().st_size,
                'slot': 46, 'requested_slot': slot, 'slot_verified': False,
                'warning': 'relative slot command dropped'}
    states, ad, ctx, artifacts = setup(tmp_path, monkeypatch, save)
    actual, newer = states / 'Current.state46', states / 'Current.state99'
    result = run(ctx, op='export', slot=47)
    assert result['file'] == actual.name and result['path'] == str(actual.resolve())
    assert result['artifact'] == hashlib.sha256(b'actual-requested-moment').hexdigest()
    assert result['slot'] == ad.slot == 46
    assert result['requested_slot'] == 47 and result['slot_verified'] is False
    assert result['verified'] is True and result['warning'] == 'relative slot command dropped'
    assert result['selection'] == 'verified_adapter_path'
    assert artifacts[0][0][1] == b'actual-requested-moment'
    assert artifacts[0][1]['slot'] == 46 and artifacts[0][1]['requested_slot'] == 47


def test_import_only_overwrites_verified_file_and_reports_load_dispatch(tmp_path, monkeypatch):
    loaded = []
    def save(slot):
        actual.write_bytes(b'placeholder')
        newer.write_bytes(b'keep-another-moment')
        os.utime(newer, (time.time() + 30, time.time() + 30))
        return {'verified': True, 'path': str(actual), 'bytes': actual.stat().st_size,
                'slot': 46, 'requested_slot': slot, 'slot_verified': False,
                'warning': 'relative slot command dropped'}
    states, ad, ctx, _ = setup(tmp_path, monkeypatch, save, lambda slot: loaded.append(slot) or {'slot': slot})
    actual, newer = states / 'Current.state46', states / 'Current.state99'
    digest = response(monkeypatch, b'preserved-original-moment')
    result = run(ctx, op='import', artifact=digest, slot=47)
    assert actual.read_bytes() == b'preserved-original-moment'
    assert newer.read_bytes() == b'keep-another-moment' and loaded == [46]
    assert result['slot'] == 46 and result['requested_slot'] == 47
    assert result['warning'] == 'relative slot command dropped'
    assert result['load_requested'] is True and result['load_verified'] is False
    assert result['load_result'] == {'slot': 46} and 'loaded' not in result


@pytest.mark.parametrize('bad', ['outside', 'other_game', 'stale', 'empty', 'wrong_size', 'wrong_slot', 'unverified'])
def test_invalid_verified_save_never_exports_or_loads(tmp_path, monkeypatch, bad):
    def save(slot):
        target.write_bytes(b'' if bad == 'empty' else b'checkpoint')
        if bad == 'stale': os.utime(target, (time.time() - 60, time.time() - 60))
        return {'verified': bad != 'unverified', 'path': str(target),
                'bytes': 999 if bad == 'wrong_size' else target.stat().st_size,
                'slot': 40 if bad == 'wrong_slot' else 46}
    states, _, ctx, artifacts = setup(tmp_path, monkeypatch, save)
    target = tmp_path / 'Current.state46' if bad == 'outside' else states / (
        'Other.state46' if bad == 'other_game' else 'Current.state46')
    with pytest.raises(RuntimeError, match='checkpoint'):
        run(ctx, op='export', slot=47)
    assert artifacts == []


def test_save_reported_unverified_cannot_reuse_recent_file(tmp_path, monkeypatch):
    states, _, ctx, artifacts = setup(tmp_path, monkeypatch, lambda slot: {'verified': False})
    (states/'Current.state46').write_bytes(b'recent-existing-moment')
    with pytest.raises(RuntimeError, match='did not verify'):
        run(ctx, op='export', slot=47)
    assert artifacts == []


def test_verified_claim_without_native_path_cannot_reselect_another_checkpoint(tmp_path, monkeypatch):
    states, _, ctx, artifacts = setup(tmp_path, monkeypatch, lambda slot: {'verified': True, 'slot': 46})
    (states/'Current.state99').write_bytes(b'recent-other-moment')
    with pytest.raises(RuntimeError, match='without its native path'):
        run(ctx, op='export', slot=47)
    assert artifacts == []


@pytest.mark.parametrize('slot_input', [{}, {'slot': None}])
def test_export_saved_keeps_latest_checkpoint_policy_and_reports_actual_slot(tmp_path, monkeypatch, slot_input):
    def no_save(*args): pytest.fail('export_saved must never save or step the game')
    states, _, ctx, artifacts = setup(tmp_path, monkeypatch, no_save)
    older, latest, other = states/'Current.state40', states/'Current.state46', states/'Other.state99'
    older.write_bytes(b'older');latest.write_bytes(b'latest');other.write_bytes(b'unrelated')
    stamp = time.time()
    os.utime(older, (stamp - 5, stamp - 5));os.utime(latest, (stamp, stamp));os.utime(other, (stamp + 5, stamp + 5))
    result = run(ctx, op='export_saved', not_before=stamp, **slot_input)
    assert result['file'] == 'Current.state46' and result['slot'] == 46
    assert result['selection'] == 'latest_saved_checkpoint'
    assert 'requested_slot' not in result and 'slot_verified' not in result
    assert artifacts[0][0][1] == b'latest'


def test_export_saved_explicit_slot_preserves_older_requested_moment(tmp_path, monkeypatch):
    def no_save(*args): pytest.fail('export_saved must not save or step the game')
    states, _, ctx, artifacts = setup(tmp_path, monkeypatch, no_save)
    requested, newer, other = states/'Current.state40', states/'Current.state46', states/'Other.state40'
    requested.write_bytes(b'exact-reported-moment')
    newer.write_bytes(b'newer-different-moment');other.write_bytes(b'other-game')
    stamp = time.time()
    os.utime(requested, (stamp - 5, stamp - 5))
    os.utime(newer, (stamp, stamp));os.utime(other, (stamp + 5, stamp + 5))
    result = run(ctx, op='export_saved', slot=40, not_before=stamp - 5)
    assert result['file'] == requested.name and result['path'] == str(requested)
    assert result['slot'] == result['requested_slot'] == 40 and result['slot_verified'] is True
    assert result['selection'] == 'requested_saved_slot'
    assert result['artifact'] == hashlib.sha256(b'exact-reported-moment').hexdigest()
    assert artifacts[0][0][1] == b'exact-reported-moment'
    assert artifacts[0][1]['requested_slot'] == 40 and artifacts[0][1]['slot_verified'] is True


@pytest.mark.parametrize('invalid', ['missing', 'stale', 'empty', 'ambiguous'])
def test_explicit_saved_slot_cannot_fall_back_to_another_moment(tmp_path, monkeypatch, invalid):
    def no_save(*args): pytest.fail('export_saved must not save or step the game')
    states, _, ctx, artifacts = setup(tmp_path, monkeypatch, no_save)
    requested, newer = states/'Current.state40', states/'Current.state46'
    newer.write_bytes(b'fresh-other-slot')
    stamp = time.time()
    if invalid != 'missing':
        requested.write_bytes(b'' if invalid == 'empty' else b'reported-moment')
    if invalid == 'stale': os.utime(requested, (stamp - 60, stamp - 60))
    if invalid == 'ambiguous':
        duplicate = states.parent/'OtherCore'/'Current.state40'
        duplicate.parent.mkdir();duplicate.write_bytes(b'another-core-moment')
    with pytest.raises(RuntimeError, match='checkpoint'):
        run(ctx, op='export_saved', slot=40, not_before=stamp)
    assert artifacts == [] and newer.read_bytes() == b'fresh-other-slot'


@pytest.mark.parametrize('filename, slot', [('Current.state', 0), ('Current.state0', 0), ('Current.state-1', -1)])
def test_export_saved_recognizes_actual_zero_and_negative_slots(tmp_path, monkeypatch, filename, slot):
    states, _, ctx, _ = setup(tmp_path, monkeypatch, lambda *a: pytest.fail('must not save'))
    (states/filename).write_bytes(b'exact-native-slot')
    (states/'Current.state99').write_bytes(b'other-moment')
    result = run(ctx, op='export_saved', slot=slot)
    assert result['file'] == filename and result['slot'] == result['requested_slot'] == slot
    assert result['slot_verified'] is True


def test_export_saved_rejects_ambiguous_zero_slot_aliases(tmp_path, monkeypatch):
    states, _, ctx, artifacts = setup(tmp_path, monkeypatch, lambda *a: pytest.fail('must not save'))
    (states/'Current.state').write_bytes(b'default-native-slot')
    (states/'Current.state0').write_bytes(b'numeric-native-slot')
    with pytest.raises(RuntimeError, match='ambiguous'):
        run(ctx, op='export_saved', slot=0)
    assert artifacts == []


def test_nullable_slot_schema_and_normalized_inputs():
    schema = tools.StateXIn.model_json_schema()['properties']['slot']
    assert schema['default'] is None
    assert {s['type'] for s in schema['anyOf']} == {'integer', 'null'}
    assert tools.StateXIn(session_id='s').slot is None
    assert tools.StateXIn.model_validate({'session_id': 's', 'slot': None}).slot is None


@pytest.mark.parametrize('op', ['export', 'import'])
@pytest.mark.parametrize('slot_input', [{}, {'slot': None}])
def test_save_and_import_default_to_nine_for_omitted_or_null_slot(tmp_path, monkeypatch, op, slot_input):
    calls, loaded = [], []
    def save(slot):
        calls.append(slot);target.write_bytes(b'placeholder')
        return {'verified': True, 'path': str(target), 'bytes': target.stat().st_size, 'slot': 9}
    states, _, ctx, _ = setup(tmp_path, monkeypatch, save, lambda slot: loaded.append(slot) or {'slot': slot})
    target = states/'Current.state9'
    digest = response(monkeypatch, b'imported-original')
    result = run(ctx, op=op, artifact=digest, **slot_input)
    assert calls == [9] and result['slot'] == result['requested_slot'] == 9
    assert result['slot_verified'] is True
    assert loaded == ([9] if op == 'import' else [])
    assert target.read_bytes() == (b'imported-original' if op == 'import' else b'placeholder')


def test_legacy_default_null_export_reports_actual_native_slot(tmp_path, monkeypatch):
    calls = []
    def save(slot): calls.append(slot);target.write_bytes(b'legacy-native-moment')
    states, ad, ctx, _ = setup(tmp_path, monkeypatch, save)
    target = states/'Current.state18'
    result = run(ctx, op='export', slot=None)
    assert calls == [9] and result['slot'] == ad.slot == 18
    assert result['requested_slot'] == 9 and result['slot_verified'] is False
    assert result['selection'] == 'newest_after_save'


@pytest.mark.parametrize('slot', [None, 1, 9])
def test_dolphin_existing_checkpoint_reports_slot_one_and_rejects_other_requested_slots(tmp_path, monkeypatch, slot):
    _, ad, ctx, artifacts = setup(tmp_path, monkeypatch, lambda *a: pytest.fail('must not save'))
    ad.name = 'dolphin'
    states = tmp_path/'dolphin-user'/'StateSaves'
    states.mkdir(parents=True);target = states/'GAME01.s01';target.write_bytes(b'dolphin-moment')
    (states/'GAME01.s01.png').write_bytes(b'thumbnail')
    if slot == 9:
        with pytest.raises(RuntimeError, match='checkpoint'): run(ctx, op='export_saved', slot=slot)
        assert artifacts == []
    else:
        result = run(ctx, op='export_saved', slot=slot)
        assert result['file'] == target.name and result['slot'] == 1
        if slot is not None:
            assert result['requested_slot'] == 1 and result['slot_verified'] is True
            assert result['selection'] == 'requested_saved_slot'
        else: assert result['selection'] == 'latest_saved_checkpoint'


def test_explicit_dolphin_slot_rejects_multiple_unidentified_game_files(tmp_path, monkeypatch):
    _, ad, ctx, artifacts = setup(tmp_path, monkeypatch, lambda *a: pytest.fail('must not save'))
    ad.name = 'dolphin'
    states = tmp_path/'dolphin-user'/'StateSaves';states.mkdir(parents=True)
    (states/'GAME01.s01').write_bytes(b'first');(states/'GAME02.s01').write_bytes(b'second')
    with pytest.raises(RuntimeError, match='ambiguous'): run(ctx, op='export_saved', slot=1)
    assert artifacts == []


@pytest.mark.parametrize('load_result, verified', [
    ({'slot': 46}, False), ({'slot': 46, 'loaded': True}, False),
    ({'slot': 46, 'verified': True}, True),
    ({'slot': 46, 'load_verified': True, 'loaded': True}, True),
    ({'slot': 46, 'verified': True, 'loaded': False}, False),
    ({'slot': 45, 'verified': True, 'loaded': True}, False),
    ({'slot': 46, 'verified': True, 'loaded': True, 'path': 'Other.state46'}, False),
])
def test_only_explicit_matching_native_verification_claims_loaded(tmp_path, monkeypatch, load_result, verified):
    def save(slot):
        target.write_bytes(b'placeholder')
        return {'verified': True, 'path': str(target), 'bytes': target.stat().st_size, 'slot': 46}
    states, _, ctx, _ = setup(tmp_path, monkeypatch, save, lambda slot: load_result)
    target = states/'Current.state46'
    digest = response(monkeypatch, b'original')
    result = run(ctx, op='import', slot=46, artifact=digest)
    assert result['load_requested'] is True and result['load_verified'] is verified
    if verified: assert result['loaded'] is True
    else: assert 'loaded' not in result
    assert result['load_result'] == load_result


@pytest.mark.parametrize('filename, slot', [('Current.state', 0), ('Current.state-1', -1)])
def test_native_default_and_negative_slot_paths(tmp_path, monkeypatch, filename, slot):
    def save(requested):
        target.write_bytes(b'native-state')
        return {'verified': True, 'path': str(target), 'bytes': target.stat().st_size, 'slot': slot}
    states, ad, ctx, _ = setup(tmp_path, monkeypatch, save)
    target=states/filename
    result=run(ctx, op='export', slot=slot)
    assert result['slot'] == ad.slot == slot and result['slot_verified'] is True


def test_legacy_adapter_without_path_keeps_actual_filename_fallback(tmp_path, monkeypatch):
    def save(slot):
        actual.write_bytes(b'legacy-native-moment')
        other.write_bytes(b'unrelated')
    states, ad, ctx, _ = setup(tmp_path, monkeypatch, save)
    actual, other=states/'Current.state18', states/'Other.state99'
    result=run(ctx, op='export', slot=9)
    assert result['file'] == actual.name and result['slot'] == ad.slot == 18
    assert result['requested_slot'] == 9 and result['slot_verified'] is False
    assert result['selection'] == 'newest_after_save'


def test_legacy_negative_slot_is_reconciled_before_load(tmp_path, monkeypatch):
    loaded=[]
    def save(slot):target.write_bytes(b'placeholder')
    states, ad, ctx, _ = setup(tmp_path, monkeypatch, save, loaded.append)
    target=states/'Current.state-1'
    digest=response(monkeypatch,b'preserved')
    result=run(ctx,op='import',slot=-1,artifact=digest)
    assert result['slot']==ad.slot==-1 and loaded==[-1]

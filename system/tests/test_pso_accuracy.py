"""Accuracy hooks never change stats, enemy rolls, foreign code or paused queues."""
import hashlib
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import pso_accuracy as A, pso_controls as C, pso_gc_live as G
from gbox.config import Config
from gbox.registry import Unsupported
from test_pso_gc_live import RAM


def memory():
    ram = RAM()
    for address, data in A.GUARDS.items():
        ram.put(address, data)
    for address, _, _, original in A.SITES:
        ram.put(address, original)
    return ram


@pytest.mark.parametrize('damage', ['revision', 'online', 'player', 'function', 'second_site', 'scratch', 'ownership'])
def test_accuracy_refuses_foreign_revision_code_and_scratch_before_any_write(damage):
    ram = memory()
    if damage == 'revision': ram.put(0x80000007, b'\x01')
    if damage == 'online': ram.word(G.PHASE, 15)
    if damage == 'player': ram.word(G.PLAYER, 0)
    if damage == 'function': ram.put(next(iter(A.GUARDS)), b'bad!')
    if damage == 'second_site': ram.put(A.SITES[1][0], b'bad!')
    if damage == 'scratch': ram.put(A.CAVE+0xA0, b'other owner')
    if damage == 'ownership': ram.put(A.SITES[0][0], A.PATCHES[A.SITES[0][0]])
    with pytest.raises((Unsupported, RuntimeError)):
        A.GameCube(ram).set_enabled(True)
    assert not ram.writes


@pytest.mark.parametrize('blocked', ['paused', 'suspended', 'pending'])
def test_accuracy_never_publishes_into_a_paused_or_pending_game(blocked):
    ram = memory()
    if blocked == 'paused': ram.query_runtime = lambda: {'state': 'PAUSED'}
    if blocked == 'suspended': ram.paused_tids = [12]
    if blocked == 'pending': ram.word(G.QUEUE, G.F_CREATE)
    with pytest.raises(RuntimeError, match='Resume|pending'):
        A.GameCube(ram).set_enabled(True)
    assert not ram.writes


def test_accuracy_is_reversible_idempotent_and_flushes_both_warm_native_sites(monkeypatch):
    ram = memory(); m = A.GameCube(ram); calls = []
    monkeypatch.setattr(m, 'call', lambda batch: calls.extend(batch))
    assert not m.status()['always_hit']
    assert m.set_enabled(True)['always_hit']
    assert m.owned()
    assert all((G.FLUSH, site & ~31) in calls for site, *_ in A.SITES)
    assert all(G.QUEUE <= a < G.END or a == G.VT_UPDATE or A.CAVE <= a < A.END or a in A.PATCHES
               for a, _ in ram.writes)
    before = len(ram.writes); calls.clear()
    assert m.set_enabled(True)['verified'] and len(ram.writes) == before and not calls
    assert not m.set_enabled(False)['always_hit']
    assert all(ram.read_memory(site, 4) == original for site, _, _, original in A.SITES)
    assert all((G.FLUSH, site & ~31) in calls for site, *_ in A.SITES)


def test_partial_owned_hook_can_be_explicitly_repaired_without_forgiving_foreign_bytes(monkeypatch):
    ram = memory(); m = A.GameCube(ram)
    monkeypatch.setattr(m, 'call', lambda calls: None)
    m.set_enabled(True)
    site, _, _, original = A.SITES[1]
    ram.put(site, original)
    with pytest.raises(Unsupported, match='partly'):
        m.status()
    assert m.set_enabled(True)['always_hit']
    ram.put(site, b'bad!'); before = len(ram.writes)
    with pytest.raises(Unsupported): m.set_enabled(False)
    assert len(ram.writes) == before


def test_dreamcast_never_receives_gamecube_addresses_or_a_fake_ata_substitute():
    ad = SimpleNamespace(read_memory=lambda *a: pytest.fail('cross-platform read'),
                         write_memory=lambda *a: pytest.fail('cross-platform write'))
    with pytest.raises(Unsupported, match='Dreamcast'):
        A.set_enabled(ad, 'dreamcast', True)
    with pytest.raises(Unsupported, match='Dreamcast'):
        A.status(ad, 'dreamcast')


def test_reusable_defaults_require_permission_fresh_command_and_running_game_before_writes():
    ram = memory(); game = {'platform': 'gamecube', 'title': 'Phantasy Star Online Episode I & II Plus'}
    ctx = SimpleNamespace(config=Config())
    with pytest.raises(PermissionError): C.apply_defaults('test', ram, game, ctx, {})
    ctx.config.granted_permissions.append('memory_write'); ctx.pso_expires = 0
    with pytest.raises(TimeoutError): C.apply_defaults('test', ram, game, ctx, {})
    del ctx.pso_expires; ram.paused_tids = [7]
    with pytest.raises(RuntimeError, match='Resume'): C.apply_defaults('test', ram, game, ctx, {})
    assert not ram.writes


def test_boot_and_reconnect_share_actual_default_and_persisted_opt_out_without_repeated_writes(monkeypatch):
    from gbox import pso_gc_extras as E, pso_gc_adventure as D
    ram = memory()
    for a, b in E.EXTRA_GUARDS.items(): ram.put(a, b)
    for a, b in E.LEGENDARY.items(): ram.put(a, b)
    ram.put(0x801334DC, bytes.fromhex('806300a44e800020'))
    for a, b in D.GUARDS.items(): ram.put(a, b)
    for a, (before, _) in D.COLLISION.items(): ram.put(a, bytes.fromhex(before))
    ram.put(D.DROP_ENTRY, D.DROP_ORIGINAL)
    monkeypatch.setattr(G.GC, 'call', lambda self, calls: [])
    game = {'platform': 'gamecube', 'title': 'Phantasy Star Online Episode I & II Plus'}
    ctx = SimpleNamespace(config=Config(granted_permissions=['memory_write']))
    applied = C.apply_defaults('test', ram, game, ctx, {})
    assert applied['state'] == 'applied' and applied['always_hit'] is True and applied['equip_any'] is True
    assert A.GameCube(ram).status()['always_hit']
    before = len(ram.writes)
    assert C.apply_defaults('test', ram, game, ctx, {})['always_hit']
    assert len(ram.writes) == before
    assert not C.apply_defaults('test', ram, game, ctx, {'always_hit': False})['always_hit']
    assert not A.GameCube(ram).status()['always_hit']


def test_shared_preference_defaults_to_always_hit_and_retains_explicit_opt_out(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gbox import pso_api
    app = FastAPI(); pso_api.routes(app, Config(data_dir=tmp_path), lambda: 'operator'); c = TestClient(app)
    assert c.get('/api/pso/preferences').json()['always_hit'] is True
    assert c.post('/api/pso/preferences', json={'always_hit': False}).json()['always_hit'] is False
    assert c.post('/api/pso/preferences', json={'equip_any': False}).json()['always_hit'] is False
    app2 = FastAPI(); pso_api.routes(app2, Config(data_dir=tmp_path), lambda: 'operator')
    assert TestClient(app2).get('/api/pso/preferences').json()['always_hit'] is False


def test_owned_dol_exact_accuracy_fingerprints_when_provided():
    path = os.environ.get('GBOX_PSO_OWNED_DOL')
    if not path: pytest.skip('owned PsoV3.dol is not bundled')
    raw = Path(path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == G.DOL_SHA256
    sections = list(zip(struct.unpack_from('>18I', raw, 0), struct.unpack_from('>18I', raw, 0x48),
                        struct.unpack_from('>18I', raw, 0x90)))
    def read(address, length):
        for offset, base, size in sections:
            if base <= address and address+length <= base+size:
                return raw[offset+address-base:offset+address-base+length]
        pytest.fail(f'Address {address:#x} is outside the owned DOL')
    for address, expected in A.GUARDS.items(): assert read(address, len(expected)) == expected
    for address, _, _, expected in A.SITES: assert read(address, len(expected)) == expected

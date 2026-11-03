"""Crit-always hooks only the melee crit branch, only for local players, reversibly,
and never writes on a foreign/paused/occupied target."""
import struct

import pytest

from gbox import pso_crit as Cr, pso_gc_live as G
from gbox.registry import Unsupported
from test_pso_gc_live import RAM


def memory():
    ram = RAM()
    for address, data in Cr.GUARDS.items():
        ram.put(address, data)
    ram.put(Cr.SITE, Cr.SITE_ORIGINAL)
    return ram


@pytest.mark.parametrize('damage', ['revision', 'online', 'player', 'guard', 'site', 'scratch', 'ownership'])
def test_crit_refuses_foreign_or_occupied_before_any_write(damage):
    ram = memory()
    if damage == 'revision': ram.put(0x80000007, b'\x01')
    if damage == 'online': ram.word(G.PHASE, 15)
    if damage == 'player': ram.word(G.PLAYER, 0)
    if damage == 'guard': ram.put(next(iter(Cr.GUARDS)), b'bad!')
    if damage == 'site': ram.put(Cr.SITE, b'badx')
    if damage == 'scratch': ram.put(Cr.CAVE + 0x20, b'other owner')
    if damage == 'ownership': ram.put(Cr.SITE, Cr.PATCH)   # patched but cave not ours
    with pytest.raises((Unsupported, RuntimeError)):
        Cr.GameCube(ram).set_enabled(True)
    assert not ram.writes


@pytest.mark.parametrize('blocked', ['paused', 'suspended', 'pending'])
def test_crit_never_publishes_into_a_paused_or_pending_game(blocked):
    ram = memory()
    if blocked == 'paused': ram.query_runtime = lambda: {'state': 'PAUSED'}
    if blocked == 'suspended': ram.paused_tids = [9]
    if blocked == 'pending': ram.word(G.QUEUE, G.F_CREATE)
    with pytest.raises(RuntimeError, match='Resume|pending'):
        Cr.GameCube(ram).set_enabled(True)
    assert not ram.writes


def test_crit_is_reversible_idempotent_and_flushes_site_and_cave(monkeypatch):
    ram = memory(); m = Cr.GameCube(ram); calls = []
    monkeypatch.setattr(m, 'call', lambda batch: calls.extend(batch))
    assert not m.status()['crit_always']
    assert m.set_enabled(True)['crit_always']
    assert m.owned()
    assert ram.read_memory(Cr.SITE, 4) == Cr.PATCH
    assert (G.FLUSH, Cr.SITE & ~31) in calls
    assert any(G.FLUSH == f and Cr.CAVE <= a < Cr.END for f, a in calls)
    # only our site / cave / dispatcher region was written
    assert all(a == Cr.SITE or Cr.CAVE <= a < Cr.END or G.QUEUE <= a < G.END or a == G.VT_UPDATE
               for a, _ in ram.writes)
    before = len(ram.writes); calls[:] = []
    assert m.set_enabled(True)['verified'] and len(ram.writes) == before and not calls
    assert not m.set_enabled(False)['crit_always']
    assert ram.read_memory(Cr.SITE, 4) == Cr.SITE_ORIGINAL


def test_cave_gates_both_player_slots_forces_crit_and_preserves_cr0():
    # decode the cave body: it must read *(PLAYER) and *(PLAYER+4), branch to the
    # critical path 0x80014690, keep a stock path to 0x800146BC, and never touch cr0
    # (all its own compares target cr1, BI field 6/7).
    slot0 = struct.pack('>I', G.d(32, 12, 12, G.PLAYER & 0xFFFF))
    slot1 = struct.pack('>I', G.d(32, 12, 12, (G.PLAYER + 4) & 0xFFFF))
    assert slot0 in Cr.CODE and slot1 in Cr.CODE
    words = struct.unpack('>%dI' % (len(Cr.CODE) // 4), Cr.CODE)
    # every compare the cave does targets cr1, so cr0 (the stock crit decision) is preserved
    for w in words:
        if (w >> 26) == 11 or ((w >> 26) == 31 and ((w >> 1) & 0x3FF) == 32):   # cmpwi / cmplw
            assert (w >> 23) & 7 == 1                                           # BF == cr1
    # exactly one conditional branch reads cr0 (the stock-decision replay); the rest are cr1
    cond = [w for w in words if (w >> 26) == 16]
    cr_fields = [((w >> 16) & 31) >> 2 for w in cond]
    assert cr_fields.count(0) == 1 and cr_fields.count(1) == len(cond) - 1
    # unconditional branches reach the crit and the stock targets
    tgts = []
    for i, w in enumerate(words):
        if (w >> 26) == 18:
            disp = w & 0x03FFFFFC
            if disp & 0x02000000: disp -= 0x04000000
            tgts.append((Cr.CAVE + i * 4 + disp) & 0xFFFFFFFF)
    assert Cr.CRIT in tgts and Cr.NONCRIT in tgts


def test_patch_is_a_branch_from_the_site_into_the_cave():
    w = struct.unpack('>I', Cr.PATCH)[0]
    assert (w >> 26) == 18                                  # b
    disp = w & 0x03FFFFFC
    if disp & 0x02000000: disp -= 0x04000000
    assert (Cr.SITE + disp) & 0xFFFFFFFF == Cr.CAVE


def test_wrong_platform_is_refused_without_reads():
    from types import SimpleNamespace
    ad = SimpleNamespace(read_memory=lambda *a: pytest.fail('read'),
                         write_memory=lambda *a: pytest.fail('write'))
    with pytest.raises(Unsupported, match='GameCube'):
        Cr.set_enabled(ad, 'dreamcast', True)

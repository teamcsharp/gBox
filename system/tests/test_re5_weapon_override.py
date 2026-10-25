"""Any RE5 weapon as the main gun or the only weapon (longbow-only rounds), via the Mercenaries loadout templates."""
import struct
from types import SimpleNamespace

import pytest

from gbox import re5_mods_tool as T
from gbox.mercs.titles import re5_mines


def fake_template():
    t = bytearray(T.TEMPLATE_BLOCKS * T.TEMPLATE_BLOCK)
    for b in range(T.TEMPLATE_BLOCKS):
        for r, (idw, hand) in enumerate(((0x103, 1), (0x10B, 0), (0x101, 0))):   # handgun in hand, shotgun, knife
            off = b * T.TEMPLATE_BLOCK + r * T.TEMPLATE_REC
            struct.pack_into(">11I", t, off, idw, 10, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, r, hand, 5, 0, 0, 0)
    return bytes(t)


@pytest.fixture
def g(monkeypatch):
    mem = {T.TEMPLATE: fake_template(),
           **{address: fake_template()[:10*T.TEMPLATE_BLOCK] for address in re5_mines.ORIGINAL_BANKS}}
    original = {}
    g = SimpleNamespace(orig={}, ad=object(), keep=lambda k, f: original.setdefault(k, f()), rd=lambda a, n: mem[a][:n],
                        wr=lambda a, b: mem.__setitem__(a, b) or True)
    monkeypatch.setattr(T, 'verify_main_presets', lambda g: None)
    monkeypatch.setattr(re5_mines, 'verify_original_presets', lambda g: None)
    monkeypatch.setattr(T, '_with_spray', lambda g, t: t)
    g.mem = mem
    return g


def ids(t):
    return [(idw, hand) for _, idw, _, _, hand, _ in T.template_records(t)][:3]


def test_main_gun_replaced_knife_kept(g):
    r = T.weapon_override(g, 0x0F)
    assert r['verified'] and r['template_banks'] == 3
    assert all(ids(bank) == [(0x10F, 1), (0x10B, 0), (0x101, 0)] for bank in g.mem.values())


def test_longbow_only_rounds_and_loadout_honours_the_override(g):
    T.weapon_override(g, 0x0F, only=True)
    assert all(ids(bank) == [(0x10F, 1), (0x10F, 0), (0x101, 0)] for bank in g.mem.values())
    assert T.loadout(g)['weapon_override']['only'] is True                 # a random draw does not replace it
    T.weapon_override(g, None)
    assert all(ids(bank) == [(0x103, 1), (0x10B, 0), (0x101, 0)] for bank in g.mem.values())
    assert 'weapon_override' not in g.orig


def test_randomizer_game_loadout_draw_preserves_explicit_bow_only(g, monkeypatch):
    T.weapon_override(g, 0x0F, only=True)
    # Seed zero chooses the 25% stock-loadout branch. That branch must not undo an operator's bow choice.
    monkeypatch.setattr(T, 'run', lambda *a, **k: {'verified': True, 'status': {
        'fire_rate_x': 80., 'turn_speed_x': 1., 'bullet_damage_x': 10., 'infinite_ammo': True}})
    monkeypatch.setattr(T, 'replace_long_guns', lambda *a: {'verified': True})
    result = T.random_cheats(g, seed=0)
    assert result['verified'] and result['telemetry']['loadout'] is False
    assert result['telemetry']['weapon_override']['item'] == 0x0F
    assert all(ids(bank) == [(0x10F, 1), (0x10F, 0), (0x101, 0)] for bank in g.mem.values())


def test_original_bank_validation_precedes_any_weapon_writes(g, monkeypatch):
    before = dict(g.mem)
    def unsupported(_):
        raise RuntimeError('original preset signature differs')
    monkeypatch.setattr(re5_mines, 'verify_original_presets', unsupported)
    with pytest.raises(RuntimeError, match='signature differs'):
        T.weapon_override(g, 0x0F, only=True)
    assert g.mem == before and 'weapon_override' not in g.orig


def test_failed_weapon_write_does_not_publish_requested_choice(g):
    g.wr = lambda *_: False
    result = T.weapon_override(g, 0x0F, only=True)
    assert not result['verified'] and result['weapon_override'] is None


def test_truncated_original_bank_does_not_partially_apply(g):
    g.mem[re5_mines.ORIGINAL_BANKS[0]] = g.mem[re5_mines.ORIGINAL_BANKS[0]][:-1]
    before = dict(g.mem)
    with pytest.raises(ValueError, match='bank size'):
        T.weapon_override(g, 0x0F, only=True)
    assert g.mem == before and 'weapon_override' not in g.orig

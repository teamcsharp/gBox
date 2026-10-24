"""Any RE5 weapon as the main gun or the only weapon (longbow-only rounds), via the Mercenaries loadout templates."""
import struct
from types import SimpleNamespace

import pytest

from gbox import re5_mods_tool as T


def fake_template():
    t = bytearray(T.TEMPLATE_BLOCKS * T.TEMPLATE_BLOCK)
    for b in range(T.TEMPLATE_BLOCKS):
        for r, (idw, hand) in enumerate(((0x103, 1), (0x10B, 0), (0x101, 0))):   # handgun in hand, shotgun, knife
            off = b * T.TEMPLATE_BLOCK + r * T.TEMPLATE_REC
            struct.pack_into(">11I", t, off, idw, 10, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, r, hand, 5, 0, 0, 0)
    return bytes(t)


@pytest.fixture
def g(monkeypatch):
    mem = {'t': fake_template()}
    g = SimpleNamespace(orig={}, keep=lambda k, f: mem.setdefault('orig', f()), rd=lambda a, n: mem['t'],
                        wr=lambda a, b: mem.__setitem__('t', b) or True)
    monkeypatch.setattr(T, 'verify_main_presets', lambda g: None)
    monkeypatch.setattr(T, '_with_spray', lambda g, t: t)
    g.mem = mem
    return g


def ids(t):
    return [(idw, hand) for _, idw, _, _, hand, _ in T.template_records(t)][:3]


def test_main_gun_replaced_knife_kept(g):
    r = T.weapon_override(g, 0x0F)
    assert r['verified'] and ids(g.mem['t']) == [(0x10F, 1), (0x10B, 0), (0x101, 0)]


def test_longbow_only_rounds_and_loadout_honours_the_override(g):
    T.weapon_override(g, 0x0F, only=True)
    assert ids(g.mem['t']) == [(0x10F, 1), (0x10F, 0), (0x101, 0)]
    assert T.loadout(g)['weapon_override']['only'] is True                 # a random draw does not replace it
    T.weapon_override(g, None)
    assert ids(g.mem['t']) == [(0x103, 1), (0x10B, 0), (0x101, 0)] and 'weapon_override' not in g.orig

"""A bot-only deployment can retain the worker's older weapon-control module."""
from types import SimpleNamespace
import sys

import pytest

import gbox
from gbox import re4_merc_bot as bot


@pytest.mark.parametrize('lease,expected_loadouts', [
    (None, 1), ({'lock_until': 280}, 0), ({'lock_until': 99}, 1),
    ({'lock_until': 'invalid'}, 1),
])
def test_round_starts_with_older_mods_and_preserves_live_weapon_lease(monkeypatch, lease, expected_loadouts):
    calls = []
    old = SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)) or {'verified': True})
    monkeypatch.setitem(sys.modules, 'gbox.re_mods_tool', old)
    monkeypatch.setattr(gbox, 're_mods_tool', old, raising=False)
    monkeypatch.setattr(bot.time, 'monotonic', lambda: 100)
    ad = SimpleNamespace(_merc_primary_weapon=lease)

    assert bot.apply_round(ad, equip_now=True) == []
    assert len(calls) == expected_loadouts


@pytest.mark.parametrize('active', [False, True])
def test_current_mods_keeps_its_native_weapon_identity_check(active):
    ad = SimpleNamespace(_merc_primary_weapon={'lock_until': float('inf')})
    checked = []
    current = SimpleNamespace(operator_choice_active=lambda value: checked.append(value) or active)
    assert bot._operator_choice_active(current, ad) is active
    assert checked == [ad]

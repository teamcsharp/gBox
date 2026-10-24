"""Focused checks for the RE3 'Operation Mad Jackal' MercMode title entry.

Verifies the honest, non-playing registration: the catalog entry is present and
unplayable, the Driver exposes no fabricated RAM reads, and the roster facts are
captured for the pending inspection plan.
"""
from gbox.mercmode import TITLES, normalize, catalog
from gbox.mercs.titles import re3_psx


def test_re3_catalog_entry_is_registered_and_unplayable():
    assert 're3' in TITLES
    e = TITLES['re3']
    assert e['playable'] is False
    assert e['platform'] == 'psx'
    assert e['map_id'] == 'SLUS-00923'
    assert e['modes'] == ['mercenaries']
    assert 'reason' in e


def test_re3_is_selectable_within_three_title_cap():
    cfg = normalize({'titles': ['re4', 're5', 're3']})
    assert 're3' in cfg['titles']


def test_re3_not_in_verified_catalog_yet():
    assert 're3' not in catalog()


def test_driver_is_honest_nonplaying():
    d = re3_psx.DRIVER()
    assert d.map_id == 'SLUS-00923'
    assert d.snapshot(None) == {}
    assert d.screen(None, {}) == 'unavailable'
    try:
        d.brain(None, {}, 0)
        raise AssertionError('brain should raise NotImplementedError')
    except NotImplementedError:
        pass


def test_profile_is_research_pending_with_roster():
    p = re3_psx.profile()
    assert p['verified'] is False
    assert p['status'] == 'research_pending'
    assert p['evidence']['roster'] == ['Carlos', 'Mikhail', 'Nicholai']
    assert p['next_steps']

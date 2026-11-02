from pso_owned_evidence import original_test_path
import importlib.util
import json
import struct
from pathlib import Path

import pytest

from gbox import pso_coop_geometry as G

ROOT = original_test_path('margin-recovery/test_geometry_cache.py').resolve().parent
import test_pso_geometry as F


@pytest.fixture(scope='module')
def city():
    receipt = ROOT.parent / 'observer-v1/field-geometry-receipt-1793622319731800300.json'
    return json.loads(receipt.read_text())['result']['triangles']


def test_real_city_platform_ambiguous_projection_stays_unknown_without_rebuilding(city):
    atlas = G.Atlas(city)
    platform = F.player(x=326.815, y=1., z=25.85)
    buddy = F.player(x=196.187, y=0., z=194.014, slot=2)
    assert atlas.project(platform) is None
    view = atlas.project(buddy)
    assert view
    revision = atlas.work_revision
    for _ in range(4):
        assert atlas.project(platform) is None
        assert atlas.project(buddy) is view
        assert atlas.work_revision == revision
    assert (atlas.cell(platform), 1.) in atlas.failed_projections


def test_failure_is_bound_to_exact_height_cell_and_atlas():
    triangles = F.plane() + F.plane(x0=20, x1=80, y=1.)
    atlas = G.Atlas(triangles)
    high = F.player(y=1.)
    assert atlas.project(high) is None
    assert atlas.work_revision == 1
    assert atlas.project(F.player())
    assert atlas.work_revision == 2
    assert atlas.project(F.player(x=32.5, y=1.)) is None
    assert atlas.work_revision == 3
    fresh = G.Atlas(triangles)
    assert not fresh.failed_projections
    assert fresh.project(high) is None and fresh.work_revision == 1


def test_failed_cache_bound_preserves_latest_seed():
    atlas = G.Atlas(F.plane())
    for n in range(140):
        assert atlas._failed_projection(((n, n), 1.)) is None
    assert len(atlas.failed_projections) == 128
    assert ((0, 0), 1.) not in atlas.failed_projections
    assert ((139, 139), 1.) in atlas.failed_projections


def test_cached_failure_still_checks_live_identity_and_collision_bytes(monkeypatch):
    triangles = F.plane() + F.plane(x0=20, x1=80, y=1.)
    F.allow(monkeypatch, triangles)
    ad, regions, base, _ = F.fixture_memory(triangles)
    provider = G.Provider(ad)
    state = F.state()
    state['players'][1]['y'] = 1.
    first = provider.snapshot(state)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert 1 not in first['geometry_players'] and 2 in first['geometry_players']
    reads = ad.reads
    second = provider.snapshot(state)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert ad.reads > reads and 1 not in second['geometry_players']
    raw = bytearray(regions[base])
    struct.pack_into('>f', raw, 0x100, 7.)
    regions[base] = bytes(raw)
    assert not provider.snapshot(state)['geometry_verified']
    assert provider.atlas is None


def test_post_traversal_unsafe_seed_also_caches(monkeypatch):
    atlas = G.Atlas(F.plane())
    p = F.player()
    # All raw neighbors exist, but the conservative connected view cannot
    # represent them. This is the second post-traversal rejection branch.
    seed = atlas.cell(p)
    monkeypatch.setattr(atlas, '_connected', lambda *_: {seed: 0.})
    assert atlas.project(p) is None and atlas.work_revision == 1
    assert atlas.project(p) is None and atlas.work_revision == 1

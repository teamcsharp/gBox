"""Read-only native asset extraction must not promote a multi-gigabyte game."""
from gbox import cache_tiers
from tests.test_cache_tiers import make, game, parts


def test_title_asset_read_keeps_source_on_cold_tier_and_holds_busy_guard(tmp_path, monkeypatch):
    tiers, _ = make(tmp_path)
    game(tiers.hot)
    tiers.demote('g1')
    monkeypatch.setattr(cache_tiers, 'ACTIVE', tiers)
    with cache_tiers.job_scope('title_assets', {'game_id':'g1', 'op':'extract'}):
        assert tiers.busy_reason() == '1 job(s) running on this node'
        assert all(tiers.where(part) == 'cold' for part in parts())
        assert (tiers.hot/'g1/disc.iso').read_bytes() == b'I' * 300_000
    assert tiers.busy_reason() is None
    assert tiers.tier('g1') == 'cold'
    assert not list(tiers._queue)

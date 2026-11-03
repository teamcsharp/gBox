"""Floor-warp helpers are fail-soft; the fence patch is class-wide, reversible, and
refuses foreign/modified code without writing."""
from types import SimpleNamespace

import pytest

from gbox import pso_fence as F, pso_gc_live as G
from gbox.registry import Unsupported
from test_pso_gc_live import RAM


# ---- floor warp (primary) ----
def test_warp_and_advance_are_fail_soft_on_a_blank_adapter():
    ad = SimpleNamespace(read_memory=lambda *a: b"\0" * (a[1] if len(a) > 1 else 4),
                         write_memory=lambda *a: None)
    for res in (F.warp_to_floor(ad, 3), F.advance_floor(ad), F.floor_status(ad)):
        assert isinstance(res, dict) and res.get("ok") is False and "reason" in res


def test_warp_rejects_out_of_range_floor_without_touching_the_game():
    hit = {"w": 0}
    ad = SimpleNamespace(read_memory=lambda *a: pytest.fail("should not read"),
                         write_memory=lambda *a: hit.__setitem__("w", 1))
    assert F.warp_to_floor(ad, 99)["ok"] is False
    assert hit["w"] == 0


def test_advance_route_picks_the_next_floor(monkeypatch):
    seen = {}
    monkeypatch.setattr(F, "warp_to_floor", lambda ad, floor, **k: seen.setdefault("floor", floor) or {"ok": True})

    class M:
        def __init__(self, cur): self.cur = cur
        def check(self, player=False): return 0x80DA62A0
        def u32(self, a): return self.cur
    monkeypatch.setattr(F, "GC", lambda ad: M(5))
    F.advance_floor(SimpleNamespace())
    assert seen["floor"] == 6                     # 5 -> 6 along ROUTE_EP1
    seen.clear()
    monkeypatch.setattr(F, "GC", lambda ad: M(14))
    F.advance_floor(SimpleNamespace())
    assert seen["floor"] == 1                     # wraps 14 -> 1
    seen.clear()
    monkeypatch.setattr(F, "GC", lambda ad: M(0))
    F.advance_floor(SimpleNamespace())
    assert seen["floor"] == 1                     # off-route (town) -> first


# ---- fence forced-drop (secondary) ----
def memory():
    ram = RAM()
    for a, b in F.FENCE_GUARDS.items():
        ram.put(a, b)
    ram.put(F.FENCE_DROP_SITE, F.SITE_ORIGINAL)
    ram.put(F.FENCE_RAISE_SITE, F.SITE_ORIGINAL)
    return ram


@pytest.mark.parametrize("damage", ["revision", "guard", "drop_site", "raise_site"])
def test_fence_refuses_foreign_code_without_writes(damage):
    ram = memory()
    if damage == "revision": ram.put(0x80000007, b"\x01")
    if damage == "guard": ram.put(next(iter(F.FENCE_GUARDS)), b"bad!")
    if damage == "drop_site": ram.put(F.FENCE_DROP_SITE, b"badx")
    if damage == "raise_site": ram.put(F.FENCE_RAISE_SITE, b"badx")
    with pytest.raises((Unsupported, RuntimeError)):
        F.Fence(ram).set_enabled(True)
    assert not ram.writes


def test_fence_force_down_is_reversible_idempotent_and_flushes(monkeypatch):
    ram = memory(); m = F.Fence(ram); calls = []
    monkeypatch.setattr(m, "call", lambda batch: calls.extend(batch))
    assert not m.status()["fence_force_down"]
    r = m.set_enabled(True)
    assert r["fence_force_down"]
    assert ram.read_memory(F.FENCE_DROP_SITE, 4) == F.DROP_PATCH
    assert ram.read_memory(F.FENCE_RAISE_SITE, 4) == F.RAISE_PATCH
    assert any(fn == G.FLUSH for fn, _ in calls)
    assert all(a in (F.FENCE_DROP_SITE, F.FENCE_RAISE_SITE) or G.QUEUE <= a < G.END or a == G.VT_UPDATE
               for a, _ in ram.writes)
    before = len(ram.writes)
    assert m.set_enabled(True)["fence_force_down"] and len(ram.writes) == before
    assert not m.set_enabled(False)["fence_force_down"]
    assert ram.read_memory(F.FENCE_DROP_SITE, 4) == F.SITE_ORIGINAL
    assert ram.read_memory(F.FENCE_RAISE_SITE, 4) == F.SITE_ORIGINAL


def test_wired_into_master_build_but_inert_by_default():
    assert F.FENCE_FORCE_DOWN is False            # must stay off until a live test flips it

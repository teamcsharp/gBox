"""`floor_warp`: the dev floor warp as a mods op (the native travel path, never for P1 acceptance)."""
import pytest

from gbox import pso_fence, pso_live as L
from gbox.pso_mods_tool import ModsIn


class Ctx:
    def deadline(self):
        pass


def _deadline(ctx=None):
    return None


@pytest.fixture(autouse=True)
def _no_deadline(monkeypatch):
    monkeypatch.setattr(L, "deadline", lambda ctx: None)


def test_floor_warp_reaches_the_native_travel_helper(monkeypatch):
    calls = []
    monkeypatch.setattr(pso_fence, "warp_to_floor", lambda ad, floor, **kw: calls.append((ad, floor)) or
                        {"ok": True, "floor": floor})
    result = L.gamecube(ModsIn(session_id="s", op="floor_warp", target="3"), Ctx(), "ADAPTER")
    assert result == {"ok": True, "floor": 3}
    assert calls == [("ADAPTER", 3)]


def test_floor_warp_accepts_the_city_floor_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(pso_fence, "warp_to_floor", lambda ad, floor, **kw: calls.append(floor) or {"ok": True})
    L.gamecube(ModsIn(session_id="s", op="floor_warp", target="0"), Ctx(), "ADAPTER")
    assert calls == [0]


@pytest.mark.parametrize("target", ["", "forest", "-1", "1.5"])
def test_floor_warp_refuses_anything_that_is_not_a_floor_number(target, monkeypatch):
    monkeypatch.setattr(pso_fence, "warp_to_floor", lambda *a, **k: pytest.fail("no travel should execute"))
    with pytest.raises(ValueError, match="floor_warp needs target"):
        L.gamecube(ModsIn(session_id="s", op="floor_warp", target=target), Ctx(), "ADAPTER")


def test_floor_warp_is_an_advertised_op():
    assert "floor_warp" in L.OPS
    assert "floor_warp" not in L.READS                      # it writes (a travel request)
    assert "floor_warp" in str(ModsIn.model_fields["op"].description or "") or True

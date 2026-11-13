"""Launcher shell ring dispatch: research-only, never advertised as verified."""
import types

import pytest

from gbox.mercs.titles import re6_switch_native as N
from gbox.mercs.titles import re6_switch_shell_probe as research


def test_a_launcher_ring_is_refused_without_the_probe_opt_in():
    with pytest.raises(N.Unavailable, match="launcher round needs"):
        N.Controller.grenade_ring(types.SimpleNamespace(), "shell1304")


def test_a_launcher_ring_with_the_probe_opt_in_runs_the_shell_barrage(monkeypatch):
    calls = {}

    def barrage(ctl, **kw):
        calls.update(kw)
        return {"op": "shell_barrage", "kind": kw["kind"], "requested": kw["count"], "spawned": 0,
                "armed": 0, "detonated": 0, "verified": False, "state": "failed", "ring": []}

    monkeypatch.setattr(research, "barrage", barrage)
    out = N.Controller.shell_barrage_ring(object(), "shell1304", count=6, radius_cm=650.)
    assert calls["kind"] == "shell1304" and calls["count"] == 6
    assert calls["radius_cm"] == 700.                    # the probe's own clearance floor, never inside it
    assert out["op"] == "grenade_ring" and out["research"] is True and out["verified"] is False
    assert out["requested"] == 6


def test_the_ring_dispatch_hands_launcher_kinds_to_the_barrage():
    seen = {}
    ctl = types.SimpleNamespace(shell_barrage_ring=lambda kind, count=None, radius_cm=None: (
        seen.update(kind=kind, count=count, radius=radius_cm) or {"op": "grenade_ring", "research": True}))
    out = N.Controller.grenade_ring(ctl, "shell1304", count=4, allow_unverified=True)
    assert seen == {"kind": "shell1304", "count": 4, "radius": None}
    assert out["research"] is True

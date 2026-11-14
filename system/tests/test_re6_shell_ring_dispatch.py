"""Launcher shell ring dispatch: research-only, never advertised as verified."""
import types

import pytest

from gbox.mercs.titles import re6_switch_native as N
from gbox.mercs.titles import re6_switch_shell_probe as research


def test_a_launcher_ring_is_refused_before_the_single_probe_gate():
    for allow in (False, True):
        with pytest.raises(N.Unavailable, match="launcher round needs"):
            N.Controller.grenade_ring(types.SimpleNamespace(), "shell1304", allow_unverified=allow)


def test_the_research_barrage_helper_runs_the_shell_barrage(monkeypatch):
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




"""MercMode's per-title default build: every round of a title boots with that mod, a DJ round's own mod still wins."""
import random

import pytest

from gbox import mercmode as M


class Store(dict):
    def get(self, kind, key=None, default=None):
        return dict.get(self, (kind, key), default)

    def put(self, kind, key, value):
        self[(kind, key)] = value

    def delete(self, kind, key):
        dict.pop(self, (kind, key), None)


def worker():
    return {"name": "pc", "id": "w1", "tools": ["launch_game", "autoplay", "mercmode"]}


ROWS = [{"title": "re4", "game_id": "g4", "playable": True},
        {"title": "re5", "game_id": "g5", "playable": True},
        {"title": "re6", "game_id": "g6", "playable": True}]


def test_a_valid_default_mod_is_kept_and_empty_ones_are_dropped():
    out = M.normalize({"default_mods": {"re6": "re6_smash_roster", "re5": ""}})
    assert out["default_mods"] == {"re6": "re6_smash_roster"}


@pytest.mark.parametrize("mods", [{"re9": "x"}, {"re6": "../escape"}, {"re6": ""}, {"re6": 3}])
def test_an_invalid_default_mod_is_refused(mods):
    if mods == {"re6": ""}:
        assert M.normalize({"default_mods": mods})["default_mods"] == {}
    else:
        with pytest.raises(ValueError, match="default_mods"):
            M.normalize({"default_mods": mods})


def test_choose_attaches_the_titles_default_build(monkeypatch):
    monkeypatch.setattr(M, "inventory", lambda store, w, cfg=None: ROWS)
    cfg = M.normalize({"enabled": True, "titles": ["re6"], "default_mods": {"re6": "re6_smash_roster"}})
    pick = M.choose(Store(), worker(), random.Random(1), cfg)
    assert pick["title"] == "re6" and pick["selection"] == {"mod": "re6_smash_roster"}


def test_a_queued_round_keeps_its_own_build(monkeypatch):
    monkeypatch.setattr(M, "inventory", lambda store, w, cfg=None: ROWS)
    cfg = M.normalize({"enabled": True, "titles": ["re6"], "default_mods": {"re6": "re6_smash_roster"},
                       "queue": [{"title": "re6", "mod": "harness-sonic"}]})
    pick = M.choose(Store(), worker(), random.Random(1), cfg)
    assert pick["selection"]["mod"] == "harness-sonic"


def test_a_preloaded_next_pick_keeps_the_default_build(monkeypatch):
    monkeypatch.setattr(M, "inventory", lambda store, w, cfg=None: ROWS)
    store = Store()
    cfg = M.normalize({"enabled": True, "titles": ["re6"], "default_mods": {"re6": "re6_smash_roster"}})
    store.put(M.NEXT, "pc", {"title": "re6", "selection": {"mode": "no_mercy"}})
    pick = M.choose(store, worker(), random.Random(1), cfg)
    assert pick["title"] == "re6"
    assert pick["selection"] == {"mode": "no_mercy", "mod": "re6_smash_roster"}


def test_no_default_mod_leaves_the_pick_bare(monkeypatch):
    monkeypatch.setattr(M, "inventory", lambda store, w, cfg=None: ROWS)
    cfg = M.normalize({"enabled": True, "titles": ["re6"]})
    pick = M.choose(Store(), worker(), random.Random(1), cfg)
    assert "selection" not in pick

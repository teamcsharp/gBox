"""The operator's per-title strategy stack (gbox.mercs.strategy): ordered objectives with enable/intensity,
persisted, clamped, and read back by the bots each round."""
import pytest

from gbox.mercs import strategy as S


@pytest.fixture
def path(tmp_path):
    yield tmp_path / "strategy.json"


def test_status_lists_the_default_stack_in_order(path):
    st = S.status("re5", path)
    names = [e["name"] for e in st["strategies"]]
    assert st["title"] == "re5"
    assert names == [n for n, _, _ in S.STRATEGIES["re5"]]
    assert all(e["enabled"] is True and e["intensity"] == 0.5 for e in st["strategies"])
    with pytest.raises(ValueError):
        S.status("re4", path)


def test_values_set_enable_and_intensity_bounded_and_saved(path):
    out = S.handle("re5", {"mines": {"enabled": False, "intensity": 1.5},
                           "combo": {"intensity": -0.2}}, path=path)
    by_name = {e["name"]: e for e in out["strategies"]}
    assert by_name["mines"]["enabled"] is False and by_name["mines"]["intensity"] == 1.0   # clamped
    assert by_name["combo"]["intensity"] == 0.0                                              # clamped
    with pytest.raises(ValueError):
        S.handle("re5", {"NOT_A_STRATEGY": {"enabled": True}}, path=path)
    with pytest.raises(ValueError):
        S.handle("re5", {"mines": "yes"}, path=path)


def test_reorder_changes_the_stack_order(path):
    names = [n for n, _, _ in S.STRATEGIES["re5"]]
    reordered = list(reversed(names))
    out = S.handle("re5", reorder=reordered, path=path)
    assert [e["name"] for e in out["strategies"]] == reordered
    with pytest.raises(ValueError):
        S.handle("re5", reorder=names[:-1], path=path)            # wrong length
    with pytest.raises(ValueError):
        S.handle("re5", reorder=["x"] * len(names), path=path)    # not a permutation


def test_reset_restores_defaults(path):
    S.handle("re5", {"mines": {"enabled": False, "intensity": 0.1}}, path=path)
    out = S.handle("re5", reset=["mines"], path=path)
    mines = next(e for e in out["strategies"] if e["name"] == "mines")
    assert mines["enabled"] is True and mines["intensity"] == 0.5
    S.handle("re5", {"mines": {"enabled": False}, "combo": {"intensity": 0.9}}, path=path)
    out = S.handle("re5", reset=True, path=path)
    assert all(e["enabled"] is True and e["intensity"] == 0.5 for e in out["strategies"])


def test_apply_saved_returns_the_stack_for_the_bots(path):
    S.handle("re6", {"taunts": {"enabled": False, "intensity": 0.9},
                     "survive": {"intensity": 1.0}}, path=path)
    applied = S.apply_saved("re6", path)
    assert applied["taunts"] == {"enabled": False, "intensity": 0.9, "order": 12}
    assert applied["survive"]["intensity"] == 1.0
    assert applied["survive"]["order"] == 0


def test_status_survives_a_bad_file(path):
    path.write_text("{not json", encoding="utf-8")
    st = S.status("re5", path)
    assert len(st["strategies"]) == len(S.STRATEGIES["re5"])

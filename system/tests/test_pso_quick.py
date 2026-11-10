"""gbox.pso_quick: the Select+L1+R1 randomizer, against a model shop (no emulator)."""
import pytest

from gbox import pso_quick as Q

ROWS = [
    {"code": "000100", "name": "Saber", "rare": False},
    {"code": "000A00", "name": "Flowen's Sword", "rare": True},
    {"code": "000B00", "name": "Last Survivor", "rare": True},
    {"code": "010100", "name": "Frame", "rare": True},
    {"code": "010200", "name": "Barrier", "rare": True},
    {"code": "010300", "name": "Unit", "rare": True},          # not an equippable code prefix
    {"code": "02AB00", "name": "Monomate", "rare": True},      # 02 is armour-code range in this catalog
]


class Shop:
    def __init__(self, refuse_equip=(), refuse_give=()):
        self.refuse_equip = set(refuse_equip)
        self.refuse_give = set(refuse_give)
        self.given, self.equipped = [], []

    def give(self, code):
        if code in self.refuse_give:
            raise ValueError("inventory full")
        self.given.append(code)
        return {"verified": True, "ids": [0x00F00000 + len(self.given)]}

    def equip_id(self, item_id):
        code = self.given[item_id - 0x00F00001]
        if code in self.refuse_equip:
            return False
        self.equipped.append(code)
        return True


def test_candidates_keep_only_equippable_rares():
    pool = Q.candidates(ROWS)
    codes = [r["code"] for r in pool]
    assert "000100" not in codes          # not rare
    assert "010300" not in codes          # not an equippable prefix
    assert codes == ["000A00", "000B00", "010100", "010200", "02AB00"]


def test_randomize_equipment_gives_and_equips_the_picks():
    shop = Shop()
    out = Q.randomize_equipment(shop, ROWS, count=2, rng=__import__("random").Random(7))
    assert out["ok"] is True and len(out["given"]) == 2 and len(out["equipped"]) == 2
    assert out["refused"] == []
    assert all(g["code"] in [r["code"] for r in Q.candidates(ROWS)] for g in out["given"])


def test_a_refused_equip_is_reported_not_raised():
    shop = Shop(refuse_equip={"000A00"})
    out = Q.randomize_equipment(shop, ROWS, count=1, rng=__import__("random").Random(1))
    # the one pick may or may not be the refused code; either way nothing raises and the report is consistent
    assert out["ok"] is True
    if out["refused"]:
        assert out["refused"][0]["why"] == "the game refused to equip it"
        assert out["equipped"] == []


def test_a_refused_give_is_reported_not_raised():
    shop = Shop(refuse_give={"000A00", "000B00", "010100", "010200", "02AB00"})
    out = Q.randomize_equipment(shop, ROWS, count=2, rng=__import__("random").Random(3))
    assert out["ok"] is False and out["given"] == []
    assert len(out["refused"]) == 2


def test_an_empty_catalog_says_why():
    out = Q.randomize_equipment(Shop(), [], count=4)
    assert out["ok"] is False and "no rare items" in out["why"]


def test_local_rows_reads_a_list_and_tolerates_a_missing_file(tmp_path):
    good = tmp_path / "rows.json"
    good.write_text('[{"code": "000A00", "rare": true}]')
    assert Q.local_rows(good) == [{"code": "000A00", "rare": True}]
    assert Q.local_rows(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert Q.local_rows(bad) == []


def test_chord_action_never_raises(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no adapter")

    monkeypatch.setattr("gbox.pso_gc_extras.Extras", Boom)
    out = Q.chord_action("sid", object())
    assert out["ok"] is False and "no adapter" in out["why"]

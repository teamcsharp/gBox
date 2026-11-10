"""#9344 (docs/research/mercs-enemy-aim-heights.md, written by Hermes; its rows re-measured from the RomFS on lilspark
2026-11-10): the measured bodies of the classes that stand apart from a man (re5_switch / re6_switch MEASURED,
combat.measured / combat.differs); the crawlers and dogs stay estimates (not determined)."""
import json
from pathlib import Path

from gbox.mercs.core import combat as C
from gbox.mercs.titles import re5_switch as R5
from gbox.mercs.titles import re6_switch as R6

DOCS = Path(__file__).resolve().parents[1] / "docs" / "research"


def doc(name):
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


# --- #9344: the bodies -------------------------------------------------------------------------------------------------
def standing(title):
    return R5.HUMAN if title == "RE5" else C.Body(R6.HEAD_H, R6.CHEST_H, R6.KNEE_H, R6.SHOULDER_H, R6.BODY_R)


def test_the_measured_rows_that_differ_from_a_man_are_exactly_the_titles_measured_bodies():
    rows = doc("mercs-enemy-aim-heights.json")
    for title, module in (("RE5", R5), ("RE6", R6)):
        man = standing(title)
        picked = set()
        for cls, row in rows[title].items():
            if row["status"] != "measured":
                assert cls not in module.MEASURED, (title, cls, "not determined: no measured body")
                continue
            b = C.measured(row["head"], row["chest"], row["knee"], row["shoulder"], row["radius"], man.r)
            if C.differs(b, man):
                picked.add(cls)
                assert module.MEASURED[cls] == b, (title, cls)
        assert picked == set(module.MEASURED), title
    assert set(R5.MEASURED) == {"uEm34"} and set(R6.MEASURED) == {"uEm4800", "uEm4700"}


def test_the_bodies_aim_the_big_ones_at_their_own_height_and_the_rest_as_before(monkeypatch):
    reaper, majini, licker = R5.body({"class": "uEm34"}), R5.body({"class": "uEm10"}), R5.body({"class": "uEm32"})
    assert reaper.head == 257.5 and reaper.chest == 205.5 and reaper.r == R5.BODY_R, "the joints' 29 cm: BODY_R"
    assert majini is R5.HUMAN and licker is C.KIND_BODIES["crawler"], "a Majini and the not-determined crawler"
    assert R5.combat_profile().body({"class": "uEm34"}) == reaper
    ogroman, raskl, javo = (R6.body({"class": c}) for c in ("uEm4800", "uEm4700", "uEm1000"))
    assert ogroman.head == 962.5 and ogroman.r == 174.7 and raskl.head == 202.5 and raskl.r == R6.BODY_R
    assert javo == standing("RE6") and R6.combat_profile().body({"class": "uEm4800"}) == ogroman
    assert R6.aim_point({"class": "uEm4800", "pos": (0.0, 0.0, 0.0)}, (0.0, 0.0, 500.0))[1] == 687.8
    monkeypatch.setattr(R5, "MEASURED_BODIES", False)
    monkeypatch.setattr(R6, "MEASURED_BODIES", False)
    assert R5.body({"class": "uEm34"}) is R5.HUMAN and R6.body({"class": "uEm4800"}) == standing("RE6")


def test_the_crawlers_and_dogs_are_not_determined_so_their_estimates_stand():
    rows = doc("mercs-enemy-aim-heights.json")
    for cls in ("uEm32", "uEm0b"):
        assert rows["RE5"][cls]["status"] == "not determined" and rows["RE5"][cls]["head"] == "not determined"
    assert R5.LOW_BODIES["uEm32"] is C.KIND_BODIES["crawler"] and R5.LOW_BODIES["uEm0b"] is C.KIND_BODIES["dog"]
    assert rows["RE6"]["uEm5700"]["status"] == "not determined" and "uEm5700" not in R6.body_classes()

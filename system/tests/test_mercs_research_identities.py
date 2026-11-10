"""#9343 re6-switch-enemy-identities (RE6's names and levels) and #9345 re4-switch-mercs-spawns (RE4's set lists by
stage, enemy_identity.RE4_SET_LISTS, and the census unit's key by its health: re4_unit_key - the Switch unit's +0x3CE
is not the list's type), as gbox/mercs/enemy_identity.py carries them. Both written by Hermes, checked against the
RomFS on lilspark 2026-11-10 (the cited archive entries, the message strings, the ESL rows and hashes)."""
import json
from pathlib import Path

from gbox.mercs import enemy_identity as EI
from gbox.mercs.core import combat as C

DOCS = Path(__file__).resolve().parents[1] / "docs" / "research"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def doc(name):
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


# --- #9343: RE6's names -------------------------------------------------------------------------------------------------
NAME_AS = {"Rasklapanje (torso part)": "Rasklapanje (torso)", "Rasklapanje (hand part)": "Rasklapanje (hand)"}


def test_every_class_the_doc_settles_carries_its_name_and_level_and_the_rest_stay_as_they_were():
    rows = doc("re6-switch-enemy-identities.json")
    for cls, row in rows.items():
        e = EI.identity(EI.RE6, cls)
        assert e is not None, cls
        if row["level"] in ("verified", "matched"):
            assert e["level"] == row["level"] and e["name"] == NAME_AS.get(row["name"], row["name"]), cls
            assert "#9343" in e["evidence"], cls
        else:
            assert not e["confirmed"], cls                     # not determined: the old, unconfirmed row
    assert set(rows) - {"uEm2010", "uEm2230", "uEm3320", "uEm4100"} == {
        c for c, r in rows.items() if r["level"] in ("verified", "matched")}


def test_re6_tiers_keep_the_bosses_first():
    boss = {c for c, e in EI.TABLE[EI.RE6].items() if e["tier"] == "boss"}
    assert {"uEm3200", "uEm3300", "uEm3301", "uEm3320", "uEm4300", "uEm4800"} <= boss
    assert EI.tier(EI.RE6, "uEm3301") == EI.tier(EI.RE6, "uEm3300") == "boss", "the same archive: the same enemy"
    assert EI.tier(EI.RE6, "uEm1370") == "dangerous" and EI.name(EI.RE6, "uEm1370") == "Chrysalid"
    assert EI.name(EI.RE6, "uEm2300") == "Telo-Eksplozija" and EI.tier(EI.RE6, "uEm2300") == "dangerous"
    assert EI.tier(EI.RE6, "uEm5500") == "dangerous" and EI.name(EI.RE6, "uEm5500") == "Shrieker"
    assert EI.tier(EI.RE6, "uEm9906") == "harmless" and EI.tier(EI.RE6, "uEm5700") == "normal"
    assert C.identity_tier(EI.RE6)({"class": "uEm3301"}) == "boss", "the fight's scorer reads it"


# --- #9345: RE4's set lists and the census --------------------------------------------------------------------------------
def test_the_set_lists_are_the_docs_rows_and_re4_key_names_each_as_the_doc():
    rows = doc("re4-switch-mercs-spawns.json")
    for stage, group in rows.items():
        mine = {(r["type"], r["hp"]): r["identity"] for r in group}
        assert EI.RE4_SET_LISTS[stage] == mine, stage
        for r in group:
            assert EI.re4_key(r["type"], r["hp"], r["pack"]) == r["identity"], (stage, r)
    assert sum(r["count"] for r in rows["Village"]) == 130 and sum(r["count"] for r in rows["Castle"]) == 117
    ganado = sum(r["count"] for r in rows["Village"] if r["identity"] == "ganado")
    zealot = sum(r["count"] for r in rows["Castle"] if r["identity"] == "zealot")
    assert (ganado, zealot) == (118, 112) and "118 placements" in EI.identity(EI.RE4, "ganado")["evidence"] \
        and "112 placements" in EI.identity(EI.RE4, "zealot")["evidence"], "the doc's corrections"


def test_a_census_unit_is_named_by_its_health_in_its_stage_not_by_its_state_byte():
    unit = lambda hp, t=0, **kw: {"class": 0xAE7050, "type": t, "hp_max": hp, "hp": hp, **kw}   # noqa: E731
    assert EI.class_of(EI.RE4, unit(1000)) is None, "1000: a zealot, a soldier or a dog - not Colmillos by a 0"
    assert EI.resolve(EI.RE4, unit(1000))["tier"] == "normal"
    assert EI.resolve(EI.RE4, unit(1000), stage="Base")["cls"] == "militia"
    assert EI.class_of(EI.RE4, unit(1000, stage="Village")) == "colmillos"
    assert EI.class_of(EI.RE4, unit(2000)) == "jj" and EI.class_of(EI.RE4, unit(1400)) == "ganado"
    assert EI.class_of(EI.RE4, unit(6500)) is None and EI.resolve(EI.RE4, unit(6500))["tier"] == "boss"
    assert EI.class_of(EI.RE4, unit(6500, 12)) == "bella", "a type byte that is a row with that health settles it"
    assert EI.class_of(EI.RE4, unit(400, 22)) is None, "0x16, the AI state #9345 found written there: no row"
    assert EI.class_of(EI.RE4, unit(2500, stage="r402")) is None and EI.class_of(EI.RE4, unit(2600)) == "garrador"
    assert EI.class_of(EI.RE4, {"type": 22, "hp_max": 3500}) == "super_salvador", "a set list's own type: re4_key"


def test_the_live_census_fixture_reads_zero_in_the_type_byte():
    raw = json.loads((FIXTURES / "re4sw_units_live.json").read_text(encoding="utf-8"))["objects"]
    ganados = {k: bytes.fromhex(v["hex"]) for k, v in raw.items() if k.startswith("ganado")}
    assert ganados and all(b[0x3CE] == 0 for b in ganados.values()), "#9345: +0x3CE is not the list's type"
    hp = {k: int.from_bytes(b[0x3C4:0x3C6], "little") for k, b in ganados.items()}
    assert EI.class_of(EI.RE4, {"class": 0xAE7050, "type": 0, "hp_max": hp["ganado_22"]}) == "super_salvador"

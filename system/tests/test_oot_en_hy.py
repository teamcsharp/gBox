"""En_Hy (Market / Kakariko townsfolk) as one compound OoT cast slot: eight body objects, sixteen head lists, the same
new model appended at the same offset in every object (gbox.oot_cast.compound_spec + gbox.oot_swap.write_group)."""
import json
import struct
from types import SimpleNamespace

import pytest

from gbox import characters as C, oot_cast as OC, oot_swap as SW, oot_writer as OW
from tests.test_oot_cast import DEKU, LIMBS, OOT, SA, _donor, humanoid_object, synthetic_rom

SKEL = 0x1000
HEADS = (0x1800, 0x1840)                                 # two head lists per object in the synthetic objects


def _obj(limbs_ok: bool = True) -> bytes:
    d = bytearray(humanoid_object(SKEL, 0x2000))
    old_head = OW.skeleton(bytes(d), SKEL)["limbs"][14]["dls"][0]
    for h in HEADS:                                       # an old head list: a branch to the old head limb's list
        d[h:h + 8] = OW._w(0xDE010000, old_head)
    if not limbs_ok:
        d[SKEL + 4] = len(LIMBS) - 1
    return bytes(d)


@pytest.fixture()
def en_hy(monkeypatch):
    g = dict(SW.GROUPS[("En_Hy", SW.OBJ_AOB)])
    g["skels"] = [(o, SKEL) for o in SW.EN_HY_OBJECTS]
    g["head_dls"] = [(o, h) for o in SW.EN_HY_OBJECTS for h in HEADS]
    monkeypatch.setitem(SW.GROUPS, ("En_Hy", SW.OBJ_AOB), g)
    monkeypatch.setitem(OC.BY_SLOT, "hylian_townsfolk", {**OC.BY_SLOT["hylian_townsfolk"], "skel": SKEL})
    return g


def test_catalogue_offers_every_townsperson_as_one_slot():
    c = OC.BY_SLOT["hylian_townsfolk"]
    assert not c.get("refuse") and c["group"] == ("En_Hy", "object_aob") and c["actors"] == ["En_Hy"]
    g = SW.GROUPS[("En_Hy", SW.OBJ_AOB)]
    assert g["compound"] and len(g["objects"]) == 8 and len(g["head_dls"]) == 16 and g["head_limb"] == 14
    assert {OC.object_id(n) for n in ["object_aob"] + c["objects_also"]} == set(g["objects"])
    assert {o for o, _ in g["head_dls"]} <= set(g["objects"]) and dict(g["skels"])[SW.OBJ_COB] == 0x21F8
    row = {r["slot"]: r for r in OC.cast_slots()}["hylian_townsfolk"]
    assert row.get("status") is None and row["mode"] == "retarget"


def test_compound_spec_checks_every_skeleton_and_head(en_hy):
    rom = OW.Rom(synthetic_rom({o: _obj() for o in SW.EN_HY_OBJECTS}))
    sp = OC.slot_spec(rom, "hylian_townsfolk")
    assert sp["objects"] == list(SW.EN_HY_OBJECTS) and sp["regions"] == [] and len(sp["group"]["skels"]) == 8
    bad = OW.Rom(synthetic_rom({o: _obj(o != SW.OBJ_BJI) for o in SW.EN_HY_OBJECTS}))
    with pytest.raises(ValueError, match="limbs"):
        OC.slot_spec(bad, "hylian_townsfolk")


def test_build_cast_writes_every_townsfolk_object(tmp_path, monkeypatch, en_hy):
    monkeypatch.setattr(C, "_blender", lambda cfg: None)
    data = synthetic_rom({SA: humanoid_object(0xB1A0, 0xB1B0, textured=True),
                          DEKU: humanoid_object(0x3268, 0x3278, flex=False), **{o: _obj() for o in SW.EN_HY_OBJECTS}})
    meta = _donor(tmp_path, data)
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    r = SW.build_cast(cfg, OOT, [("hylian_townsfolk", meta)], "townsfolk", root=tmp_path / "lib", rom_data=data)
    row = r["slots"]["hylian_townsfolk"]
    assert r["mod"] == "townsfolk" and row["status"] == "built", r
    img = tmp_path / "cache" / "mods" / OOT["game_id"] / "townsfolk"
    out = (img / json.loads((img / ".gbox-mod.json").read_text())["image"]).read_bytes()
    new, old = OW.Rom(out), OW.Rom(data)
    limb_dls = None
    for o in SW.EN_HY_OBJECTS:
        obj = new.object(o)
        assert len(obj) > len(old.object(o))                          # the new model appended to every object
        sk = OW.skeleton(obj, SKEL)
        dls = [lb["dls"] for lb in sk["limbs"]]
        assert limb_dls in (None, dls)                                # the same offsets in all eight objects
        limb_dls = dls
        assert not OC.check_object(obj, SKEL, {4: new.object(OW.OBJECT_GAMEPLAY_KEEP)})
        head = dls[14][0]
        for h in HEADS:                                               # every head list now draws the new head
            assert obj[h:h + 8] == OW._w(0xDE010000, head)

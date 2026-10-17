"""`zelda` op=catalog (#212, the Equip screen): the game's item table grouped for the card, which items can go on a button,
and the live save values when a save is loaded. Offline, on dict-backed fake adapters (SNES WRAM for A Link to the Past,
zeroed N64 RDRAM for Ocarina of Time with no save loaded)."""
import pytest

from gbox import agent, zelda_tool

ALTTP = "The Legend of Zelda: A Link to the Past (USA)"
OOT = "Legend of Zelda, The: Ocarina of Time (USA)"


class FakeSNES:
    def __init__(self):
        self.mem = {}

    def read_memory(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def write_memory(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b


class ZeroN64:
    def read_memory(self, a, n):
        return bytes(n)


def _items(r):
    return {i["name"]: i for i in r["catalog"]["items"]}


@pytest.mark.parametrize("op", ["catalog", "screen", "equip_screen", "item_screen", "Equip Screen"])
def test_catalog_needs_no_gameplay_and_groups_the_table(op):
    r = zelda_tool.run(FakeSNES(), ALTTP, "snes", op)
    assert r["op"] == "catalog" and r["game"] == "A Link to the Past"
    assert r["state"] is None and "live values unavailable" in r["note"]
    cat, it = r["catalog"], _items(r)
    assert cat["groups"] == ["inventory", "equipment", "upgrades"] and cat["buttons"] == ["y"] and cat["default_button"] == "y"
    assert cat["unrestrict"] and cat["all_items"] and cat["hearts"] and cat["rupees"]
    assert it["hookshot"] == {"name": "hookshot", "group": "inventory", "equip": "button", "count": None}
    assert it["bombs"]["equip"] == "button" and it["bombs"]["count"] == 10
    assert it["master sword"]["group"] == "equipment" and it["master sword"]["equip"] == "worn"
    assert it["pegasus boots"]["group"] == "equipment" and it["moon pearl"]["group"] == "equipment"
    assert it["bomb upgrade"]["group"] == "upgrades" and it["bomb upgrade"]["equip"] is None
    assert it["all pendants"]["group"] == "upgrades" and it["half magic"]["group"] == "upgrades"
    assert it["magic powder"]["group"] == "inventory", "magic items are not magic upgrades"
    assert it["arrows"]["equip"] is None


def test_catalog_adds_the_live_values_once_a_save_is_loaded():
    ad = FakeSNES()
    ad.mem[0x7E0010] = 0x07                                   # main module: dungeon
    ad.mem[0x7EF342] = 1                                      # hookshot owned
    ad.mem[0x7E0202] = 3                                      # Y item = hookshot (menu index 3)
    ad.mem[0x7EF36C] = 24                                     # 3 heart containers
    ad.mem[0x7EF36D] = 16                                     # 2 hearts left
    ad.mem[0x7EF360] = 42
    r = zelda_tool.run(ad, ALTTP, "snes", "catalog")
    assert "note" not in r
    assert "hookshot" in r["state"]["items"] and r["state"]["buttons"] == {"y": "hookshot"}
    assert r["state"]["hearts"] == 2.0 and r["state"]["max_hearts"] == 3 and r["state"]["rupees"] == 42
    assert "changes" not in r, "catalog reads only"


def test_catalog_on_ocarina_of_time_without_a_save():
    r = zelda_tool.run(ZeroN64(), OOT, "n64", "catalog")
    assert r["state"] is None and "no OoT save" in r["note"]
    cat, it = r["catalog"], _items(r)
    assert cat["buttons"] == ["b", "c-left", "c-down", "c-right"] and cat["default_button"] == "c-left"
    assert it["bow"] == {"name": "bow", "group": "inventory", "equip": "button", "count": 30}
    assert it["bottle"]["equip"] == "button" and it["weird egg"]["equip"] == "button"
    assert it["kokiri tunic"]["group"] == "equipment" and it["kokiri tunic"]["equip"] == "worn"
    assert it["master sword"]["equip"] == "worn" and it["hover boots"]["equip"] == "worn"
    assert it["giants wallet"]["group"] == "upgrades" and it["all songs"]["group"] == "upgrades" and it["magic"]["group"] == "upgrades"
    assert it["giants wallet"]["equip"] is None
    groups = {i["group"] for i in cat["items"]}
    assert groups == {"inventory", "equipment", "upgrades"}


def test_every_zelda_table_builds_a_catalog_with_only_known_equip_kinds():
    for key, g in zelda_tool.GAMES.items():
        for name, sp in g["items"].items():
            group = zelda_tool.catalog_group(name, sp)
            assert group in zelda_tool.CATALOG_GROUPS, (key, name)
            assert zelda_tool.catalog_equip(g, sp, group) in ("button", "worn", None), (key, name)
        if g.get("equip"):
            assert any(zelda_tool.catalog_equip(g, sp, zelda_tool.catalog_group(n, sp)) for n, sp in g["items"].items()), key
    z2 = zelda_tool.GAMES["z2"]
    assert all(zelda_tool.catalog_equip(z2, sp, zelda_tool.catalog_group(n, sp)) is None for n, sp in z2["items"].items()), "Zelda II has no item buttons"


def test_agent_turns_the_catalog_into_the_equip_card_and_slims_the_model_view():
    r = zelda_tool.run(FakeSNES(), ALTTP, "snes", "catalog")
    out = agent.zelda_equip_card(r, "pc-1")
    card = out["_cards"]
    assert card["kind"] == "equip" and card["session_id"] == "pc-1" and card["game"] == "A Link to the Past"
    assert card["items"] == r["catalog"]["items"] and card["catalog"]["buttons"] == ["y"] and card["state"] is None
    assert out["catalog"]["items"] == [i["name"] for i in r["catalog"]["items"]]
    assert "items" in out["catalog"] and isinstance(out["catalog"]["items"][0], str)
    assert "Equip screen card" in out["shown"] and out["op"] == "catalog"

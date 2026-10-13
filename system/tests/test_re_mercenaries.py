"""#511 / #512 / #1104: Mercenaries mods across the owned Resident Evils.
RE4 GameCube/Wii (re_mods: combo_time, grenade_safe, punch, loadout amounts, address table) on a fake Dolphin memory,
RE5 Gold PS3 (re5: save-file unlock with the published Game Genie offsets + checksum) on a fake RPCS3 folder, and the
agent routing for the operator's phrasings."""
import random
import struct

import pytest

from gbox import agent, re5_tool as R5, re_games as R, re_mods_tool as T
from gbox.registry import Unsupported


class FakeDolphin:
    """Big-endian GameCube RAM as a sparse byte map (unwritten bytes read 0), like Dolphin's GDB stub serves it."""

    def __init__(self, game_id=b"G4BE08"):
        self.mem, self.writes = {}, []
        self.put(0x80000000, game_id)

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def read_memory(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def write_memory(self, a, data):
        self.writes.append((a, bytes(data)))
        self.put(a, data)
        return {"written": len(data)}


def gc_game(game_id=b"G4BE08"):
    ad = FakeDolphin(game_id)
    ad.put(R.COMBO_WINDOW[0], struct.pack(">I", R.COMBO_WINDOW[1]))      # as the main.dol's .sdata holds it
    for a, orig, _, _ in R.GRENADE_SAFE:
        ad.put(a, bytes.fromhex(orig))
    g = T.RE4(ad)
    g.status = lambda: {}                                                # run() appends it; not under test here
    return ad, g


# ------------------------------------------------------------------------------------------- address table

def test_every_new_address_has_a_source_and_is_not_live_checked_yet():
    assert set(R.MERC_ADDRESS_TABLE) == {"G4BE08", "RB4P08"}
    for gid, entries in R.MERC_ADDRESS_TABLE.items():
        for name, e in entries.items():
            assert e["source"] and e["what"] and e["confidence"], (gid, name)
            assert e["live_checked"] is False, (gid, name)
    t = R.address_table(b"G4BE08")
    assert t["COMBO_WINDOW"]["address"] == "0x802B17F0" and "0401EF40 60000000" in t["COMBO_WINDOW"]["source"]


def test_unknown_releases_are_refused():
    with pytest.raises(KeyError):
        R.address_table("GXXE08")
    with pytest.raises(Unsupported):
        T.RE4(FakeDolphin(b"G4BP08"))                                    # PAL GameCube: no tables, refused


def test_table_values_are_consistent_with_the_rest_of_the_module():
    # r13 = 0x802B9780 (pG = *(r13-0x7500) = 0x802B2280); the combo window is r13-0x7F90
    assert 0x802B9780 - 0x7500 == R.P_GLOBAL and 0x802B9780 - 0x7F90 == R.COMBO_WINDOW[0]
    # the grenade patch is lwz r3,-0x673C(r13) = *P_PLAYER, the owner explosive_melee's verified cave code uses
    w = int(R.GRENADE_SAFE[0][2], 16)
    assert w >> 26 == 32 and (w >> 21) & 31 == 3 and (w >> 16) & 31 == 13
    assert 0x802B9780 + struct.unpack(">h", struct.pack(">H", w & 0xFFFF))[0] == R.P_PLAYER
    assert "806d98c4" in R.MELEE_CODE["OWNED_GRENADE"][1].hex()
    assert all(o == "38600000" for _, o, _, _ in R.GRENADE_SAFE)      # li r3,0 (owner 0 = hurts everyone)


# ------------------------------------------------------------------------------------------- combo_time (#512)

@pytest.mark.parametrize("factor,frames", [(3, 900), (4, 1200), (1, 300), (0.5, 150)])
def test_combo_time_scales_the_combo_window(factor, frames):
    ad, g = gc_game()
    r = T.run(ad, "combo_time", multiplier=factor, g=g)
    assert r["verified"] and g.m.u32(R.COMBO_WINDOW[0]) == frames
    assert r["combo_window_seconds"] == frames / 30 and r["COMBO_WINDOW"]["live_checked"] is False


def test_combo_time_aliases_and_off_restores_the_game_value():
    ad, g = gc_game()
    assert T.run(ad, "combo bonus time", multiplier=4, g=g)["combo_window_x"] == 4
    r = T.run(ad, "combo_time", on=False, g=g)
    assert r["combo_window_x"] == 1 and g.m.u32(R.COMBO_WINDOW[0]) == 300


def test_combo_time_refuses_a_value_that_is_not_the_window_and_silly_factors():
    ad, g = gc_game()
    ad.put(R.COMBO_WINDOW[0], b"\x7f\xff\xff\xff")
    with pytest.raises(RuntimeError, match="not the combo window"):
        T.combo_time(g, 3)
    with pytest.raises(ValueError):
        T.combo_time(gc_game()[1], 100)


def test_wii_refuses_the_ops_that_are_not_located_there():
    ad, g = gc_game(b"RB4P08")
    for op in ("combo_time", "grenade_safe"):
        with pytest.raises(Unsupported, match="not located in Resident Evil 4: Wii"):
            T.run(ad, op, multiplier=3, g=g)


# ------------------------------------------------------------------------------------------- grenade_safe (#512)

def test_grenade_safe_makes_the_blast_player_owned_and_off_restores():
    ad, g = gc_game()
    r = T.run(ad, "grenades_safe", on=True, g=g)
    assert r["verified"] and T.grenade_safe_state(g) == "on"
    assert all(g.m.rd(a, 4).hex() == "806d98c4" for a, *_ in R.GRENADE_SAFE)
    r = T.run(ad, "grenade_safe", on=False, g=g)
    assert r["verified"] and T.grenade_safe_state(g) == "off"


def test_grenade_safe_refuses_unexpected_code_without_writing():
    ad, g = gc_game()
    ad.put(R.GRENADE_SAFE[1][0], bytes.fromhex("60000000"))
    n = len(ad.writes)
    with pytest.raises(RuntimeError, match="unexpected code"):
        T.grenade_safe(g, True)
    assert len(ad.writes) == n


# ------------------------------------------------------------------------------------------- punch / loadouts

def test_punch_is_a_precise_statement_with_what_to_use_instead():
    ad, g = gc_game()
    r = T.run(ad, "punch enemies", g=g)
    assert r["possible"] is False and "no free punch" in r["statement"] and "context" in r["statement"]
    assert any("explosive_melee" in x for x in r["instead"])


@pytest.mark.parametrize("q,want", [("handgun ammo:200", (0x04, 200)), ("shotgun shells x50", (0x18, 50)),
                                    ("rocket launcher*1", (0x35, 1)), ("0x37", (0x37, None)), ("0x37:5", (0x37, 5)),
                                    ("killer7", (0x2A, None)), ("hand grenade:9", (0x01, 9))])
def test_loadout_entries_take_an_amount(q, want):
    assert T._loadout_entry(q) == want


def test_merc_loadout_writes_one_record_per_item_with_its_amount(monkeypatch):
    ad, g = gc_game()
    ad.put(R.RECS, b"\xfe" + bytes(5))                                   # what install_weapon_code leaves: no records
    monkeypatch.setattr(T, "install_weapon_code", lambda g: None)
    monkeypatch.setattr(T, "weapon_classes", lambda g: {0x37: (0x0E, 0), 0x35: (0x0D, 0), 0x23: (0, 0)})
    r = T.run(ad, "loadout", character="wesker", items=["handcannon", "handcannon ammo:50", "rocket launcher"],
              on=True, g=g)
    recs = T.read_recs(g)
    assert r["verified"] and r["equipped"] == "Handcannon"
    assert (5, 1, 0x37, 0) in recs and (5, 0, 0x1A, 50) in recs and (5, 0, 0x35, 0) in recs
    assert all((5, 2, w, 0) in recs for w in R.MERC_DEFAULT_WEAPONS[5])          # Wesker's own guns removed
    listed = T.run(ad, "merc_loadout_list", g=g)["records"]
    assert {"character": "wesker", "action": "give", "item": "Handcannon Ammo", "id": "0x1A", "amount": 50} in listed


def test_item_ids_and_addresses_ops():
    ad, g = gc_game()
    ids = T.run(ad, "item_ids", g=g)["items"]
    assert {"name": "Handcannon", "id": "0x37", "kind": "weapon"} in ids
    a = T.run(ad, "addresses", g=g)
    assert a["game_id"] == "G4BE08" and "GRENADE_OWNER_A" in a["addresses"] and a["unlock_scope"]["characters"]


# ------------------------------------------------------------------------------------------- RE5 Gold (#1104)

def make_save(tmp_path, serial="BLUS30491", size=0x5000, seed=1):
    rnd = random.Random(seed)
    d = bytearray(rnd.randbytes(size))
    d[0x80:0x120] = bytes(0xA0)                                          # nothing unlocked yet
    struct.pack_into(">I", d, 8, R5.checksum(bytes(d)))
    p = tmp_path / "dev_hdd0" / "home" / "00000001" / "savedata" / f"{serial}-SAVE00" / "DATA0.DAT"
    p.parent.mkdir(parents=True)
    p.write_bytes(bytes(d))
    return p


def test_re5_codes_are_the_published_game_genie_lines():
    assert R5.GG_CODES["bonus_features"][1] == ["200000A4 FFFFFFFF", "200000A8 FFFFFFFF", "200000AC FFFFFFFF"]
    assert R5.parse_code("0000010B 000000FF") == (1, 0x10B, 0xFF)
    assert R5.parse_code("1000010E 0000FFFF") == (2, 0x10E, 0xFFFF)
    assert R5.parse_code("20000091 FFFFFFFF") == (4, 0x91, 0xFFFFFFFF)
    with pytest.raises(ValueError):
        R5.parse_code("4100315A 0000270F")                               # multi-write types are not used here
    for v in R5.VERSIONS.values():
        assert v["live_checked"] is False and "apollo-patches" in v["source"]


def test_re5_unlock_all_patches_every_group_and_keeps_the_checksum(tmp_path):
    p = make_save(tmp_path)
    orig = p.read_bytes()
    r = R5.run(tmp_path, "BLUS30491", "unlock everything")
    s = r["saves"][0]
    assert r["verified"] and all(s["groups"].values()) and set(s["groups"]) == set(R5.DEFAULT_GROUPS)
    new = p.read_bytes()
    assert R5.checksum_ok(new) and new[0xA4:0xB0] == b"\xff" * 12 and new[0x10B] == 0xFF
    assert new[0xE0:0xE8] == orig[0xE0:0xE8]                             # money / points untouched by default
    assert (p.parent / "DATA0.DAT.gbox-backup").read_bytes() == orig
    st = R5.run(tmp_path, "BLUS30491", "status")["saves"][0]
    assert st["checksum_ok"] and st["unlocked"]["bonus_features"] and not st["unlocked"]["points"]
    r = R5.run(tmp_path, "BLUS30491", "unlock_all", on=False)
    assert r["op"] == "revert" and r["verified"] and p.read_bytes() == orig


def test_re5_refuses_a_save_whose_checksum_does_not_follow_the_rule(tmp_path):
    p = make_save(tmp_path)
    d = bytearray(p.read_bytes())
    d[8] ^= 0xFF
    p.write_bytes(bytes(d))
    with pytest.raises(RuntimeError, match="checksum rule"):
        R5.run(tmp_path, "BLUS30491", "unlock_all")
    assert p.read_bytes() == bytes(d) and not (p.parent / "DATA0.DAT.gbox-backup").exists()


def test_re5_refuses_unknown_versions_and_merc_time(tmp_path):
    make_save(tmp_path, serial="BLUS30270")
    with pytest.raises(Unsupported, match="no verified save layout"):
        R5.run(tmp_path, "BLUS30270", "unlock_all")
    for op in ("merc_time", "combo_time", "merc_time_bonus"):
        with pytest.raises(Unsupported, match="no published address"):
            R5.run(tmp_path, "BLUS30491", op)


def test_re5_subset_groups_and_eu_serial(tmp_path):
    p = make_save(tmp_path, serial="BLES00816")
    r = R5.run(tmp_path, "BLES00816", "unlock_all", groups=["files", "points"])
    assert r["verified"] and r["groups"] == ["files", "points"]
    d = p.read_bytes()
    assert d[0x82:0x84] == b"\xff\xff" and d[0xE4:0xE8] == bytes.fromhex("05F5E0FF") and d[0xA4] == 0
    with pytest.raises(ValueError, match="unknown group"):
        R5.run(tmp_path, "BLES00816", "unlock_all", groups=["mercenaries"])


def test_re5_without_a_save_says_how_to_get_one(tmp_path):
    with pytest.raises(RuntimeError, match="start RE5 once"):
        R5.run(tmp_path, "BLUS30491", "unlock_all")


# ------------------------------------------------------------------------------------------- registration + agent

def test_tools_are_registered():
    from gbox import registry, tools
    assert "re5_tool" in tools._load_tool_modules.__defaults__[0] and "re5" in registry.REGISTRY
    inp = registry.REGISTRY["re5"].In.model_validate({"op": "unlock_all"})
    assert inp.on and inp.groups == [] and inp.session_id == ""


def _spec(name):
    return next(t["function"] for t in agent.tool_specs() if t["function"]["name"] == name)


def test_agent_offers_the_ops_and_routes_the_phrasings():
    d = _spec("re_mods")["description"]
    assert "combo_time multiplier=N" in d and "grenade_safe" in d and "punch" in d and "name:amount" in d
    assert "unlock all secret / hidden content" in _spec("re5")["description"].lower()
    assert "re5" in agent.WORKER_TOOLS and "re5" in agent.MODIFIES
    assert agent._modifies_game("re5", {"op": "unlock_all"}) and not agent._modifies_game("re5", {"op": "status"})
    block = agent.SYSTEM[agent.SYSTEM.index("- Resident Evil Mercenaries / unlock asks"):][:1400]
    for phrase in ("Triple / quadruple the combo", "op=combo_time multiplier=3|4", "Grenades don't hurt me",
                   "op=grenade_safe on=true", "Punch enemies", "op=punch", "re5 op=unlock_all", "secret / hidden",
                   "op=merc_loadout", "name:amount"):
        assert phrase in block, phrase


def test_agent_re5_dispatches_to_the_session_worker_or_the_windows_node():
    a = object.__new__(agent.Agent)
    sent = []

    def job(tool, inp, node=None, limit=900, worker=None):
        sent.append((tool, inp, node, worker))
        return {"state": "succeeded", "output": {"result": {"verified": True}}}
    a._job = job
    assert a.re5("unlock_all", session_id="nuc123-abc")["verified"]
    assert sent[-1] == ("re5", {"op": "unlock_all", "session_id": "nuc123-abc", "on": True, "groups": [], "serial": ""},
                        None, "nuc123")
    a.re5("status")
    assert sent[-1][2] == "windows" and sent[-1][3] is None

"""Mario Kart 64 items (#226: 'give me infinite red shells'): item ids, the per-player slot addresses of the USA ROM,
the always / infinite holds, and the agent routing. A fake N64 adapter serves RDRAM as 32-bit little-endian words like
RetroArch's ParaLLEl / mupen cores (gbox.oot._rd/_wr un-swap it), so the bytes checked here are the console's own."""
import struct

import pytest

from gbox import agent, cheats, mk64_items as mk

TITLE = "Mario Kart 64 (USA)"

# the published USA GameShark "Weapon Modifier" pairs (almarsguides.com P1/P2-mode and P3/P4-mode lists): item byte, icon byte
GS_USA = {("1p2p", 1): (0x80165F5D, 0x80165F8A), ("1p2p", 2): (0x8016603D, 0x8016606A),
          ("3p4p", 1): (0x8016611D, 0x8016614A), ("3p4p", 2): (0x801661FD, 0x8016622A),
          ("3p4p", 3): (0x801662DD, 0x8016630A), ("3p4p", 4): (0x801663BD, 0x801663EA)}


class FakeN64:
    """RDRAM the way RetroArch's N64 cores expose it: a flat byte store of host-endian 32-bit words, so the console's
    byte at address a lives at a ^ 3 (gbox/cheats.py, gbox/oot.py). read_memory / write_memory are the adapter's raw
    accesses; put / get speak console (big-endian) addresses like the game does."""

    def __init__(self):
        self.phys, self.writes = {}, []

    def put(self, a, data):
        for i, b in enumerate(data):
            self.phys[(a + i) ^ 3] = b

    def get(self, a, n):
        return bytes(self.phys.get((a + i) ^ 3, 0) for i in range(n))

    def read_memory(self, a, n):
        return bytes(self.phys.get(a + i, 0) for i in range(n))

    def write_memory(self, a, data):
        self.writes.append((a, bytes(data)))
        for i, b in enumerate(data):
            self.phys[a + i] = b
        return {"written": len(data)}


def hold_item(ad, s, item):
    """What the game does: currentItem (s16) and the HUD icon of a window object."""
    ad.put(s["item"], struct.pack(">h", item))
    ad.put(s["icon"], bytes([item]))


@pytest.fixture(autouse=True)
def no_leftover_holds():
    yield
    for h in list(mk.HOLDS.values()):
        h["stop"].set()
    mk.HOLDS.clear()


# ---------------------------------------------------------------------------------------------------- item ids

def test_item_ids_are_the_decomp_enum():
    assert mk.ITEMS[5] == "red shell" and mk.DECOMP_NAMES[5] == "ITEM_RED_SHELL"
    assert mk.ITEMS[6] == "triple red shells" and mk.DECOMP_NAMES[6] == "ITEM_TRIPLE_RED_SHELL"
    assert mk.ITEMS[7] == "blue shell" and mk.DECOMP_NAMES[7] == "ITEM_BLUE_SPINY_SHELL"
    assert mk.ITEMS[8] == "lightning" and mk.DECOMP_NAMES[8] == "ITEM_THUNDERBOLT"
    assert mk.ITEMS[10] == "star" and mk.ITEMS[11] == "boo" and mk.ITEMS[15] == "super mushroom"
    assert sorted(mk.ITEMS) == list(range(16)) and set(mk.ALIASES.values()) == set(range(16))


@pytest.mark.parametrize("asked,item_id", [
    ("red shell", 5), ("red shells", 5), ("infinite red shells", 5), ("a red shell please", 5), ("Red Shell!", 5),
    ("triple red shells", 6), ("3 red shells", 6), ("three red shells", 6),
    ("blue shell", 7), ("spiny shell", 7), ("blue shells", 7),
    ("lightning", 8), ("lightning bolt", 8), ("thunderbolt", 8),
    ("star", 10), ("invincibility", 10), ("boo", 11), ("ghost", 11),
    ("mushroom", 12), ("double mushrooms", 13), ("triple mushrooms", 14), ("golden mushroom", 15), ("super mushroom", 15),
    ("banana", 1), ("banana bunch", 2), ("green shell", 3), ("triple green shells", 4), ("fake item box", 9), ("fake box", 9),
    ("5", 5), ("nothing", 0),
])
def test_item_names_resolve(asked, item_id):
    assert mk.resolve_item(asked) == (item_id, mk.ITEMS[item_id])


def test_unknown_item_lists_the_names():
    with pytest.raises(ValueError, match="red shell.*blue shell.*super mushroom"):
        mk.resolve_item("portable chainsaw")
    with pytest.raises(ValueError, match="item required"):
        mk.resolve_item("")


# ---------------------------------------------------------------------------------------------------- addresses

@pytest.mark.parametrize("split,player", sorted(GS_USA))
def test_usa_slots_match_the_published_gameshark_pairs(split, player):
    gs_item, gs_icon = GS_USA[(split, player)]
    s = mk.slot("us", player, split)
    assert s["item"] + 1 == gs_item, "GameShark byte = low byte of the big-endian s16 currentItem"
    assert s["icon"] == gs_icon
    assert s["item"] == mk.LAYOUTS["us"]["object_list"] + s["object"] * mk.OBJECT_SIZE + mk.O_ITEM
    assert s["icon"] - s["item"] == mk.O_ICON - mk.O_ITEM == 0x2E


def test_window_objects_follow_the_hud_init_order():
    assert [mk.slot("us", p, "1p2p")["object"] for p in (1, 2)] == [3, 4]
    assert [mk.slot("us", p, "3p4p")["object"] for p in (1, 2, 3, 4)] == [5, 6, 7, 8]
    assert mk.slot("us", 2, "1p2p")["item"] - mk.slot("us", 1, "1p2p")["item"] == 0xE0 == mk.OBJECT_SIZE


def test_players_3_and_4_need_the_split_screen_layout():
    with pytest.raises(ValueError, match="split='3p4p'"):
        mk.slot("us", 3, "1p2p")
    with pytest.raises(ValueError, match="player must be 1..4"):
        mk.slot("us", 5, "3p4p")
    with pytest.raises(ValueError, match="split must be"):
        mk.slot("us", 1, "5p")


def test_gameshark_lines_are_the_published_codes():
    assert mk.gameshark("us", 1, "1p2p", 5) == ["80165F5D 0005", "80165F8A 0005"]
    assert mk.gameshark("us", 4, "3p4p", 0x0A) == ["801663BD 000A", "801663EA 000A"]


def test_gbox_cheat_decoder_and_the_module_land_on_the_same_bytes():
    """The cheats tool (op=add '80165F5D 0005') and mario_kart write the same console bytes through the word swap."""
    via_code, via_tool = FakeN64(), FakeN64()
    for line in mk.gameshark("us", 1, "1p2p", 5):
        ops, bad = cheats.decode("n64", line)
        assert not bad
        for kind, a, d in ops:
            assert kind == "w"
            via_code.write_memory(a, d)
    mk.write_slot(via_tool, mk.slot("us", 1, "1p2p"), 5)
    assert via_code.get(0x80165F5D, 1) == via_tool.get(0x80165F5D, 1) == b"\x05"
    assert via_code.get(0x80165F8A, 1) == via_tool.get(0x80165F8A, 1) == b"\x05"
    assert via_tool.get(0x80165F5C, 2) == b"\x00\x05"                 # the whole s16, not just its low byte
    assert via_code.writes[0][0] == 0x80165F5E                        # the core's byte for console 0x80165F5D (a ^ 3)


# ---------------------------------------------------------------------------------------------------- detection

@pytest.mark.parametrize("title,platform,key", [
    ("Mario Kart 64 (USA)", "n64", "us"), ("Mario Kart 64 (U) [!]", "n64", "us"), ("Mario Kart 64", "n64", "us"),
    ("Mario Kart 64 (Europe) (En,Fr,De)", "n64", "eu"), ("Mario Kart 64 (Japan)", "n64", "jp"),
    ("Super Mario 64 (USA)", "n64", None), ("Mario Kart: Double Dash!! (USA)", "gamecube", None),
])
def test_detect(title, platform, key):
    assert mk.detect(title, platform)[0] == key


def test_other_games_and_unmapped_revisions_are_refused_with_the_gap():
    assert "not Mario Kart 64" in mk.run(FakeN64(), "Super Mario 64 (USA)", "n64", "always", item="star")["error"]
    r = mk.run(FakeN64(), "Mario Kart 64 (Europe)", "n64", "always", item="red shell")
    assert "80165FBD" in r["error"] and "unverified" in r["error"]
    assert mk.run(FakeN64(), "Mario Kart 64", "n64", "state")["note"].startswith("no region tag")
    g = mk.run(FakeN64(), "Mario Kart 64 (USA)", "n64", "games")
    assert g["detected"] == "us" and "eu" in g["gaps"] and "init_hud" in " ".join(g["games"]["us"]["sources"])


# ---------------------------------------------------------------------------------------------------- live ops

def test_give_writes_item_and_icon_and_verifies():
    ad = FakeN64()
    r = mk.run(ad, TITLE, "n64", "give", item="blue shell")
    assert r["verified"] and r["item"] == "blue shell" and r["item_id"] == 7 and r["object"] == 3
    assert ad.get(0x80165F5C, 2) == b"\x00\x07" and ad.get(0x80165F8A, 1) == b"\x07"
    assert r["codes"] == ["80165F5D 0007", "80165F8A 0007"] and r["address"] == "0x80165f5c"
    assert not mk.HOLDS                                                   # give is a one-off


def test_state_reads_every_window_and_names_the_item():
    ad = FakeN64()
    hold_item(ad, mk.slot("us", 1, "1p2p"), 10)
    hold_item(ad, mk.slot("us", 3, "3p4p"), 6)
    r = mk.run(ad, TITLE, "n64", "state")
    assert r["players"]["1p2p"]["p1"]["name"] == "star" and r["players"]["1p2p"]["p2"]["item"] == 0
    assert r["players"]["3p4p"]["p3"]["name"] == "triple red shells" and r["holds"] == [] and r["live_checked"] is False


def test_always_tick_refills_the_slot_after_the_game_consumes_the_item():
    ad, s = FakeN64(), mk.slot("us", 1, "1p2p")
    hold = {"mode": "always", "item": 5, "refills": 0}
    assert mk._tick(ad, s, hold) and ad.get(0x80165F5C, 2) == b"\x00\x05" and hold["refills"] == 1
    assert mk._tick(ad, s, hold) and hold["refills"] == 1                 # nothing to do while the item is there
    hold_item(ad, s, 0)                                                   # consume_item(): currentItem = ITEM_NONE
    assert mk._tick(ad, s, hold) and ad.get(0x80165F5C, 2) == b"\x00\x05" and ad.get(0x80165F8A, 1) == b"\x05"
    assert hold["refills"] == 2


def test_infinite_tick_keeps_whatever_was_picked_up():
    ad, s = FakeN64(), mk.slot("us", 2, "1p2p")
    hold = {"mode": "infinite", "item": 0, "refills": 0}
    assert mk._tick(ad, s, hold) and not ad.writes                        # empty slot, nothing remembered yet
    hold_item(ad, s, 10)                                                  # the roulette gives a star
    assert mk._tick(ad, s, hold) and hold["item"] == 10 and not ad.writes
    hold_item(ad, s, 0)                                                   # used it
    assert mk._tick(ad, s, hold) and ad.get(0x8016603C, 2) == b"\x00\x0a" and ad.get(0x8016606A, 1) == b"\x0a"
    hold_item(ad, s, 7)                                                   # later a blue shell replaces it
    mk._tick(ad, s, hold)
    assert hold["item"] == 7


def test_tick_stops_when_the_session_is_gone():
    class Gone:
        def read_memory(self, a, n):
            raise ConnectionError("session ended")
    assert mk._tick(Gone(), mk.slot("us", 1, "1p2p"), {"mode": "always", "item": 5}) is False


def test_hold_loop_forgets_itself_when_the_session_ends():
    ad = FakeN64()
    mk.run(ad, TITLE, "n64", "always", item="star")
    hold = mk.HOLDS[(id(ad), "1p2p", 1)]
    ad.read_memory = lambda a, n: (_ for _ in ()).throw(ConnectionError("session ended"))
    hold["thread"].join(2)
    assert not hold["thread"].is_alive() and not mk.HOLDS


def test_always_starts_a_hold_and_release_stops_it():
    ad = FakeN64()
    r = mk.run(ad, TITLE, "n64", "always", item="infinite red shells")
    assert r["held"] and r["mode"] == "always" and r["item"] == "red shell" and r["verified"]
    assert r["undo"] == "mario_kart op=release player=1" and r["codes"][0] == "80165F5D 0005"
    assert ad.get(0x80165F5C, 2) == b"\x00\x05"
    assert mk.run(ad, TITLE, "n64", "state")["holds"] == [{"player": 1, "split": "1p2p", "mode": "always", "item": "red shell", "refills": 0}]
    hold = mk.HOLDS[(id(ad), "1p2p", 1)]
    hold_item(ad, mk.slot("us", 1, "1p2p"), 0)                            # thrown
    hold["thread"].join(0.01)
    for _ in range(100):                                                  # the hold thread refills within ~50 ms
        if ad.get(0x80165F5C, 2) == b"\x00\x05":
            break
        hold["stop"].wait(0.01)
    assert ad.get(0x80165F5C, 2) == b"\x00\x05"
    r2 = mk.run(ad, TITLE, "n64", "release", player=1)
    assert r2["released"] == [{"player": 1, "split": "1p2p", "mode": "always", "item": "red shell"}]
    assert hold["stop"].is_set() and not mk.HOLDS
    hold["thread"].join(1)
    assert not hold["thread"].is_alive()


def test_infinite_with_an_item_named_is_always_and_always_without_one_is_infinite():
    ad = FakeN64()
    r = mk.run(ad, TITLE, "n64", "infinite", item="triple red shells", player=2)
    assert r["mode"] == "always" and r["item_id"] == 6 and r["player"] == 2 and ad.get(0x8016603C, 2) == b"\x00\x06"
    r = mk.run(ad, TITLE, "n64", "always", player=1)
    assert r["mode"] == "infinite" and r["current"] == "none" and not ad.get(0x80165F5C, 2).strip(b"\x00")
    for vague in ("items", "any item", "whatever I pick up", ""):              # no real item named: keep what is picked up
        assert mk.run(ad, TITLE, "n64", "infinite", item=vague)["mode"] == "infinite"
        assert mk.run(ad, TITLE, "n64", "always", item=vague)["mode"] == "infinite"
    assert {h["player"] for h in mk.run(ad, TITLE, "n64", "state")["holds"]} == {1, 2}
    assert mk.run(ad, TITLE, "n64", "always", player=2, on=False)["released"][0]["player"] == 2
    assert [h["player"] for h in mk.run(ad, TITLE, "n64", "state")["holds"]] == [1]
    assert len(mk.run(ad, TITLE, "n64", "release")["released"]) == 1 and not mk.HOLDS


def test_restarting_a_hold_replaces_the_previous_one():
    ad = FakeN64()
    mk.run(ad, TITLE, "n64", "always", item="star")
    first = mk.HOLDS[(id(ad), "1p2p", 1)]
    mk.run(ad, TITLE, "n64", "always", item="lightning")
    assert first["stop"].is_set() and mk.HOLDS[(id(ad), "1p2p", 1)]["item"] == 8 and len(mk.HOLDS) == 1
    assert ad.get(0x80165F5C, 2) == b"\x00\x08"


def test_split_screen_players_use_their_own_windows():
    ad = FakeN64()
    r = mk.run(ad, TITLE, "n64", "give", item="star", player=4, split="3p4p")
    assert r["object"] == 8 and ad.get(0x801663BC, 2) == b"\x00\x0a" and ad.get(0x801663EA, 1) == b"\x0a"
    assert "split='3p4p'" in str(pytest.raises(ValueError, mk.run, ad, TITLE, "n64", "give", item="star", player=3).value)


def test_op_aliases_and_unknown_ops():
    ad = FakeN64()
    assert mk.run(ad, TITLE, "n64", "list")["op"] == "state"
    assert mk.run(ad, TITLE, "n64", "items")["items"]["red shell"] == {"id": 5, "decomp": "ITEM_RED_SHELL"}
    assert "unknown op" in mk.run(ad, TITLE, "n64", "teleport")["error"]
    assert mk.run(ad, TITLE, "n64", "hold", item="boo")["mode"] == "always"


# ---------------------------------------------------------------------------------------------------- registration + agent

def test_tool_is_registered_with_the_worker():
    from gbox import registry, tools
    assert "mario_kart" in registry.REGISTRY and "mk64_items" in tools._load_tool_modules.__defaults__[0]
    t = registry.REGISTRY["mario_kart"]
    inp = t.In.model_validate({"session_id": "w-1", "op": "always", "item": "red shell"})
    assert (inp.player, inp.split, inp.on) == (1, "1p2p", True)


def _spec(name):
    return next(t["function"] for t in agent.tool_specs() if t["function"]["name"] == name)


def test_agent_offers_the_tool_with_the_items_and_ops():
    desc = _spec("mario_kart")["description"]
    assert "infinite red shells" in desc and "op=always item='red shell'" in desc and "op=infinite" in desc
    assert {"session_id", "op", "item", "player", "split", "on"} <= set(_spec("mario_kart")["parameters"]["properties"])
    assert "mario_kart" in agent.WORKER_TOOLS and "mario_kart" in agent.MODIFIES
    assert agent._modifies_game("mario_kart", {"op": "always"}) and not agent._modifies_game("mario_kart", {"op": "state"})


def test_system_prompt_routes_infinite_red_shells_to_mario_kart():
    line = next(l for l in agent.SYSTEM.splitlines() if l.startswith("- Mario Kart 64 items"))
    assert "infinite red shells" in line and "mario_kart" in line
    block = agent.SYSTEM[agent.SYSTEM.index("- Mario Kart 64 items"):]
    assert 'op=always item="red shell"' in block[:900] and "op=infinite" in block[:900] and "op=release" in block[:900]
    act = next(l for l in agent.SYSTEM.splitlines() if "(0) the game's own tool" in l)
    assert "mario_kart op=always" in act
    assert "mario_kart for Mario Kart 64 items" in agent.SYSTEM


def test_agent_call_dispatches_a_worker_job_on_the_session_worker():
    a = object.__new__(agent.Agent)
    sent = []
    def job(tool, inp, node=None, limit=900, worker=None):
        sent.append((tool, inp, worker))
        return {"state": "succeeded", "output": {"result": {"held": True, "verified": True, "item": "red shell"}}}
    a._job = job
    r = a.mario_kart("worker-abc123", op="always", item="red shell")
    assert r["verified"] and sent == [("mario_kart", {"session_id": "worker-abc123", "op": "always", "item": "red shell",
                                                        "player": 1, "split": "1p2p", "on": True}, "worker")]
    a._job = lambda *_a, **_k: {"state": "failed", "error": "no session", "output": None}
    assert a.mario_kart("worker-abc123", op="release")["error"] == "no session"

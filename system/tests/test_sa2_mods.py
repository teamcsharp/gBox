"""Sonic Adventure 2 (#217: 'skip to the end of any level', 'instant S rank', 'all the emblems'): the per-build address
tables, the finish / rank / emblem ops on a fake console that runs the game's own 100-ring check every frame, the
published CodeBreaker codes, and the agent routing. FakeSA2 serves memory the way gBox's adapters do: Flycast hands back
the SH-4's little-endian bytes, Dolphin the PowerPC's big-endian ones."""
import struct

import pytest

from gbox import agent, cheats, sa2_mods as sa

DC, GC = sa.LAYOUTS["dc_us"], sa.LAYOUTS["gc_us"]
DC_TITLE, GC_TITLE = "Sonic Adventure 2 (USA)", "Sonic Adventure 2 - Battle (USA)"


class FakeSA2:
    """Console memory + one rule of the game: every frame (here: every read) the main loop's mission-2 check runs -
    MissionNum == 1, no 2P, level <= max or == 70, Rings[0] >= 100, LevelCleared == 0 -> AwardWin(0): LevelCleared = 1,
    TimerStopped = 1. Paused (GameState 17) runs no frames."""

    def __init__(self, lay, level=13, mission=0, character=0, state=16):
        self.lay, self.e, self.mem, self.writes, self.frames = lay, lay["endian"], {}, [], 0
        a, sig = lay["signature"]
        self.raw(a, sig)
        if lay.get("disc_id"):
            self.raw(0x80000000, lay["disc_id"])
        self.set("game_state", state)
        self.set("level", level)
        self.set("character", character)
        self.set("mission", mission)
        self.set("rings", 37)
        self.set("perfect_rings", 300)
        self.set("score", 4200)
        self.set("minutes", 1)
        self.set("seconds", 42)
        self.set("frames", 7)
        # rank tables: City Escape (13) + Wild Canyon (16) rows, then the 91 terminator (DC/GC data as in the binaries)
        for mi, base in lay["score_tables"].items():
            rows = [(13, 90, 110, 140, 180), (16, 80, 100, 140, 160), (34, 50, 70, 90, 110), (91, 0, 0, 0, 0)]
            for i, row in enumerate(rows):
                self.raw(base + 10 * i, struct.pack(self.e + "5h", *row))
        for mi, base in lay["time_tables"].items():
            rows = [bytes([13, 2, 30, 2, 0, 1, 40, 1, 20]), bytes([16, 4, 30, 3, 0, 2, 0, 1, 30]), bytes([91] + [0] * 8)]
            for i, row in enumerate(rows):
                self.raw(base + 9 * i, row)

    def raw(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def set(self, name, v):
        a, f = self.lay["fields"][name]
        self.raw(a, struct.pack(self.e + f, v))

    def get(self, name):
        a, f = self.lay["fields"][name]
        return struct.unpack(self.e + f, bytes(self.mem.get(a + i, 0) for i in range(struct.calcsize(f))))[0]

    def frame(self):
        if self.get("game_state") != 16:
            return
        self.frames += 1
        hi, extra = self.lay["ring_finish_levels"]
        lv = self.get("level")
        if (self.get("mission") == 1 and not self.get("two_player") and (lv <= hi or lv == extra)
                and self.get("rings") >= 100 and not self.get("cleared")):
            self.set("cleared", 1)
            self.set("timer_stopped", 1)

    def read_memory(self, a, n):
        self.frame()
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def write_memory(self, a, data):
        self.writes.append((a, bytes(data)))
        self.raw(a, data)
        return {"written": len(data)}


def run(ad, op, title=DC_TITLE, platform="dreamcast", **kw):
    kw.setdefault("timeout_s", 0.5)
    return sa.run(ad, title, platform, op, **kw)


# ---------------------------------------------------------------------------------------------------- addresses

def test_dreamcast_addresses_match_the_published_codebreaker_codes():
    """almarsguides.com SA2 (USA) CodeBreaker list: 0T AAAAAA, T = 0/1/2 = 8/16/32-bit at 0x8C000000 + AAAAAA."""
    f = DC["fields"]
    assert f["lives"] == (0x8C0DB26C, "h")            # Unlimited Lives      010DB26C 00000004
    assert f["rings"] == (0x8C0DB270, "h")            # Max Infinite Rings   010DB270 000003E7
    assert f["score"] == (0x8C0DB294, "i")            # Max Score            020DB294 05F5E0FF
    assert f["level"] == (0x8C24EE64, "h")            # Level Modifier       0024EE64 000000??
    assert f["character"] == (0x8C24EE6C, "i")        # Always Tails         0124EE6C 00000006 (6 = Tails' Cyclone)
    assert sa.CHARACTERS[6] == "Tails (Cyclone)"
    # Stop Timer 01052C18 0009 nops the seconds store of the tick that runs on G = 0x8C0DB20C: the clock is G+0x1B..1D
    assert [f[k][0] - 0x8C0DB20C for k in ("timer_stopped", "minutes", "seconds", "frames", "two_player")] == [0x1A, 0x1B, 0x1C, 0x1D, 0x1E]


def test_gamecube_global_block_is_the_pc_port_layout():
    """sa2-mod-loader SA2Variables.h: TimerMinutes 0x174AFDB, MissionNum 0x174AFE3, CurrentLevelRank 0x174B001,
    Life_Count 0x174B024, RingCount 0x174B028, ScoreP1 0x174B050 - the same offsets from PC 0x174AFC0 / GC 0x801CC168."""
    pc = {"minutes": 0x174AFDB, "mission": 0x174AFE3, "rank": 0x174B001, "lives": 0x174B024, "rings": 0x174B028, "score": 0x174B050}
    for k, a in pc.items():
        assert GC["fields"][k][0] - 0x801CC168 == a - 0x174AFC0, k
    assert GC["fields"]["level"][0] == 0x803B52C0 - 0x7AA0 and GC["fields"]["game_state"][0] == 0x803B52C0 - 0x7AA6
    assert GC["fields"]["character"][0] - GC["fields"]["level"][0] == DC["fields"]["character"][0] - DC["fields"]["level"][0] == 8


def test_emblem_slots_are_the_games_180():
    for lay in (DC, GC):
        slots = sa.emblem_slots(lay)
        assert len(slots) == 180 and len({s["address"] for s in slots}) == 180
        assert sum(s["kind"] == "rank" for s in slots) == 155 and sum("kart" in s["label"] for s in slots) == 3
        assert slots[0]["label"] == "City Escape mission 1" and slots[145]["label"] == "Route 101 mission 1"
    assert sa.emblem_slots(DC)[0]["address"] == 0x8C26A664 + 0x6C + 13 * 0x88
    assert sa.emblem_slots(GC)[0]["address"] == 0x801F2340 + 0x38 + 13 * 0xC4      # PC SaveData.Levels[13].Ranks[0]
    assert DC["fields"]["emblem_count"][0] == 0x8C26A671 and GC["fields"]["emblem_count"][0] == 0x801F234D
    assert len(sa.EMBLEM_STAGES) == 29 and 31 not in sa.EMBLEM_STAGES             # Green Hill is the 180 reward
    assert all(not v["live_checked"] for v in sa.LAYOUTS.values())


def test_codebreaker_lines_decode_onto_the_same_bytes():
    """sonic_adventure_2's CodeBreaker/Gecko equivalents go through the cheats tool's decoder to the same console bytes."""
    lines = sa.codes_for(DC, [(0x8C0DB294, 4, 18000), (0x8C0DB270, 2, 100), (0x8C0DB22E, 1, 1)])
    assert lines == ["020DB294 00004650", "010DB270 00000064", "000DB22E 00000001"]
    ops, bad = cheats.decode("dreamcast", ";".join(lines))
    assert not bad and ops == [("w", 0x8C0DB294, struct.pack("<I", 18000)), ("w", 0x8C0DB270, b"\x64\x00"),
                               ("w", 0x8C0DB22E, b"\x01")]
    # the published codes: Max Score is a 32-bit write, Unlimited Lives a 16-bit one, Level Modifier 8-bit
    ops, bad = cheats.decode("dreamcast", "020DB294 05F5E0FF;010DB26C 00000004;0024EE64 0000000D")
    assert not bad and ops == [("w", 0x8C0DB294, struct.pack("<I", 99999999)), ("w", 0x8C0DB26C, b"\x04\x00"),
                               ("w", 0x8C24EE64, b"\x0d")]
    g = sa.codes_for(GC, [(0x801CC1F8, 4, 18000), (0x801CC1D0, 2, 100), (0x801F234D, 1, 180)])
    assert g == ["041CC1F8 00004650", "021CC1D0 00000064", "001F234D 000000B4"]
    w, bad = cheats.decode_writes(g)
    assert not bad and w == [(0x801CC1F8, struct.pack(">I", 18000)), (0x801CC1D0, b"\x00\x64"), (0x801F234D, b"\xb4")]


# ---------------------------------------------------------------------------------------------------- detection

@pytest.mark.parametrize("title,platform,key", [
    ("Sonic Adventure 2 (USA)", "dreamcast", "dc_us"), ("Sonic Adventure 2", "dreamcast", "dc_us"),
    ("Sonic Adventure 2 - Battle (USA)", "gamecube", "gc_us"), ("Sonic Adventure 2 Battle", "", "gc_us"),
    ("Sonic Adventure 2 (Europe)", "dreamcast", "dc_eu"), ("Sonic Adventure 2 (Japan)", "dreamcast", "dc_jp"),
    ("Sonic Adventure 2 - Battle (Europe)", "gamecube", "gc_eu"),
    ("Sonic Adventure (USA)", "dreamcast", None), ("Sonic Adventure 2", "pc", None), ("Mario Kart 64", "n64", None),
])
def test_detect(title, platform, key):
    assert sa.detect(title, platform)[0] == key


def test_unknown_regions_other_games_and_other_builds_are_refused():
    assert "not Sonic Adventure 2" in run(FakeSA2(DC), "finish_level", "Sonic Adventure (USA)")["error"]
    r = run(FakeSA2(DC), "emblems", "Sonic Adventure 2 (Europe)")
    assert "not mapped" in r["error"] and "games" in r
    other = FakeSA2(DC)
    other.raw(DC["signature"][0], b"\x00" * 10)                            # a different 1ST_READ.BIN
    assert "build check failed" in run(other, "finish_level")["error"] and not other.writes
    pal = FakeSA2(GC)
    pal.raw(0x80000000, b"GSNP8P")
    assert "GSNP8P" in run(pal, "status", GC_TITLE, "gamecube")["error"]
    g = run(FakeSA2(DC), "games")
    assert set(g["games"]) == {"dc_us", "gc_us"} and "dc_eu" in g["gaps"] and g["detected"] == "dc_us"


# ---------------------------------------------------------------------------------------------------- status

@pytest.mark.parametrize("lay,title,platform", [(DC, DC_TITLE, "dreamcast"), (GC, GC_TITLE, "gamecube")])
def test_status_reads_stage_character_mission_score_time_rings(lay, title, platform):
    ad = FakeSA2(lay, level=16, mission=0, character=4)
    r = run(ad, "status", title, platform)
    st = r["state"]
    assert (st["level_name"], st["character_name"], st["mission_number"]) == ("Wild Canyon", "Knuckles", 1)
    assert (st["score"], st["rings"], st["time"], st["state_name"]) == (4200, 37, "1:42.07", "in game")
    assert r["rank_table"]["A"] == 16000 and r["finishable"] == "yes" and r["live_checked"] is False
    # (4200 + time bonus 10000 - 20 * 42) / 100 = 133 -> >= D 80, C 100, < B 140: C
    assert r["grade_now"] == "C" and r["emblems"]["total"] == 180 and r["emblems"]["earned"] == 0
    assert not ad.writes


def test_grade_follows_the_results_screen():
    e = {"kind": "score", "D": 9000, "C": 11000, "B": 14000, "A": 18000}
    st = {"score": 8000, "minutes": 1, "seconds": 0, "frames": 0, "rings": 5, "perfect_rings": 300}
    assert sa.time_bonus(60) == 10000 and sa.time_bonus(30) == 10000 and sa.time_bonus(600) == 0
    assert sa.grade(st, e) == "A"                                    # 8000 + 10000 = 18000
    assert sa.grade(dict(st, minutes=2), e) == "B"                   # 8000 + 8800
    assert sa.grade(dict(st, rings=300), {**e, "A": 99999}) == "A"   # perfect: rings >= PerfectRings
    t = {"kind": "time", "D": 150, "C": 120, "B": 100, "A": 80}
    assert sa.grade(dict(st, minutes=1, seconds=20, frames=0), t) == "A"
    assert sa.grade(dict(st, minutes=1, seconds=20, frames=1), t) == "B"      # frames round the clock up a second
    assert sa.grade(dict(st, minutes=9), t) == "E"


# ---------------------------------------------------------------------------------------------------- finish_level

@pytest.mark.parametrize("lay,title,platform", [(DC, DC_TITLE, "dreamcast"), (GC, GC_TITLE, "gamecube")])
def test_finish_level_lets_the_game_clear_the_stage_and_restores_mission_and_rings(lay, title, platform):
    ad = FakeSA2(lay, level=13, mission=3)                          # City Escape, mission 4
    r = run(ad, "finish_level", title, platform)
    assert r["finished"] and r["verified"] and r["mission"] == 4 and r["level"] == "City Escape"
    assert ad.get("cleared") == 1 and ad.get("timer_stopped") == 1
    assert ad.get("mission") == 3 and ad.get("rings") == 37            # graded + saved as the real mission
    assert r["restored"] == {"mission": 4, "rings": 37}
    m_addr, r_addr = lay["fields"]["mission"][0], lay["fields"]["rings"][0]
    assert [a for a, _ in ad.writes] == [m_addr, r_addr, m_addr, r_addr]   # the only bytes touched


def test_finish_level_on_the_100_ring_mission_and_when_already_cleared():
    ad = FakeSA2(DC, level=70, mission=1)
    ad.set("rings", 150)
    r = run(ad, "finish_level")
    assert r["finished"] and ad.get("rings") == 150 and ad.get("mission") == 1
    again = run(ad, "finish_level")
    assert again["already"] and again["verified"]


@pytest.mark.parametrize("setup,needle", [
    (dict(level=61), "outside the stages"), (dict(level=90), "outside the stages"),
    (dict(state=7), "not in a stage"), ("2p", "2-player"),
])
def test_finish_level_refuses_what_the_game_check_cannot_end(setup, needle):
    ad = FakeSA2(DC, **({} if setup == "2p" else setup))
    if setup == "2p":
        ad.set("two_player", 1)
    r = run(ad, "finish_level")
    assert not r["finished"] and needle in r["error"] and not ad.writes


def test_finish_level_times_out_while_paused_and_puts_everything_back():
    ad = FakeSA2(DC, level=13, mission=2, state=17)
    r = run(ad, "finish_level", timeout_s=0.1)
    assert not r["finished"] and "paused" in r["error"]
    assert ad.get("mission") == 2 and ad.get("rings") == 37 and ad.get("cleared") == 0


def test_gamecube_allows_levels_up_to_60_dreamcast_up_to_46():
    assert run(FakeSA2(GC, level=55), "finish_level", GC_TITLE, "gamecube")["finished"]
    assert "outside" in run(FakeSA2(DC, level=55), "finish_level")["error"]


def test_a_boss_finish_is_flagged_untested():
    r = run(FakeSA2(DC, level=19), "finish_level")
    assert r["finished"] and "untested" in r["note"]


# ---------------------------------------------------------------------------------------------------- rank

def test_s_rank_is_an_a_on_a_score_mission():
    ad = FakeSA2(DC, level=13, mission=0)
    r = run(ad, "rank", rank="S")
    assert r["finish"]["finished"] and r["rank"] == "A" and "no S rank" in r["note"]
    assert ad.get("score") == 18000 and r["grade_now"] == "A" and r["verified"]
    assert r["codes"] == ["020DB294 00004650"] and r["thresholds"]["table"] == hex(0x8C0E5ABC)


def test_mission_5_uses_its_own_score_table_and_keeps_a_higher_score():
    ad = FakeSA2(GC, level=16, mission=4)
    ad.set("score", 50000)
    r = run(ad, "rank", GC_TITLE, "gamecube")
    assert r["thresholds"]["table"] == hex(0x801B3728) and ad.get("score") == 50000 and r["grade_now"] == "A"


def test_a_rank_on_a_time_mission_sets_the_clock_after_the_timer_stops():
    ad = FakeSA2(DC, level=13, mission=1)                           # 100 rings: A = 1:20
    r = run(ad, "rank", rank="A")
    assert r["finish"]["finished"] and ad.get("timer_stopped") == 1
    assert (ad.get("minutes"), ad.get("seconds"), ad.get("frames")) == (1, 19, 0) and r["grade_now"] == "A"
    assert r["codes"] == ["000DB227 00000001", "000DB228 00000013", "000DB229 00000000"]


def test_rank_without_finishing_and_other_letters():
    ad = FakeSA2(DC, level=16, mission=2)                           # lost chao: A = 1:30
    r = run(ad, "rank", rank="b", finish=False)
    assert "finish" not in r and r["rank"] == "B" and (ad.get("minutes"), ad.get("seconds")) == (1, 0)
    assert ad.get("cleared") == 0 and "headroom" in r["note"]
    assert "rank must be" in run(FakeSA2(DC), "rank", rank="Z")["error"]


def test_rank_needs_a_table_for_the_stage():
    r = run(FakeSA2(DC, level=70, mission=0), "rank")
    assert "no rank table" in r["error"]


# ---------------------------------------------------------------------------------------------------- emblems

@pytest.mark.parametrize("lay,title,platform", [(DC, DC_TITLE, "dreamcast"), (GC, GC_TITLE, "gamecube")])
def test_all_emblems_marks_the_180_bytes_and_the_count(lay, title, platform):
    ad = FakeSA2(lay)
    first = sa.emblem_slots(lay)[0]["address"]
    ad.raw(first, b"\x03")                                         # City Escape M1 already cleared with a C
    r = run(ad, "emblems", title, platform)
    assert r["verified"] and r["added"] == 179 and r["emblems"] == 180 and ad.get("emblem_count") == 180
    assert ad.mem[first] == 3                                        # an existing rank is kept
    slots = sa.emblem_slots(lay)
    assert all(ad.mem[s["address"]] == (5 if s["kind"] == "rank" else 1) for s in slots[1:])
    assert "Green Hill" in r["note"] and "VMU" in r["note"]


def test_some_emblems():
    ad = FakeSA2(DC)
    r = run(ad, "emblems", count=4)
    assert r["added"] == 4 and r["emblems"] == 4 and r["verified"]
    assert r["added_labels"] == [f"City Escape mission {i}" for i in (1, 2, 3, 4)]
    assert 0x8C26A664 + 0x6C + 13 * 0x88 == 0x8C26ADB8
    assert r["codes"][:2] == ["0026ADB8 00000005", "0026ADB9 00000005"] and r["codes"][-1] == "0026A671 00000004"
    assert run(ad, "status")["emblems"]["earned"] == 4


# ---------------------------------------------------------------------------------------------------- registration + agent

def test_tool_is_registered_with_the_worker():
    from gbox import registry, tools
    assert "sonic_adventure_2" in registry.REGISTRY and "sa2_mods" in tools._load_tool_modules.__defaults__[0]
    t = registry.REGISTRY["sonic_adventure_2"]
    inp = t.In.model_validate({"session_id": "w-1", "op": "finish_level"})
    assert (inp.rank, inp.count, inp.finish) == ("A", 0, True)


def _spec(name):
    return next(t["function"] for t in agent.tool_specs() if t["function"]["name"] == name)


def test_agent_offers_the_tool():
    desc = _spec("sonic_adventure_2")["description"]
    assert "skip to the end of this level" in desc and "S rank" in desc and "all 180" in desc
    assert {"session_id", "op", "rank", "count", "finish"} <= set(_spec("sonic_adventure_2")["parameters"]["properties"])
    assert "sonic_adventure_2" in agent.WORKER_TOOLS and "sonic_adventure_2" in agent.MODIFIES
    assert agent._modifies_game("sonic_adventure_2", {"op": "finish_level"})
    assert not agent._modifies_game("sonic_adventure_2", {"op": "status"})


def test_system_prompt_routes_the_ticket_phrases_straight_to_the_tool():
    line = next(l for l in agent.SYSTEM.splitlines() if l.startswith("- Sonic Adventure 2"))
    block = agent.SYSTEM[agent.SYSTEM.index(line):][:1100]
    for phrase in ("skip to the end of this level", "give me an S rank", "give me all the emblems", "nothing else",
                   "op=finish_level", "op=rank rank=A", "op=emblems"):
        assert phrase in block, phrase
    act = agent.SYSTEM[agent.SYSTEM.index("(0) the game's own tool"):][:400]
    assert "sonic_adventure_2 op=finish_level" in act


def test_agent_call_dispatches_a_worker_job():
    a = object.__new__(agent.Agent)
    sent = []

    def job(tool, inp, node=None, limit=900, worker=None):
        sent.append((tool, inp, worker))
        return {"state": "succeeded", "output": {"result": {"finished": True, "verified": True}}}
    a._job = job
    assert a.sonic_adventure_2("worker-abc123", op="rank", rank="S")["verified"]
    assert sent == [("sonic_adventure_2", {"session_id": "worker-abc123", "op": "rank", "rank": "S", "count": 0,
                                           "finish": True, "timeout_s": 3.0}, "worker")]

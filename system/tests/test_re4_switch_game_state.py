"""RE4 Switch: where the game is comes from the game's own state, not from a timeout, a census or a guessed clock.

2026-11-10 (lilspark, Krauser on Waterworld): the round's intro card "Eliminate as many Ganados ..." waited for A while
the runner took the unnamed picture for the round after 6 s, the Bot fired at the Ganados the round had already placed
in RAM ("crowd fire: 4 within 6 m", 620 shots, 0 hits) and the map's clock was a float ClockFinder had picked. These tests
pin the replacement: re4_switch.game_state (MercSysWk's intro / round / results runs, pG's event / suspend / death /
case / grab flags, the pad mask, the HUD's CountDown), the Bot that never fires out of control, and the runner that
decides the round from RAM and logs where the frame disagrees. The byte values are the ones read live
(session 5a68e96bfd1447a2-780e877d92ec4151).
"""
import json
import struct

from gbox import re4switch_bot as B
from gbox.mercs.titles import re4_switch as D

BASE = D.KNOWN_BASES[0]
PG = BASE + D.PG_OBJ

# live, 2026-11-10 04:18-04:19
INTRO = dict(system=0x40000804, stop=0x80400100, status=(0x3001310, 0x18000200, 0, 0), start=(1, 1), main=0,
             result=(0, 0), cd_state=9, frame=3600.0)
PLAYING = dict(system=0x40000804, stop=0, status=(0x3000310, 0x8000200, 0, 0), start=(0, 2), main=1, result=(0, 0),
               cd_state=1, frame=3582.5)
GRABBED = dict(PLAYING, status=(0x3000310, 0x8008200, 0, 0), frame=3488.88)
DEAD = dict(system=0x40000804, stop=0x80400100, status=(0x3100310, 0x8000200, 0, 0), start=(0, 2), main=1,
            result=(0, 0), cd_state=0, frame=2969.4)
RESULTS = dict(PLAYING, main=0, result=(1, 1), stop=0xFFFFFFFF, status=(0x3001310, 0x18000200, 0, 0), frame=0.0)
MENU = dict(system=0x00040004, stop=0, status=(0x1000000, 0x40, 0x8000, 0), start=(0, 0), main=0, result=(0, 0),
            cd_state=0, frame=0.0)


def merc_bytes(st, kills=0, score=0, combo=0, mode=2, stage=3) -> bytes:
    b = bytearray(D.MERC_WORK_SIZE)
    struct.pack_into("<I", b, D.MW_SCORE, score)
    struct.pack_into("<i", b, D.MW_COMBO, combo)
    struct.pack_into("<i", b, D.MW_KILL, kills)
    struct.pack_into("<ii", b, D.MW_MODE, mode, stage)
    b[D.MW_START], b[D.MW_START + 1] = st["start"]
    b[D.MW_MAIN] = st["main"]
    b[D.MW_RESULT], b[D.MW_RESULT + 1] = st["result"]
    return bytes(b)


def cd_bytes(st) -> bytes:
    return struct.pack("<IbbbxffI", st["cd_state"], 1, 59, 42, st["frame"], st["frame"], 0)


def decode(st, **kw) -> dict:
    return D.decode_state(st["system"], st["stop"], st["status"], merc_bytes(st, **kw), cd_bytes(st), 0.5)


def test_the_intro_card_is_not_the_round_and_its_clock_is_held():
    g = decode(INTRO)
    assert g["phase"] == "intro" and g["in_control"] is False and g["intro_step"] == 1
    assert g["clock"] == 120.0 and g["clock_running"] is False, "2:00 on the HUD, alive and paused (state 9)"
    assert g["flags"]["event"] and g["flags"]["suspend"] and g["flags"]["key_stop"]


def test_the_round_is_live_only_in_control_with_the_clock_running():
    g = decode(PLAYING)
    assert g["phase"] == "playing" and g["in_control"] is True and g["clock_running"] is True
    assert g["clock"] == round(3582.5 / 30.0, 2) and g["frame_step"] == 0.5
    assert (g["mode"], g["stage"]) == (2, 3), "Krauser on Waterworld"


def test_a_grab_the_death_camera_and_the_results_are_not_in_control():
    assert decode(GRABBED)["phase"] == "grabbed" and decode(GRABBED)["in_control"] is False
    assert decode(GRABBED)["clock_running"] is True, "the clock ran on through the grab (3489.4 -> 3488.9 live)"
    assert decode(INTRO)["clock_running"] is False and decode(DEAD)["clock_running"] is False
    dead = decode(DEAD)
    assert dead["phase"] == "dead" and dead["clock"] is None, "the cockpit stops the clock at the death (state 0)"
    res = decode(RESULTS)
    assert res["phase"] == "results" and res["result_step"] == 1 and res["in_control"] is False


def test_outside_the_mercenaries_or_between_rounds_no_round_runs():
    assert decode(MENU)["phase"] == "none"
    assert decode(dict(PLAYING, system=0x804))["phase"] == "none", "the Mercenaries flag off: not this mode's round"
    assert decode(dict(PLAYING, main=0))["phase"] == "none"


def test_a_round_byte_left_behind_by_a_soft_reset_is_no_round():
    """You Are Dead -> No soft-resets the game: pG's flags are cleared and the cockpit re-made, but MercSysWk keeps its
    round byte until the next stage starts. Without the clock alive it is not a round (and not "in control")."""
    stale = dict(PLAYING, stop=0, status=(0, 0, 0, 0), cd_state=0, frame=0.0)
    assert decode(stale)["phase"] == "none" and decode(stale)["in_control"] is False
    assert decode(dict(INTRO, cd_state=0))["phase"] == "none"


def test_the_case_and_a_held_player_are_named():
    assert decode(dict(PLAYING, status=(0x3040310, 0x8000200, 0, 0)))["phase"] == "case"
    assert decode(dict(PLAYING, stop=D.SPF_PL))["phase"] == "held"


class Mem:
    """The session's RAM as ranges: the signature, pG's pointer and fields, MercSysWk and the CountDown."""

    def __init__(self, st, kills=0):
        self.ranges = {}
        self.put(BASE + D.SIG_OFF, D.SIGNATURE)
        self.put(BASE + D.PG_PTR_VAR, struct.pack("<Q", PG))
        head = bytearray(D.PG_STOP + 4 - D.PG_SYSTEM)
        struct.pack_into("<I", head, 0, st["system"])
        struct.pack_into("<f", head, D.PG_SPEED - D.PG_SYSTEM, 0.5)
        struct.pack_into("<I", head, D.PG_STOP - D.PG_SYSTEM, st["stop"])
        self.put(PG + D.PG_SYSTEM, bytes(head))
        self.put(PG + D.PG_STATUS, struct.pack("<4I", *st["status"]))
        self.put(BASE + D.MERC_WORK, merc_bytes(st, kills=kills))
        self.put(BASE + D.COUNTDOWN, cd_bytes(st))

    def put(self, addr, data):
        self.ranges[addr] = bytes(data)

    def rd(self, a, n):
        for s, d in self.ranges.items():
            if s <= a and a + n <= s + len(d):
                return d[a - s:a - s + n]
        raise ValueError(f"unmapped {a:#x}")


def test_game_state_reads_the_session_and_the_snapshot_takes_the_hud_clock():
    m = Mem(PLAYING)
    g = D.game_state(m)
    assert g["phase"] == "playing" and g["clock"] == round(3582.5 / 30.0, 2)
    snap = D.snapshot(m, now=0.0)
    assert snap["game"]["phase"] == "playing" and snap["clock_source"] == "countdown"
    assert snap["timer"] == g["clock"] and snap["clock_addr"] == BASE + D.COUNTDOWN
    assert not hasattr(m, "re4_clock"), "ClockFinder is not run while the game's clock can be read"
    assert D.own_screen(snap) == "playing"
    assert D.own_screen(D.snapshot(Mem(INTRO), now=0.0)) == "paused"
    assert D.own_screen(D.snapshot(Mem(DEAD), now=0.0)) == "dead"


def test_unreadable_state_is_none_and_the_frame_decides():
    class Nothing:
        def rd(self, a, n):
            raise ValueError("unmapped")
    assert D.game_state(Nothing()) is None


ENEMIES = [{"ptr": 0x100 + i, "pos": (300.0 * i, 0.0, 2500.0), "hp": 400, "hp_max": 400} for i in range(4)]


def _snap(st, **kw):
    return {"game": decode(st), "player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 2400, "hp_max": 2400},
            "enemies": [dict(e) for e in ENEMIES], "timer": decode(st)["clock"], **kw}


def test_the_bot_never_fires_at_the_intro_card_it_pages_it():
    """The incident: four Ganados within 6 m on the gun's line, the card up. No shot, no aim, A, and it says so."""
    stats = {}
    bot = D.Bot(stats=stats, clock=lambda: 0.0, director=False)
    acts = [bot.tick(_snap(INTRO), now=t * 0.05) for t in range(200)]
    assert all("zl" not in (a.get("hold") or ()) and a.get("tap") != "zr" for a in acts)
    assert sum(a.get("tap") == "a" for a in acts) >= 15, "A every 0.5 s while the card waits"
    assert stats["shots"] == 0 and stats["doing"] == "intro" and "intro card" in stats["why"]
    assert D.AIM_REQUEST == {}, "no aim request for the RAM aim lock while not in control"
    act = bot.tick(_snap(PLAYING), now=11.0)
    assert stats["doing"] != "intro", "in control: the fight takes over"
    assert act is not None


def test_the_bot_mashes_a_grab_and_waits_out_the_death_camera_without_firing():
    stats = {}
    bot = D.Bot(stats=stats, clock=lambda: 0.0, director=False)
    acts = [bot.tick(_snap(GRABBED), now=t * 0.05) for t in range(40)]
    assert all(a.get("tap") in (None, "a") for a in acts) and stats["shots"] == 0
    assert stats["doing"] == "grabbed"
    acts = [bot.tick(_snap(DEAD), now=10 + t * 0.05) for t in range(40)]
    assert all(a.get("tap") in (None, "a") for a in acts) and stats["doing"] == "dead"


def test_without_the_games_state_the_fight_is_unchanged():
    stats = {}
    bot = D.Bot(stats=stats, clock=lambda: 0.0, director=False)
    snap = _snap(PLAYING)
    snap.pop("game")
    for t in range(60):
        bot.tick(snap, now=t * 0.05)
    assert stats.get("not_in_control_ticks", 0) == 0


# --- the runner -------------------------------------------------------------------------------------------------
class Adapter:
    def __init__(self):
        self.sent = []

    def get_frame(self):
        return b"frame"


class Frames:
    def __init__(self, script):
        self.script = list(script)

    def read(self, frame):
        return {"where": self.script.pop(0) if self.script else "unknown"}


class Scenario:
    """game_state and snapshot stand-ins driven by one script of states (one per runner tick)."""

    def __init__(self, states):
        self.states = list(states)
        self.i = -1

    def game_state(self, m):
        self.i += 1
        st = self.states[min(self.i, len(self.states) - 1)]
        return None if st is None else decode(st)

    def snapshot(self, m):
        st = self.states[min(max(self.i, 0), len(self.states) - 1)]
        if st is None:                                   # no state read: a snapshot without it (the fallback)
            snap = _snap(PLAYING)
            snap.pop("game")
            return snap
        return _snap(st)


def _run(monkeypatch, tmp_path, states, frames, boundary=None, n=None):
    sc = Scenario(states)
    monkeypatch.setattr(B.driver, "game_state", sc.game_state)
    monkeypatch.setattr(B.driver, "snapshot", sc.snapshot)
    monkeypatch.setattr(B.screens, "Reader", lambda: Frames(frames))
    monkeypatch.setattr(B, "STATE_LOG", tmp_path / "disagree.jsonl")
    monkeypatch.setattr(B, "_maintain_mods", lambda ad, snap, stats: None)
    ad = Adapter()
    ad.at = []                                           # the scenario's state index at every batch sent
    ticks = {"n": 0}
    limit = n if n is not None else len(states)

    def clock():
        ticks["n"] += 1
        return 1_000_000.0 + ticks["n"] * 0.05

    def stopped():
        return sc.i >= limit - 1

    stats = {}
    out = B.play(ad, lambda rows: ad.sent.append(rows) or ad.at.append(sc.i), stopped, sleep=lambda s: None,
                 stats=stats, clock=clock, m=object(), round_boundary=boundary)
    return ad, stats, out


def _downs(ad):
    return [r["key"] for batch in ad.sent for r in batch if r.get("down")]


def test_the_runner_takes_the_round_from_ram_and_the_intro_is_paged_not_shot(monkeypatch, tmp_path):
    """The frame reads "playing" through the intro (the HUD test fires on Waterworld's horizon, live 04:18:38): the
    game says intro, so the round is the intro until the game says in control - A, never the trigger."""
    states = [MENU] * 5 + [INTRO] * 120 + [PLAYING] * 60
    frames = ["select_stage"] + ["unknown"] * 4 + ["playing"] * 400
    ad, stats, _ = _run(monkeypatch, tmp_path, states, frames)
    during_intro = [r["key"] for batch, i in zip(ad.sent, ad.at) if 5 <= i < 125 for r in batch if r.get("down")]
    assert "zr" not in during_intro and "zl" not in during_intro, during_intro
    assert during_intro.count("a") >= 3 and stats["intro_taps"] >= 3, "the intro is paged with A"
    assert stats["rounds"] == 1 and stats["state_source"] == "ram"
    assert stats["screen"] == "playing" and stats["game_phase"] == "playing"
    rows = [json.loads(x) for x in (tmp_path / "disagree.jsonl").read_text().splitlines()]
    assert any(r["ram"] == "intro" and r["frame"] == "playing" for r in rows), "the disagreement is on the record"
    assert stats["state_disagreements"] >= 1


def test_no_unnamed_picture_becomes_a_round_while_the_game_says_none(monkeypatch, tmp_path):
    """The 6 s rule is gone where RAM is read: after the stage's confirm a long unnamed picture is waited out with no
    entry presses, however long it lasts."""
    states = [MENU] * 300
    frames = ["select_stage"] + ["unknown"] * 400
    ad, stats, _ = _run(monkeypatch, tmp_path, states, frames)
    assert stats["rounds"] == 0 and "a" not in _downs(ad)[1:], _downs(ad)
    assert stats["waits_no_round"] > 100


def test_the_games_results_post_the_results_boundary_after_a_live_round(monkeypatch, tmp_path):
    posted = []
    states = [INTRO] * 10 + [PLAYING] * 40 + [RESULTS] * 20
    ad, stats, out = _run(monkeypatch, tmp_path, states, ["unknown"] * 400,
                          boundary=lambda body, st: posted.append(body) or True)
    assert len(posted) == 1 and out["boundaries_posted"] == 1
    w = posted[0]["witness"]
    assert w["screen"] == "results" and w["timer"] == 0 and w["tally_ready"] is True and w["state_source"] == "ram"
    assert w["phases"][:3] == ["intro", "playing", "results"]


def test_an_intro_never_seen_live_posts_no_results(monkeypatch, tmp_path):
    posted = []
    _run(monkeypatch, tmp_path, [INTRO] * 30 + [RESULTS] * 20, ["unknown"] * 400,
         boundary=lambda body, st: posted.append(body) or True)
    assert posted == []


def test_a_named_menu_wins_over_a_round_that_is_not_live(monkeypatch, tmp_path):
    """Stale fields after a reset must not hold the walk: the title (a reference picture) while RAM still says intro
    is walked as the title, and logged."""
    states = [INTRO] * 60
    frames = ["title"] * 200
    ad, stats, _ = _run(monkeypatch, tmp_path, states, frames)
    assert stats["rounds"] == 0 and stats["screen"] == "title"
    assert stats["last_disagreement"]["frame"] == "title"


def test_without_ram_state_the_frame_fallback_still_runs(monkeypatch, tmp_path):
    states = [None] * 60
    frames = ["select_stage"] + ["unknown"] * 400
    ad, stats, _ = _run(monkeypatch, tmp_path, states, frames)
    assert stats["state_source"] == "frame" and stats["rounds"] == 1, "the RAM-less guess is the fallback only"

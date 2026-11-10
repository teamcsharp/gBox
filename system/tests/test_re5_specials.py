"""RE5 Switch: the characters' special moves in play (gbox.mercs.titles.re5_specials, driven by re5_switch.Bot).

The operator, 2026-11-09: the bot must use each character's special abilities and finishers "for added entertainment
value ... we don't want the bot standing around, losing the combo, getting lost or dying while having them do these
moves in gameplay and have them maintaining the combo" (Wesker's dash, for one).

The tables are the research's (docs/research/mercenaries-character-specials.md sections 3 and 6.2). The rounds here are
synthetic: a simulator moves him by his pad, takes a hit on the target when he pulls with the dot on him, and shows the
game's melee prompt while a staggered Majini is within reach. They measure the controller's inputs and its ledger,
never the game's real stagger, prompt or damage."""
import math
import struct

import pytest

from gbox.mercs.brain import body
from gbox.mercs.titles import re5_specials as S
from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_prompt as P

PTR = 0x5D00001000
HANDGUN, SHOTGUN = 0x02, 0x04


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)
    monkeypatch.setattr(R, "GRENADES", False)
    monkeypatch.setattr(R, "CRIT_FLASH", False)


# --- the tables --------------------------------------------------------------------------------------------------------
def test_its_copies_of_the_bots_constants_agree():
    """re5_specials never imports re5_switch (re5_switch imports it); its copies must stay the bot's."""
    assert S.LEVEL_DY == R.LEVEL_DY and S.DYING_HP == R.DYING_HP and S.PHASE_PLAYING == R.PHASE_PLAYING
    assert S.HELD_MOTIONS == R.MOTION_HELD and S.WINDUP_MOTIONS == R.WINDUP_MOTIONS and S.E_ATTACKING == R.E_ATTACKING
    assert tuple(S.DYNAMITE_CLASSES) == tuple(R.DYNAMITE_CLASSES) and S.DYNAMITE_MOTIONS == R.DYNAMITE_MOTIONS
    assert (S.LABEL_TIME_BONUS, S.LABEL_BREAK_FREE, S.LABEL_RESUSCITATE, S.LABEL_PICKUP, S.LABEL_PLACE) == (
        P.LABEL_TIME_BONUS, P.LABEL_BREAK_FREE, P.LABEL_RESUSCITATE, P.LABEL_PICKUP, P.LABEL_PLACE)
    assert S.TRAVERSE_LABELS == P.TRAVERSE_LABELS and S.KIND_AREA == P.KIND_AREA
    assert S.PLAYER_FAMILIES == R.PLAYER_FAMILIES and S.COMBO_WINDOW_S == R.COMBO_WINDOW_S
    assert S.PROMPT_R == R.PROMPT_CLEAR_R and S.HEAD_AIM_H == R.HEAD_H and S.LEG_AIM_H == body.THIGH_H
    assert S.TURN_TOL == R.TURN_TOL and S.KILL_PACE_S == R.KILL_PACE_S
    assert S.START_LEFT_S == R.COMBO_URGENT_S                # a special starts only before the combo push does
    assert set(S.COUNTERS) <= set(R.RE5Switch.round_counters)


def test_every_name_of_the_select_and_every_united_costume_has_its_characters_set():
    for name in R.CHARACTERS:
        assert name in S.COSTUMES, name
    for name, (family, note) in S.COSTUMES.items():
        assert family in S.PLANS and note
        assert set(S.MOVES[family]) == set(S.POSITIONS)
        plan = S.PLANS[family]
        assert S.move(family, plan.want) is not None and S.move(family, "grounded") is not None


TOP = [   # family, the stagger site, the move wanted, does it kill a regular 800-HP Majini that took the stagger shot
    ("Chris", "leg", "Neckbreaker", True), ("Sheva", "leg", "Throat Slit", True), ("Jill", "leg", "Head Grab", True),
    ("Josh", "leg", "Suplex", True), ("Excella", "leg", "First Aid", True), ("Wesker", "head", "Cobra Strike", True),
    ("Rebecca", "head", "Flame Spray", True), ("Barry", "head", "Headbutt", False)]


@pytest.mark.parametrize("family,site,name,kills", TOP)
def test_each_characters_top_move_is_the_researchs(family, site, name, kills):
    plan = S.plan_for(family, "Village", {"hp_max": 800})
    mv = S.move(family, plan.want)
    assert plan.site == site and mv.name == name and mv.kills(650) is kills
    assert plan.rank.startswith("6.2 #1" if site == "leg" else "6.2 #2")
    if site == "leg":                                    # the game's own answer in front: the front leg move
        assert plan.fallback == "leg_front" and S.move(family, "leg_front") is not None


def test_a_head_move_where_a_head_kill_rolls_a_cephalo_becomes_the_leg_stun(monkeypatch):
    """Missile Area: "always avoid any type of melees that hit the head" [S52]; the female Majini (700 HP) of Public
    Assembly [S49]."""
    assert S.plan_for("Wesker", "Missile Area", {"hp_max": 800}) is S.REAR_SAFE
    assert S.plan_for("Rebecca", "Public Assembly", {"hp_max": 700}) is S.REAR_SAFE
    assert S.plan_for("Rebecca", "Public Assembly", {"hp_max": 800}) is S.HEAD_KILL
    assert S.plan_for("Chris", "Missile Area", {"hp_max": 800}) is S.REAR_KILL
    monkeypatch.setattr(S, "LEG_STUNS", False)           # no thigh shots: the head move, and none where it is risky
    assert S.plan_for("Chris", "Village", {"hp_max": 800}) is S.HEAD_ONLY
    assert S.plan_for("Wesker", "Missile Area", {"hp_max": 800}) is None


def test_the_character_comes_from_the_ram_class_and_the_costume_from_the_round_name():
    assert S.identify({"player_class": "uPl03WeskerNormal", "character": "Wesker (STARS)"}) == ("Wesker", "Wesker (STARS)")
    assert S.identify({"player_class": "uPl01ShebaNormal", "character": "Chris (BSAA)"}) == ("Sheva", None)
    assert S.identify({"character": "Josh (BSAA)"}) == ("Josh", "Josh (BSAA)")
    assert S.identify({"player_class": "uPl07Rebecca", "character": "character 12",
                       "queued_selection": "no_mercy / Rebecca (STARS) / Prison"}) == ("Rebecca", "Rebecca (STARS)")
    assert S.identify({"character": "Chris"}) == ("Chris", None)
    assert S.identify({}) == (None, None)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def prompt(label=47, kind=2, token="press:y", keys=("y",), target=0, owner=PTR, button=0x5D20000000, mode=1):
    return {"token": token, "keys": keys, "button": button, "kind": kind, "mode": mode, "priority": 33,
            "key_index": 1, "label": label, "owner": owner, "target": target}


def test_a_melee_prompt_is_a_press_that_names_a_majini_or_has_one_at_arms_length():
    m = {"ptr": 0x11, "pos": at(150, 0), "hp": 600, "hp_max": 800}
    snap = {"enemies": [m]}
    pos = (0.0, 0.0, 0.0)
    assert S.melee_prompt(prompt(target=0x11), snap, pos) is m
    assert S.melee_prompt(prompt(label=47), snap, pos) is m                     # nothing named: the one in reach
    far = {"enemies": [dict(m, pos=at(400, 0))]}
    assert S.melee_prompt(prompt(label=47), far, pos) is None
    assert S.melee_prompt(prompt(target=0x11), far, pos) is not None           # named: whatever the distance
    for label in (112, 28, 55, 1, 100, 7, 8, 9, 14, 58):                       # the hourglass ... the ledges
        assert S.melee_prompt(prompt(label=label), snap, pos) is None, label
    assert S.melee_prompt(prompt(kind=3), snap, pos) is None                    # an area pickup
    assert S.melee_prompt(prompt(token="mash:wiggle", keys=()), snap, pos) is None
    assert S.melee_prompt(prompt(target=0x11), {"enemies": [dict(m, hp=0)]}, pos) is None


def test_the_rear_approach_goes_round_his_side_then_behind_him():
    e = {"pos": (0.0, 0.0, 500.0)}
    face = (0.0, -1.0)                                   # he faces the player at the origin
    side = S.approach_point((0.0, 0.0, 0.0), e, face, rear=True)
    assert abs(side[0]) == pytest.approx(S.SIDE_CM) and side[2] == pytest.approx(500.0)
    behind = S.approach_point((S.SIDE_CM, 0.0, 500.0), e, face, rear=True)  # at his side: now behind him
    assert behind[0] == pytest.approx(0.0) and behind[2] == pytest.approx(500.0 + S.BEHIND_CM)
    assert S.approach_point((0.0, 0.0, 0.0), e, face, rear=False) == e["pos"]
    assert S.round_angle((0.0, 0.0, 0.0), e, face) == pytest.approx(0.0)
    assert S.round_angle((0.0, 0.0, 700.0), e, face) == pytest.approx(180.0)
    assert S.site_of((0.0, 160.0, 500.0), e["pos"]) == "head" and S.site_of((0.0, 72.0, 500.0), e["pos"]) == "leg"
    assert S.site_of((0.0, 110.0, 500.0), e["pos"]) == "body" and S.site_of((200.0, 110.0, 500.0), e["pos"]) is None


# --- the synthetic round -------------------------------------------------------------------------------------------------
class Sim:
    """He turns with the right stick (160 deg/s, 40 aimed), walks with the left stick only with the gun down (300 cm/s,
    450 with B), the gun up (ZL) is the aimed stance a tick later. The laser's dot sits on the target at the height the
    bot wants (a perfect aim) unless dot_h says otherwise. A trigger edge with the dot on him hits him for `damage` the
    next tick; a hit Majini is staggered for `stun_s`, and the melee prompt shows while he is within `reach` of a
    staggered or floored one (on_press says what the move does)."""

    def __init__(self, enemies, *, character="Wesker (STARS)", cls="uPl03WeskerNormal", stage="Village", item=HANDGUN,
                 combo=0, combo_timer=0.0, hp=1000, damage=150, hz=30.0):
        self.clock = [0.0]
        self.stats = {"character": character, "player_class": cls, "ss_stage": stage}
        self.bot = R.Bot(stats=self.stats, clock=lambda: self.clock[0])
        self.enemies = [dict({"hp": 800, "hp_max": 800}, ptr=0x11 + i, **e) for i, e in enumerate(enemies)]
        self.pos, self.rot, self.hp, self.item = (0.0, 0.0, 0.0), 0.0, hp, item
        self.combo, self.combo_timer, self.kills = combo, combo_timer, 0
        self.damage, self.hz, self.dot_h = damage, hz, None
        self.aimed, self.zr, self.pending = False, False, None
        self.stunned, self.floored = {}, set()
        self.reach, self.stun_s, self.label, self.prompt_on = 150.0, 2.2, 47, True
        self.on_press = lambda sim, e: sim.kill(e)
        self.shown = None
        self.motion = None
        self.ticks, self.where = [], []
        self.extra = {}

    # the world
    def alive(self):
        return [e for e in self.enemies if e["hp"] > 0]

    def kill(self, e):
        e["hp"] = 0
        self.kills += 1
        self.combo, self.combo_timer = self.combo + 1, 10.0

    def wanted_h(self, e):
        sp = self.bot.__dict__.get("_sp_layer")
        att = sp.att if isinstance(sp, S.Specials) else None
        if att is not None and att.phase == "aim" and att.target == e["ptr"]:
            return S.HEAD_AIM_H if att.site == "head" else S.LEG_AIM_H
        return R.CHEST_H

    def target(self):
        live = self.alive()
        return next((e for e in live if e["ptr"] == self.bot.target), live[0] if live else None)

    def snap(self):
        now = self.clock[0]
        tgt = self.target()
        laser = {"from": (0.0, 0.0, 0.0), "at": (0.0, 0.0, 0.0), "up": False}
        if self.aimed and tgt is not None:
            h = self.dot_h if self.dot_h is not None else self.wanted_h(tgt)
            laser = {"from": (self.pos[0], 140.0, self.pos[2] + 30.0),
                     "at": (tgt["pos"][0], tgt["pos"][1] + h, tgt["pos"][2]), "up": True}
        self.shown = None
        near = [e for e in self.alive() if math.hypot(e["pos"][0] - self.pos[0], e["pos"][2] - self.pos[2]) <= self.reach
                and (self.stunned.get(e["ptr"], -1e9) > now or e["ptr"] in self.floored)]
        if near and self.prompt_on:
            self.shown = near[0]
            pr = prompt(label=self.label, target=self.shown["ptr"], button=0x5D20000000 + self.shown["ptr"])
        else:
            pr = None
        s = {"player": {"ptr": PTR, "generation": 1, "pos": self.pos, "rot": self.rot, "hp": self.hp, "hp_max": 1000,
                        "motion": self.motion if self.motion is not None else (26 if self.aimed else 0),
                        "aim_pitch": None},
             "enemies": [dict(e) for e in self.enemies],
             "inventory": [{"slot": 0, "id": 0x100 | self.item, "type": 1, "item": self.item, "rounds": 10, "cap": 10,
                            "grid": 3, "hand": True}],
             "kills": self.kills, "combo": self.combo, "combo_timer": self.combo_timer,
             "mercenaries_phase": R.PHASE_PLAYING, "laser": laser, "prompt": pr, "prompt_read": True}
        s.update(self.extra)
        return s

    def step(self):
        now = self.clock[0]
        if self.pending is not None:                     # last tick's pull lands
            e = self.pending
            e["hp"] = max(0, e["hp"] - self.damage)
            if e["hp"] <= 0:
                self.kill(e)
            else:
                self.stunned[e["ptr"]] = now + self.stun_s
            self.pending = None
        snap = self.snap()
        act = self.bot.tick(snap)
        hold = set(act.get("hold") or ())
        dt = 1.0 / self.hz
        if "zr" in hold and not self.zr and self.aimed:
            tgt = self.target()
            if tgt is not None and R.dot_on(snap["laser"]["at"], tgt["pos"]):
                self.pending = tgt
        self.zr = "zr" in hold
        if "y" in hold and self.shown is not None:       # the press: the move happens, the prompt goes
            e = self.shown
            self.stunned.pop(e["ptr"], None)
            self.floored.discard(e["ptr"])
            self.on_press(self, e)
            self.prompt_on = False
            self.reshow_at = now + 0.4
        if not self.prompt_on and now >= getattr(self, "reshow_at", 1e9):
            self.prompt_on = True
        self.aimed = "zl" in hold
        turn = math.radians(40.0 if self.aimed else 160.0) * dt
        self.rot = R.wrap(self.rot + (turn if "rleft" in hold else -turn if "rright" in hold else 0.0))
        fwd = (1 if "lup" in hold else 0) - (1 if "ldown" in hold else 0)
        side = (1 if "lleft" in hold else 0) - (1 if "lright" in hold else 0)
        if not self.aimed and (fwd or side):
            v = (450.0 if "b" in hold else 300.0) * dt / math.hypot(fwd, side)
            h, left = self.rot, self.rot + math.pi / 2
            self.pos = (self.pos[0] + v * (fwd * math.sin(h) + side * math.sin(left)), self.pos[1],
                        self.pos[2] + v * (fwd * math.cos(h) + side * math.cos(left)))
        if self.combo > 0:
            self.combo_timer = max(0.0, self.combo_timer - dt)
        self.ticks.append((now, hold, self.bot.doing, self.bot.why))
        self.where.append(self.pos)
        self.clock[0] = round(now + dt, 6)
        return hold

    def run(self, seconds):
        for _ in range(int(round(seconds * self.hz))):
            self.step()
        return self

    def until(self, cond, seconds=6.0):
        for _ in range(int(round(seconds * self.hz))):
            self.step()
            if cond(self):
                return True
        return False

    def layer(self):
        return self.bot._specials()


AHEAD = {"pos": (0.0, 0.0, 600.0)}


# --- each character's top moves --------------------------------------------------------------------------------------------
def test_wesker_head_shot_then_in_for_the_cobra_strike_and_it_is_credited():
    sim = Sim([AHEAD], combo=4, combo_timer=9.6)
    assert sim.until(lambda s: s.layer().att is not None and s.layer().att.phase == "rush", 2.0)
    att = sim.layer().att
    assert att.site == "head" and att.want.name == "Cobra Strike"
    st = sim.stats
    assert st["specials_attempts"] == 1 and st["specials_rushes"] == 1
    assert sim.until(lambda s: st["specials_presses"] == 1, 3.0)
    assert sim.until(lambda s: st["specials_completions"] == 1, 1.0)
    row = st["specials_moves"]["Wesker Cobra Strike"]
    assert row == {"attempts": 1, "presses": 1, "completions": 1, "kills": 1, "s": row["s"]} and 0.5 < row["s"] < 4.0
    ch = st["specials_by_character"]["Wesker"]
    assert ch["presses"] == 1 and ch["completions"] == 1 and ch["per_min"] > 0 and st["specials_per_min"] == ch["per_min"]
    assert "Cobra Strike" in st["specials_summary"] and st["specials_labels"]["head"] == {"47": 1}
    rush = [t for t in sim.ticks if t[3].startswith("specials: Wesker Cobra Strike: head stun")]
    assert rush and all("lup" in hold and "zl" not in hold and "zr" not in hold for _t, hold, _d, _w in rush)
    aimed = [t for t in sim.ticks if "specials: Wesker Cobra Strike: aiming his head" in t[3]]
    assert aimed                                          # the why carries the specials line while he aims


@pytest.mark.parametrize("family,cls,name", [("Chris (BSAA)", "uPl00ChrisNormal", "Neckbreaker"),
                                             ("Sheva (BSAA)", "uPl01ShebaNormal", "Throat Slit"),
                                             ("Jill (BSAA)", "uPl02Jill", "Head Grab"),
                                             ("Josh (BSAA)", "uPl04Josh", "Suplex"),
                                             ("Excella", "uPl05Excella", "First Aid")])
def test_the_rear_leg_stun_kills_thigh_shot_then_round_his_side_for_the_rear_prompt(family, cls, name):
    """He faces the player (his heading read): the run goes past his side and the prompt is taken from behind."""
    sim = Sim([dict(AHEAD, rot=math.pi)], character=family, cls=cls, combo=2, combo_timer=9.8)
    sim.reach = 120.0
    in_front = lambda s: S.round_angle(s.pos, s.enemies[0], (0.0, -1.0)) < S.BEHIND_DEG
    sim.prompt_on = False                                 # the game's prompt only behind him (the test's geometry)
    assert sim.until(lambda s: s.layer().att is not None and s.layer().att.phase == "rush", 2.0)
    assert sim.layer().att.site == "leg"
    pulls = [t for t in sim.ticks if "zr" in t[1]]
    assert pulls                                          # the thigh shot was taken (the dot at LEG_AIM_H)
    while sim.clock[0] < 6.0 and sim.stats["specials_presses"] == 0:
        sim.prompt_on = not in_front(sim)
        sim.step()
    fam = family.split(" ")[0]
    assert sim.stats["specials_presses"] == 1 and sim.stats["specials_rear"] == 1
    assert sim.until(lambda s: s.stats["specials_completions"] == 1, 1.0)
    assert sim.stats["specials_moves"][f"{fam} {name}"]["completions"] == 1
    assert sim.stats["specials_labels"]["leg_back"] == {"47": 1}
    assert max(abs(x) for x, _y, _z in sim.where) >= 80.0           # round his side, not through him
    assert max(z for _x, _y, z in sim.where) > 600.0                  # ... to his back


def test_in_front_the_game_gives_the_front_leg_move_then_the_grounded_move_finishes_him():
    """Chris in front of the leg-stunned Majini: the Uppercut (400) floors him, then the Stomp on the ground."""
    sim = Sim([AHEAD], character="Chris (BSAA)", cls="uPl00ChrisNormal", combo=2, combo_timer=9.8)
    sim.reach = 200.0

    def press(s, e):
        if e["ptr"] in s.floored or getattr(s, "uppercut", False):
            s.kill(e)                                     # the Stomp
        else:
            e["hp"] -= 400                                # the Uppercut: floored
            s.uppercut = True
            s.floored.add(e["ptr"])
    sim.on_press = press
    assert sim.until(lambda s: s.stats["specials_presses"] == 1, 4.0)
    moves = sim.stats["specials_moves"]
    assert sim.until(lambda s: s.stats["specials_ground"] == 1, 2.0)
    assert moves["Chris Uppercut"]["presses"] == 1 and moves["Chris Uppercut"]["completions"] == 0
    assert sim.until(lambda s: s.stats["specials_completions"] == 1, 3.0)
    assert moves["Chris Stomp"]["completions"] == 1 and moves["Chris Stomp"]["presses"] == 1
    assert moves["Chris Uppercut"]["attempts"] == 1 and sim.stats["specials_rear"] == 0


def kill_later(sim, delay):
    """on_press: the move's kill lands `delay` after the press (its animation)."""
    def press(s, e):
        s.due = (s.clock[0] + delay, e)
    return press


def run_with_due(sim, seconds):
    for _ in range(int(round(seconds * sim.hz))):
        due = getattr(sim, "due", None)
        if due is not None and sim.clock[0] >= due[0]:
            sim.kill(due[1])
            sim.due = None
        sim.step()


def test_no_trigger_in_the_moves_animation_and_a_kill_late_in_it_is_still_the_moves():
    """At arm's length after the press the crowd fire would pull at once: in the game the animation ignores it, but the
    ledger would call every kill the gun's. The Neckbreaker's kill lands a second into its animation."""
    sim = Sim([AHEAD], combo=4, combo_timer=9.6)
    sim.on_press = kill_later(sim, 1.0)
    assert sim.until(lambda s: s.stats["specials_presses"] == 1, 4.0)
    pressed = sim.clock[0]
    run_with_due(sim, 1.5)
    assert sim.stats["specials_completions"] == 1, sim.stats.get("specials_last")
    anim = [h for t, h, _d, _w in sim.ticks if pressed <= t < pressed + S.ANIM_S - 0.05]
    assert anim and not any("zr" in h for h in anim)
    assert sim.stats["specials_anim_holds"] > 0 and "the move killed him" in sim.stats["specials_last"]


def test_a_front_move_that_kills_late_is_credited_not_its_follow_up():
    sim = Sim([AHEAD], character="Chris (BSAA)", cls="uPl00ChrisNormal", combo=2, combo_timer=9.8)
    sim.reach = 200.0
    sim.on_press = kill_later(sim, 1.6)                   # past GROUND_DELAY_S: the follow-up is already under way
    assert sim.until(lambda s: s.stats["specials_presses"] == 1, 4.0)
    run_with_due(sim, 2.5)
    moves = sim.stats["specials_moves"]
    assert moves["Chris Uppercut"]["completions"] == 1 and sim.stats["specials_completions"] == 1
    assert "Chris Stomp" not in moves and sim.stats["specials_ground"] == 0
    assert "late in its animation" in sim.stats["specials_last"]


def test_rebecca_flame_spray_counts_every_kill_it_makes():
    sim = Sim([AHEAD, {"pos": (400.0, 0.0, 1300.0)}], character="Rebecca (STARS)", cls="uPl07Rebecca",
              combo=3, combo_timer=9.9)

    def spray(s, e):                                      # several at once [S19]
        s.kill(e)
        s.kill(s.enemies[1])
    sim.on_press = spray
    assert sim.until(lambda s: s.stats["specials_completions"] == 1, 5.0)
    assert sim.stats["specials_kills"] == 2 and sim.stats["specials_moves"]["Rebecca Flame Spray"]["kills"] == 2


# --- the combo window -----------------------------------------------------------------------------------------------------
def test_a_special_starts_only_right_after_a_kill_or_with_no_combo_running():
    late = Sim([AHEAD], combo=8, combo_timer=6.5)          # 3.5 s after the kill: the next kill is owed - the gun
    late.run(1.0)
    assert late.stats["specials_attempts"] == 0 and "right after a kill" in late.layer().reason
    assert late.stats["specials_status"].startswith("idle: combo")
    fresh = Sim([AHEAD], combo=8, combo_timer=9.5)
    fresh.run(0.3)
    assert fresh.stats["specials_attempts"] == 1
    none = Sim([AHEAD])                                    # no combo running: any time
    none.run(0.3)
    assert none.stats["specials_attempts"] == 1


def test_a_special_not_yet_pressed_is_dropped_when_the_window_runs_short_and_the_gun_finishes_him():
    sim = Sim([AHEAD], combo=4, combo_timer=9.6)
    sim.prompt_on = False                                  # no prompt comes
    assert sim.until(lambda s: s.layer().att is not None and s.layer().att.phase == "rush", 2.0)
    sim.combo_timer = S.ABORT_LEFT_S - 0.2
    sim.step()
    assert sim.layer().att is None and sim.stats["specials_aborts"] == 1
    assert "the gun finishes him" in sim.stats["specials_last"]
    sim.run(0.5)
    assert any("zl" in hold for _t, hold, _d, _w in sim.ticks[-10:])      # the fight raised the gun at once


def test_once_pressed_a_short_window_does_not_stop_the_move():
    sim = Sim([AHEAD], combo=4, combo_timer=9.6)
    sim.on_press = lambda s, e: None                       # the move's animation: he dies a moment later
    assert sim.until(lambda s: s.stats["specials_presses"] == 1, 4.0)
    sim.combo_timer = 1.0
    sim.step()
    sim.kill(sim.enemies[0])
    sim.step()
    assert sim.stats["specials_completions"] == 1 and sim.stats["specials_aborts"] == 0


def test_no_stagger_in_time_or_a_rush_with_no_prompt_ends_and_the_majini_is_left_a_while():
    sim = Sim([AHEAD], combo=4, combo_timer=9.9)
    sim.prompt_on = False
    sim.combo_timer = 9.9
    assert sim.until(lambda s: s.layer().att is not None and s.layer().att.phase == "rush", 2.0)
    sim.reach = 0.0
    assert sim.until(lambda s: s.layer().att is None, S.STUN_S + 0.5)
    assert "no prompt within" in sim.stats["specials_last"]
    assert sim.layer().blocked.get(0x11, 0) > sim.clock[0]                 # RETRY_S
    sim.combo, sim.combo_timer = 0, 0.0
    sim.run(1.0)
    assert sim.stats["specials_attempts"] == 1                             # not that one again so soon


# --- the gates ----------------------------------------------------------------------------------------------------------
GATES = [
    ("held", dict(motion=106), "held"),
    ("dying", dict(hp=1), "dying"),
    ("low", dict(hp=300), "health"),
    ("crowd near him", dict(others=[{"pos": (150.0, 0.0, 100.0)}]), "another Majini"),
    ("crowd near his target", dict(others=[{"pos": (100.0, 0.0, 700.0)}]), "another Majini"),
    ("crowd", dict(others=[{"pos": at(500, a)} for a in (60, 120, 180)]), "others within"),
    ("boss", dict(target={"hp": 8000, "hp_max": 8000}), "a boss"),
    ("winding", dict(target={"motion": 80}), "winds up"),
    ("dynamite", dict(target={"motion": 70, "class": "uEm21"}), "dynamite"),
    ("shotgun", dict(item=SHOTGUN), "cannot place a site shot"),
    ("operator", dict(extra={"operator_control": True}), "operator"),
]


@pytest.mark.parametrize("name,kw,why", GATES, ids=[g[0] for g in GATES])
def test_no_special_starts_through_a_gate(name, kw, why):
    """Through the bot's whole tick no special starts (where the bot's own earlier rule takes the tick - held, the
    crowd fire - the specials are not even asked), and the gate itself names the reason."""
    target = dict(AHEAD, **kw.get("target", {}))
    sim = Sim([target] + kw.get("others", []), item=kw.get("item", HANDGUN), hp=kw.get("hp", 1000))
    if "motion" in kw:
        sim.motion = kw["motion"]
    if "extra" in kw:
        sim.stats.update(kw["extra"])
    for _ in range(12):
        sim.step()
    assert sim.stats["specials_attempts"] == 0, sim.stats.get("specials_status")
    snap, layer = sim.snap(), sim.layer()
    reason = layer.gate(sim.bot, snap, snap["enemies"][0], start=True)
    if reason is None:                                   # (the weapon is the setup's own check, after the gate)
        layer.consider(sim.bot, snap["player"], snap, snap["enemies"][0], sim.clock[0] + 10.0)
        reason = layer.reason
    assert reason and why in reason, reason


def test_never_while_healing():
    sim = Sim([AHEAD])
    sim.bot.healing = {"player": PTR, "id": 0x304, "hp": 300, "at": 0.0, "uses": 0, "last_use": -1e9, "count": 1,
                       "equips": 1, "equip_at": 0.0, "gun": None}
    assert sim.layer().gate(sim.bot, sim.snap(), sim.enemies[0], start=True) == "healing"


def test_a_majini_closing_in_during_the_rush_stops_it():
    sim = Sim([AHEAD, {"pos": (0.0, 0.0, 1500.0)}], combo=4, combo_timer=9.6)
    sim.prompt_on = False
    assert sim.until(lambda s: s.layer().att is not None and s.layer().att.phase == "rush", 2.0)
    sim.enemies[1]["pos"] = (sim.pos[0] + 120.0, 0.0, sim.pos[2] + 60.0)
    sim.step()
    assert sim.layer().att is None and "another Majini" in sim.stats["specials_last"]


def test_held_or_dying_mid_special_ends_it():
    sim = Sim([AHEAD], combo=4, combo_timer=9.6)
    sim.prompt_on = False
    assert sim.until(lambda s: s.layer().att is not None and s.layer().att.phase == "rush", 2.0)
    sim.motion = 106
    sim.step()
    sim.step()
    assert sim.layer().att is None and sim.stats["specials_aborts"] == 1


def test_he_never_stands_through_a_special():
    """Every tick of a special either aims (ZL: the fight's own stance), moves him (the left stick) or presses the
    prompt (the move itself)."""
    sim = Sim([AHEAD], combo=4, combo_timer=9.6)
    sim.until(lambda s: s.stats["specials_completions"] == 1, 5.0)
    for _t, hold, doing, why in sim.ticks:
        if "specials:" in why:
            assert hold & {"zl", "lup", "ldown", "lleft", "lright", "y"}, (doing, why, hold)


def test_the_site_shot_waits_a_moment_for_the_dot_to_reach_the_head_then_takes_any_hit():
    sim = Sim([AHEAD], combo=4, combo_timer=9.9)
    sim.dot_h = R.CHEST_H                                  # the aim stuck on his chest
    sim.run(S.SITE_PATIENCE_S - 0.1)
    assert sim.stats["specials_site_waits"] > 0 and not any("zr" in h for _t, h, _d, _w in sim.ticks)
    sim.run(0.4)
    assert any("zr" in h for _t, h, _d, _w in sim.ticks)  # never longer than SITE_PATIENCE_S: he fires


def test_the_site_shot_is_one_short_pull_then_its_stagger_is_waited_for_never_longer_than_the_hit_window():
    """A held trigger repeats (2.7 shots/s with the M92F, 25 with fire_rate): held, the shots would kill him before
    any stagger. One pull, then up to HIT_WINDOW_S for its hit; no hit - the next pull."""
    sim = Sim([AHEAD], combo=4, combo_timer=9.9)
    sim.damage = 0                                         # (the shot misses: no stagger comes)
    sim.run(1.6)
    pulls = [t for t, h, _d, _w in sim.ticks if "zr" in h]
    starts = [t for (t, h, _d, _w), (_t0, h0, _d0, _w0) in zip(sim.ticks[1:], sim.ticks) if "zr" in h and "zr" not in h0]
    assert pulls and sim.stats["specials_site_holds"] > 0 and len(starts) >= 2
    assert all(b - a >= S.SITE_PULL_S + S.HIT_WINDOW_S - 0.05 for a, b in zip(starts, starts[1:]))
    assert len(pulls) <= 3 * len(starts)                   # each pull a tick or two
    waits = [w for _t, _h, _d, w in sim.ticks if "its stagger awaited" in w]
    run, longest = 0, 0
    for _t, h, _d, w in sim.ticks:                         # the trigger held back by the specials: one window at most
        run = run + 1 if "its stagger awaited" in w else 0
        longest = max(longest, run)
    assert waits and longest <= round(S.HIT_WINDOW_S * sim.hz) + 1


# --- what he presses without a setup, and the bosses -----------------------------------------------------------------
def test_a_melee_prompt_he_did_not_set_up_is_counted_by_its_label_and_credited():
    sim = Sim([{"pos": (0.0, 0.0, 120.0), "hp": 500}], character="Chris (BSAA)", cls="uPl00ChrisNormal",
              combo=6, combo_timer=4.0)                    # (no setup: the window is short)
    sim.stunned[0x11] = 5.0
    sim.label = 52
    assert sim.until(lambda s: s.stats["specials_completions"] == 1, 1.0)
    assert sim.stats["specials_opportunistic"] == 1 and sim.stats["specials_attempts"] == 0
    assert sim.stats["specials_moves"]["Chris melee (label 52)"]["completions"] == 1
    assert sim.stats["specials_labels"]["unknown"] == {"52": 1}


def test_a_boss_gets_no_setup_his_prompts_are_counted_and_after_the_second_melee_he_steps_away():
    boss = {"pos": (0.0, 0.0, 130.0), "hp": 8000, "hp_max": 8000}
    sim = Sim([boss], character="Chris (BSAA)", cls="uPl00ChrisNormal")
    sim.stunned[0x11] = 30.0
    sim.on_press = lambda s, e: e.__setitem__("hp", e["hp"] - 3000)
    assert sim.until(lambda s: s.stats["specials_boss_melees"] == 2, 3.0)
    assert sim.stats["specials_attempts"] == 0
    second = sim.clock[0]
    sim.stunned.clear()
    sim.stun_s, sim.damage = 0.0, 10                     # (no more prompts: the step is what is watched)
    assert sim.until(lambda s: s.stats["specials_boss_steps"] == 1, 2.0)
    steps = [t for t in sim.ticks if "stepping away from the boss" in t[3]]
    assert steps and all("ldown" in hold for _t, hold, _d, _w in steps)
    assert steps[0][0] >= second + S.BOSS_ANIM_S - 0.1                   # after the move's own animation
    sim.run(S.BOSS_STEP_S + 0.5)
    steps = [t for t in sim.ticks if "stepping away from the boss" in t[3]]
    assert steps[-1][0] - steps[0][0] <= S.BOSS_STEP_S + 0.05
    assert not any("stepping away" in t[3] for t in sim.ticks[-10:])     # then the fight again


# --- REAR_DEFER_S ----------------------------------------------------------------------------------------------------------
def test_a_front_prompt_is_pressed_at_once_unless_rear_defer_holds_it(monkeypatch):
    def run(defer):
        monkeypatch.setattr(S, "REAR_DEFER_S", defer)
        sim = Sim([dict(AHEAD, rot=math.pi)], character="Chris (BSAA)", cls="uPl00ChrisNormal", combo=2,
                  combo_timer=9.8)
        sim.reach = 260.0                                  # the prompt shows while he is still in front
        sim.until(lambda s: s.stats["specials_presses"] == 1, 4.0)
        return sim
    now = run(0.0)
    assert now.stats["specials_rear_defers"] == 0 and "Chris Uppercut" in now.stats["specials_moves"]
    held = run(0.6)
    assert held.stats["specials_rear_defers"] > 0 and held.stats["specials_presses"] == 1   # then pressed all the same
    assert held.stats["specials_rear_defers"] <= int(0.6 * 30) + 1                          # never past REAR_DEFER_S


# --- Wesker's dash ------------------------------------------------------------------------------------------------------------
def test_the_dash_is_off_by_default():
    sim = Sim([AHEAD])
    sim.run(1.0)
    assert not any("rstick" in h or "lstick" in h for _t, h, _d, _w in sim.ticks)


def test_the_dash_then_the_knee_when_on_and_it_checks_itself(monkeypatch):
    monkeypatch.setattr(S, "DASH", True)
    sim = Sim([dict(AHEAD, hp=800)])
    dashed = []

    def step():                                          # the dash: 5 m/s on the click
        hold = sim.step()
        if "rstick" in hold:
            dashed.append(sim.clock[0])
        if dashed and sim.clock[0] - dashed[-1] < 0.6:
            sim.pos = (sim.pos[0], 0.0, sim.pos[2] + 500.0 / 30.0)
        return hold
    for _ in range(40):
        hold = step()
        if "zr" in hold and sim.layer().att is not None and sim.layer().att.kind == "dash":
            break
    assert dashed and sim.stats["specials_dash_attempts"] == 1
    assert sim.layer().att.dash["knee_at"] is not None                    # the knee (ZR) near him
    sim.kill(sim.enemies[0])
    sim.step()
    sim.step()
    assert sim.stats["specials_completions"] == 1 and sim.stats["specials_moves"]["Wesker Knee Cannon"]["kills"] == 1
    assert sim.stats["specials_dash_seen"] == 1 and "dash seen" in sim.stats["specials_dash_status"]


def test_a_dash_that_never_shows_tries_both_sticks_then_turns_itself_off(monkeypatch):
    monkeypatch.setattr(S, "DASH", True)
    monkeypatch.setattr(S, "DASH_GAP_S", 0.0)
    monkeypatch.setattr(S, "GAP_S", 0.0)
    layer = S.Specials({"player_class": "uPl03WeskerNormal", "character": "Wesker (Midnight)"})
    keys = []

    class Bot:                                            # (he never moves: the click does nothing)
        healing, doing, why, _pr = None, "aim", "", None
        stats = layer.stats

        def _gun_down(self):
            pass

        def _turn(self, err, tol=0.0):
            return ()
    bot = Bot()
    t = 0.0
    for _ in range(2 * S.DASH_TRIES):
        snap = {"player": {"ptr": PTR, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000},
                "enemies": [{"ptr": 0x11, "pos": (0.0, 0.0, 600.0), "hp": 800, "hp_max": 800}],
                "inventory": [], "mercenaries_phase": R.PHASE_PLAYING}
        act = layer.consider(bot, snap["player"], snap, snap["enemies"][0], t)
        keys.append(tuple(k for k in act["hold"] if k in ("rstick", "lstick")))
        for k in range(30):
            t += 1 / 30
            layer.drive(bot, snap["player"], snap, t)
        layer._end(t, "test: next")
        t += 0.1
    assert keys[:S.DASH_TRIES] == [("rstick",)] * S.DASH_TRIES
    assert keys[S.DASH_TRIES:] == [("lstick", "rstick")] * S.DASH_TRIES
    assert layer.dash["off"] and "off for the run" in layer.stats["specials_dash_status"]


def test_no_dash_under_its_health_floor_nor_off_the_lane(monkeypatch):
    monkeypatch.setattr(S, "DASH", True)
    low = Sim([AHEAD], hp=500)
    low.run(0.5)
    aside = Sim([{"pos": at(600, 40)}])
    aside.run(0.1)
    assert low.stats["specials_dash_attempts"] == 0 and aside.stats["specials_dash_attempts"] == 0


# --- hot reload -----------------------------------------------------------------------------------------------------------
def test_a_bot_from_before_the_layer_or_with_a_replaced_class_gets_a_fresh_one():
    sim = Sim([AHEAD])
    sim.bot.__dict__.pop("_sp_layer", None)
    sim.step()
    assert isinstance(sim.bot.__dict__["_sp_layer"], S.Specials)

    class Old:                                            # a layer object of a class a reload redefined
        pass
    sim.bot._sp_layer = Old()
    sim.step()
    assert isinstance(sim.bot._sp_layer, S.Specials)


def test_a_broken_layer_never_stops_the_bot(monkeypatch):
    sim = Sim([AHEAD])
    monkeypatch.setattr(S.Specials, "observe", lambda self, bot, snap, now: 1 / 0)
    sim.run(0.3)
    assert "ZeroDivisionError" in sim.stats["specials_error"] and any("zl" in h for _t, h, _d, _w in sim.ticks)


# --- the snapshot's enemy heading -----------------------------------------------------------------------------------------
@pytest.fixture
def _fresh_laser_caches():
    for cache in (R._LASER, R._LASER_MISS, R._NOT_LASER):
        cache.clear()
    yield
    for cache in (R._LASER, R._LASER_MISS, R._NOT_LASER):
        cache.clear()


def test_a_near_majinis_heading_is_read_only_from_a_unit_quaternion(monkeypatch, _fresh_laser_caches):
    from test_re5_switch import round_guest
    monkeypatch.setattr(R, "CYCLE", False)
    g = round_guest()
    e = R.snapshot(g)["enemies"][0]
    assert "rot" not in e                                 # zeros at +0x70: not a rotation
    h = math.radians(-120.0)
    g.put(e["ptr"] + R.E_ROT, struct.pack("<4f", 0.0, math.sin(h / 2), 0.0, math.cos(h / 2)))
    assert R.snapshot(g)["enemies"][0]["rot"] == pytest.approx(h, abs=1e-5)
    g.put(e["ptr"] + R.E_ROT, struct.pack("<4f", 3.0, 0.5, 0.0, 1.0))
    assert "rot" not in R.snapshot(g)["enemies"][0]

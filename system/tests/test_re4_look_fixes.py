"""RE4 look fixes (operator 2026-10-26, the first live stats.look read: Castle, Leon, the semi-auto rifle): (1) the shot
counter took each shot's own fire-motion start for a second shot - a 'miss:no_damage' 70 ms after every real one; (2)
fights interleaved with bonus runs every second or two - now one at a time, with a reason for each change."""
import math

from gbox import re4_merc_bot as B
from tests.test_re4_merc_bot import EM, PL, STRIDE, facing, run, world


def seen(bot, seq, t0=0.0, dt=1 / 30):
    for k, (r, f) in enumerate(seq):
        bot._shot_seen({"r": r, "mframe": f}, t0 + k * dt)


# --- (1) the shot counter ----------------------------------------------------------------------------------------------
def test_a_semi_auto_rifle_shot_is_counted_once_not_twice():
    """Live RAM (120 Hz, 2026-10-26): aim 00 06 01 01 frames 1..9, the shot enters 00 06 02 00 with the aim motion's
    frame (10), the fire motion starts over at 1 a frame later (00 06 02 01), then back to aiming: one shot."""
    bot = B.Bot(world([]), nav=False)
    aim = [((0, 6, 1, 1), float(f)) for f in range(1, 10)]
    shot = [((0, 6, 2, 0), 10.0), ((0, 6, 2, 1), 1.0), ((0, 6, 2, 1), 2.0), ((0, 6, 1, 0), 3.0)]
    seen(bot, aim + shot + aim + shot)
    assert bot.shots.stats["shots"] == 2 and bot.stats["fire_motion_starts"] == 2
    assert bot.stats.get("shots_held", 0) == 0


def test_a_shotgun_shot_whose_motion_restarts_inside_the_fire_state_is_one_shot():
    bot = B.Bot(world([]), nav=False)
    seq = [((0, 6, 1, 1), 27.0), ((0, 6, 2, 0), 28.0), ((0, 6, 2, 0), 1.0)] + \
          [((0, 6, 2, 1), float(f)) for f in range(1, 31)] + [((0, 6, 1, 4), 32.0)]
    seen(bot, seq)
    assert bot.shots.stats["shots"] == 1


def test_held_auto_fire_repeats_still_count_once_the_motion_has_started():
    bot = B.Bot(world([]), nav=False)
    seq = [((0, 6, 1, 1), 9.0), ((0, 6, 2, 0), 10.0), ((0, 6, 2, 1), 1.0), ((0, 6, 2, 1), 2.0), ((0, 6, 2, 1), 3.0),
           ((0, 6, 2, 1), 1.0), ((0, 6, 2, 1), 2.0), ((0, 6, 2, 1), 1.0)]   # the start, then two restarts held
    seen(bot, seq)
    assert bot.shots.stats["shots"] == 3 and bot.stats["shots_held"] == 2
    late = B.Bot(world([]), nav=False)                                    # the entry read after the start already
    seen(late, [((0, 6, 1, 1), 9.0), ((0, 6, 2, 1), 1.0), ((0, 6, 2, 1), 3.0), ((0, 6, 2, 1), 1.0)])
    assert late.shots.stats["shots"] == 2


def test_the_look_shows_one_entry_per_real_rifle_shot():
    now = [0.0]
    m = world([((0, 0, 1500), True)], room=0x402)
    facing(m, 0.0)
    m.put(PL + B.threats_ram.EM_ROUTINE, "4B", 0, 6, 1, 1)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0, 8)
    for r, f in (((0, 6, 2, 0), 10.0), ((0, 6, 2, 1), 1.0), ((0, 6, 2, 1), 2.0), ((0, 6, 1, 0), 3.0)):
        m.put(PL + B.threats_ram.EM_ROUTINE, "4B", *r)
        m.put(PL + B.threats_ram.EM_FRAME, ">fH", f, 30)
        run(bot, m, now, now[0] + 0.05)
    assert len(bot.look.snapshot()["shots"]) == 1 and bot.shots.stats["shots"] == 1


# --- (2) one at a time: the fight or the bonus run ---------------------------------------------------------------------
def place(m, x, z):
    m.put(EM + STRIDE + 0x94, ">3f", float(x), 0.0, float(z))


def commits(bot):
    return [d for d in bot.look.snapshot()["decisions"] if d["decision"] in ("engage", "break off for the bonus")]


def test_a_bonus_run_gives_way_only_to_a_ganado_about_to_reach_him_and_a_fight_is_finished():
    """Live 21:50: "hold fire: wall in the aim line" -> "run to a time bonus 2.6 m" -> "turning to slot 71 (gun down)"
    -> "run to a time bonus 2.5 m". A Ganado walking 2.0 .. 3.0 m away no longer flips him; the fight that starts
    holds until none is in view within 3 m for FIGHT_KEEP_S, then the bonus, each with its reason."""
    now = [0.0]
    m = world([((0, 0, 2600), True)], room=0x400)                         # the Village: time bonuses on the field
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0, 4)
    assert bot.commit[0] == "bonus"                                       # 2.6 m, not coming: the bonus first
    t = now[0]
    for k in range(30):                                                   # he walks 2.2 .. 2.8 m away for 1.5 s
        place(m, 0, 2500 + 300 * math.sin(k / 3))
        run(bot, m, now, t + 0.05 * (k + 1))
    assert bot.commit[0] == "bonus" and bot.stats.get("commit_changes") == 1   # no flip on the band's edge
    place(m, 0, 1700)                                                     # 1.7 m: about to reach him
    run(bot, m, now, now[0] + 0.05, 3)
    assert bot.commit[0] == "fight" and "the bonus run gives way" in bot.commit[2]
    place(m, 0, 2700)                                                     # he steps back to 2.7 m: the fight goes on
    acts = run(bot, m, now, now[0] + 0.05, 20)
    assert bot.commit[0] == "fight" and all(a.get("tap") is None for a in acts)
    place(m, 0, 9000)                                                     # gone: FIGHT_KEEP_S later, the bonus
    run(bot, m, now, now[0] + 0.05, int(B.FIGHT_KEEP_S / 0.05) + 6)
    assert bot.commit[0] == "bonus" and "off to the time bonus" in bot.commit[2]
    reasons = [d["reason"] for d in commits(bot)]
    assert len(reasons) == 3 and "gives way" in reasons[1] and "off to the time bonus" in reasons[2]


def test_a_fight_without_bonuses_left_takes_any_ganado_in_view():
    now = [0.0]
    m = world([((0, 0, 3000), True)], room=0x402)                         # no time bonuses on this map
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0, 3)
    assert bot.commit[0] == "fight" and bot.stats["phase"] in ("fight", "run_to_target")


def test_an_attack_landing_cuts_into_the_bonus_run_at_once(monkeypatch):
    now = [0.0]
    m = world([((0, 0, 2600), True)], room=0x400)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0, 2)
    assert bot.commit[0] == "bonus"
    s = B.snapshot(m)
    swing = B.threats_ram.Threat(1, "swing", 0.8, (0.0, 0.0, 2600.0), 2600.0, enemy=s["enemies"][0])
    bot._threats = [swing]
    why = bot._danger(s["player"], s, B.BONUS_SAFE_R, now[0])
    assert why.startswith("swing from slot 1 lands in 0.8")
    assert bot._commit("fight", why, now[0] + 0.1, force="lands" in why) and bot.commit[0] == "fight"


# --- (1b) the rifle's scope aim: stale aim readings ---------------------------------------------------------------------
def test_the_aim_readings_are_marked_stale_while_the_yaw_offset_holds_the_games_marker():
    m = world([((0, 0, 1500), True)], room=0x402)
    m.put(PL + B.threats_ram.EM_ROUTINE, "4B", 0, 6, 1, 1)
    m.put(PL + B.AIM_YAW_OFF, ">f", 123.0)                                # the marker (the semi-auto rifle's scope)
    assert B.snapshot(m)["player"]["aim_live"] is False
    m.put(PL + B.AIM_YAW_OFF, ">f", 0.12)
    assert B.snapshot(m)["player"]["aim_live"] is True
    m.put(PL + B.AIM_YAW_OFF, ">f", 123.0)
    m.put(PL + B.threats_ram.EM_ROUTINE, "4B", 0, 0, 1, 0)                # not aiming: nothing to judge
    assert B.snapshot(m)["player"]["aim_live"] is True


def test_with_stale_aim_readings_the_stick_never_steers_the_pitch_and_the_shot_goes_level():
    """Live: the bot pushed up from a stale pitch (-0.72, the game's marker in the yaw offset), nothing moved, and after
    PITCH_LIMIT_S it fired anyway ("the game's limit"); stats.look had those shots on the floor / no damage."""
    now = [0.0]
    m = world([((0, 0, 1500), True)], room=0x402)
    facing(m, 0.0)
    m.put(PL + B.threats_ram.EM_ROUTINE, "4B", 0, 6, 1, 1)
    m.put(PL + B.AIM_YAW_OFF, ">f", 123.0)
    m.put(B.AIM_PITCH, ">f", -0.72)                                      # a stale pitch far below the head band
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = run(bot, m, now, 0.0, 14)
    assert not any({"up", "down"} & a.get("hold", set()) for a in acts if "r" in a.get("hold", set()))
    assert any("a" in a.get("hold", set()) for a in acts) and bot.stats["aim_scope_level"] >= 1
    s = B.snapshot(m)
    assert bot._aim_line(s["player"], s)[0] == "target"                  # the aim line level: on him, not the floor
    m.put(PL + B.AIM_YAW_OFF, ">f", 0.0)                                  # live readings: the pitch is steered again
    bot2 = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = run(bot2, m, now, now[0] + 0.05, 14)
    assert any({"up", "down"} & a.get("hold", set()) for a in acts)


def test_a_shot_is_recorded_with_the_aim_line_its_trigger_was_pulled_on():
    """Live: 'hit:ganado' then 'miss:wall' 70 ms later - the second record (the phantom) read the line after the
    target had died, so it ended on the wall behind him. The look keeps the line the trigger was pulled on."""
    now = [0.0]
    m = world([((0, 0, 1500), True)], room=0x402)
    facing(m, 0.0)
    m.put(PL + B.threats_ram.EM_ROUTINE, "4B", 0, 6, 1, 1)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0, 8)                                              # on him: the trigger pulled on "target"
    assert bot._look_ctx.get("line", (("none",),))[0][0] == "target"
    bot.st = {"walls": [[-2000.0, 2500.0, 2000.0, 2500.0, -1000.0, 3000.0, 0.0]]}   # a wall behind him
    m.put(EM + STRIDE + B.EM_HP, ">hh", 0, 1000)                          # the shot killed him: no longer in the line
    m.put(PL + B.threats_ram.EM_ROUTINE, "4B", 0, 6, 2, 0)
    m.put(PL + B.threats_ram.EM_FRAME, ">fH", 10.0, 30)
    run(bot, m, now, now[0] + 0.05)
    shot = bot.look.snapshot()["shots"][-1]
    assert shot["dot_on"] == "target" and bot.look.snapshot()["walls_shot"] == 0

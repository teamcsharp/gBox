"""The Mercenaries 3D bot's decisions on synthetic snapshots (gbox.mercs.titles.merc3d_bot): the operator's rules -
fire only on a confirmed line or point blank, never at the sky, crowd control first, chase for the combo."""
import math

from gbox.mercs.titles import merc3d_bot as B

C = B.CONTROLS


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def snap(enemies, me=(0.0, 0.0, 0.0), rot=0.0, ray=None, hp=1000.0):
    return {"player": {"pos": me, "rot": rot, "hp": hp, "hp_max": 1000.0},
            "enemies": [{"ptr": 0x08500000 + 0x1000 * i, "pos": p, "hp": h, "hp_max": 300.0, "class": "uEm"}
                        for i, (p, h) in enumerate(enemies)],
            "aim": {"up": ray is not None, "ray": ray}}


def test_no_player_or_no_foes_holds_nothing():
    b = B.Bot(clock=Clock())
    assert b.tick({"player": None}) == {"hold": ()}
    assert b.tick(snap([((0, 0, 500), 0)])) == {"hold": ()} and b.doing == "no_foes"


def test_turns_with_the_gun_down_toward_a_target_off_to_the_side():
    b = B.Bot(clock=Clock())
    act = b.tick(snap([((500.0, 0.0, 0.0), 300)]))                # +x = heading +90 deg: a larger heading
    assert b.doing == "turn" and act["hold"] == (C["left"],) and C["raise"] not in act["hold"]


def test_fires_only_when_the_ray_runs_through_him():
    b = B.Bot(clock=Clock())
    e = ((0.0, 0.0, 1500.0), 300)
    on = ((0.0, 150.0, 0.0), (0.0, 120.0, 1520.0))               # muzzle to a dot just behind his chest
    act = b.tick(snap([e], ray=on))
    assert C["fire"] in act["hold"] and C["raise"] in act["hold"] and b.stats["long_shots"] == 1
    b2 = B.Bot(clock=Clock())
    wall = ((0.0, 150.0, 0.0), (0.0, 120.0, 700.0))              # the ray stops at a wall 8 m short of him
    act = b2.tick(snap([e], ray=wall))
    assert C["fire"] not in act["hold"] and b2.doing == "aim"


def test_point_blank_fires_without_a_ray():
    b = B.Bot(clock=Clock())
    act = b.tick(snap([((0.0, 0.0, 120.0), 300)]))
    assert C["fire"] in act["hold"] and b.stats["point_blank_shots"] == 1


def test_the_sky_guard_pushes_the_aim_down():
    b = B.Bot(clock=Clock())
    e = ((0.0, 0.0, 800.0), 300)
    sky = ((0.0, 150.0, 0.0), (0.0, 900.0, 800.0))              # the dot far above his head
    act = b.tick(snap([e], ray=sky))
    assert C["aim_down"] in act["hold"] and C["aim_up"] not in act["hold"] and C["fire"] not in act["hold"]
    assert b.stats["sky_corrections"] == 1


def test_crowd_control_kites_away_from_the_centroid():
    b = B.Bot(clock=Clock())
    crowd = [((100.0, 0.0, 150.0), 300), ((-100.0, 0.0, 150.0), 300), ((0.0, 0.0, 200.0), 300)]
    act = b.tick(snap(crowd))                                    # all in front: run away means turning round
    assert b.doing == "kite" and b.stats["kites"] == 1
    act = b.tick(snap(crowd, rot=math.pi))                       # facing away now: run
    assert C["forward"] in act["hold"] and C["run"] in act["hold"]


def test_one_behind_at_arms_length_is_a_reason_to_move():
    b = B.Bot(clock=Clock())
    b.tick(snap([((0.0, 0.0, -100.0), 300)]))
    assert b.doing == "kite"


def test_a_far_target_gets_a_look_for_a_long_shot_then_the_chase():
    clock = Clock()
    b = B.Bot(clock=clock)
    far = [((0.0, 0.0, 3000.0), 300), ((0.0, 0.0, 5000.0), 300)]
    act = b.tick(snap(far))
    assert b.doing == "aim" and C["raise"] in act["hold"] and C["fire"] not in act["hold"]   # never a blind long shot
    clock.t += B.LONG_LOOK_S + 0.1
    act = b.tick(snap(far))
    assert b.doing == "chase" and C["forward"] in act["hold"] and C["run"] in act["hold"]


def test_chases_a_far_target_behind_him():
    b = B.Bot(clock=Clock())
    act = b.tick(snap([((0.0, 0.0, -3000.0), 300)]))
    assert b.doing == "chase"


def test_a_target_without_a_line_is_dropped_for_another():
    clock = Clock()
    b = B.Bot(clock=clock)
    far = ((0.0, 0.0, 800.0), 300)
    wall = ((0.0, 150.0, 0.0), (0.0, 120.0, 300.0))
    b.tick(snap([far], ray=wall))
    clock.t += B.STUCK_S + 0.1
    b.tick(snap([far], ray=wall))
    assert b.stats["los_blocks"] == 1 and b.target is None


def test_nearest_threat_in_front_is_chosen():
    b = B.Bot(clock=Clock())
    b.tick(snap([((0.0, 0.0, 700.0), 300), ((0.0, 0.0, 400.0), 300)]))
    assert b.target == 0x08501000


def test_the_fire_key_is_learned_from_his_vitality():
    """No damage point blank: the trigger moves to the next candidate; damage: it stays (kept for the process)."""
    B.FIRE.update(key="a", confirmed=False)
    clock = Clock()
    b = B.Bot(clock=clock)
    e = [((0.0, 0.0, 120.0), 600)]
    act = b.tick(snap(e))
    assert "a" in act["hold"]
    for _ in range(10):                                          # 2 s of trigger time, his vitality unchanged
        clock.t += 0.2
        act = b.tick(snap(e))
    assert B.FIRE["key"] == "y" and "y" in act["hold"] and b.stats["fire_key_switches"] == 1
    clock.t += 0.2
    b.tick(snap([((0.0, 0.0, 120.0), 540)]))                     # he took damage: y is the trigger
    assert B.FIRE["confirmed"] is True and b.stats["fire_key"] == "y"
    for _ in range(12):
        clock.t += 0.2
        act = b.tick(snap([((0.0, 0.0, 120.0), 540)]))
    assert B.FIRE["key"] == "y"
    B.FIRE.update(key=B.CONTROLS["fire"], confirmed=False)


def test_semi_automatic_target_receives_repeated_trigger_edges_without_lowering_aim(monkeypatch):
    monkeypatch.setitem(B.FIRE, "key", "y")
    monkeypatch.setitem(B.FIRE, "confirmed", True)
    clock = Clock()
    bot = B.Bot(clock=clock)
    held = False
    released_at = None
    hits = 0
    for _ in range(120):
        act = bot.tick(snap([((0, 0, 300), 600)]))
        assert C["raise"] in act["hold"]
        down = "y" in act["hold"]
        # An edge-triggered gun accepts another shot only after a visible
        # released frame. Test the resulting action stream, not private phase state.
        if down and not held:
            assert released_at is None or clock.t - released_at >= 1 / 30
            hits += 1
        elif held and not down:
            released_at = clock.t
        held = down
        clock.t += 1 / 60
    assert hits >= 8


def test_slow_ticks_cannot_skip_trigger_release_and_target_loss_releases_everything(monkeypatch):
    monkeypatch.setitem(B.FIRE, "key", "y")
    monkeypatch.setitem(B.FIRE, "confirmed", True)
    clock = Clock()
    bot = B.Bot(clock=clock)
    target = snap([((0, 0, 300), 600)])
    assert "y" in bot.tick(target)["hold"]
    clock.t += 5
    assert bot.tick(target)["hold"] == (C["raise"],)
    clock.t += 5
    assert "y" in bot.tick(target)["hold"]
    assert bot.tick(snap([]))["hold"] == ()
    assert "y" in bot.tick(target)["hold"]

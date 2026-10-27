"""gbox.mercs.bot_look: the shared stats["look"] view (operator 2026-10-26: "when i say 'look at the bot' i want you able
to see the last things and results of the last bullets being fired by the bot") - one schema for RE4 and RE5."""
import json

from gbox.mercs import bot_look as L

SHOT_KEYS = {"t", "weapon", "gate", "target", "aim_err_deg", "dot_on", "outcome", "hp_delta"}
TARGET_KEYS = {"id", "kind", "dist_m", "bearing_deg"}


def clock(start=1_800_000_000.0):
    now = [start]
    return now, (lambda: now[0])


def test_the_snapshot_has_exactly_the_shared_schema():
    now, ep = clock()
    look = L.BotLook(epoch=ep)
    shot = look.record_shot("Shotgun (0x2c)", "on him", L.make_target(3, "ganado", 4.25, -12.34), aim_err_deg=1.26,
                            dot_on="target")
    look.resolve(shot, "hit:ganado", -45)
    look.record_decision("fight", "fire", "on slot 3 d 4250 yaw -1.3 FIRE")
    snap = look.snapshot()
    assert set(snap) == {"shots", "decisions", "idle_among_foes_s", "walls_shot"}
    s = snap["shots"][0]
    assert set(s) == SHOT_KEYS and set(s["target"]) == TARGET_KEYS
    assert s == {"t": 1_800_000_000.0, "weapon": "Shotgun (0x2c)", "gate": "on him",
                 "target": {"id": "3", "kind": "ganado", "dist_m": 4.2, "bearing_deg": -12.3},
                 "aim_err_deg": 1.3, "dot_on": "target", "outcome": "hit:ganado", "hp_delta": -45}
    assert snap["decisions"] == [{"t": 1_800_000_000.0, "phase": "fight", "decision": "fire",
                                  "reason": "on slot 3 d 4250 yaw -1.3 FIRE"}]
    assert isinstance(snap["idle_among_foes_s"], float) and snap["walls_shot"] == 0
    json.dumps(snap)                                                      # telemetry-ready


def test_a_shot_at_no_foe_and_bad_values_still_fit_the_schema():
    look = L.BotLook(epoch=lambda: 5.0)
    s = look.record_shot(None, None, None, aim_err_deg=float("nan"), dot_on="laser?", outcome="maybe", hp_delta="x")
    assert s["target"] == {"id": None, "kind": "none", "dist_m": 0.0, "bearing_deg": 0.0}
    assert s["weapon"] == "unknown" and s["gate"] == "" and s["aim_err_deg"] is None
    assert s["dot_on"] == "none" and s["outcome"] == "unknown" and s["hp_delta"] is None
    assert L.make_target(1, "boss", 2.0, 270.0)["bearing_deg"] == -90.0         # wrapped to -180 .. 180
    assert L.outcome_text("hit:") == "unknown" and L.outcome_text("miss:wall") == "miss:wall"


def test_the_buffers_keep_the_newest_thirty_newest_last():
    now, ep = clock()
    look = L.BotLook(epoch=ep)
    for k in range(45):
        now[0] += 0.05
        look.record_shot("TMP (0x30)", "on him", L.make_target(k, "ganado", 3.0, 0.0), dot_on="target")
        look.record_decision("fight" if k % 2 else "run_to_target", "fire" if k % 2 else "run", f"step {k}")
    snap = look.snapshot()
    assert len(snap["shots"]) == L.MAX_SHOTS and snap["shots"][-1]["target"]["id"] == "44"
    assert snap["shots"][0]["target"]["id"] == "15"
    assert len(snap["decisions"]) == L.MAX_DECISIONS and snap["decisions"][-1]["reason"] == "step 44"


def test_a_repeated_decision_updates_its_reason_and_keeps_its_start():
    now, ep = clock()
    look = L.BotLook(epoch=ep)
    assert look.record_decision("fight", "aim", "yaw +8.0")
    now[0] += 0.5
    assert not look.record_decision("fight", "aim", "yaw +3.1")
    assert look.snapshot()["decisions"] == [{"t": 1_800_000_000.0, "phase": "fight", "decision": "aim",
                                             "reason": "yaw +3.1"}]
    now[0] += 0.5
    assert look.record_decision("fight", "fire", "on him")
    assert [d["decision"] for d in look.snapshot()["decisions"]] == ["aim", "fire"]


def test_walls_shot_counts_each_shot_into_a_wall_once():
    look = L.BotLook(epoch=lambda: 1.0)
    a = look.record_shot("Handgun (0x23)", "on him", L.make_target(2, "ganado", 6.0, 3.0), dot_on="wall")
    look.resolve(a, "miss:wall")                                          # read on the wall already: once
    b = look.record_shot("Handgun (0x23)", "on him", L.make_target(2, "ganado", 6.0, 3.0), dot_on="target")
    look.resolve(b, "miss:wall")                                          # found to be a wall afterwards
    look.resolve(b, "miss:wall")
    look.record_shot("Handgun (0x23)", "on him", L.make_target(2, "ganado", 6.0, 3.0), dot_on="floor")
    assert look.snapshot()["walls_shot"] == 2
    look.new_round()
    snap = look.snapshot()
    assert snap["walls_shot"] == 0 and len(snap["shots"]) == 3           # the last shots stay in view


def test_the_idle_streak_grows_only_among_foes_with_nothing_done():
    now, ep = clock()
    look = L.BotLook(epoch=ep)
    for _ in range(21):                                                   # 1 s standing among foes
        look.tick_idle(foes_near=True, busy=False)
        now[0] += 0.05
    assert abs(look.snapshot()["idle_among_foes_s"] - 1.0) < 0.06
    look.tick_idle(foes_near=True, busy=True)                             # he shoots / moves: over
    assert look.snapshot()["idle_among_foes_s"] == 0.0 and look.idle_max_s >= 0.95
    look.tick_idle(foes_near=False, busy=False)                           # alone and still: not idle among foes
    now[0] += 5.0
    look.tick_idle(foes_near=False, busy=False)
    assert look.idle_s == 0.0
    look.tick_idle(foes_near=True, busy=False)
    now[0] += 30.0                                                        # a stalled caller: at most 1 s a call
    assert look.tick_idle(foes_near=True, busy=False) == L.IDLE_STEP_MAX_S


def test_the_snapshot_is_a_copy_the_server_can_hold():
    look = L.BotLook(epoch=lambda: 2.0)
    shot = look.record_shot("Rifle (0x2e)", "on him", L.make_target(1, "ganado", 12.0, 0.5), dot_on="target")
    snap = look.snapshot()
    look.resolve(shot, "miss:no_damage")
    snap["shots"][0]["target"]["id"] = "changed"
    assert snap["shots"][0]["outcome"] == "unknown"                       # taken before the result
    assert look.snapshot()["shots"][0]["target"]["id"] == "1" and look.snapshot()["shots"][0]["outcome"] == "miss:no_damage"


def test_the_worker_telemetry_carries_stats_look_and_only_within_its_bound(monkeypatch):
    """The watch panel / "look at the bot" read the autoplay telemetry: stats["look"] goes with the scalar stats (other
    dict stats stay out, as before); a look that would not fit the bound is left out, never the whole packet."""
    from types import SimpleNamespace
    from gbox import tools
    threads, packets = [], []

    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target
            threads.append(self)

        def start(self):
            pass

    monkeypatch.setattr(tools.threading, "Thread", Thread)
    monkeypatch.setattr(tools.time, "sleep", lambda _: None)
    monkeypatch.setattr(tools, "_ap_headers", lambda ctx: {})
    monkeypatch.setattr(tools.httpx, "post", lambda *a, **kw: packets.append(kw["json"]))
    look = L.BotLook(epoch=lambda: 3.0)
    look.record_shot("Handgun (0x23)", "on him", L.make_target(1, "ganado", 2.0, 4.0), 0.5, "wall", "miss:wall")
    live = {"phase": "fight", "look": look.snapshot(), "round_audit": {"verdict": "OK"}}
    tools._telemetry({"sid": "s1", "live": live}, SimpleNamespace(server="http://test", job_id="j"))
    threads[0].target()                                                   # the run is over: its last packet
    assert packets[-1]["stats"] == {"phase": "fight", "look": live["look"]}
    live["look"] = dict(live["look"], decisions=[{"t": 1.0, "phase": "x", "decision": "y", "reason": "z" * 50_000}])
    assert "look" not in tools._telemetry_blocks(live)

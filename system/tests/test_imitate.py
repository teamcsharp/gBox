"""Autoplay from the operator's recorded play (gbox.imitate) and the autoplay tool's modes, chaining and pad chord."""
import random
import threading
from types import SimpleNamespace

import pytest

from gbox import imitate, padstate


def pad(at, events=(), stick=None, i=[0]):
    i[0] += 1
    return {"id": i[0], "kind": "pad", "at": at,
            "payload": {"events": [{"key": k, "down": d} for k, d in events], "stick": stick or {"x": 0, "y": 0},
                        "rstick": {"x": 0, "y": 0}}}


def test_held_timeline_names_buttons_for_each_emulator():
    ev = [pad(1.0, [("b", True)], {"x": 0.9, "y": 0}), pad(1.1, [("b", False), ("up", True)]),
          {"id": 99, "kind": "mod_action", "at": 1.2, "payload": {}}]
    assert imitate.held_timeline(ev, "retroarch", "dreamcast") == [(1.0, frozenset({"b", "lright"})), (1.1, frozenset({"up"}))]
    # Dolphin on Windows: GameCube keyboard names (Xbox A = RetroPad b = GC A), main stick = arrows, D-pad = t/g/f/h
    assert imitate.held_timeline(ev, "dolphin", "gamecube") == [(1.0, frozenset({"a", "right"})), (1.1, frozenset({"t"}))]


def test_replay_plan_keeps_timing_from_boot_and_caps_idle_gaps():
    tl = [(103.0, frozenset({"start"})), (103.2, frozenset()), (200.0, frozenset({"a"})), (200.1, frozenset({"a"})),
          (200.3, frozenset())]
    plan = imitate.replay_plan(tl, 100.0, idle_cap=20)
    assert plan[0] == (3.0, [{"key": "start", "down": True}])
    assert plan[1] == (3.2, [{"key": "start", "down": False}])
    assert plan[2][0] == pytest.approx(23.2)                  # 96.8 s away from the pad played as 20 s
    assert [r for _, rows in plan for r in rows][-1] == {"key": "a", "down": False}
    assert len(plan) == 4                                      # an unchanged report sends nothing


def test_replay_plan_releases_before_pressing_and_lets_go_at_the_end():
    plan = imitate.replay_plan([(1.0, frozenset({"lleft"})), (1.5, frozenset({"lright"}))], 0.0)
    assert plan[1][1] == [{"key": "lleft", "down": False}, {"key": "lright", "down": True}]
    assert plan[-1][1] == [{"key": "lright", "down": False}]


def test_pick_run_prefers_the_newest_real_run_on_the_same_emulator():
    runs = [{"id": "poke", "adapter": "dolphin", "updated": 9, "events": {"pad": 30}},
            {"id": "old", "adapter": "dolphin", "updated": 1, "events": {"pad": 900}},
            {"id": "ra", "adapter": "retroarch", "updated": 5, "events": {"pad": 900}},
            {"id": "new", "adapter": "dolphin", "updated": 3, "events": {"pad": 500}}]
    assert imitate.pick_run(runs, "dolphin")["id"] == "new"
    assert imitate.pick_run(runs, "retroarch")["id"] == "ra"
    assert imitate.pick_run(runs, "mame")["id"] == "ra"         # no run on this emulator: the newest real run
    assert imitate.pick_run(runs, "dolphin", "poke")["id"] == "poke"
    assert imitate.pick_run([runs[0]], "dolphin") is None


def test_bursts_split_on_idle_and_cut_long_holds_into_moves():
    f = frozenset
    tl = [(0.0, f({"x"})), (0.1, f()), (0.2, f({"x"})), (0.3, f()),       # 0.1 s apart: one burst (a double tap)
          (1.0, f({"lright"})), (1.5, f({"lright", "x", "start"})), (3.2, f({"lright"})), (3.3, f())]
    out = imitate.bursts(tl)
    assert [start for start, _ in out] == [0.0, 1.0, 3.2]
    assert out[0][1] == [(0.0, f({"x"})), (0.1, f()), (0.2, f({"x"})), (0.3, f())]
    assert out[1][1] == [(0.0, f({"lright"})), (0.5, f({"lright", "x"})), (2.2, f())]   # start never learned; cut at 2 s
    assert out[2][1] == [(0.0, f({"lright"})), (0.1, f())]


def test_learn_counts_moves_follow_ups_and_gaps():
    f = frozenset
    tl = []
    for t in (0.0, 1.0, 2.0):                                   # x, then down+b, three times
        tl += [(t, f({"x"})), (t + 0.1, f()), (t + 0.5, f({"down", "b"})), (t + 0.7, f())]
    m = imitate.learn(tl)
    assert m["total"] == 6 and len(m["bursts"]) == 2
    assert [b["n"] for b in m["bursts"]] == [3, 3]
    assert m["follows"] == {"0": {1: 3}, "1": {0: 2}}
    assert m["gaps"] == [0.4, 0.3, 0.4, 0.3, 0.4]


def test_style_follows_the_operators_order_and_play_style_lets_go():
    m = {"bursts": [{"steps": [[0, ["x"]], [0.1, []]], "n": 1}, {"steps": [[0, ["lright"]], [0.2, ["lright", "a"]], [0.3, []]], "n": 1}],
         "follows": {"0": {"1": 5}, "1": {"0": 5}}, "gaps": [0.1], "total": 2}
    st = imitate.Style(m, random.Random(1))
    sent, slept = [], []
    n = imitate.play_style(st, send=sent.append, stopped=lambda: False, sleep=slept.append, limit=4)
    assert n == 4
    held = set()
    for rows in sent:
        for r in rows:
            held.add(r["key"]) if r["down"] else held.discard(r["key"])
    assert held == set()                                        # nothing left held
    assert all(r["key"] not in imitate.NO_LEARN for rows in sent for r in rows)


def test_play_plan_skips_what_already_passed_and_stops_on_takeover():
    now = [0.0]
    clock = lambda: now[0]
    def sleep(s): now[0] += max(s, 0.01)
    plan = [(1.0, ["a"]), (2.0, ["b"]), (5.0, ["c"])]
    sent = []
    out = imitate.play_plan(plan, send=sent.append, stopped=lambda: now[0] > 2, clock=clock, sleep=sleep, offset=1.5)
    assert sent == [["b"]] and out["completed"] is False


def test_chord_starts_without_counting_as_a_touch(monkeypatch):
    sid = "s-chord"
    padstate.PLAYER_TOUCH.pop(sid, None)
    fire, ch = padstate.chord_step(sid, set(), {"select"}, False, False)
    assert not fire and not ch and padstate.PLAYER_TOUCH[sid]   # Select alone is a touch (hands control back)
    padstate.PLAYER_TOUCH[sid] = 0
    fire, ch = padstate.chord_step(sid, {"select"}, {"select", "b"}, False, ch)
    assert fire and ch and padstate.PLAYER_TOUCH[sid] == 0       # Select+A: the chord, not a touch
    fire, ch = padstate.chord_step(sid, {"select", "b"}, {"select"}, False, ch)
    assert not fire and ch and padstate.PLAYER_TOUCH[sid] == 0   # letting go of the chord isn't a touch either
    fire, ch = padstate.chord_step(sid, {"select"}, set(), False, ch)
    assert not ch and padstate.PLAYER_TOUCH[sid] == 0
    fire, ch = padstate.chord_step(sid, set(), {"x"}, False, ch)
    assert not fire and padstate.touched_after(sid, 1)         # real play afterwards is a touch


# --- the autoplay tool ---

class FakeDriver:
    runs = []

    def __init__(self, *a, **k):
        self.stopped, self.trace = False, []

    def run_mission(self, m, **k):
        FakeDriver.runs.append(m["name"])
        return {"ok": True}


@pytest.fixture
def ap(monkeypatch, tmp_path):
    from gbox import tools, autoplay as apmod
    FakeDriver.runs = []
    monkeypatch.setattr(apmod, "Driver", FakeDriver)
    sess = [{"session_id": "s1", "game_id": "g1", "started": 0}]
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: SimpleNamespace(json=lambda: sess, raise_for_status=lambda: None))
    sent = []
    ad = SimpleNamespace(name="retroarch", supported={"send_input"}, send_input=sent.append, reset=lambda: sent.append("reset"))
    monkeypatch.setitem(tools.SESSIONS, "s1", (ad, {"platform": "dreamcast", "title": "T"}))
    monkeypatch.setattr(tools, "AUTOPLAY", {})
    ctx = SimpleNamespace(server="http://x", headers={"authorization": "Bearer t"}, config=SimpleNamespace(runtime=tmp_path))
    return SimpleNamespace(tools=tools, ctx=ctx, sent=sent, sess=sess)


def test_missions_chain_through_then(ap, monkeypatch):
    t = ap.tools
    monkeypatch.setattr(t, "_missions", lambda game_id=None: [{"name": "m1", "then": "m2"}, {"name": "m2"}])
    r = t.autoplay(t.AutoplayIn(session_id="s1", op="start", mission="m1", mode="mission"), ap.ctx)["result"]
    assert r["started"] == "m1"
    t.AUTOPLAY["s1"]["thread"].join(5)
    assert FakeDriver.runs == ["m1", "m2"]                      # the chain used to stop after the first mission
    assert t.AUTOPLAY["s1"]["ended"]


def test_learned_mode_needs_enough_play_then_plays_it(ap, monkeypatch):
    t = ap.tools
    monkeypatch.setattr(t, "LEARNED", {})
    monkeypatch.setattr(t, "_recorded_play", lambda ctx, gid: [{"id": "r1", "events": {"pad": 50}, "adapter": "retroarch"}])
    few = [pad(1.0, [("x", True)]), pad(1.1, [("x", False)])]
    monkeypatch.setattr(t, "_run_events", lambda ctx, rid: few)
    with pytest.raises(ValueError, match="bursts recorded"):
        t.autoplay(t.AutoplayIn(session_id="s1", op="start", mode="learned"), ap.ctx)
    many = []
    for i in range(30):
        many += [pad(i, [("x", True)], {"x": 0.9, "y": 0}), pad(i + 0.1, [("x", False)])]
    t.LEARNED.clear()
    monkeypatch.setattr(t, "_run_events", lambda ctx, rid: many)
    stop = threading.Event()
    monkeypatch.setattr(t.time, "sleep", lambda s: stop.wait(0.001))
    r = t.autoplay(t.AutoplayIn(session_id="s1", op="start", mode="learned"), ap.ctx)["result"]
    assert r["mode"] == "learned"
    run = t.AUTOPLAY["s1"]
    for _ in range(200):
        if ap.sent:
            break
        stop.wait(0.01)
    run["driver"].stopped = True
    run["thread"].join(5)
    keys = {e["key"] for rows in ap.sent if isinstance(rows, list) for e in rows}
    assert {"x", "lright"} <= keys


def test_auto_mode_at_the_title_screen_replays_the_operators_run(ap, monkeypatch):
    t = ap.tools
    ap.sess[0]["started"] = t.time.time() - 5                   # five seconds after launch
    monkeypatch.setattr(t, "_missions", lambda game_id=None: [])
    monkeypatch.setattr(t, "_recorded_play", lambda ctx, gid: [{"id": "r1", "events": {"pad": 500}, "adapter": "retroarch",
                                                                "started": 100.0, "updated": 1}])
    monkeypatch.setattr(t, "_run_events", lambda ctx, rid: [pad(103.0, [("start", True)]), pad(103.2, [("start", False)])])
    r = t.autoplay(t.AutoplayIn(session_id="s1", op="start"), ap.ctx)["result"]
    assert r["mode"] == "replay"
    t.AUTOPLAY["s1"]["driver"].stopped = True
    t.AUTOPLAY["s1"]["thread"].join(5)


def test_unknown_mode_is_refused(ap):
    t = ap.tools
    with pytest.raises(ValueError, match="mode"):
        t.autoplay(t.AutoplayIn(session_id="s1", op="start", mode="dance"), ap.ctx)


# --- screen anchors ---

def _png(level, box=None):
    import io as _io
    from PIL import Image
    im = Image.new("RGB", (320, 240), (level, level, level))
    if box:
        im.paste((255, 255, 255), box)
    b = _io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def test_thumbnails_match_the_same_screen_and_not_another():
    title, menu = imitate.thumb(_png(20)), imitate.thumb(_png(20, (0, 0, 320, 120)))
    assert imitate.distance(title, imitate.thumb(_png(22))) < imitate.MATCH       # same screen, slightly different
    assert imitate.distance(title, menu) > imitate.MATCH


def test_replay_plan_puts_each_anchor_on_the_press_it_preceded():
    tl = [(10.0, frozenset({"start"})), (10.2, frozenset()), (30.0, frozenset({"b"})), (30.1, frozenset())]
    plan = imitate.replay_plan(tl, 0.0, marks=[(9.9, "T"), (25.0, "far"), (30.0, "M")])
    assert [p[2] for p in plan] == ["T", None, "M", None]   # 25.0 is 5 s before any press: not an anchor


def test_play_plan_holds_at_an_anchor_and_shifts_the_rest():
    now = [0.0]
    clock = lambda: now[0]
    def sleep(s): now[0] += max(s, 0.01)
    sent = []
    def sync(mark):                                          # the game loads 4 s slower than when it was recorded
        now[0] += 4.0
        return 4.0
    plan = [(1.0, "start", "T"), (2.0, "a", None), (3.0, "b", None)]
    out = imitate.play_plan(plan, send=lambda r: sent.append((r, round(now[0], 1))), stopped=lambda: False,
                            clock=clock, sleep=sleep, sync=sync)
    assert [r for r, _ in sent] == ["start", "a", "b"]
    assert sent[1][1] - sent[0][1] == pytest.approx(1.0, abs=0.06)   # the gaps after the anchor keep their timing
    assert out["synced"] == 1 and out["held_for_screens"] == 4.0


def test_wait_for_screen_returns_when_the_screen_matches_or_times_out():
    now = [0.0]
    clock = lambda: now[0]
    def sleep(s): now[0] += s
    target = imitate.thumb(_png(200))
    shots = iter([_png(10), _png(10), _png(200)])
    held = imitate.wait_for_screen(target, lambda: imitate.thumb(next(shots)), lambda: False, clock=clock, sleep=sleep)
    assert held == pytest.approx(0.4)
    held = imitate.wait_for_screen(target, lambda: imitate.thumb(_png(10)), lambda: False, clock=clock, sleep=sleep, timeout=2)
    assert held >= 2


def test_screensaver_replay_goes_on_in_your_style_and_reports_back(ap, monkeypatch):
    t = ap.tools
    posts = []
    monkeypatch.setattr(t.httpx, "post", lambda url, **k: posts.append((url.rsplit("/", 1)[-1], k["json"])))
    monkeypatch.setattr(t, "LEARNED", {})
    monkeypatch.setattr(t, "_recorded_play", lambda ctx, gid: [{"id": "r1", "events": {"pad": 500}, "adapter": "retroarch",
                                                                "started": 0.0, "updated": 1}])
    many = []
    for i in range(30):
        many += [pad(i * 0.01, [("x", True)], {"x": 0.9, "y": 0}), pad(i * 0.01 + 0.005, [("x", False)])]
    monkeypatch.setattr(t, "_run_events", lambda ctx, rid: many)
    monkeypatch.setattr(imitate, "BURST_GAP", 0.003)          # the recording is compressed 40x for the test
    stop = threading.Event()
    monkeypatch.setattr(t.time, "sleep", lambda s: stop.wait(0.0005))
    r = t.autoplay(t.AutoplayIn(session_id="s1", op="start", mode="replay", screensaver=True), ap.ctx)["result"]
    run = t.AUTOPLAY["s1"]
    for _ in range(400):
        if run["mission"].startswith("learned"):
            break
        stop.wait(0.01)
    assert run["mission"].startswith("learned: your style")    # the replay finished: the screensaver keeps playing
    padstate.PLAYER_TOUCH["s1"] = t.time.time() + 1            # the operator grabs the pad
    run["thread"].join(5)
    assert run["took_over"]
    kinds = [k for k, _ in posts]
    assert "yield" in kinds and "result" in kinds
    assert dict(posts)["yield"] == {"session_id": "s1", "reason": "pad"}
    padstate.PLAYER_TOUCH.pop("s1", None)


# --- getting to gameplay ---

def test_menu_keys_are_the_lone_presses_after_a_pause_with_start_first():
    f = frozenset
    tl = [(0, f()), (2.0, f({"b"})), (2.1, f()), (4.0, f({"b"})), (4.1, f()), (6.0, f({"lup"})), (6.2, f()),
          (8.0, f({"x"})), (8.1, f()), (8.2, f({"x"})), (8.3, f())]          # the second x follows too soon: not a menu press
    assert imitate.menu_keys(tl) == ["start", "b", "x"]


def test_stuck_fires_on_a_still_screen_and_not_during_play():
    now = [0.0]
    frames = iter([_png(10)] * 3 + [_png(10, (0, 0, 160, 240)), _png(200)] + [_png(200)] * 10)
    st = imitate.Stuck(lambda: imitate.thumb(next(frames)), clock=lambda: now[0], still_for=4)
    seen = []
    for _ in range(12):
        seen.append(st())
        now[0] += 1
    assert seen[:4] == [False, False, False, False]          # the screen changes at 3 s and 4 s
    assert seen[8] is True and not any(seen[:8])               # 4 s after the last change


def test_play_style_presses_through_a_stuck_screen():
    m = {"bursts": [{"steps": [[0, ["x"]], [0.1, []]], "n": 1}], "follows": {}, "gaps": [0.1], "total": 1,
         "menu": ["start", "b"]}
    calls = iter([True, True, False, False])

    class S:
        def __call__(self):
            return next(calls, False)

        def reset(self):
            pass
    sent = []
    imitate.play_style(imitate.Style(m, random.Random(0)), send=sent.append, stopped=lambda: False, sleep=lambda s: None,
                       limit=2, stuck=S())
    downs = [r[0]["key"] for r in sent if r and r[0]["down"]]
    assert downs[:2] == ["start", "b"] and "x" in downs[2:]


# --- the screensaver improving over time ---

def test_choose_knobs_defaults_then_prefers_the_best_average():
    assert imitate.choose_knobs([]) == imitate.DEFAULT_KNOBS
    a = {"follow": 0.4, "pace": 1.0, "favor": 1.0}
    b = {"follow": 0.9, "pace": 1.5, "favor": 2.0}
    hist = [{"knobs": a, "score": 1.0}, {"knobs": a, "score": 1.0}, {"knobs": b, "score": 3.0}, {"knobs": b, "score": 0.5}]
    assert imitate.choose_knobs(hist, random.Random(0), explore=0) == b          # mean 1.75 beats 1.0
    n = imitate.choose_knobs(hist, random.Random(3), explore=1)                  # exploring: one knob one step away
    assert sum(n[k] != b[k] for k in b) <= 1 and all(n[k] in imitate.KNOBS[k] for k in n)


def test_novelty_rewards_a_moving_varied_screen():
    now = [0.0]
    still = imitate.Stuck(lambda: imitate.thumb(_png(10)), clock=lambda: now[0])
    shots = iter([_png(10 * i, (0, 0, 32 * i, 240)) for i in range(1, 9)])
    lively = imitate.Stuck(lambda: imitate.thumb(next(shots)), clock=lambda: now[0])
    for _ in range(8):
        still(); lively(); now[0] += 1
    assert still.novelty()["score"] == 0 and still.novelty()["screens"] == 1
    assert lively.novelty()["moving"] > 0.8 and lively.novelty()["screens"] >= 4 and lively.novelty()["score"] > 1


def test_style_knobs_change_pace_and_favour():
    m = {"bursts": [{"steps": [[0, ["x"]], [0.1, []]], "n": 9}, {"steps": [[0, ["a"]], [0.1, []]], "n": 1}],
         "follows": {}, "gaps": [0.2], "total": 10}
    fast = imitate.Style(m, random.Random(0), {"pace": 0.6, "favor": 2.0})
    assert fast.gap() == pytest.approx(0.12) and fast.weights == [81.0, 1.0]
    assert imitate.Style(m, random.Random(0)).gap() == pytest.approx(0.2)


def test_screensaver_send_raises_the_window_and_retries_a_refused_input(monkeypatch):
    from gbox import tools as T
    fronts = []
    monkeypatch.setattr(T, "_front", lambda ad: fronts.append(1) or True)
    calls = []

    def send_input(rows):
        calls.append(rows)
        if len(calls) == 1:
            raise RuntimeError("gBox or the emulator must be active to send emulator input safely")
        return {"sent": len(rows)}
    send = T._screensaver_send(SimpleNamespace(send_input=send_input))
    assert send([{"key": "a", "down": True}]) == {"sent": 1}
    assert len(calls) == 2 and len(fronts) == 2                 # once up front, once for the refused input
    calls.clear()
    monkeypatch.setattr(T, "_front", lambda ad: False)
    send2 = T._screensaver_send(SimpleNamespace(send_input=lambda rows: (_ for _ in ()).throw(
        RuntimeError("gBox or the emulator must be active to send emulator input safely"))))
    with pytest.raises(RuntimeError):
        send2([{"key": "a", "down": True}])                     # cannot come to the front: the error stands

"""The Mercenaries deployment layer (gbox.mercs_bot): a title takes part through its RAM map's "mercs" block, the
playbook boots it from RAM through the block's menus module and hands each round to the engine
(gbox.mercs.engine.play_round), and coaching notes and ⚑ reports on the title go to its run-lessons log
(gbox.mercs.lessons.append) in the schema agreed with the engine."""
import base64
import sys
import time
import types
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import coaching, mercs_bot as MB, ram_map, re4_menus as RM, screensaver
from gbox.server import create_app
from test_re4_menus import PG, FakeRE4

PROFILE = {"menus": "gbox.re4_menus", "early_ops": ["mercenaries_unlock"], "jump_at": "select_player",
           "package": [["mercenaries_unlock", {"on": True}], ["merc_loadout", {"character": "leon"}],
           ["infinite_ammo", {"on": True}]], "map_id": "G4BE08", "platform": "gamecube"}


@pytest.fixture
def lessons(monkeypatch):
    """gbox.mercs.lessons (the engine's) as a recorder: [(map_id, entry, run)]."""
    rows = []
    pkg = types.ModuleType("gbox.mercs")
    pkg.lessons = SimpleNamespace(append=lambda map_id, entry, run=None: rows.append((map_id, entry, run)))
    monkeypatch.setitem(sys.modules, "gbox.mercs", pkg)
    return rows


def a_map(spec):
    return SimpleNamespace(id="G4BE08", platform="gamecube", spec=spec)


def test_the_profile_is_the_mercs_block_of_the_titles_ram_map(monkeypatch):
    block = {k: v for k, v in PROFILE.items() if k not in ("map_id", "platform")} | {"driver": "gbox.mercs.titles.x"}
    monkeypatch.setattr(ram_map, "find", lambda g: a_map({"mercs": block}) if g.get("game_id") == "re4" else None)
    prof = MB.profile_for(None, {"game_id": "re4"})
    assert prof == block | {"map_id": "G4BE08", "platform": "gamecube"}         # the engine's own keys ride along
    assert MB.profile_for(None, {"game_id": "doa2"}) is None                      # no map
    monkeypatch.setattr(ram_map, "find", lambda g: a_map({"mercs": {"driver": "x"}}))
    assert MB.profile_for(None, {"game_id": "re4"}) is None                       # no menus module: nothing to boot by
    assert MB.map_id_for({"game_id": "re4"}) == "G4BE08"                          # ...but its notes still count


def test_it_plays_only_once_the_engine_is_installed(monkeypatch):
    monkeypatch.setattr(MB, "profile_for", lambda ad, g: PROFILE if g.get("game_id") == "re4" else None)
    monkeypatch.setitem(sys.modules, "gbox.mercs", None)                          # no gbox.mercs package yet
    assert MB.engine() is None and not MB.matches(None, {"game_id": "re4"})
    assert MB.lessons_writer("G4BE08") is None
    pkg = types.ModuleType("gbox.mercs")
    pkg.engine = SimpleNamespace(play_round=lambda *a: "round", READY=False)       # installed, not ready yet
    monkeypatch.setitem(sys.modules, "gbox.mercs", pkg)
    assert MB.engine() is None and not MB.matches(None, {"game_id": "re4"})
    pkg.engine.READY = True
    assert MB.engine() is pkg.engine and MB.matches(None, {"game_id": "re4"})
    monkeypatch.setattr(MB, "engine", lambda: SimpleNamespace(play_round=lambda *a: "round"))
    assert MB.matches(None, {"game_id": "re4"}) and not MB.matches(None, {"game_id": "doa2"})
    from gbox import tools
    assert tools.PLAYBOOKS[0] == "mercs_bot" and "re4_merc_bot" in tools.PLAYBOOKS   # asked first; RE4's own after


def test_play_boots_from_the_title_and_hands_each_round_to_the_engine(monkeypatch, lessons):
    g = FakeRE4(routine=4, step=0, menu_cursor=3)
    now, ops, rounds = [0.0], [], []
    monkeypatch.setattr(MB, "profile_for", lambda ad, game: PROFILE)
    monkeypatch.setattr(MB, "apply_ops", lambda ad, x, prof=None: ops.append([op for op, _ in x]) or [])
    monkeypatch.setattr(MB, "save_menu_moment", lambda ad, game: "G4BE08.sav")

    def play_round(prof, m, send, stopped, stats, lesson):
        assert prof is PROFILE and m is g and RM.screen(m)["where"] == "playing"
        rounds.append(list(g.picks))
        lesson({"kind": "round_end", "n": len(rounds)})
        if len(rounds) == 2:
            return "stopped"
        g.title_task(True)                                   # results done: the title task's Mercenaries menu again
        g.tw(6, 4)
        g.put(PG + RM.G_ROUTINE, "B", 0)
        g.picks.clear()
        return "round"
    monkeypatch.setattr(MB, "engine", lambda: SimpleNamespace(play_round=play_round))
    steps = iter(range(800))
    stats = MB.play(object(), g.send, lambda: next(steps, None) is None, game={"game_id": "re4"}, m=g,
                    sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert rounds == [["THE MERCENARIES", "GAME START", "Leon", "Village"], ["GAME START", "Leon", "Village"]]
    assert stats["rounds"] == 2 and not stats.get("hung") and stats["profile"] == "G4BE08"
    assert ops == [["mercenaries_unlock"], ["merc_loadout", "infinite_ammo"]]   # the unlock at once; hooks once per boot
    assert stats["menu_moment"] == "G4BE08.sav" and stats["hooks"] == "applied"
    assert [(mid, e["kind"]) for mid, e, run in lessons] == [("G4BE08", "round_end")] * 2
    assert all(run for _, _, run in lessons)                 # the engine's events go to this run's log


def test_play_ends_the_run_on_a_lost_round_or_a_story_game(monkeypatch):
    g = FakeRE4(routine=4)
    g.round()
    monkeypatch.setattr(MB, "profile_for", lambda ad, game: PROFILE)
    monkeypatch.setattr(MB, "engine", lambda: SimpleNamespace(play_round=lambda *a: "lost"))
    now = [0.0]
    stats = MB.play(None, g.send, lambda: now[0] > 60, m=g, sleep=lambda s: now.__setitem__(0, now[0] + s),
                    clock=lambda: now[0])
    assert stats["hung"] is True and "lost" in stats["wandered"] and stats["rounds"] == 1
    g.put(PG + RM.G_ROOM, ">H", 0x101)                       # a story room: never played, the run ends
    stats = MB.play(None, g.send, lambda: now[0] > 120, m=g, sleep=lambda s: now.__setitem__(0, now[0] + s),
                    clock=lambda: now[0])
    assert stats["hung"] is True and "story" in stats["wandered"] and stats["rounds"] == 0


def test_a_title_without_a_profile_is_refused():
    with pytest.raises(ValueError, match="no Mercenaries profile"):
        MB.play(None, lambda rows: None, lambda: True, game={"game_id": "nothing-here"}, m=FakeRE4())


def test_midround_resume_arms_health_before_engine_and_keeps_owning_adapter(monkeypatch):
    g = FakeRE4(routine=4)
    g.round()
    ad, operations = object(), []
    profile = dict(PROFILE, early_ops=[], playing_ops=[["unlimited_health", {"on": True}]])
    monkeypatch.setattr(MB, "profile_for", lambda *_: profile)
    monkeypatch.setattr(MB, "apply_ops", lambda adapter, ops, *args: operations.extend(ops) or [])

    def run(*args, **kwargs):
        assert g.adapter is ad
        assert operations == [("unlimited_health", {"on": True})]
        return "stopped"

    monkeypatch.setattr(MB, "engine", lambda: SimpleNamespace(play_round=run))
    stats = MB.play(ad, g.send, lambda: False, m=g)
    assert stats["playing_hooks"] == "applied"


def test_screens_are_named_only_when_the_code_signatures_match():
    g = FakeRE4(routine=5, step=1)
    assert RM.screen(g)["where"] == "main_menu"
    other = FakeRE4(routine=5, step=1)
    addr, sig = next(iter(RM.SIGNATURES.items()))
    other.put(addr, f"{len(sig)}s", bytes(len(sig)))         # another build / another game at these addresses
    scr = RM.screen(other)
    assert scr["where"] == "unknown" and "SIGNATURES" in scr["error"] and RM.step(scr) is None


def test_notes_and_reports_go_to_the_titles_lessons_in_the_agreed_schema(monkeypatch, lessons):
    monkeypatch.setattr(MB, "map_id_for", lambda g: "G4BE08" if (g or {}).get("game_id") == "re4" else None)
    e = MB.lesson("coach", "aim higher", session_id="w1-a", note=3, worker="spark", junk="dropped", ts=5.0)
    assert tuple(e) == MB.LESSON_KEYS and e["kind"] == "coach" and e["note"] == 3 and e["ts"] == 5.0
    assert MB.note_lesson({"game_id": "re4"}, e) and lessons == [("G4BE08", e, None)]
    assert not MB.note_lesson({"game_id": "doa2"}, e)                             # not a Mercenaries title
    monkeypatch.setitem(sys.modules, "gbox.mercs", None)
    assert not MB.note_lesson({"game_id": "re4"}, e)                              # no engine: nothing, no error


GID = "78ab9efa2e310db4"


@pytest.fixture
def plane(cfg, monkeypatch, lessons):
    app = create_app(cfg)
    store = app.state.store
    monkeypatch.setattr(coaching, "_spawn", lambda fn, *args: None)
    monkeypatch.setattr(MB, "map_id_for", lambda g: "G4BE08" if (g or {}).get("game_id") == GID else None)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    client.post("/api/workers/register", json={"id": "w1", "name": "spark", "os": "linux",
                                                "tools": ["get_frame", "session_op"]}).raise_for_status()
    store.upsert_catalog([{"game_id": GID, "title": "Resident Evil 4", "platform": "gamecube",
                           "source_paths": ["re4.iso"], "format": "iso", "profile_id": GID}])
    store.put("session", "w1-abc", {"session_id": "w1-abc", "game_id": GID, "title": "Resident Evil 4",
                                    "adapter": "dolphin", "state": "running", "started": time.time(),
                                    "detail": {"worker_name": "spark"}})
    screensaver.TELEMETRY.clear()
    screensaver.telemetry_put("w1-abc", {"running": True, "mode": "playbook", "mission": "playbook: re4_merc_bot",
                                         "demo": True, "stats": {"screen": "playing", "rounds": 2}})
    client.app_ = app
    return client


def test_a_coaching_note_on_a_mercenaries_title_is_a_lesson_for_the_engine(plane, lessons):
    r = plane.post("/api/sessions/w1-abc/coach", json={"text": "shoot the dynamite men first"})
    assert r.status_code == 200, r.text
    out = r.json()
    [(mid, e, run)] = lessons
    assert (mid, run) == ("G4BE08", None) and tuple(e) == MB.LESSON_KEYS
    assert e["kind"] == "coach" and e["text"] == "shoot the dynamite men first" and e["note"] == out["note"] == 1
    assert e["request_id"] == out["request_id"] and e["session_id"] == "w1-abc" and e["worker"] == "spark"
    assert e["telemetry"]["stats"] == {"screen": "playing", "rounds": 2} and set(e["captures"]) == set(coaching.CAPTURES)


def test_a_report_on_a_mercenaries_session_is_a_lesson_for_the_engine(plane, lessons):
    route = next(r for r in plane.app_.routes if getattr(r, "path", "") == "/api/requests/issue")
    closure = dict(zip(route.endpoint.__code__.co_freevars, route.endpoint.__closure__))
    closure["_issue_log"].cell_contents = lambda sid, session: ("", "not available in test")
    closure["_issue_chat"].cell_contents = lambda sid: []
    img = base64.b64encode(b"frame").decode()
    r = plane.post("/api/requests/issue", json={"session_id": "w1-abc", "what": "Bot demo", "save_state": False,
                                                "note": "it walked into the fence for a minute", "image_b64": img})
    assert r.status_code == 200, r.text
    [(mid, e, run)] = lessons
    assert (mid, run, e["kind"], e["request_id"], e["session_id"]) == ("G4BE08", None, "report", r.json()["id"], "w1-abc")
    assert tuple(e) == MB.LESSON_KEYS and e["worker"] == "spark"
    assert "it walked into the fence for a minute" in e["text"] and e["telemetry"]["demo"] is True
    plane.app_.state.store.put("session", "w1-zzz", {"session_id": "w1-zzz", "game_id": "doa2", "state": "running"})
    plane.post("/api/requests/issue", json={"session_id": "w1-zzz", "what": "x", "save_state": False,
                                            "image_b64": img}).raise_for_status()
    assert len(lessons) == 1                                                       # another title: no lesson


def test_boot_confirms_screens_ram_cannot_name_with_the_titles_boot_key():
    # JAYBUILTFINALE 2026-10-22: RE5's cold boot sat on its HDD notice (no unit names it), hung at 30 s and relaunched
    # into the same notice; the title's BOOT_KEY now confirms such screens every BOOT_PRESS_S
    now, sent = [0.0], []
    menus = SimpleNamespace(BOOT_KEY="cross", screen=lambda m, merc=None: {"where": "unknown"},
                            step=lambda scr: None, wandered=lambda scr: None)
    boot = MB.Boot(menus, None, sent.extend, sleep=lambda s: None, clock=lambda: now[0])
    for t in range(1, 11):                                  # (a clock at 0 reads as "not lost yet")
        now[0] = float(t)
        assert boot.tick() is None
    downs = [e for e in sent if e["down"]]
    assert [e["key"] for e in downs] == ["cross"] * 3 and boot.stats["boot_presses"] == 3   # at 4, 7, 10 s
    now[0] = MB.MENU_LOST_S + 2
    assert "did not name" in boot.tick()                    # still unnamed after the presses: the run ends as before
    sent.clear()
    plain = MB.Boot(SimpleNamespace(screen=menus.screen, step=menus.step, wandered=menus.wandered), None, sent.extend,
                    sleep=lambda s: None, clock=lambda: now[0])
    now[0] = 100.0
    plain.tick(); now[0] = 110.0; plain.tick()
    assert sent == []                                       # a title without BOOT_KEY presses nothing it can't name

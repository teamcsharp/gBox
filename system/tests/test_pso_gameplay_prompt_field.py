"""Actual joined-buddy context and menu-over-gameplay control admission."""
import copy
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from gbox import pso_coop as C, pso_campaign as P


def town():
    players = {slot: {"ptr": f"80D0{slot}000", "class": "TObjPlayer", "kind": "player",
                       "room": 10, "x": 213. + slot, "y": 0., "z": 254.,
                       "heading_deg": 270., "hp": 33, "hp_max": 33} for slot in (1, 2)}
    return {"verified": True, "phase": 14, "episode": 1, "floor": 0, "difficulty": 0,
            "difficulty_verified": True, "players": players, "entities": list(players.values()) + [
                {"kind": "object", "class": "TObjCityDoor_Warp", "entity_id": 16405,
                 "ptr": "80DAE180", "room": 10, "x": 254.001, "y": 0., "z": 25.002}]}


def context(state=None):
    return {"native_state": state or town(), "existing_buddies": True, "awaiting_entry": False,
            "characters": [{"player": 1, "name": "LYRA95", "class": "RAcast"},
                           {"player": 2, "name": "AXIS92", "class": "HUnewearl"}]}


def test_joined_buddies_receive_actual_town_goal_without_setup_instructions():
    original = context()
    prompt, compact = C.planner_input(original)
    assert prompt == C.GAMEPLAY_PROMPT
    assert "Select offline multi mode, join both controllers" not in prompt
    assert "TOWN EXIT CANDIDATE, not a proven usable portal" in prompt
    assert "dup/ddown/dleft/dright" in prompt and "lup/ldown/lleft/lright" in prompt
    assert compact["characters"] == original["characters"]
    assert compact["native_players"][2]["x"] == 215.
    assert compact["nearby_native_landmarks"] == [{"class": "TObjCityDoor_Warp", "kind": "object",
        "entity_id": 16405, "room": 10, "x": 254.001, "y": 0., "z": 25.002}]
    assert "ptr" not in repr(compact) and "native_state" not in compact
    assert compact["initialization_authorized"] is False
    assert original["native_state"]["entities"][-1]["ptr"] == "80DAE180"


@pytest.mark.parametrize("change", [{"room": 11}, {"x": 2000.}, {"y": 16.},
                                    {"z": float("nan")}, {"x": True}, {"kind": "particle"}])
def test_unrelated_nonfinite_or_different_elevation_landmarks_are_not_planner_goals(change):
    native = town()
    native["entities"].append(native["entities"][-1] | change | {"entity_id": 99})
    _, compact = C.planner_input(context(native))
    assert [e["entity_id"] for e in compact["nearby_native_landmarks"]] == [16405]


@pytest.mark.parametrize("change", [{"verified": False}, {"phase": 1}, {"players": {}}])
def test_unverified_gameplay_preserves_guarded_setup_context(change):
    data = context(town() | change)
    prompt, actual = C.planner_input(data)
    assert prompt == C.PROMPT and actual is not data
    assert {k: v for k, v in actual.items() if k != "native_state"} == {
        k: v for k, v in data.items() if k != "native_state"}
    assert actual["native_state"]["verified"] == data["native_state"]["verified"]
    assert actual["native_state"]["phase"] == data["native_state"]["phase"]


def test_completed_route_requests_save_path_without_recreating_characters():
    data = context()
    data.update(C.buddy_context(data["characters"], data["native_state"], {}, "test", awaiting_entry=True))
    assert data["awaiting_entry"] is True
    prompt, actual = C.planner_input(data)
    assert prompt == C.PROMPT and actual is not data
    assert {k: v for k, v in actual.items() if k != "native_state"} == {
        k: v for k, v in data.items() if k != "native_state"}
    assert actual["native_state"]["verified"] == data["native_state"]["verified"]
    assert actual["native_state"]["phase"] == data["native_state"]["phase"]
    assert "same saved buddies" in data["next"]
    assert data["isolated_new_card_initialization_authorized"] is False


def test_phase14_menu_pause_releases_pads_and_discards_navigation():
    calls = []
    menu = SimpleNamespace(observe_frame=lambda *a, **kw: calls.append(kw) or True,
                           observation={"kind": "quit_confirmation"})
    controller = SimpleNamespace(goals={1: {"x": 5}}, approaches={2: {"x": 6}})
    stats = {}
    assert C.observe_menu_controls(menu, b"frame", town(), controller,
                                  SimpleNamespace(release=lambda: calls.append("release_both")), stats)
    assert calls[0]["native_gameplay"] is True and calls[-1] == "release_both"
    assert not controller.goals and not controller.approaches
    assert stats["menu_controls_paused"] and stats["menu_observation"]["kind"] == "quit_confirmation"


@pytest.mark.parametrize("initial_menu", [True, False])
@pytest.mark.parametrize("floor", [0, 1])
def test_play_checks_menu_before_mapping_and_after_menu_input_before_native_tick(monkeypatch, tmp_path, initial_menu, floor):
    scene = {"menu": initial_menu, "loops": 0, "ticks": 0, "mapping": 0, "start": 0}
    clock = [10.]
    class Menu:
        repeats, stalled = 0, False
        previous, observation = {}, {}
        def __init__(self, **kw): pass
        def observe_frame(self, *_a, **_kw): return scene["menu"]
        def review(self, plan, selected, *_a, **kw):
            assert kw["finish_save"] is False
            return selected, ""
    class Controller:
        damage = kills = attacks = blocked = 0
        combat_status = {}
        town = SimpleNamespace(status={})
        engagements = SimpleNamespace(recoveries=0, deferred=0, rows={})
        def __init__(self, *_):
            self.goals, self.approaches = {}, {}
            self.weapon_ranges = SimpleNamespace(cache={}, attempted={})
        def accept_goals(self, *_): self.goals[1] = {"x": 1}
        def tick(self, _):
            assert not scene["menu"], "Native controls leaked behind the menu"
            scene["ticks"] += 1
    class Planner:
        def __call__(self, *_):
            return {"screen": "gameplay", "actions": [{"player": 1, "keys": ["start"], "secs": .1}]}
        def close(self): pass
    class Executor:
        def __init__(self, **_): pass
        def submit(self, fn, *args):
            result = Future()
            result.set_result(fn(*args))
            return result
        def shutdown(self, **_): pass
    def probe(*_):
        assert not scene["menu"], "Mapping probe ran behind the menu"
        scene["mapping"] += 1
        return []
    def hold(self, commands):
        if commands[0][1] == ["start"]:
            scene["menu"] = True
            scene["start"] += 1
    def wait(*_):
        scene["loops"] += 1
        clock[0] += 9
    monkeypatch.setattr(C, "MenuProgress", Menu)
    monkeypatch.setattr(C, "Controller", Controller)
    monkeypatch.setattr(C, "mapping_probe", probe)
    monkeypatch.setattr(C.Inputs, "hold", hold)
    monkeypatch.setattr(C, "Reader", lambda _: SimpleNamespace(snapshot=lambda: copy.deepcopy(town() | {"floor":floor})))
    monkeypatch.setattr(C, "SpeedSampler", lambda *_: SimpleNamespace(observe=lambda _: None, invalidate=lambda: None, failure=None))
    monkeypatch.setattr(C, "ThreadPoolExecutor", Executor)
    monkeypatch.setattr(P, "Planner", lambda *_: Planner())
    monkeypatch.setattr(P, "wait", wait)
    monkeypatch.setattr(C.time, "monotonic", lambda: clock[0])
    ad = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), get_frame=lambda: b"frame",
                         send_input_player=lambda rows, player: {"sent": len(rows)})
    stats = C.play(ad, lambda rows: {"sent": len(rows)}, lambda: scene["loops"] >= 2,
                   driver=SimpleNamespace(), session_id="test")
    assert scene["mapping"] == (0 if initial_menu else 1)
    assert scene["ticks"] == (0 if initial_menu else 2)
    assert stats["menu_controls_paused"] == initial_menu
    assert scene["start"] == int(initial_menu and floor == 0)

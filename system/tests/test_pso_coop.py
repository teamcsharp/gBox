import copy
import struct
from types import SimpleNamespace

import pytest

from gbox import pso_coop as C, pso_campaign as P
from gbox.pso_coop_nav import RoomMap, room_key
from gbox.registry import Unsupported


def state(episode=1, floor=0, difficulty=0):
    players = {slot: {"ptr": f"80D0{slot}000", "class": "TObjPlayer", "entity_id": slot - 1,
                      "kind": "player", "x": float(slot * 30), "y": 0., "z": 0., "room": 0,
                      "heading_deg": 0., "hp": 40, "hp_max": 40} for slot in (1, 2)}
    return {"verified": True, "phase": 14, "episode": episode, "floor": floor,
            "players": players, "player": players[1], "entities": list(players.values()),
            "difficulty": difficulty, "difficulty_verified": True}


def test_random_creator_preferences_are_two_distinct_reproducible_new_characters():
    a = C.character_preferences(51)
    assert a == C.character_preferences(51)
    assert a != C.character_preferences(52)
    assert [p["player"] for p in a] == [1, 2]
    assert a[0]["name"] != a[1]["name"]
    assert all(p["class"] in C.CLASSES and 0 <= p["costume"] <= 8 for p in a)


def test_creator_preferences_survive_restart_and_malformed_metadata_is_not_replaced(tmp_path):
    path = tmp_path / "characters.json"
    initial = C.saved_preferences(path)
    assert C.saved_preferences(path) == initial
    path.write_text('{"name":"old save"}', encoding="utf-8")
    with pytest.raises(Unsupported, match="identities"):
        C.saved_preferences(path)
    assert path.read_text(encoding="utf-8") == '{"name":"old save"}'


@pytest.mark.parametrize("action", [{"keys": ["a"], "secs": .1}, {"player": True, "keys": ["a"], "secs": .1},
                                      {"player": 3, "keys": ["a"], "secs": .1}, {"player": 2, "keys": ["a"], "secs": .7}])
def test_coop_actions_need_explicit_bounded_controller(action):
    with pytest.raises(ValueError):
        C.actions({"actions": [action]})
    assert C.actions({"needs_operator": True, "actions": [action]}) == []


def test_two_controller_hold_releases_both_when_stop_arrives(monkeypatch):
    events, stop = [], {"value": False}
    def send(events_in, player):
        events.append((player, events_in))
        if player == 2 and events_in[0]["down"]:
            stop["value"] = True
        return {"sent": len(events_in)}
    inputs = C.Inputs(SimpleNamespace(send_input_player=send, autoplay_speed=4), lambda: stop["value"])
    monkeypatch.setattr(P.time, "sleep", lambda _: pytest.fail("Stopped holds must not sleep"))
    inputs.hold([(1, ["lup"], .4), (2, ["a"], .12)])
    assert {(p, e[0]["key"]) for p, e in events if e[0]["down"]} == {(1, "lup"), (2, "a")}
    assert all(any(p == slot and not e[0]["down"] for p, e in events) for slot in (1, 2))


def test_release_attempts_second_pad_when_first_pad_errors():
    sent = []
    def send(events, player):
        sent.append(player)
        if player == 1:
            raise OSError("pad 1 disconnected")
    with pytest.raises(OSError):
        C.Inputs(SimpleNamespace(send_input_player=send), lambda: False).release()
    assert sent == [1, 2]


def test_native_reader_joins_slots_by_pointer_not_entity_order(monkeypatch):
    snapshot = state()
    snapshot["entities"].reverse()
    monkeypatch.setattr(P.Reader, "snapshot", lambda _: copy.deepcopy(snapshot))
    monkeypatch.setattr(C, "native_context", lambda _: {"difficulty": 0, "difficulty_verified": True})
    ptrs = struct.pack(">2I", *[int(snapshot["players"][slot]["ptr"], 16) for slot in (1, 2)])
    reader = C.Reader.__new__(C.Reader)
    reader.ad = SimpleNamespace(read_memory=lambda a, n: ptrs)
    reader.gc = SimpleNamespace(ptr=lambda *args: None, u32=lambda a: C.VT_UPDATE - 12)
    result = reader.snapshot()
    assert result["players"][1]["entity_id"] == 0 and result["players"][2]["entity_id"] == 1
    snapshot["players"][2]["entity_id"] = 0
    with pytest.raises(Unsupported, match="controller 2"):
        reader.snapshot()


def test_one_player_is_not_mislabeled_cooperative(monkeypatch):
    snapshot = state()
    monkeypatch.setattr(P.Reader, "snapshot", lambda _: copy.deepcopy(snapshot))
    reader = C.Reader.__new__(C.Reader)
    reader.ad = SimpleNamespace(read_memory=lambda a, n: struct.pack(">2I", 0x80D01000, 0))
    result = reader.snapshot()
    assert not result["verified"] and not result["cooperative"] and result["players"] == {}


@pytest.mark.parametrize("wrong_pad", [False, True])
def test_pad_probe_requires_exclusive_native_actor_movement(monkeypatch, wrong_pad):
    current = state()
    reader = SimpleNamespace(snapshot=lambda: copy.deepcopy(current))
    def hold(commands):
        player = commands[0][0]
        current["players"][3 - player if wrong_pad else player]["z"] += 8
    inputs = SimpleNamespace(hold=hold, speed=lambda: 1, stopped=lambda: False)
    monkeypatch.setattr(P, "wait", lambda *_: None)
    if wrong_pad:
        with pytest.raises(Unsupported, match="wrong buddy"):
            C.mapping_probe(reader, inputs, current)
    else:
        receipts = C.mapping_probe(reader, inputs, current)
        assert [r["native_slot"] for r in receipts] == [0, 1]
        assert all(r["moved"] == 8 and r["other_moved"] == 0 for r in receipts)


def test_stall_memory_is_persistent_and_routes_around_known_edge(tmp_path):
    path = tmp_path / "room.json"
    nav = RoomMap(path)
    assert not nav.observe((6, 6), (6, 6), (6, 18), reliable=True)
    assert nav.observe((6, 6), (6, 6), (6, 18), reliable=True)
    restored = RoomMap(path)
    route = restored.route((6, 6), (6, 30))
    assert route and route[1] != (6, 18)
    assert ((0, 0), (0, 1)) in restored.blocked
    # Walking through a previously closed door revokes the observed obstacle.
    restored.observe((6, 6), (6, 20), (6, 20), reliable=True)
    assert ((0, 0), (0, 1)) not in restored.blocked


def test_combat_damage_or_loading_stalls_do_not_poison_wall_memory(tmp_path):
    nav = RoomMap(tmp_path / "room.json")
    for _ in range(10):
        nav.observe((6, 6), (6, 6), (6, 18), reliable=False)
    assert not nav.blocked and not nav.failures and not nav.path.exists()


def test_geometry_route_has_no_outside_goal_or_corner_cut_fallback():
    nav = RoomMap(floor={(0, 0), (1, 1)}, walls={(0, 1), (1, 0)})
    assert nav.route((6, 6), (18, 18)) is None
    assert nav.route((6, 6), (120, 120)) is None


def test_room_memory_changes_with_actual_landmarks_not_just_room_number():
    a, b = state(), state()
    assert room_key(a, a["player"])[1] is False
    a["entities"].append({"kind": "gate", "class": "TObjDoor", "room": 0, "x": 30., "z": 40.})
    b["entities"].append({"kind": "gate", "class": "TObjDoor", "room": 0, "x": 30., "z": 80.})
    assert room_key(a, a["player"])[0] != room_key(b, b["player"])[0]
    assert room_key(a, a["player"])[1]


def finish(progress, episode, difficulty, at):
    for floor in sorted(P.REQUIRED_FLOORS[episode]):
        progress.observe(state(episode, floor, difficulty))
    for hp in (100, 0):
        snapshot = state(episode, P.FINAL_FLOORS[episode], difficulty)
        snapshot["entities"].append({"ptr": "80DFF000", "class": "TBossFinal", "hp": hp, "hp_max": 100})
        progress.observe(snapshot)
    progress.ending("credits", f"first-{at}", at)
    return progress.ending("credits", f"second-{at}", at + 3)


def test_difficulty_advances_only_after_both_episodes_and_all_four_are_required():
    progress = C.Progress()
    for difficulty in range(4):
        for episode in (1, 2):
            receipt = finish(progress, episode, difficulty, difficulty * 100 + episode * 10)
            assert receipt["outcome"] == "episode_complete" and receipt["difficulty"] == difficulty
            if difficulty < 3 or episode < 2:
                assert not progress.status()["completion_verified"]
    assert progress.difficulty == 0 and progress.difficulty_cycles == 1
    assert progress.status()["completion_verified"]


def test_unknown_or_wrong_difficulty_never_records_campaign_completion():
    progress = C.Progress()
    for floor in range(1, 15):
        observed = state(floor=floor)
        observed["difficulty_verified"] = False
        progress.observe(observed)
    assert not progress.visited and not progress.started_at_entry
    assert finish(progress, 1, 2, 0) is None
    assert progress.episodes == 0


def test_native_difficulty_evidence_survives_transition_to_ending_credits():
    progress = C.Progress()
    for floor in sorted(P.REQUIRED_FLOORS[1]):
        progress.observe(state(floor=floor))
    for hp in (100, 0):
        observed = state(floor=P.FINAL_FLOORS[1])
        observed["entities"].append({"ptr": "80DFF000", "class": "TBossFinal", "hp": hp, "hp_max": 100})
        progress.observe(observed)
    progress.observe({"phase": 4, "verified": False, "players": {}})
    assert progress.ending("credits", "first", 0) is None
    receipt = progress.ending("credits", "second", 3)
    assert receipt["outcome"] == "episode_complete" and receipt["difficulty"] == 0


def test_native_combat_attacks_with_both_pads_without_waiting_for_planner(monkeypatch, tmp_path):
    observed = state(floor=1)
    for player in observed["players"].values():
        observed["entities"].append({"kind": "enemy", "ptr": player["ptr"] + "E", "class": "TObjEneBeast",
                                     "room": player["room"], "x": player["x"], "z": 20., "hp": 100, "hp_max": 100})
    sent = []
    inputs = SimpleNamespace(hold=lambda commands: sent.append(commands), speed=lambda: 1, stopped=lambda: False)
    controller = C.Controller(SimpleNamespace(snapshot=lambda: copy.deepcopy(observed)), inputs, C.Maps(tmp_path))
    monkeypatch.setattr(P, "wait", lambda *_: None)
    assert controller.tick(observed)
    assert sent[-1] == [(1, ["a"], .12), (2, ["a"], .12)]
    assert controller.attacks == 2 and controller.kills == 0


def test_pad_probe_never_moves_characters_in_enemy_area():
    observed = state(floor=1)
    with pytest.raises(Unsupported, match="Pioneer 2"):
        C.mapping_probe(None, SimpleNamespace(hold=lambda *_: pytest.fail("No input outside safe probe area")), observed)


@pytest.mark.parametrize("receipt", [{"sent": 0}, {"sent": 1, "held": "operator typing"}, {"sent": 1, "stopped": "focus changed"}, None])
def test_unacknowledged_inputs_are_deferred_and_released(receipt):
    sent = []
    def send(events, player, polite=False):
        sent.append((player, events, polite))
        return receipt
    inputs = C.Inputs(SimpleNamespace(send_input_player=send), lambda: False, polite=True)
    with pytest.raises(C.InputDeferred):
        inputs.hold([(2, ["a"], .1)])
    assert sent[-1] == (2, [{"key": "a", "down": False}], True)


@pytest.mark.parametrize("difficulty", range(4))
def test_native_difficulty_is_read_from_guarded_runtime_global(difficulty):
    from gbox import pso_coop_native as N
    memory = {0x80000000: b"GPOE8P\0\x02", N.PHASE: struct.pack(">I", 14),
              N.DIFFICULTY: struct.pack(">I", difficulty), **N.GUARDS}
    adapter = SimpleNamespace(read_memory=lambda address, size: memory[address][:size])
    assert N.context(adapter)["difficulty"] == difficulty
    assert N.context(adapter)["difficulty_verified"]
    memory[0x800ACA34] = bytes(12)
    with pytest.raises(Unsupported, match="fingerprint"):
        N.context(adapter)


def test_native_difficulty_rejects_unknown_value_and_menu_selection():
    from gbox import pso_coop_native as N
    memory = {0x80000000: b"GPOE8P\0\x02", N.PHASE: struct.pack(">I", 14),
              N.DIFFICULTY: struct.pack(">I", 7), **N.GUARDS}
    adapter = SimpleNamespace(read_memory=lambda address, size: memory[address][:size])
    with pytest.raises(Unsupported, match="outside"):
        N.context(adapter)
    memory[N.PHASE] = struct.pack(">I", 3)
    assert N.context(adapter) == {"difficulty_verified": False}


def test_multiplayer_native_boss_and_town_evidence_can_loop_without_credits():
    progress = C.Progress()
    for floor in sorted(P.REQUIRED_FLOORS[1]):
        progress.observe(state(floor=floor), now=0)
    observed = state(floor=P.FINAL_FLOORS[1])
    boss = {"ptr": "80DFF000", "class": "TBossFinal", "hp": 100, "hp_max": 100}
    observed["entities"].append(boss)
    progress.observe(observed, now=1)
    boss["hp"] = 0
    progress.observe(observed, now=2)
    progress.observe(observed, now=4)
    progress.observe(state(floor=0), now=5)
    assert not progress.pending_receipts
    progress.observe(state(floor=0), now=6)
    receipt = progress.pending_receipts[0]
    assert receipt["outcome"] == "episode_route_complete"
    assert not receipt["full_campaign_verified"] and not receipt["all_rooms_verified"]
    assert progress.target == 2 and progress.route_episodes == 1
    assert not progress.status()["completion_verified"]


def test_multiplayer_return_to_town_after_boss_despawn_does_not_advance():
    progress = C.Progress()
    observed = state(floor=P.FINAL_FLOORS[1])
    observed["entities"].append({"ptr": "80DFF000", "class": "TBossFinal", "hp": 100, "hp_max": 100})
    progress.observe(observed, now=0)
    for now in (1, 3, 5):
        progress.observe(state(floor=0), now=now)
    assert not progress.pending_receipts and progress.target == 1


def test_stacked_room_observations_never_share_blocked_edges(tmp_path):
    lower, upper = state(), state()
    for snapshot in (lower, upper):
        snapshot["entities"].append({"kind": "gate", "class": "TObjDoor", "room": 0, "x": 30., "z": 40.})
    upper["player"]["y"] = 20.
    assert room_key(lower, lower["player"])[0] != room_key(upper, upper["player"])[0]
    maps = C.Maps(tmp_path)
    assert maps.get(lower, lower["player"]) is not maps.get(upper, upper["player"])
    lower["collision_grid"] = {"floor": [[0, 0]], "walls": []}
    assert maps.get(lower, lower["player"]).floor is None
    lower["geometry_layer"] = "native-ground-face-17"
    assert maps.get(lower, lower["player"]).floor == {(0, 0)}


@pytest.mark.parametrize('flag,error', [('_autoplay_speed_changing', C.SpeedChanging),
                                       ('_pso_timing_paused', C.EmulationPaused),
                                       ('_pso_timing_epoch', C.EmulationPaused)])
def test_speed_change_or_pause_interrupts_both_held_pads(monkeypatch, flag, error):
    sent = []
    ad = SimpleNamespace(autoplay_speed=1, _autoplay_speed_known=True,
                         send_input_player=lambda events, player: sent.append((player, events)) or {"sent": len(events)})
    inputs = C.Inputs(ad, lambda: False)
    def change_during_wait(seconds, stopped):
        setattr(ad, flag, True)
        assert stopped(), "An in-flight hold must wake as soon as speed changes or the emulator pauses"
    monkeypatch.setattr(P, "wait", change_during_wait)
    with pytest.raises(error):
        inputs.hold([(1, ["lup"], .4), (2, ["a"], .12)])
    for player in (1, 2):
        assert any(slot == player and event[0]["down"] for slot, event in sent)
        assert any(slot == player and not event[0]["down"] for slot, event in sent)


def test_speed_change_between_pad_presses_never_starts_the_second_pad():
    sent = []
    ad = SimpleNamespace(autoplay_speed=1, _autoplay_speed_known=True)
    def send(events, player):
        sent.append((player, events))
        if events[0]["down"]:
            ad._autoplay_speed_changing = True
        return {"sent": len(events)}
    ad.send_input_player = send
    with pytest.raises(C.SpeedChanging):
        C.Inputs(ad, lambda: False).hold([(1, ["lup"], .4), (2, ["a"], .12)])
    assert not any(player == 2 and events[0]["down"] for player, events in sent)
    assert sent[-1] == (1, [{"key": "lup", "down": False}])


def test_play_waits_released_during_speed_sweep_and_requires_relaunch_on_interruption(monkeypatch, tmp_path):
    sent, waits = [], []
    ad = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), autoplay_speed=1,
                         _autoplay_speed_changing=True, _autoplay_speed_known=True,
                         send_input_player=lambda events, player: sent.append((player, events)) or {"sent": len(events)})
    monkeypatch.setattr(C, "Reader", lambda _: SimpleNamespace(snapshot=lambda: pytest.fail("No decisions during speed sweep")))
    monkeypatch.setattr(P, "Planner", lambda *_: SimpleNamespace(close=lambda: None))
    def interrupted(seconds, stopped):
        waits.append(seconds)
        assert seconds <= .1
        ad._autoplay_speed_changing = False
        ad._autoplay_speed_known = False
    monkeypatch.setattr(P, "wait", interrupted)
    result = C.play(ad, lambda events: ad.send_input_player(events, 1), lambda: False,
                    driver=SimpleNamespace(), session_id="test")
    assert waits == [.1]
    assert not result["ok"] and result["campaign_state"] == "needs_relaunch"
    assert "relaunch" in result["stopped_reason"]
    assert {player for player, _ in sent} == {1, 2}
    assert all(not event["down"] for _, events in sent for event in events)


@pytest.mark.parametrize("speed,verified", [(1, False), (2, False), (4, False), (8, False), (10, False), (4, True)])
def test_wall_learning_requires_observed_fast_rate_not_just_requested_rate(monkeypatch, tmp_path, speed, verified):
    observed = state(floor=1)
    observed["entities"].append({"kind": "gate", "class": "TObjDoor", "room": 0, "x": 30., "z": 90.})
    ad = SimpleNamespace(autoplay_speed=speed,
                         send_input_player=lambda events, player: {"sent": len(events)})
    monkeypatch.setattr(C.time, "monotonic", lambda: 100.)
    if verified:
        ad._autoplay_speed_observed = {"requested": speed, "actual": speed, "verified": True, "monotonic": 100.}
    inputs = C.Inputs(ad, lambda: False)
    monkeypatch.setattr(inputs, "hold", lambda _: None)
    monkeypatch.setattr(P, "wait", lambda *_: None)
    maps = C.Maps(tmp_path)
    controller = C.Controller(SimpleNamespace(snapshot=lambda: copy.deepcopy(observed)), inputs, maps)
    controller.accept_goals({"goals": [{"player": 1, "room": 0, "x": 30., "z": 60.}]}, observed)
    for _ in range(3):
        controller.tick(observed)
    nav = maps.get(observed, observed["player"])
    if speed == 1 or verified:
        assert controller.blocked and nav.blocked and nav.path.exists()
    else:
        assert not controller.blocked and not nav.blocked and not nav.failures and not nav.path.exists()


@pytest.mark.parametrize("receipt", [
    {"requested": 4, "actual": 4, "verified": True, "monotonic": 97.},
    {"requested": 4, "actual": 1, "verified": True, "monotonic": 100.},
    {"requested": 2, "actual": 4, "verified": True, "monotonic": 100.},
    {"requested": 4, "actual": 4, "verified": False, "monotonic": 100.},
])
def test_stale_or_mismatched_speed_readback_cannot_teach_walls(monkeypatch, receipt):
    monkeypatch.setattr(C.time, "monotonic", lambda: 100.)
    ad = SimpleNamespace(autoplay_speed=4, _autoplay_speed_observed=receipt,
                         send_input_player=lambda *_: None)
    assert not C.Inputs(ad, lambda: False).wall_learning_safe()


def test_default_speed_pause_cannot_teach_walls_and_resume_restores_learning(tmp_path):
    ad = SimpleNamespace(autoplay_speed=1, _pso_timing_paused=True, send_input_player=lambda *_: None)
    inputs = C.Inputs(ad, lambda: False)
    nav = RoomMap(tmp_path / 'paused-room.json')
    for _ in range(3):
        nav.observe((6, 6), (6, 6), (6, 18), reliable=inputs.wall_learning_safe())
    assert not nav.failures and not nav.blocked and not nav.path.exists()
    ad._pso_timing_paused = False
    assert inputs.wall_learning_safe()
    for _ in range(2):
        nav.observe((6, 6), (6, 6), (6, 18), reliable=inputs.wall_learning_safe())
    assert nav.blocked and nav.path.exists()

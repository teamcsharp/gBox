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
    with pytest.raises(InterruptedError):
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
                                     "room": player["room"], "x": player["x"], "z": 8., "hp": 100, "hp_max": 100})
    sent = []
    inputs = SimpleNamespace(hold=lambda commands: sent.append(commands), speed=lambda: 1, stopped=lambda: False)
    controller = C.Controller(SimpleNamespace(snapshot=lambda: copy.deepcopy(observed)), inputs, C.Maps(tmp_path))
    monkeypatch.setattr(P, "wait", lambda *_: None)
    assert controller.tick(observed)
    assert sent[-1] == [(1, ["a"], .12), (2, ["a"], .12)]
    assert controller.attacks == 2 and controller.kills == 0


def test_camera_recenter_only_on_staleness_or_a_real_turn(monkeypatch, tmp_path):
    """Operator 2026-11-02: no constant reframing — an L reset per pad only when its
    alignment is stale (RECENTER_S) or its actor turned since the last reset."""
    observed = state(floor=1)
    sent = []
    inputs = SimpleNamespace(hold=lambda commands: sent.append(commands), speed=lambda: 1, stopped=lambda: False)
    controller = C.Controller(SimpleNamespace(snapshot=lambda: copy.deepcopy(observed)), inputs, C.Maps(tmp_path))
    monkeypatch.setattr(P, "wait", lambda *_: None)
    pressed = lambda: [c[0] for batch in sent for c in batch if "l" in c[1]]
    controller.tick(copy.deepcopy(observed))
    assert set(pressed()) == {1, 2}            # the first tick aligns both pads once
    sent.clear()
    controller.tick(copy.deepcopy(observed))   # unchanged headings inside the window: no reframing
    assert pressed() == []
    observed["players"][2]["heading_deg"] = 90.
    sent.clear()
    controller.tick(copy.deepcopy(observed))   # only the pad whose actor turned realigns
    assert pressed() == [2]


def test_default_speed_steps_to_2x_once_and_never_overrides_the_operator():
    """Operator 2026-11-02: buddies default to 2x; the one-shot never fights a later choice."""
    calls = []
    ad = SimpleNamespace(autoplay_speed=1, set_autoplay_speed=lambda m: calls.append(m) or {"requested": m})
    stats = {}
    C.apply_default_speed(ad, stats)
    assert calls == [C.DEFAULT_AUTOPLAY_SPEED] and ad._pso_coop_speed_defaulted
    assert stats["default_speed"]["requested"] == C.DEFAULT_AUTOPLAY_SPEED
    C.apply_default_speed(ad, stats)                      # one-shot: no second step
    assert calls == [C.DEFAULT_AUTOPLAY_SPEED]
    # The operator since set 4x by hand; a fresh launch must not pull it back to 2x.
    ad2 = SimpleNamespace(autoplay_speed=4, set_autoplay_speed=lambda m: calls.append(m))
    C.apply_default_speed(ad2, {})
    assert calls == [C.DEFAULT_AUTOPLAY_SPEED]


def test_default_speed_never_blocks_play_on_a_failed_step():
    def boom(_):
        raise RuntimeError("speed input was interrupted")
    ad = SimpleNamespace(autoplay_speed=1, set_autoplay_speed=boom)
    stats = {}
    C.apply_default_speed(ad, stats)                      # swallowed, recorded
    assert "interrupted" in stats["default_speed_error"] and ad._pso_coop_speed_defaulted


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


def _field_state(room=10, p1=(30., 0.), p2=(60., 0.)):
    """A verified gameplay floor with NO geometry_verified: field_owned is False, so
    the buddies depend on the geometry-free forward fallback to keep advancing."""
    s = state(floor=1)
    s["players"][1].update(room=room, x=p1[0], z=p1[1])
    s["players"][2].update(room=room, x=p2[0], z=p2[1])
    s["entities"] = list(s["players"].values())
    return s


def _gate(cls, x, z, room=10, eid=9000):
    return {"kind": "gate", "class": cls, "ptr": f"80DB{eid:04X}", "entity_id": eid,
            "room": room, "x": float(x), "y": 0., "z": float(z), "heading_deg": 0.}


def test_buddies_advance_toward_room_switch_when_geometry_unverified(monkeypatch, tmp_path):
    """Party model: P1 (sole navigator) leads to the nearer switch; P2 is a swarm
    follower - with no threat it just closes the gap to P1 (placed behind, beyond
    the follow radius), never navigating on its own."""
    observed = _field_state(p2=(30., -60.))                 # P2 behind P1, outside the follow band
    observed["entities"] += [_gate("TLazerFenceSw", 30., 80., eid=16501),
                             _gate("TObjDoor", 30., 160., eid=16502)]
    sent, stats = [], {}
    inputs = SimpleNamespace(hold=lambda c: sent.append(c), speed=lambda: 1,
                             stopped=lambda: False, stats=stats)
    controller = C.Controller(SimpleNamespace(snapshot=lambda: copy.deepcopy(observed)), inputs, C.Maps(tmp_path))
    monkeypatch.setattr(P, "wait", lambda *_: None)
    assert controller.tick(observed)
    moves = [c for batch in sent for c in batch if c[1] not in (["l"], ["a"])]
    moved = {c[0] for c in moves}
    assert moved == {1, 2}                                   # P1 leads forward; P2 closes toward P1
    assert all("lup" in c[1] for c in moves)                # both head +z (P1 to switch, P2 up to P1)
    assert stats["forward_fallback_target"] == "TLazerFenceSw"   # P1 reaches the switch before the door
    assert stats["forward_fallback_engaged"] is True
    assert stats["forward_room"] == 10 and stats["forward_stuck"] is False


def test_forward_fallback_rotates_off_a_gate_that_stops_progressing():
    """A blocked affordance is abandoned after the stall window and the next candidate
    is tried, so the pair never pushes one wall forever."""
    observed = _field_state()
    observed["entities"] += [_gate("TLazerFenceSw", 30., 80., eid=16501),
                             _gate("TObjDoor", 30., 160., eid=16502)]
    maps = C.Maps.__new__(C.Maps)   # not needed by forward_fallback
    controller = C.Controller(SimpleNamespace(), SimpleNamespace(stats={}), None)
    player = observed["players"][1]
    assert controller.forward_fallback(observed, 1, player, 100.) == (30., 80.)   # switch first
    assert controller.forward_fallback(observed, 1, player, 101.) == (30., 80.)   # still trying
    # No progress past the stall window: the switch is cooled down, the door is next
    # and the pair is aimed just BEYOND it so they commit through (not stop short).
    through = controller.forward_fallback(observed, 1, player, 108.)
    assert through[0] == 30. and through[1] > 160. and controller.forward_interact[1] is False
    book = controller.fallback[(1, 1, None)]
    assert any(k[0] == "TLazerFenceSw" for k in book["cooldown"])


def test_combat_engages_enemy_in_reach_despite_room_id_mismatch(monkeypatch, tmp_path):
    """Room ids can lag the live actor; an enemy physically within reach is still
    attacked even when its room field does not match the player's."""
    observed = state(floor=1)
    for player in observed["players"].values():
        player["room"] = 10
        observed["entities"].append({"kind": "enemy", "ptr": player["ptr"] + "E", "class": "TObjEneBeast",
                                     "room": 999, "x": player["x"], "z": 8., "hp": 100, "hp_max": 100})
    observed["entities"] = list(observed["players"].values()) + observed["entities"][2:]
    sent = []
    inputs = SimpleNamespace(hold=lambda c: sent.append(c), speed=lambda: 1, stopped=lambda: False)
    controller = C.Controller(SimpleNamespace(snapshot=lambda: copy.deepcopy(observed)), inputs, C.Maps(tmp_path))
    monkeypatch.setattr(P, "wait", lambda *_: None)
    assert controller.tick(observed)
    assert sent[-1] == [(1, ["a"], .12), (2, ["a"], .12)]
    assert controller.attacks == 2


def test_forward_stuck_fires_until_a_new_room_is_reached_not_on_hub_bounce():
    """The fail-safe timer measures time since P1 reached a NEW (unvisited) room,
    by the visited-room COUNT - so bouncing between already-visited hub rooms does
    not keep resetting it; only reaching a genuinely new room does."""
    stats = {}
    controller = C.Controller(SimpleNamespace(), SimpleNamespace(stats=stats), None)
    observed = _field_state()
    controller.p1_visited = {5, 10}                             # hub rooms already visited
    controller._forward_dwell_telemetry(observed, 1000., False)
    assert stats["forward_stuck"] is False and stats["forward_time_since_new_room_s"] == 0.0
    # Bouncing 5<->10 does not grow the visited set -> the timer accumulates.
    controller._forward_dwell_telemetry(observed, 1000. + C.FALLBACK_STUCK_S + 1, False)
    assert stats["forward_stuck"] is True                       # stuck: no NEW room reached
    controller.p1_visited = {5, 10, 11}                         # a genuinely new room: real progress
    controller._forward_dwell_telemetry(observed, 1000. + C.FALLBACK_STUCK_S + 2, True)
    assert stats["forward_stuck"] is False and stats["forward_time_since_new_room_s"] == 0.0


def test_buddies_advance_when_geometry_verified_but_no_collision_grid(monkeypatch, tmp_path):
    """Live deadlock (i9, Ep1 Fl1): geometry_verified is True (field_owned) yet
    there is no usable collision grid, so FieldObjectives yields nothing and the
    old code idled P1 (waiting on P2's missing layer). Now P1 is the sole
    navigator and still advances to the room's switch/door; P2 is a geometry-free
    swarm follower (placed behind, it just closes the gap) - never the stall."""
    observed = _field_state(p2=(30., -60.))         # P2 behind P1, outside the follow band
    observed["geometry_verified"] = True            # field_owned True, but no geometry_players
    observed["entities"] += [_gate("TLazerFenceSw", 30., 90., eid=16501),
                             _gate("TObjDoor", 30., 200., eid=16502)]
    sent = []
    inputs = SimpleNamespace(hold=lambda c: sent.append(c), speed=lambda: 1,
                             stopped=lambda: False, stats={})
    controller = C.Controller(SimpleNamespace(snapshot=lambda: copy.deepcopy(observed)), inputs, C.Maps(tmp_path))
    monkeypatch.setattr(P, "wait", lambda *_: None)
    assert controller.tick(observed)
    moved = {c[0] for batch in sent for c in batch if c[1] not in (["l"], ["a"])}
    assert moved == {1, 2}                           # P1 navigates forward; P2 closes to P1 (no deadlock)
    assert all("lup" in c[1] for batch in sent for c in batch if c[1] not in (["l"], ["a"]))


def test_play_survives_transient_window_focus_loss_and_ends_only_on_stop(monkeypatch, tmp_path):
    """Operator rule: PSO must always be playing. A host focus/active-window
    RuntimeError (adapters.py: 'must be active to send emulator input') must PAUSE
    the run - release inputs, count the wait, raise the window, retry - and NEVER
    end the loop. Only stopped() ends it."""
    calls, waits = {"n": 0}, []
    def snapshot():
        calls["n"] += 1
        raise RuntimeError("gBox or the emulator must be active to send emulator input safely")
    def stopped():
        return calls["n"] >= 3                         # end only after surviving 3 focus errors
    ad = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), autoplay_speed=1,
                         _autoplay_speed_known=True,
                         send_input_player=lambda events, player: {"sent": len(events)})
    stats = {}
    monkeypatch.setattr(C, "Reader", lambda _: SimpleNamespace(snapshot=snapshot))
    monkeypatch.setattr(P, "Planner", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(P, "wait", lambda seconds, _stopped=None: waits.append(seconds))
    result = C.play(ad, lambda events: ad.send_input_player(events, 1), stopped,
                    stats=stats, driver=SimpleNamespace(), session_id="test")
    assert calls["n"] == 3                              # the loop kept going past every focus error
    assert stats["input_wait"] == 3                     # each counted and made visible
    assert stats["input_wait_active"] is True
    assert waits.count(C.FOCUS_WAIT_BACKOFF_S) == 3     # it paused and backed off, did not exit
    assert result["stopped"] is True                    # it ended ONLY because stopped() went true


def test_play_still_propagates_a_non_focus_runtime_error(monkeypatch, tmp_path):
    """A RuntimeError that is NOT the transient focus condition is still fatal -
    the resilience catch must not swallow real crashes."""
    def snapshot():
        raise RuntimeError("some genuinely unexpected failure")
    ad = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), autoplay_speed=1,
                         _autoplay_speed_known=True,
                         send_input_player=lambda events, player: {"sent": len(events)})
    monkeypatch.setattr(C, "Reader", lambda _: SimpleNamespace(snapshot=snapshot))
    monkeypatch.setattr(P, "Planner", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(P, "wait", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="genuinely unexpected"):
        C.play(ad, lambda events: ad.send_input_player(events, 1), lambda: False,
               stats={}, driver=SimpleNamespace(), session_id="test")


# --- Forward door/room progression (operator 2026-11-02: open and pass through
# --- EVERY door with gusto). See system/docs/pso-progression.md.

def _coop_room(entities, p1=(0., 0.), p2=(3., 0.), room=10):
    """A verified 2P field state with the given gate/switch entities in `room`."""
    players = {1: {"ptr": "80D01000", "class": "TObjPlayer", "entity_id": 0, "kind": "player",
                   "controller": 1, "x": p1[0], "y": 0., "z": p1[1], "room": room,
                   "heading_deg": 0., "hp": 40, "hp_max": 40},
               2: {"ptr": "80D02000", "class": "TObjPlayer", "entity_id": 1, "kind": "player",
                   "controller": 2, "x": p2[0], "y": 0., "z": p2[1], "room": room,
                   "heading_deg": 0., "hp": 40, "hp_max": 40}}
    ents = list(players.values()) + [dict(e, kind="gate") for e in entities]
    return {"verified": True, "phase": 14, "episode": 1, "floor": 1, "players": players,
            "player": players[1], "entities": ents, "difficulty": 0, "difficulty_verified": True,
            "geometry_identity": "g"}


def _controller(tmp_path, ad=None):
    inputs = SimpleNamespace(stats={}, speed=lambda: 1, stopped=lambda: False, hold=lambda c: None, ad=ad)
    return C.Controller(SimpleNamespace(ad=ad), inputs, C.Maps(tmp_path))


def test_switch_room_presses_the_panel_then_rotates_to_the_door(tmp_path):
    """SWITCH door: P1 presses the nearest panel, and after a short dwell rotates
    to the door it gates (the Forest-1 room 10 'open two door panels' case)."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoorKey", "x": 5., "z": 0., "room": 10},
                     {"class": "TObjDoor", "x": 100., "z": 0., "room": 10}])
    p1 = st["players"][1]
    dest = ctrl.forward_fallback(st, 1, p1, now=100.0)
    assert dest == (5., 0.) and ctrl.forward_interact[1] is True          # standing on panel -> press A
    assert ctrl.forward_fallback(st, 1, p1, now=100.7)[0] == 5.           # still inside the press window
    advanced = ctrl.forward_fallback(st, 1, p1, now=100.0 + C.SWITCH_PRESS_S + 0.1)
    assert ctrl.forward_interact[1] is False and advanced[0] > 100.       # panel pressed; now walk THROUGH the door


def test_walkthrough_door_targets_a_point_beyond_the_threshold(tmp_path):
    """OPEN door: aim past the door so the actor commits across, not short of it."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoor", "x": 100., "z": 0., "room": 10}])
    dest = ctrl.forward_fallback(st, 1, st["players"][1], now=50.0)
    assert dest[0] > 100. and ctrl.forward_interact[1] is False
    assert ctrl.inputs.stats["forward_fallback_action"] == "walk_through"


def test_room_clear_fence_is_a_walk_through_once_the_room_is_empty(tmp_path):
    """ROOM-CLEAR laser fence with no live enemy present: treat it as a door to
    cross (combat owns clearing; an empty room's fence is walked through)."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjLazerFenceNorm", "x": 80., "z": 0., "room": 10}])
    dest = ctrl.forward_fallback(st, 1, st["players"][1], now=50.0)
    assert dest[0] > 80. and ctrl.forward_interact[1] is False


def test_drive_forward_taps_a_on_a_panel_and_moves_toward_a_door(tmp_path):
    ctrl = _controller(tmp_path)
    on_panel = _coop_room([{"class": "TObjDoorKey", "x": 5., "z": 0., "room": 10}])
    cmds, moves, steer, fb = [], {}, {}, []
    assert ctrl.drive_forward(on_panel, 1, on_panel["players"][1], 100.0, cmds, moves, steer, fb)
    assert cmds == [(1, ["a"], .12)] and fb == [1] and not moves      # press, do not walk off the panel
    far_door = _coop_room([{"class": "TObjDoor", "x": 100., "z": 0., "room": 10}])
    cmds, moves, steer, fb = [], {}, {}, []
    assert ctrl.drive_forward(far_door, 1, far_door["players"][1], 100.0, cmds, moves, steer, fb)
    assert cmds and cmds[0][0] == 1 and cmds[0][1] != ["a"] and 1 in moves   # decisive movement toward the door


def test_drive_forward_steers_straight_when_no_grid_route_exists(tmp_path):
    """A gate off the (small spawn) collision grid must still get a committed push,
    not a dropped command - the live room-10 freeze was timid frontier hops."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoor", "x": 100., "z": 0., "room": 10}])
    nav = ctrl.maps.get(st, st["players"][1])
    nav.floor = {(0, 0)}            # a one-cell grid: the far door is NOT reachable on it
    cmds, moves, steer, fb = [], {}, {}, []
    assert ctrl.drive_forward(st, 1, st["players"][1], 100.0, cmds, moves, steer, fb)
    assert cmds and cmds[0][0] == 1 and cmds[0][2] == .40      # still a committed forward hold


def test_buddy_two_follows_the_leaders_committed_choice(tmp_path):
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoorKey", "x": 5., "z": 0., "room": 10}], p2=(60., 0.))
    ctrl.forward_fallback(st, 1, st["players"][1], now=100.0)      # P1 commits to the panel
    follow = ctrl.forward_fallback(st, 2, st["players"][2], now=100.0)
    assert follow == (5., 0.) and ctrl.forward_interact[2] is False     # P2 heads to where P1 went


def test_two_panel_room_is_split_so_both_panels_are_held_at_once(tmp_path):
    """Forest-1 'open two door panels': the buddies take DIFFERENT panels (two
    simultaneous holds), not both the nearest one."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoorKey", "x": 20., "z": 0., "room": 10},
                     {"class": "TObjDoorKey", "x": 200., "z": 0., "room": 10}],
                    p1=(0., 0.), p2=(180., 0.))
    p1_dest = ctrl.forward_fallback(st, 1, st["players"][1], now=100.0)   # P1 -> nearest panel
    p2_dest = ctrl.forward_fallback(st, 2, st["players"][2], now=100.0)   # P2 -> the OTHER panel
    assert p1_dest == (20., 0.) and p2_dest == (200., 0.) and p1_dest != p2_dest


def test_frontier_door_is_not_abandoned_after_the_stall_window(tmp_path):
    """A never-traversed (frontier) door - its far side may be a NEW room - is not
    cooled away when slow to reach, so P1 keeps committing to it instead of
    retreating through a known backward connector and oscillating."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoor", "x": 200., "z": 0., "room": 10}], p1=(0., 0.))
    assert ctrl.forward_fallback(st, 1, st["players"][1], now=100.)[0] > 200.   # targets the frontier door
    again = ctrl.forward_fallback(st, 1, st["players"][1], now=100. + C.FALLBACK_STALL_S + 2)
    assert again is not None and again[0] > 200.                               # still committed, not cooled
    assert ("TObjDoor", 200.0, 0.0) not in ctrl.fallback[(1, 1, "g")]["cooldown"]


def test_p1_prefers_the_door_to_an_unvisited_room_not_the_backtrack(tmp_path):
    """Forward-only progression: given a door back to a VISITED room and a door to
    an unvisited/unknown one, P1 drives through the forward (unvisited) door - it
    does not backtrack toward the spawn hub."""
    ctrl = _controller(tmp_path)
    back = {"class": "TObjDoor", "x": -100., "z": 0., "room": 10}   # learned: connects 10<->5 (both visited)
    fwd = {"class": "TObjDoor", "x": 100., "z": 0., "room": 10}     # forward / unknown destination
    st = _coop_room([back, fwd], p1=(0., 0.))
    ctrl.door_links[("TObjDoor", -100.0, 0.0)] = {5, 10}
    ctrl.p1_visited = {5, 10}
    ctrl._p1_room = 10
    dest = ctrl.forward_fallback(st, 1, st["players"][1], now=100.)
    assert dest[0] > 100.                                          # commits through the forward door


def test_traversed_door_is_cooled_so_p1_does_not_immediately_recross(tmp_path):
    """Cross-room anti-ping-pong: once P1 walks through a door (its room changes),
    that connector is cooled so P1 heads onward instead of bouncing back."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoor", "x": 300., "z": 0., "room": 10}], p1=(0., 0.))
    ctrl.forward_fallback(st, 1, st["players"][1], now=100.)           # P1 commits to the door
    assert ctrl._p1_door == ("TObjDoor", 300.0, 0.0) and ctrl._p1_room == 10
    st["players"][1].update(room=11, x=300., z=0.)                     # P1 crossed into the next room
    ctrl.forward_fallback(st, 1, st["players"][1], now=101.)
    assert ctrl.door_cooldown.get(("TObjDoor", 300.0, 0.0), 0) > 101.  # the used door is now on cooldown


def test_leader_does_not_backtrack_through_the_door_it_just_entered(tmp_path):
    """P1 heads for the boss, not back the way it came: entering a room by one
    door, it picks the FORWARD door, not the entry-adjacent one - so it stops
    ping-ponging a connected-room hub."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoor", "x": 5., "z": 0., "room": 10},     # back-door, by the entry
                     {"class": "TObjDoor", "x": 300., "z": 0., "room": 10}])  # forward door, far
    dest = ctrl.forward_fallback(st, 1, st["players"][1], now=100.)           # entry recorded at (0,0)
    assert dest[0] > 300.                                                     # drives through the FORWARD door


def test_goto_directive_routes_p1_then_clears_on_arrival(tmp_path):
    """RTS GOTO: a parsed in-scope goto makes P1's destination the clicked point;
    once P1 is within reach it is marked done (resume autonomous)."""
    ctrl = _controller(tmp_path)
    ctrl._directive = {"op": "goto", "id": "click1", "x": 100., "z": 0., "episode": 1, "floor": 1}
    st = _coop_room([], p1=(0., 0.))
    assert ctrl.goto_destination(st, st["players"][1], now=1.) == (100., 0.)   # navigate to the click
    st["players"][1].update(x=98., z=0.)                                       # arrived (within reach)
    assert ctrl.goto_destination(st, st["players"][1], now=2.) is None         # reached -> done
    assert ctrl._directive_done == "click1"
    assert ctrl.goto_destination(st, st["players"][1], now=3.) is None         # not re-pursued
    # A stale-area directive never steers P1.
    ctrl._directive = {"op": "goto", "id": "c2", "x": 5., "z": 5., "floor": 9}
    assert ctrl.goto_destination(st, st["players"][1], now=4.) is None


def test_autonomous_heads_to_the_exit_warp_when_no_gates_remain(tmp_path):
    """Idle->exit: with no switch/door left, P1 drives to the area's warp/
    teleporter (the level exit) so it keeps progressing toward the boss."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjAreaWarpForest", "x": 200., "z": 0., "room": 10}], p1=(0., 0.))
    dest = ctrl.forward_fallback(st, 1, st["players"][1], now=1.)
    assert dest is not None and dest[0] > 200.                                 # aimed through the exit warp
    assert ctrl.inputs.stats["forward_fallback_action"] == "exit_warp"


def test_publish_surface_writes_the_map_file_and_records_it_in_the_crystal(tmp_path):
    from gbox.pso_knowledge import KnowledgeStore
    from gbox.pso_coop_nav import room_key
    ctrl = _controller(tmp_path)
    ctrl.map_root = tmp_path
    ctrl.knowledge = KnowledgeStore(tmp_path / "pso-knowledge.json")
    st = _coop_room([{"class": "TObjDoorKey", "x": 5., "z": 0., "room": 10, "flag_index": 7}], p1=(0., 0.))
    st.update(geometry_verified=True, geometry_identity="area1",
              collision_grid={"size": 12.0, "floor": [[0, 0], [1, 0], [0, 1]], "walls": [],
                              "heights": [[0, 0, 0.0]], "max_step": .75, "max_slope": .75})
    ctrl.publish_surface(st)
    fp = room_key(st, st["players"][1])[0]
    assert (tmp_path / "pso-maps" / (fp + ".json")).is_file()                  # surface published for the viewer
    assert ctrl.knowledge.recall(fp)["surface"]["cell_count"] == 3            # summary folded into the crystal


def test_swarm_follower_closes_defends_and_never_navigates(tmp_path):
    """P2+ are pure swarm-followers: close the gap to P1 when far, hold in the
    follow band, engage any enemy near P1 - and never feed field nav / wall
    learning (no moves[]), so a follower can never stall the party."""
    ctrl = _controller(tmp_path)
    far = _coop_room([], p1=(0., 0.), p2=(0., -80.))
    cmds, moves, steer = [], {}, {}
    ctrl.swarm_follow(far, 2, far["players"][2], 100., [], C.FALLBACK, cmds, moves, steer, {})
    assert cmds and cmds[0][0] == 2 and "lup" in cmds[0][1] and not moves   # closes toward P1, no field nav
    band = _coop_room([], p1=(0., 0.), p2=(0., -25.))
    cmds = []
    ctrl.swarm_follow(band, 2, band["players"][2], 100., [], C.FALLBACK, cmds, {}, {}, {})
    assert cmds == []                                                       # in the band: holds station
    near = _coop_room([], p1=(0., 0.), p2=(0., 5.))
    enemy = {"kind": "enemy", "class": "TObjEneMoja", "ptr": "80DEAD00", "room": 10,
             "x": 0., "z": 9., "hp": 100, "hp_max": 100}
    near["entities"].append(enemy)
    cmds, attack_rows = [], {}
    ctrl.swarm_follow(near, 2, near["players"][2], 100., [enemy], C.FALLBACK, cmds, {}, {}, attack_rows)
    assert cmds and cmds[0][1] == ["a"] and attack_rows.get(2)             # attack-dog engages the enemy near P1


def test_leader_drives_forward_even_when_the_buddy_is_in_another_room(monkeypatch, tmp_path):
    """P1 leads decisively and never idles: with P2 off in another room (the live
    case where P2 ran ahead and P1 sat wedged), P1 still receives forward input."""
    observed = _coop_room([{"class": "TObjDoorKey", "x": -120., "z": 70., "room": 10}])
    observed["players"][2]["room"] = 99                     # buddy far away in another room
    sent = []
    inputs = SimpleNamespace(hold=lambda c: sent.append(c), speed=lambda: 1, stopped=lambda: False,
                             stats={}, ad=None)
    ctrl = C.Controller(SimpleNamespace(snapshot=lambda: copy.deepcopy(observed), ad=None), inputs, C.Maps(tmp_path))
    monkeypatch.setattr(P, "wait", lambda *_: None)
    ctrl.tick(observed)
    p1_moves = [c for batch in sent for c in batch if c[0] == 1 and c[1] not in (["l"], ["a"])]
    assert p1_moves                                         # P1 led forward instead of waiting on the buddy


def test_wall_wedge_recovery_backs_a_stalled_buddy_off_and_clears_on_progress(tmp_path):
    """A buddy pinned on geometry (a goal but no translation) backs off and tries
    another octant; one that is making progress is left to approach normally."""
    ctrl = _controller(tmp_path)
    p = {"x": 0., "z": 0., "heading_deg": 0.}
    wp = (0., 100.)                                                  # straight ahead (+z) -> ['lup']
    assert ctrl._unwedge(1, p, wp, now=100.) == (["lup"], False)      # just arrived: approach
    assert ctrl._unwedge(1, p, wp, now=101.) == (["lup"], False)      # still inside the stall window
    keys, escaping = ctrl._unwedge(1, p, wp, now=100. + C.WEDGE_STALL_S)
    assert escaping is True and keys != ["lup"]                       # wedged: back off, not into the wall
    held, _ = ctrl._unwedge(1, p, wp, now=100. + C.WEDGE_STALL_S + 0.1)
    assert held == keys                                              # hold the escape heading briefly
    moved = {"x": 0., "z": 50., "heading_deg": 0.}                   # translated: progress
    assert ctrl._unwedge(1, moved, wp, now=100. + C.WEDGE_STALL_S + 5) == (["lup"], False)
    assert ctrl.inputs.stats["wedge_recovery"]["slot"] == 1


def test_movement_path_is_input_only_and_writes_no_memory(tmp_path):
    """The normal drive-forward path is input-only; the only memory write is the
    separate, guarded force_forward_unlock fail-safe (tested below)."""
    writes = []
    ad = SimpleNamespace(write_memory=lambda *a, **k: writes.append(a),
                         read_memory=lambda *a, **k: pytest.fail("the movement path is input-only"))
    ctrl = _controller(tmp_path, ad=ad)
    st = _coop_room([{"class": "TObjDoor", "x": 100., "z": 0., "room": 10},
                     {"class": "TObjDoorKey", "x": 5., "z": 0., "room": 10}])
    cmds, moves, steer, fb = [], {}, {}, []
    ctrl.drive_forward(st, 1, st["players"][1], 100.0, cmds, moves, steer, fb)
    assert writes == [] and "forced_door_unlock" not in ctrl.inputs.stats


# --- Forced stage-flag unlock (operator's GUARANTEED fail-safe) ---------------

def _room10_flag_entities():
    """Forest-1 room 10: two TObjDoorKey panels (flags 7, 6) + the room-11 energy
    barrier (flag 10), each with a ptr whose +0xC8 holds its flag index."""
    return [{"class": "TObjDoorKey", "ptr": "80DB7560", "x": -127., "z": 71., "room": 10, "flag": 7},
            {"class": "TObjDoorKey", "ptr": "80DB76F0", "x": -95., "z": 214., "room": 10, "flag": 6},
            {"class": "TOBarrierEnergy01", "ptr": "80DB8CD0", "x": 221., "z": 492., "room": 11, "flag": 10}]


def _flag_ad(floor=1):
    """A fake GC adapter exposing the verified stage-flag array (base 0x80515CC8)
    and each gate object's +0xC8 flag index; records writes."""
    import gbox.pso_coop_gates as G
    mem, writes = {}, []
    c8 = {}
    for e in _room10_flag_entities():
        c8[int(e["ptr"], 16) + 0xC8] = e["flag"]
    def read(addr, n):
        a = int(addr)
        if a == G.STAGE_FLAG_GROUP_PTR:
            return struct.pack(">I", floor)
        if a in c8:
            return struct.pack(">I", c8[a])
        if G.STAGE_FLAG_BASE <= a < G.STAGE_FLAG_BASE + G.STAGE_FLAG_GROUPS * G.STAGE_GROUP_SIZE:
            return bytes(mem.get(a + i, 0) for i in range(n))
        return bytes(n)
    def write(addr, data):
        a = int(addr)
        for i, b in enumerate(data):
            mem[a + i] = b
        writes.append((a, bytes(data)))
    return SimpleNamespace(read_memory=read, write_memory=write), writes, mem


def test_forward_stuck_counts_time_since_new_room_not_hub_bounce(tmp_path):
    """The stuck timer accumulates while no NEW room is reached (hub bounce), and
    only a genuinely new visited room resets it - not standing still, not bouncing
    between already-visited rooms."""
    ctrl = _controller(tmp_path)
    st = _coop_room(_room10_flag_entities())
    ctrl.p1_visited = {5, 10}
    ctrl._forward_dwell_telemetry(st, now=100., engaged=True)
    assert ctrl.inputs.stats["forward_stuck"] is False
    ctrl._forward_dwell_telemetry(st, now=100. + C.FALLBACK_STUCK_S + 1, engaged=True)
    assert ctrl.inputs.stats["forward_stuck"] is True     # no new room reached -> stuck
    ctrl.p1_visited = {5, 10, 11}                          # real progress: a new room
    ctrl._forward_dwell_telemetry(st, now=100. + C.FALLBACK_STUCK_S + 2, engaged=True)
    assert ctrl.inputs.stats["forward_stuck"] is False


def test_force_unlock_sets_exactly_the_rooms_gate_flags(monkeypatch, tmp_path):
    import gbox.pso_coop_gates as G
    monkeypatch.setattr(G, "stage_flag_code_ok", lambda read: True)   # unit-test the write, not the on-disk build hash
    ad, writes, mem = _flag_ad(floor=1)
    ctrl = _controller(tmp_path, ad=ad)
    st = _coop_room(_room10_flag_entities())
    result = ctrl.force_forward_unlock(st, 1, st["players"][1], now=1000.)
    assert result == [6, 7, 10]
    # group 1 (floor 1): base 0x80515CC8 + 32 -> byte 0x80515CE8 holds flags 6|7, +1 holds flag 10
    assert mem[0x80515CE8] == 0x03 and mem[0x80515CE9] == 0x20
    fdu = ctrl.inputs.stats["forced_door_unlock"]
    assert fdu["flags"] == [6, 7, 10] and fdu["group"] == 1 and fdu["base"] == "0x80515cc8"
    # one shot per room: a second call does nothing new
    writes.clear()
    assert ctrl.force_forward_unlock(st, 1, st["players"][1], now=1001.) is None and writes == []


def test_force_adjacent_door_sets_the_rooms_gate_flags_for_the_pursued_door(monkeypatch, tmp_path):
    """The cluster-exit fix: a plain TObjDoor has no valid own +0xC8 flag index, so
    force_adjacent_door opens it with the ROOM's switch + nearest-barrier flags
    (the verified force_forward_unlock resolution), recomputed from P1's position AT
    the door. Keyed per-door with a re-arm window."""
    import gbox.pso_coop_gates as G
    monkeypatch.setattr(G, "stage_flag_code_ok", lambda read: True)
    ad, writes, mem = _flag_ad(floor=1)                 # switches flag 6,7 + nearest barrier flag 10
    ctrl = _controller(tmp_path, ad=ad)
    door = {"class": "TObjDoor", "ptr": "80DB9000", "x": 100., "z": 0., "room": 10, "kind": "gate"}
    st = _coop_room(_room10_flag_entities() + [door], p1=(0., 0.))
    gkey = ("TObjDoor", 100.0, 0.0)
    result = ctrl.force_adjacent_door(st, st["players"][1], gkey, now=1000.)
    assert result == [6, 7, 10]                         # the room's gate flags, not the door's own field
    assert mem[0x80515CE8] == 0x03 and mem[0x80515CE9] == 0x20   # flags 6|7 and 10 set
    assert ctrl.inputs.stats["forced_adjacent_door"]["written"] == [6, 7, 10]
    assert ctrl._adj_skip == "ok" and ctrl._adj_fires == 1
    # per-door one-shot within the re-arm window: an immediate second call writes nothing
    writes.clear()
    assert ctrl.force_adjacent_door(st, st["players"][1], gkey, now=1001.) is None and writes == []
    assert ctrl._adj_skip == "rearm_window"


def test_force_unlock_refuses_on_wrong_build_signature(tmp_path):
    """A wrong accessor/r13 signature (here: all-zero reads) must NOT write - a
    wrong base would corrupt the game, so the guard fails closed."""
    ad, writes, mem = _flag_ad(floor=1)
    ad.read_memory = lambda a, n: bytes(n)            # zero everything -> signature mismatch
    writes2 = []
    ad.write_memory = lambda a, d: writes2.append((a, d))
    ctrl = _controller(tmp_path, ad=ad)
    st = _coop_room(_room10_flag_entities())
    assert ctrl.force_forward_unlock(st, 1, st["players"][1], now=1000.) is None
    assert writes2 == [] and ctrl.inputs.stats["forced_door_unlock_skipped"]["reason"] == "build_signature_mismatch"


def test_force_unlock_refuses_when_group_ptr_is_not_the_floor(monkeypatch, tmp_path):
    import gbox.pso_coop_gates as G
    monkeypatch.setattr(G, "stage_flag_code_ok", lambda read: True)
    ad, writes, mem = _flag_ad(floor=5)               # array group ptr says floor 5...
    ctrl = _controller(tmp_path, ad=ad)
    st = _coop_room(_room10_flag_entities())           # ...but the state is floor 1
    assert ctrl.force_forward_unlock(st, 1, st["players"][1], now=1000.) is None and writes == []


def test_maybe_force_unlock_is_gated_by_the_stuck_timer(monkeypatch, tmp_path):
    import gbox.pso_coop_gates as G
    monkeypatch.setattr(G, "stage_flag_code_ok", lambda read: True)
    ad, writes, mem = _flag_ad(floor=1)
    ctrl = _controller(tmp_path, ad=ad)
    st = _coop_room(_room10_flag_entities())
    key = (st["episode"] if "episode" in st else 1, 1, 10)
    # Just arrived: no dwell, no recall -> no forced write.
    ctrl.room_dwell["_cur"] = {"key": (1, 1, 10), "since": 1000., "anchor": (0., 0.)}
    ctrl.maybe_force_unlock(st, now=1000.)
    assert writes == []
    # Past the stuck threshold -> the fail-safe fires.
    ctrl.maybe_force_unlock(st, now=1000. + C.FALLBACK_STUCK_S + 1)
    assert mem[0x80515CE8] == 0x03 and mem[0x80515CE9] == 0x20


def test_room_clear_gate_is_never_force_unlocked_with_enemies_present(monkeypatch, tmp_path):
    import gbox.pso_coop_gates as G
    monkeypatch.setattr(G, "stage_flag_code_ok", lambda read: True)
    ad, writes, mem = _flag_ad(floor=1)
    ctrl = _controller(tmp_path, ad=ad)
    st = _coop_room(_room10_flag_entities())
    st["entities"].append({"kind": "enemy", "class": "TObjEneMoja", "room": 10, "x": 0., "z": 10., "hp": 50})
    ctrl.room_dwell["_cur"] = {"key": (1, 1, 10), "since": 0., "anchor": (0., 0.)}
    ctrl.maybe_force_unlock(st, now=10_000.)           # long past the timer, but a live enemy is here
    assert writes == []


def test_knowledge_persists_the_gate_recipe_and_recalls_it_instantly(monkeypatch, tmp_path):
    from gbox.pso_knowledge import KnowledgeStore
    import gbox.pso_coop_gates as G
    monkeypatch.setattr(G, "stage_flag_code_ok", lambda read: True)
    ad, writes, mem = _flag_ad(floor=1)
    ctrl = _controller(tmp_path, ad=ad)
    ctrl.knowledge = KnowledgeStore(tmp_path / "pso-knowledge.json")
    st = _coop_room(_room10_flag_entities())
    assert ctrl.force_forward_unlock(st, 1, st["players"][1], now=1000.) == [6, 7, 10]
    # The recipe is on disk, keyed by the room fingerprint.
    reloaded = KnowledgeStore(tmp_path / "pso-knowledge.json")
    from gbox.pso_coop_nav import room_key
    fp = room_key(st, st["players"][1])[0]
    assert reloaded.recall(fp)["forward_flags"] == [6, 7, 10]
    # A FRESH controller recalls it and force-unlocks immediately, before any stuck timer.
    ad2, writes2, mem2 = _flag_ad(floor=1)
    fresh = _controller(tmp_path, ad=ad2)
    fresh.knowledge = reloaded
    assert fresh._recalled_flags(st, st["players"][1]) == [6, 7, 10]
    fresh.room_dwell["_cur"] = {"key": (1, 1, 10), "since": 1000., "anchor": (0., 0.)}
    fresh.maybe_force_unlock(st, now=1000.)            # dwell 0, but recalled -> fires now
    assert mem2[0x80515CE8] == 0x03 and mem2[0x80515CE9] == 0x20


def test_p1_crossing_records_a_directed_edge_and_a_later_run_recalls_it(tmp_path):
    """The convergence crystal: P1 crossing a door records a directed edge
    (from_room -> door -> to_room) and the run's exploration order; a later run
    over the same area recalls the graph + critical path, so a room OWNS its
    outbound door from the first step and the route compounds across runs."""
    from gbox.pso_knowledge import KnowledgeStore, area_fingerprint
    area = area_fingerprint(1, 1, "g")
    ctrl = _controller(tmp_path)
    ctrl.knowledge = KnowledgeStore(tmp_path / "pso-knowledge.json")
    # Run 1: P1 commits to room 10's forward door, then is seen in room 11.
    st10 = _coop_room([{"class": "TObjDoor", "x": 100., "z": 0., "room": 10}], room=10)
    ctrl.forward_fallback(st10, 1, st10["players"][1], now=50.0)
    assert ctrl._p1_door == ("TObjDoor", 100.0, 0.0)             # pursuing room 10's door
    st11 = _coop_room([{"class": "TObjDoor", "x": 200., "z": 0., "room": 11}], room=11)
    ctrl.forward_fallback(st11, 1, st11["players"][1], now=51.0)  # crossed -> edge + path recorded
    assert ctrl.knowledge.area_edges(area) == {10: {"('TObjDoor', 100.0, 0.0)": 11}}
    assert ctrl.knowledge.critical_path(area) == [10, 11]
    # Run 2: a fresh controller on the SAME crystal recalls the graph + path on
    # area entry (before any crossing this run).
    run2 = _controller(tmp_path)
    run2.knowledge = KnowledgeStore(tmp_path / "pso-knowledge.json")
    fresh10 = _coop_room([{"class": "TObjDoor", "x": 100., "z": 0., "room": 10}], room=10)
    run2.forward_fallback(fresh10, 1, fresh10["players"][1], now=10.0)
    assert run2._area_graph == {10: {"('TObjDoor', 100.0, 0.0)": 11}}
    assert run2._crit_path == [10, 11]
    assert run2._path_next(10) == 11 and run2._path_next(11) is None


def test_p1_rejects_a_crystal_recalled_dead_end_door_for_an_untraversed_one(tmp_path):
    """The convergence fix: when the crystal recalls a door's destination as an
    already-VISITED room (a dead-end branch) and another door is untraversed, P1
    takes the untraversed (frontier) door - it does not commit to the recalled
    dead-end even when that dead-end door is nearer. This is the 10<->11/14 wall:
    every recalled edge led back to a visited room, so P1 must explore the frontier."""
    ctrl = _controller(tmp_path)
    dead = {"class": "TObjLazerFenceNorm", "x": 40., "z": 0., "room": 10}   # recalled 10->14 (14 visited)
    frontier = {"class": "TObjDoor", "x": 120., "z": 0., "room": 10}        # never traversed
    st = _coop_room([dead, frontier], p1=(0., 0.))
    ctrl.p1_visited = {10, 14}
    ctrl._p1_room = 10
    ctrl._area_graph = {10: {"('TObjLazerFenceNorm', 40.0, 0.0)": 14}}      # crystal: dead -> visited 14
    dest = ctrl.forward_fallback(st, 1, st["players"][1], now=100.)
    assert dest[0] > 120.                                                   # commits through the frontier door, not the nearer dead-end


def test_recovery_grid_relaxes_a_partial_floor_but_a_complete_grid_does_not():
    """Fix (A): a RECOVERY grid (partial floor, no wall data) relaxes floor
    membership so A* still routes to a target its partial surface doesn't cover,
    instead of the caller straight-lining into a wall; a COMPLETE projection is
    never relaxed, so a goal outside its floor stays unreachable (cliff / out-of-
    bounds safety preserved)."""
    floor = [[i, 0] for i in range(0, 6)]        # a thin strip of cells (0..5, 0); goal cell (5,5) is NOT on it
    start, goal = (5., 5.), (55., 55.)           # cells (0,0) -> (5,5)
    complete = RoomMap(size=10.0, floor=floor, recovery=False)
    assert complete.route(start, goal) is None   # complete grid: goal off-floor stays unreachable (safe)
    recovered = RoomMap(size=10.0, floor=floor, recovery=True)
    path = recovered.route(start, goal)
    assert path is not None and path[-1] == recovered.center((5, 5))   # recovery grid: relaxed, routes to the target


def test_toward_approaches_an_unreachable_goal_to_the_nearest_reachable_cell():
    """The full-floor-can't-reach-far-target fix: toward() returns the exact path when
    the goal is reachable, else the path to the nearest reachable cell on P1's OWN
    component (so P1 walks UP TO a door it can't path past, instead of straight-lining
    into the wall). exact flags which happened; it never returns None from a usable start."""
    floor = [[i, 0] for i in range(0, 6)]            # cells (0..5, 0); start cell (0,0)
    m = RoomMap(size=10.0, floor=floor)
    reachable, exact = m.toward((5., 5.), (55., 5.))   # goal cell (5,0) is ON the floor
    assert exact is True and reachable[-1] == m.center((5, 0))
    approach, exact2 = m.toward((5., 5.), (105., 5.))  # goal cell (10,0) is OFF the floor (disconnected)
    assert exact2 is False and approach is not None and approach[-1] == m.center((5, 0))  # best-effort to the edge


def test_coordinate_drive_engages_when_stuck_on_an_unreachable_forward_door(tmp_path):
    """Fallback (B): in a CLEARED room, when A* can't path past the forward door
    (route_exact False) for COORD_DRIVE_AFTER_S, P1 commits to driving STRAIGHT at
    the door's coordinates (bypassing A*'s backward waypoint) instead of oscillating."""
    ctrl = _controller(tmp_path)
    st = _coop_room([{"class": "TObjDoor", "x": 300., "z": 0., "room": 10}], p1=(0., 0.))
    # A partial floor that excludes the door cell, so A* cannot reach it (route_exact False).
    st["geometry_players"] = {1: {"geometry_layer": "L", "collision_grid":
        {"size": 10.0, "floor": [[i, 0] for i in range(0, 6)], "walls": [], "heights": []}}}
    p1 = st["players"][1]
    cmds, moves, steer, fb = [], {}, {}, []
    ctrl.drive_forward(st, 1, p1, 100.0, cmds, moves, steer, fb)           # commit starts; grace not elapsed
    assert ctrl.inputs.stats.get("coord_drive") == 0
    cmds, moves, steer, fb = [], {}, {}, []
    ctrl.drive_forward(st, 1, p1, 100.0 + C.COORD_DRIVE_AFTER_S + 0.1, cmds, moves, steer, fb)
    assert ctrl.inputs.stats.get("coord_drive") == 1                      # committed: driving straight at the door
    assert steer[1][2] == "forward_coord_drive"


def test_two_player_hold_fence_crossing_targets_fence_and_switch(tmp_path):
    """The Forest hold-puzzle exit: a TObjLazerFenceNorm + a TLazerFenceSw within
    FENCE_PAIR_DIST is selected as the forward objective (regardless of visited room);
    P1's fence-role drives THROUGH the fence, P2's drives to STAND ON the switch and
    hold it. A fence P1 already crossed is not re-targeted."""
    ctrl = _controller(tmp_path)
    fence = {"class": "TObjLazerFenceNorm", "x": -420., "z": 485.8, "room": 5, "kind": "gate"}
    switch = {"class": "TLazerFenceSw", "x": -399.7, "z": 541.0, "room": 5, "kind": "gate"}
    st = _coop_room([fence, switch], p1=(0., 0.), p2=(10., 0.), room=5)
    obj = ctrl.select_fence_objective(st, st["players"][1])
    assert obj is not None and obj["fence"] == ("TObjLazerFenceNorm", -420.0, 485.8)
    assert round(obj["sx"], 1) == -399.7 and round(obj["sz"], 1) == 541.0
    ctrl._fence_obj = obj
    # P2 far from the switch -> P1 WAITS at the fence (doesn't bounce the raised fence).
    cmds, moves, steer = [], {}, {}
    assert ctrl.fence_role(st, 1, st["players"][1], 100.0, cmds, moves, steer) is True
    assert steer[1][2].startswith("fence_wait")
    # P2 drives to hold the switch.
    cmds, moves, steer = [], {}, {}
    assert ctrl.fence_role(st, 2, st["players"][2], 100.0, cmds, moves, steer) is True
    assert steer[2][2].startswith("fence_switch")
    # With P2 standing ON the switch, P1 COMMITS through the fence.
    st["players"][2]["x"], st["players"][2]["z"] = -399.7, 541.0
    cmds, moves, steer = [], {}, {}
    assert ctrl.fence_role(st, 1, st["players"][1], 100.0, cmds, moves, steer) is True
    assert steer[1][2].startswith("fence_cross")
    ctrl._crossed_fences.add(obj["fence"])
    assert ctrl.select_fence_objective(st, st["players"][1]) is None   # a crossed fence is not re-targeted


def test_p2_routes_door_by_door_to_the_switch_room(tmp_path):
    """When P2 isn't yet in the switch's room, it ROUTES through the door from its room
    toward the switch's room (via the crystal room-graph P1 built) instead of
    straight-driving into the boundary wall."""
    ctrl = _controller(tmp_path)
    door = {"class": "TObjDoor", "x": 100., "z": 0., "room": 10, "kind": "gate"}
    fence = {"class": "TObjLazerFenceNorm", "x": -420., "z": 485.8, "room": 5, "kind": "gate"}
    switch = {"class": "TLazerFenceSw", "x": -399.7, "z": 541.0, "room": 5, "kind": "gate"}
    st = _coop_room([door, fence, switch], p1=(-420., 485.8), p2=(0., 0.), room=10)
    st["players"][1]["room"] = 5                      # P1 is already in room 5 at the fence
    ctrl._area_graph = {10: {"('TObjDoor', 100.0, 0.0)": 5}}   # crystal: room 10 -> this door -> room 5
    ctrl._fence_obj = ctrl.select_fence_objective(st, st["players"][1])
    assert ctrl._fence_obj is not None and ctrl._fence_obj["sroom"] == 5
    assert ctrl._next_door_toward(10, 5) == "('TObjDoor', 100.0, 0.0)"
    cmds, moves, steer = [], {}, {}
    assert ctrl.fence_role(st, 2, st["players"][2], 100.0, cmds, moves, steer) is True
    assert steer[2][2].startswith("fence_route")      # P2 heads THROUGH the door toward room 5, not at the switch


def test_place_p2_on_switch_writes_p2_position_onto_the_switch(tmp_path):
    """RAM fallback: when P2 can't physically reach the hold-switch, its actor position
    is written directly onto the switch's exact 3D coords (x/y/z f32 at ptr+0x38, using
    the switch entity's OWN y) under the verified two-player / room-clear guards."""
    writes = []
    ad = SimpleNamespace(read_memory=lambda a, n: bytes(n),
                         write_memory=lambda a, d: writes.append((int(a), bytes(d))))
    ctrl = _controller(tmp_path, ad=ad)
    switch = {"class": "TLazerFenceSw", "x": -399.7, "z": 541.0, "y": 12.5, "room": 5, "kind": "gate"}
    fence = {"class": "TObjLazerFenceNorm", "x": -420., "z": 485.8, "room": 5, "kind": "gate"}
    st = _coop_room([fence, switch], p1=(-420., 485.8), p2=(0., 0.), room=5)
    ctrl._fence_obj = ctrl.select_fence_objective(st, st["players"][1])
    assert ctrl._fence_obj is not None and ctrl._fence_obj["sy"] == 12.5
    p2 = st["players"][2]
    assert ctrl.place_p2_on_switch(st, p2, now=100.) is True and ctrl._p2_placed is True
    addr = int(p2["ptr"], 16) + 0x38
    wrote = [d for a, d in writes if a == addr]
    assert wrote and wrote[0] == struct.pack(">3f", -399.7, 12.5, 541.0)   # x/y/z onto the switch


def test_place_p1_across_fence_writes_p1_past_the_fence(tmp_path):
    """RAM fallback LAST step: when the fence's gate flag is already set but P1 can't
    step across the threshold, P1's actor position is written to a point PAST the fence
    (along its approach, at the fence's own y) so it lands in the next room."""
    writes = []
    ad = SimpleNamespace(read_memory=lambda a, n: bytes(n),
                         write_memory=lambda a, d: writes.append((int(a), bytes(d))))
    ctrl = _controller(tmp_path, ad=ad)
    switch = {"class": "TLazerFenceSw", "x": -399.7, "z": 541.0, "y": 12.5, "room": 5, "kind": "gate"}
    fence = {"class": "TObjLazerFenceNorm", "x": -420., "z": 485.8, "y": 20.0, "room": 5, "kind": "gate"}
    st = _coop_room([fence, switch], p1=(-400., 485.8), p2=(-399.7, 541.0), room=5)
    ctrl._fence_obj = ctrl.select_fence_objective(st, st["players"][1])
    assert ctrl._fence_obj is not None and ctrl._fence_obj["fy"] == 20.0
    p1 = st["players"][1]
    assert ctrl.place_p1_across_fence(st, p1, now=100.) is True and ctrl._p1_placed is True
    addr = int(p1["ptr"], 16) + 0x38
    wrote = [d for a, d in writes if a == addr]
    assert wrote
    x, y, z = struct.unpack(">3f", wrote[0])
    assert abs(y - 20.0) < 0.01 and x < -420. and abs(z - 485.8) < 0.1   # past the fence, at the fence's y


def test_force_fence_collision_off_is_class_verified_and_writes_the_sub_object(tmp_path):
    """Bounded collision probe: class-VERIFY the fence (object+0x0 -> 'TObjLazerFenceNorm')
    then write the laser collision sub-object's (+0xA4 -> +0x14) field to 0. Fails closed
    if the class string doesn't match."""
    FENCE, CLASS, SUB = 0x80DB1ED0, 0x80445B84, 0x81495B20
    def rd(a, n):
        a = int(a)
        if a == FENCE:
            return struct.pack(">I", CLASS)
        if a == CLASS:
            return (b"TObjLazerFenceNorm" + bytes(max(0, n - 18)))[:n]
        if a == FENCE + 0xA4:
            return struct.pack(">I", SUB)
        if a == SUB + 0x14:
            return struct.pack(">I", 1)
        return bytes(n)
    writes = []
    ad = SimpleNamespace(read_memory=rd, write_memory=lambda a, d: writes.append((int(a), bytes(d))))
    ctrl = _controller(tmp_path, ad=ad)
    ents = [{"class": "TObjLazerFenceNorm", "x": -420., "z": 485.8, "room": 5, "ptr": hex(FENCE), "kind": "gate"},
            {"class": "TLazerFenceSw", "x": -399.7, "z": 541.0, "room": 5, "kind": "gate"}]
    st = _coop_room(ents, p1=(-420., 485.8), p2=(0., 0.), room=5)
    ctrl._fence_obj = ctrl.select_fence_objective(st, st["players"][1])
    addr = ctrl.force_fence_collision_off(st, now=100.)
    assert addr == SUB + 0x14 and (SUB + 0x14, struct.pack(">I", 0)) in writes and ctrl._fence_coll_before == 1
    # Fail closed on a class mismatch (all-zero reads -> bad class ptr).
    ctrl2 = _controller(tmp_path, ad=SimpleNamespace(read_memory=lambda a, n: bytes(n), write_memory=lambda a, d: None))
    ctrl2._fence_obj = ctrl.select_fence_objective(st, st["players"][1])
    assert ctrl2.force_fence_collision_off(st, now=100.) is None


def test_physical_hold_p2_fine_approach_and_p1_crosses_only_when_fence_down(tmp_path):
    """The physical two-player hold primitive: P2 within FENCE_FINE_DIST of the plate
    uses a TIGHT terminal approach (short precise pulses), and P1 physically crosses
    ONLY when the fence's live collision reads DOWN (frame-synced), waiting otherwise."""
    FENCE, SUB, coll = 0x80DB1ED0, 0x81495B20, {"v": 1}
    def rd(a, n):
        a = int(a)
        if a == FENCE + 0xAC:
            return struct.pack(">I", 7)
        if a == FENCE + 0xA4:
            return struct.pack(">I", SUB)
        if a == SUB + 0x14:
            return struct.pack(">I", coll["v"])
        return bytes(n)
    ad = SimpleNamespace(read_memory=rd, write_memory=lambda a, d: None)
    ctrl = _controller(tmp_path, ad=ad)
    fence = {"class": "TObjLazerFenceNorm", "x": -420., "z": 485.8, "room": 5, "ptr": hex(FENCE), "kind": "gate"}
    switch = {"class": "TLazerFenceSw", "x": -399.7, "z": 541.0, "room": 5, "kind": "gate"}
    st = _coop_room([fence, switch], p1=(-420., 485.8), p2=(-370., 560.), room=5)   # P2 ~35u from plate
    ctrl._fence_obj = ctrl.select_fence_objective(st, st["players"][1])
    cmds, moves, steer = [], {}, {}
    assert ctrl.fence_role(st, 2, st["players"][2], 100.0, cmds, moves, steer) is True
    assert steer[2][2] == "fence_switch_fine" and cmds[0][2] == 0.08          # tight terminal approach
    cmds, moves, steer = [], {}, {}
    ctrl.fence_role(st, 1, st["players"][1], 100.0, cmds, moves, steer)
    assert steer[1][2] == "fence_wait"                                        # fence up -> P1 waits
    coll["v"] = 0                                                            # sensor fired -> laser physically down
    cmds, moves, steer = [], {}, {}
    ctrl.fence_role(st, 1, st["players"][1], 100.0, cmds, moves, steer)
    assert steer[1][2] == "fence_cross" and ctrl.inputs.stats.get("fence_coll_live") == 0


def test_advance_on_stall_warps_when_cleared_room_stalls_but_fights_first(tmp_path):
    """Perpetual play: a cleared room with no NEW room for ADVANCE_STALL_S triggers a
    native floor-advance warp (throttled); a room with a live enemy does NOT (fight
    first). The warp is fail-soft when the engine module isn't present."""
    ad = SimpleNamespace(read_memory=lambda a, n: bytes(n), write_memory=lambda a, d: None)
    ctrl = _controller(tmp_path, ad=ad)
    st = _coop_room([], p1=(0., 0.), p2=(5., 0.), room=10)             # floor 1, cleared
    ctrl._adv_floor = 1                                                # already settled in this area (no floor-change reset)
    ctrl.room_dwell['_cur'] = {'nvisited': 2, 'since': 100.}
    assert ctrl.advance_on_stall(st, now=110.) is False                # not stalled long enough
    assert ctrl.advance_on_stall(st, now=100. + C.ADVANCE_STALL_S + 1) is True   # stalled -> warp attempted
    assert ctrl._floor_advances == 1 and ctrl.inputs.stats.get('floor_advances') == 1
    assert ctrl.advance_on_stall(st, now=100. + C.ADVANCE_STALL_S + 2) is False  # throttled
    # A fresh floor resets the window (play each area through, don't warp immediately).
    st_f2 = _coop_room([], p1=(0., 0.), p2=(5., 0.), room=10)
    st_f2["floor"] = 2
    ctrl.room_dwell['_cur'] = {'nvisited': 2, 'since': 0.}
    assert ctrl.advance_on_stall(st_f2, now=100. + C.ADVANCE_STALL_S + 3) is False and ctrl._adv_floor == 2
    # A live enemy in P1's room -> fight first, no warp.
    ctrl._last_warp_at = 0.
    ctrl._adv_floor = 2
    ctrl.room_dwell['_cur'] = {'nvisited': 2, 'since': 0.}
    st2 = _coop_room([], room=10)
    st2["floor"] = 2
    st2["entities"].append({"class": "TObjEneMoja", "kind": "enemy", "hp": 50, "x": 1., "z": 0., "room": 10})
    assert ctrl.advance_on_stall(st2, now=C.ADVANCE_STALL_S + 5) is False   # below hard cap: fight first
    # ABSOLUTE anti-freeze: past STALL_HARDCAP_S it warps DESPITE the live enemies.
    ctrl._last_warp_at = 0.
    assert ctrl.advance_on_stall(st2, now=C.STALL_HARDCAP_S + 1) is True
    assert ctrl._hardcap_warps == 1 and ctrl.inputs.stats.get('stall_hardcap_warps') == 1


def test_menu_unstick_warps_instead_of_stopping_and_is_throttled(monkeypatch):
    """INVARIANT: a stuck menu / needs_operator / boss-end dialogue NEVER halts the
    loop. menu_unstick fires the native floor-warp (bypasses any menu via a RAM load),
    records the flat proof key menu_stuck_warps, is throttled so it can't hammer the
    loader, and is fail-soft (a raising engine is swallowed, still counts the attempt,
    never raises -> the caller continues playing)."""
    import gbox.pso_fence as F
    warps = []
    monkeypatch.setattr(F, "advance_floor", lambda ad: warps.append(ad) or {"ok": True, "floor": 5})

    t = [1000.0]
    monkeypatch.setattr(C.time, "monotonic", lambda: t[0])
    ad = SimpleNamespace()
    stats = {}

    assert C.menu_unstick(ad, stats) is True                     # first call warps
    assert len(warps) == 1
    assert stats["menu_stuck_warps"] == 1                         # flat proof key
    assert stats["menu_stuck_warp_ok"] is True and stats["menu_stuck_warp_floor"] == 5
    assert stats["action"] == "menu_unstick_warp"

    t[0] += C.MENU_WARP_GAP_S / 2                                 # within the throttle window
    assert C.menu_unstick(ad, stats) is False and len(warps) == 1 and stats["menu_stuck_warps"] == 1

    t[0] += C.MENU_WARP_GAP_S                                     # past the throttle -> warps again
    assert C.menu_unstick(ad, stats) is True and len(warps) == 2 and stats["menu_stuck_warps"] == 2

    # Fail-soft: an engine that raises must NOT halt - it still counts and returns True.
    monkeypatch.setattr(F, "advance_floor", lambda ad: (_ for _ in ()).throw(RuntimeError("boom")))
    t[0] += C.MENU_WARP_GAP_S
    assert C.menu_unstick(ad, stats) is True
    assert stats["menu_stuck_warps"] == 3 and stats["menu_stuck_warp_ok"] is False


def test_master_build_tick_gates_throttles_and_flags_reroll(monkeypatch):
    """The co-op loop's master-build call: gated to live gameplay, throttled between
    ticks (but forced at spawn / on room change), reports per-player and returns True
    only when a weapon re-rolled so the caller reobserves weapon ranges."""
    import gbox.pso_master_build as MB
    calls = []

    def stub(ad, **kw):
        calls.append(kw)
        return {0: {"ok": True, "lck": 100, "weapon": {"code": "003300", "rerolled": ad._reroll},
                    "errors": {}},
                1: {"ok": True, "lck": 100, "weapon": {"code": "001000", "rerolled": False}, "errors": {}}}
    monkeypatch.setattr(MB, "apply_master_build_all", stub)

    ad = SimpleNamespace(_reroll=True)
    gameplay = state(floor=1)                       # verified, phase 14, floor 1
    stats = {}
    # Not in gameplay -> no call, no reroll.
    assert C.apply_master_build_tick(ad, state(floor=0), stats) is False and not calls
    # Spawn (force) in gameplay -> calls, records summary, reports the reroll.
    assert C.apply_master_build_tick(ad, gameplay, stats, force=True) is True
    assert len(calls) == 1 and stats["master_build"]["0"]["weapon"] == "003300"
    # FLAT scalar mirrors survive the telemetry endpoint (nested dicts are dropped).
    assert stats["mb_ok_p1"] == 1 and stats["mb_lck_p1"] == 100 and stats["mb_weapon_p1"] == "003300"
    assert stats["mb_weapon_p2"] == "001000"
    # Immediately again, same room, not forced -> throttled (no new call).
    ad._reroll = False
    assert C.apply_master_build_tick(ad, gameplay, stats) is False and len(calls) == 1
    # A room change forces a call through the throttle.
    moved = state(floor=1)
    moved["players"][1]["room"] = 11
    assert C.apply_master_build_tick(ad, moved, stats) is False and len(calls) == 2

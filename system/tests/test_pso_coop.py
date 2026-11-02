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
    """Operator 2026-11-02 top pain: with no verified grid the buddies must still MOVE
    toward the room's switch/door instead of idling. P1 leads to the nearer switch; P2
    follows the same committed affordance."""
    observed = _field_state()
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
    assert moved == {1, 2}                                   # both buddies received movement
    assert all("lup" in c[1] for c in moves)                # +z is straight ahead of heading 0
    assert stats["forward_fallback_target"] == "TLazerFenceSw"   # switch is reached before the door
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


def test_forward_stuck_flag_fires_after_threshold_and_resets_on_translation():
    """The scalar fail-safe telemetry flags a room held with no forward translation
    (operator cue that the physical switch/door path has not progressed)."""
    stats = {}
    controller = C.Controller(SimpleNamespace(), SimpleNamespace(stats=stats), None)
    observed = _field_state()
    controller._forward_dwell_telemetry(observed, 1000., False)
    assert stats["forward_stuck"] is False and stats["forward_time_in_room_s"] == 0.0
    controller._forward_dwell_telemetry(observed, 1000. + C.FALLBACK_STUCK_S + 1, False)
    assert stats["forward_stuck"] is True                       # held one spot past the threshold
    observed["players"][1]["x"] = 300.                          # P1 translated far: progress
    controller._forward_dwell_telemetry(observed, 1000. + C.FALLBACK_STUCK_S + 2, True)
    assert stats["forward_stuck"] is False and stats["forward_time_in_room_s"] == 0.0


def test_buddies_advance_when_geometry_verified_but_no_collision_grid(monkeypatch, tmp_path):
    """Live deadlock (i9, Ep1 Fl1): geometry_verified is True (field_owned) yet the
    buddies have no usable collision grid, so FieldObjectives yields nothing and the
    old code idled both (P1 waiting on P2's missing layer, P2 stuck in margin
    recovery). They must still advance toward the room's forward switch/door."""
    observed = _field_state()
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
    assert moved == {1, 2}                           # neither buddy idles in the deadlock
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


def test_forward_progression_never_blind_writes_memory(tmp_path):
    """STEP 3 forced-unlock is DEFERRED: the shipped logic opens no door by RAM
    write (no verified open-flag offset), so it must touch no memory."""
    writes = []
    ad = SimpleNamespace(write_memory=lambda *a, **k: writes.append(a),
                         read_memory=lambda *a, **k: pytest.fail("forward progression is input-only"))
    ctrl = _controller(tmp_path, ad=ad)
    st = _coop_room([{"class": "TObjDoor", "x": 100., "z": 0., "room": 10},
                     {"class": "TObjDoorKey", "x": 5., "z": 0., "room": 10}])
    cmds, moves, steer, fb = [], {}, {}, []
    ctrl.drive_forward(st, 1, st["players"][1], 100.0, cmds, moves, steer, fb)
    assert writes == [] and "forced_door_unlock" not in ctrl.inputs.stats

"""Campaign truthfulness and control boundaries, independent of a live emulator."""
from types import SimpleNamespace

import pytest

from gbox import pso_campaign as P
from gbox.registry import Unsupported


def state(episode=1, floor=1, hp=None, **extra):
    enemies = [] if hp is None else [{"kind": "enemy", "ptr": "80A00000", "class": "TBossFinal",
                                      "hp": hp, "hp_max": 1000, "x": 0, "z": 0}]
    return {"verified": True, "phase": 14, "episode": episode, "floor": floor,
            "player": {"hp": 40, "hp_max": 40, "x": 0, "z": 0}, "entities": enemies, **extra}


def finish(progress, episode, start=0):
    for floor in sorted(P.REQUIRED_FLOORS[episode]):
        progress.observe(state(episode, floor))
    progress.observe(state(episode, P.FINAL_FLOORS[episode], 1000))
    progress.observe(state(episode, P.FINAL_FLOORS[episode], 0))
    assert progress.ending("credits", f"first-{start}", start) is None
    return progress.ending("credits", f"second-{start}", start + 3)


def test_both_episodes_are_required_before_a_cycle_is_complete():
    p = P.Progress()
    one = finish(p, 1)
    assert one["outcome"] == "episode_complete"
    assert p.target == 2 and p.episodes == 1 and p.cycles == 0
    assert not p.status()["completion_verified"]
    two = finish(p, 2, 10)
    assert two["outcome"] == "episode_complete"
    assert p.target == 1 and p.cycles == 1 and p.episodes == 2
    assert p.status()["completion_verified"]
    finish(p, 1, 20)
    assert p.cycles == 1 and p.target == 2


@pytest.mark.parametrize("ending", ["menu", "loading", "gameplay", "death", "unknown"])
def test_empty_arena_and_loading_screens_are_not_completion(ending):
    p = P.Progress()
    p.observe(state(floor=14, hp=1000))
    p.observe(state(floor=14))  # despawn is not a zero-HP observation
    assert p.ending(ending, "one", 0) is None
    assert p.ending("credits", "two", 5) is None
    assert not p.boss_zero and p.cycles == 0


def test_dead_regular_enemy_and_unverified_memory_do_not_prove_final_boss():
    for fixture in [state(floor=14, hp=0, verified=False),
                    state(floor=14, hp=0, entities=[{"kind": "enemy", "class": "TObjEneBeast", "hp": 0, "hp_max": 10}])]:
        p = P.Progress()
        p.observe(fixture)
        assert p.ending("credits", "a", 0) is None
        assert p.ending("credits", "b", 10) is None


def test_zero_at_arrival_is_not_evidence_of_a_kill():
    p = P.Progress()
    p.observe(state(floor=14, hp=0))
    assert not p.boss_zero


def test_boss_phase_change_and_living_parts_revoke_zero_evidence():
    p = P.Progress()
    p.observe(state(floor=14, hp=1000))
    p.observe(state(floor=14, hp=0))
    assert p.boss_zero
    parts = state(floor=14, hp=0)
    parts["entities"].insert(0, {"kind": "enemy", "ptr": "80B00000", "class": "TBossFinalSecondForm", "hp": 500, "hp_max": 1000})
    p.observe(parts)
    assert not p.boss_zero


def test_duplicate_or_fast_frames_do_not_count_and_noncredits_break_sequence():
    p = P.Progress()
    p.observe(state(floor=14, hp=1000))
    p.observe(state(floor=14, hp=0))
    assert p.ending("credits", "a", 0) is None
    assert p.ending("credits", "a", 10) is None
    assert p.ending("gameplay", "b", 12) is None
    assert p.ending("credits", "c", 13) is None
    assert p.ending("credits", "d", 14) is None
    assert p.ending("credits", "e", 16)["outcome"] == "partial_episode_finish"
    assert p.target == 1 and p.episodes == 0


def test_partial_run_restarts_without_aggregating_coverage_across_saves():
    p = P.Progress()
    for floor in range(1, 10):
        p.observe(state(floor=floor))
    p.observe({"phase": 3, "verified": False})
    p.observe(state(floor=10))
    for floor in range(11, 15):
        p.observe(state(floor=floor))
    p.observe(state(floor=14, hp=1000))
    p.observe(state(floor=14, hp=0))
    p.ending("credits", "a", 0)
    receipt = p.ending("credits", "b", 3)
    assert receipt["outcome"] == "partial_episode_finish"
    assert not receipt["started_at_entry"] and receipt["missing_floors"] == list(range(1, 10))


def test_town_trip_does_not_invalidate_a_running_route():
    p = P.Progress()
    p.observe(state(floor=1))
    p.observe(state(floor=0))
    p.observe(state(floor=2))
    assert p.visited == {1, 2} and p.started_at_entry


def test_credits_in_menu_keep_the_native_evidence_until_receipted():
    p = P.Progress()
    for floor in range(1, 15):
        p.observe(state(floor=floor))
    p.observe(state(floor=14, hp=1000))
    p.observe(state(floor=14, hp=0))
    p.observe({"phase": 4, "verified": False})
    p.ending("credits", "a", 0)
    assert p.ending("credits", "b", 3)["outcome"] == "episode_complete"


@pytest.mark.parametrize("action", [None, {"keys": ["delete"], "secs": 1}, {"keys": ["a"], "secs": -1},
    {"keys": ["a"], "secs": 120}, {"keys": ["a"], "secs": float("nan")}, {"keys": "a", "secs": 1},
    {"keys": ["a"], "secs": True}, {"keys": [{}], "secs": 1}])
def test_planner_actions_reject_unknown_keys_and_unbounded_holds(action):
    with pytest.raises(ValueError):
        P.actions({"actions": [{"keys": ["a"], "secs": 0.1}, action]})


def test_needs_operator_suppresses_all_planned_input():
    assert P.actions({"needs_operator": True, "actions": [{"keys": ["a"], "secs": 1}]}) == []
    assert P.actions({"actions": [{"keys": ["lup"], "secs": 0.5}]}) == [(["lup"], 0.5)]


def test_wrong_revision_and_online_are_refused_without_writing():
    ad = SimpleNamespace(read_memory=lambda a, n: b"GPOE8P\0\x01"[:n])
    with pytest.raises(Unsupported, match="revision 2"):
        P.setup(ad)
    def read(address, length):
        return {0x80000000: b"GPOE8P\0\x02", P.PHASE: (15).to_bytes(4, "big")}[address][:length]
    ad.read_memory, ad.write_memory = read, lambda *args: pytest.fail("Campaign must never write RAM")
    with pytest.raises(Unsupported, match="offline"):
        P.Reader(ad).snapshot()


def test_area_loader_does_not_dereference_an_absent_player(monkeypatch):
    from test_pso_gc_adventure import memory
    ad = memory()
    ad.word(P.TRAVELLING, 1)
    ad.word(P.PLAYER, 0)
    reader = P.Reader(ad)
    monkeypatch.setattr(reader.extractor, "state", lambda: pytest.fail("Loader has no initialized entities"))
    observed = reader.snapshot()
    assert observed["travelling"] and observed["phase"] == 14 and not observed["verified"]
    assert not ad.writes


def test_stop_interrupts_hold_and_releases_its_buttons(monkeypatch):
    sent, stopped = [], {"value": False}
    def send(events):
        sent.append(events)
        if events[0]["down"]:
            stopped["value"] = True
    fighter = P.LocalDriver(None, send, lambda: stopped["value"], P.Progress())
    monkeypatch.setattr(P.time, "sleep", lambda secs: pytest.fail("Stop should interrupt the wait immediately"))
    fighter.hold(["a"], 1.5)
    assert sent == [[{"key": "a", "down": True}], [{"key": "a", "down": False}]]
    with pytest.raises(InterruptedError):
        fighter.hold(["a"], 1)


def test_play_stops_on_card_prompt_and_releases_input(monkeypatch, tmp_path):
    class FakeReader:
        def __init__(self, ad):
            pass
        def snapshot(self):
            return {"phase": 3, "verified": False, "entities": [], "player": None}
    class FakePlanner:
        def __init__(self, driver, config=None):
            pass
        def __call__(self, frame, context):
            return {"thought": "The card asks to format", "screen": "menu", "needs_operator": True,
                    "actions": [{"keys": ["a"], "secs": 1}]}
        def close(self):
            pass
    monkeypatch.setattr(P, "Reader", FakeReader)
    monkeypatch.setattr(P, "Planner", FakePlanner)
    sent = []
    ad = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), get_frame=lambda: b"frame")
    result = P.play(ad, sent.extend, lambda: False, driver=object(), session_id="test")
    assert not result["ok"] and result["campaign_state"] == "needs_operator"
    assert sent and not any(e["down"] for e in sent)


def test_autoplay_input_keeps_campaign_for_resume():
    from gbox.tools import AutoplayIn
    request = AutoplayIn(session_id="worker-test", op="start", mode="playbook", campaign=P.CAMPAIGN, continuous=True)
    assert AutoplayIn.model_validate(request.model_dump()).campaign == P.CAMPAIGN


def test_vision_endpoint_uses_configured_remote_worker_service():
    driver = SimpleNamespace(api=SimpleNamespace(base_url="http://federated-authority:8787"))
    config = SimpleNamespace(agent={"llm_url": "http://127.0.0.1:11434/v1", "vision_model": "vision-test"},
                             llm_endpoints=[SimpleNamespace(url="http://spark:11434/v1")])
    assert P.vision_settings(driver, config) == ("http://spark:11434/v1", "vision-test")
    config.agent["vision_url"] = "http://localhost:2345/v1"
    assert P.vision_settings(driver, config) == ("http://localhost:2345/v1", "vision-test")


def test_missing_vision_model_fails_preflight_before_start():
    planner = P.Planner.__new__(P.Planner)
    planner.model = "missing"
    planner.api = SimpleNamespace(base_url="http://test:11434/v1", get=lambda *a, **k:
                                 SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": [{"id": "other"}]}))
    with pytest.raises(Unsupported, match="not available"):
        planner.preflight()

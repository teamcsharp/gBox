import struct
from types import SimpleNamespace

import pytest

from gbox import oot, oot_live as live, oot_hot_swap as hot


@pytest.fixture
def memory(monkeypatch):
    class Memory:
        base = 0x80200000
        data = bytearray(b"abcdefghABCDEFGH")
        writes = 0
        fail_once = False

        def read(self, address, size):
            return bytes(self.data[address - self.base:address - self.base + size])

        def write(self, address, data):
            self.writes += 1
            self.data[address - self.base:address - self.base + len(data)] = data
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("partial write")

    ad = Memory()
    monkeypatch.setattr(oot, "_rd", lambda a, p, n: a.read(p, n))
    monkeypatch.setattr(oot, "_wr", lambda a, p, b: a.write(p, b))
    monkeypatch.setattr(oot, "layout", lambda a: {"version": "ntsc-1.2", "save": oot.SAVE, "play": oot.PLAY, "play_checked": True})
    monkeypatch.setattr(live, "object_slots", lambda a: [{"id": 42, "segment": a.base}])
    monkeypatch.setattr(live, "u32", lambda a, p: a.base if p == oot.PLAY + live.OBJECT_CTX else a.base + 16)
    monkeypatch.setattr(live, "actors", lambda a: [{"object": 42, "drawn": True, "id": 12}])
    return ad


def item(data=b"abXXefghABCYYFGH"):
    return {"object": 42, "actor_id": 12, "expected": b"abcdefghABCDEFGH".hex(), "data": data.hex()}


def test_verified_swap_then_second_character_then_reload(memory):
    first = hot.replace_object(memory, item())
    assert bytes(memory.data) == bytes.fromhex(item()["data"])
    second = hot.replace_object(memory, item(b"abZZefghABCQQFGH"), first)
    assert second["bytes_written"] == 4
    memory.data[:] = bytes.fromhex(item()["expected"])
    hot.replace_object(memory, item(), second)
    assert bytes(memory.data) == bytes.fromhex(item()["data"])


def test_unknown_model_never_writes(memory):
    memory.data[2] = 0
    with pytest.raises(ValueError, match="differs"):
        hot.replace_object(memory, item())
    assert memory.writes == 0


def test_preserves_runtime_bytes_outside_model_changes(memory):
    memory.data[0] = 0
    hot.replace_object(memory, item())
    assert memory.data[0] == 0


def test_partial_write_is_rolled_back(memory):
    memory.fail_once = True
    before = bytes(memory.data)
    with pytest.raises(RuntimeError, match="partial write"):
        hot.replace_object(memory, item())
    assert bytes(memory.data) == before


def test_readback_corruption_is_rolled_back(memory, monkeypatch):
    write = memory.write
    def corrupt(p, b):
        write(p, b)
        if memory.writes == 1:
            memory.data[p - memory.base] = 0
    monkeypatch.setattr(memory, "write", corrupt)
    with pytest.raises(RuntimeError, match="readback"):
        hot.replace_object(memory, item())
    assert bytes(memory.data) == b"abcdefghABCDEFGH"


@pytest.mark.parametrize("change", ["oversize", "shared", "wrong_actor", "unloaded"])
def test_invalid_target_never_writes(memory, change, monkeypatch):
    inp = item()
    if change == "oversize":
        inp.update(expected=(b"a" * 32).hex(), data=(b"b" * 32).hex())
    elif change == "shared":
        inp["object"] = 1
    elif change == "wrong_actor":
        inp["actor_id"] = 99
    else:
        monkeypatch.setattr(live, "object_slots", lambda a: [])
    with pytest.raises(ValueError):
        hot.replace_object(memory, inp)
    assert memory.writes == 0


def test_real_encoder_keeps_model_and_skeleton_inside_object():
    original = bytes(2048)
    skeleton = {"limbs": [{"at": 0, "dls": [0x06000100]}, {"at": 16, "dls": [0x06000108]}]}
    triangle = tuple((p, (0, 0, 1), (0, 0)) for p in ((0, 0, 0), (10, 0, 0), (0, 10, 0)))
    data = hot.bounded_model(original, skeleton, {0: [(0, triangle)]},
                             [{"color": (255, 0, 0), "tex": None}], [(256, 2048)])
    assert len(data) == len(original)
    from gbox import oot_writer as W
    draw = struct.unpack_from(">I", data, 8)[0]
    empty = struct.unpack_from(">I", data, 24)[0]
    assert 256 <= (draw & 0xFFFFFF) < 2048
    assert data[empty & 0xFFFFFF:(empty & 0xFFFFFF) + 8] == W.ENDDL
    assert W.run_dl({6: data}, draw)["vtx"]


def test_encoder_rejects_tail():
    with pytest.raises(ValueError, match="growth"):
        hot.bounded_model(bytes(128), {"limbs": []}, {0: []}, [], [(64, 80)])


@pytest.mark.parametrize("paused", [False, True])
def test_tool_preserves_pause_state(memory, monkeypatch, paused):
    from gbox.tools import SESSIONS
    state = {"paused": paused, "resumes": 0}
    memory.query_runtime = lambda: {"state": "PAUSED" if state["paused"] else "PLAYING"}
    def pause():
        state["paused"] = True
        return {"state": "PAUSED"}
    def resume():
        state["paused"] = False
        state["resumes"] += 1
    memory.pause, memory.resume = pause, resume
    monkeypatch.setattr(oot, "check", lambda a: None)
    monkeypatch.setitem(SESSIONS, "hot-test", (memory, {}))
    monkeypatch.setattr(live, "LIVE_SWAPS", {})
    res = live.oot_models(live.OotModelsIn(session_id="hot-test", op="replace_object", items=[item()]), None)
    assert res["result"]["verified"]
    assert state["paused"] == paused
    assert state["resumes"] == (0 if paused else 1)


def test_other_games_return_unsupported_without_side_effects(monkeypatch):
    from gbox import characters as C
    monkeypatch.setattr(C, "_session", lambda ctx, sid: {"state": "running", "game_id": "other"})
    inp = SimpleNamespace(session_id="worker-game")
    res = hot.use(None, {}, {"game_id": "other", "title": "Other game"}, inp)
    assert res["status"] == "unsupported_live_swap"
    assert res["session_preserved"] and not res["in_engine"]


def test_nested_character_jobs_keep_original_request(monkeypatch):
    from gbox import characters as C
    calls = []
    def api(ctx, method, path, **kw):
        calls.append(kw["json"])
        return {"state": "succeeded"}
    monkeypatch.setattr(C, "_api", api)
    C._job(SimpleNamespace(parent_request_id="633561512cf34b12"), "oot_models", {"op": "pick"}, "worker")
    assert calls[0]["parent_request_id"] == "633561512cf34b12"
    assert calls[0]["require_worker"] == "worker"

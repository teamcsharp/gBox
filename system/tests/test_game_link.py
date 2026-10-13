import time

from gbox import tools


class Fake:
    name, supported = "fake", set()

    def __init__(self):
        self.mem, self.paused, self.loads = bytearray(16), False, 0

    def read_memory(self, a, n):
        return bytes(self.mem[a:a + n])

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def load_state(self):
        self.loads += 1


def test_link_round(monkeypatch):
    host, guest = Fake(), Fake()
    tools.SESSIONS.update({"h-1": (host, {"platform": "ps3"}), "g-1": (guest, {"platform": "ps3"})})
    applied = []
    monkeypatch.setattr(tools, "script_patch", lambda inp, ctx: applied.append(inp.preset))
    real_sleep = time.sleep
    monkeypatch.setattr(tools.time, "sleep", lambda s: real_sleep(min(s, 0.01)))   # the 3 s reload settle, fast
    f = getattr(tools.game_link, "__wrapped__", tools.game_link)
    spec = lambda a: {"address": hex(a), "type": "u8", "eq": 1}
    f(tools.LinkIn(host="h-1", guest="g-1", trigger=spec(0), win=spec(1), lose=spec(2), poll_s=0.01), None)
    host.mem[0] = 1                                        # bullet-cam starts
    for _ in range(200):
        if host.paused and guest.loads:
            break
        real_sleep(0.01)
    assert host.paused and guest.loads == 1
    guest.mem[1] = 1                                       # player wins the match
    for _ in range(200):
        if applied and not host.paused:                    # the verdict goes in first, then the host resumes
            break
        real_sleep(0.01)
    assert applied == ["god_hit"] and not host.paused and guest.paused
    host.mem[0] = 0
    r = f(tools.LinkIn(op="stop", host="h-1", guest="g-1"), None)["result"]
    assert r["rounds"] == 1 and r["history"][0]["verdict"] == "win"
    tools.SESSIONS.pop("h-1"); tools.SESSIONS.pop("g-1")


def test_link_lose_round(monkeypatch):
    host, guest = Fake(), Fake()
    tools.SESSIONS.update({"h-1": (host, {"platform": "ps3"}), "g-1": (guest, {"platform": "ps3"})})
    applied = []
    monkeypatch.setattr(tools, "script_patch", lambda inp, ctx: applied.append(inp.preset))
    real_sleep = time.sleep
    monkeypatch.setattr(tools.time, "sleep", lambda s: real_sleep(min(s, 0.01)))
    f = getattr(tools.game_link, "__wrapped__", tools.game_link)
    spec = lambda a: {"address": hex(a), "type": "u8", "eq": 1}
    f(tools.LinkIn(host="h-1", guest="g-1", trigger=spec(0), win=spec(1), lose=spec(2), poll_s=0.01), None)
    host.mem[0] = 1
    for _ in range(200):
        if host.paused and guest.loads:
            break
        real_sleep(0.01)
    assert host.paused and guest.loads == 1
    guest.mem[2] = 1                                       # player loses the match
    for _ in range(200):
        if applied:
            break
        real_sleep(0.01)
    assert applied == ["god_miss"] and not host.paused and guest.paused
    r = f(tools.LinkIn(op="stop", host="h-1", guest="g-1"), None)["result"]
    assert r["rounds"] == 1 and r["history"][0]["verdict"] == "lose"
    tools.SESSIONS.pop("h-1"); tools.SESSIONS.pop("g-1")


def test_link_start_requires_watch_addresses():
    f = getattr(tools.game_link, "__wrapped__", tools.game_link)
    for missing in ("trigger", "win", "lose"):
        kwargs = {"op": "start", "host": "h-1", "guest": "g-1",
                  "trigger": {"address": "0x0"}, "win": {"address": "0x1"}, "lose": {"address": "0x2"}}
        kwargs[missing] = {}
        try:
            f(tools.LinkIn(**kwargs), None)
        except ValueError as e:
            assert missing in str(e)
        else:
            raise AssertionError(f"start without {missing} address must raise ValueError")
        tools.LINKS.clear()

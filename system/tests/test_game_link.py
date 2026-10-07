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
        if applied:
            break
        real_sleep(0.01)
    assert applied == ["god_hit"] and not host.paused and guest.paused
    host.mem[0] = 0
    r = f(tools.LinkIn(op="stop", host="h-1", guest="g-1"), None)["result"]
    assert r["rounds"] == 1 and r["history"][0]["verdict"] == "win"
    tools.SESSIONS.pop("h-1"); tools.SESSIONS.pop("g-1")

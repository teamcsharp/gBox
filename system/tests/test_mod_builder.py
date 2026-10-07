import types

from gbox import tools


class FakeAd:
    name, supported = "fake", {"read_memory", "write_memory"}

    def __init__(self):
        self.mem = bytearray(64)

    def read_memory(self, a, n):
        return bytes(self.mem[a:a + n])

    def write_memory(self, a, d):
        self.mem[a:a + len(d)] = d
        return {"written": len(d)}


def test_mod_save_apply_verify_rollback(tmp_path):
    ad = FakeAd()
    tools.SESSIONS["t-1"] = (ad, {"game_id": "g1", "title": "Test", "platform": "test"})
    ctx = types.SimpleNamespace(config=types.SimpleNamespace(data_dir=tmp_path), artifact=lambda *a, **k: None, progress=lambda *a: None)
    f = getattr(tools.mod_tool, "__wrapped__", tools.mod_tool)
    run = lambda **kw: f(tools.ModIn(session_id="t-1", **kw), ctx)["result"]
    run(op="save", name="lives", changes=[{"kind": "write", "address": "0x10", "hex": "6363"}])
    assert run(op="list")["mods"][0]["name"] == "lives"
    run(op="apply", name="lives")
    assert ad.mem[0x10:0x12] == b"cc" and run(op="verify", name="lives")["ok"]
    ad.mem[0x10] = 0                                       # the game overwrote it: regression check notices
    assert not run(op="verify", name="lives")["ok"]
    run(op="rollback", name="lives")
    assert ad.mem[0x10:0x12] == b"\0\0" and not run(op="verify", name="lives")["applied"]
    tools.SESSIONS.pop("t-1")

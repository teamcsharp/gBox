"""Infinite Scape Dolls + never-die revive backstop + death logging: self-throttling
(cheap revive every tick, heavy native work <= HEAVY_INTERVAL_S), logs a death only on the
transition into HP==0, and is fail-soft."""
import struct

import pytest

from gbox import pso_survival as S
from gbox.pso_gc_live import PLAYER, SURVIVAL, FLOOR

P = 0x80DA0000


def _doll(count):
    d = bytearray(10)
    d[:3] = bytes.fromhex(S.SCAPE_DOLL)
    d[5] = count
    return {"code": S.SCAPE_DOLL, "data": d.hex()}


class FakeM:
    """Backs both the adapter (read_memory/write_memory) and the Extras/GC surface, so the
    passed `m` and any internal GC(ad)/Extras(ad) share one coherent memory."""
    def __init__(self, hp=200, maxhp=200, dolls=10, floor=3):
        self.mem = bytearray(0x1800000)
        self.writes = []; self.inv = []; self.given = []; self.surv = 0; self.revived = 0
        self.session_id = "runX"
        self._w16(P + 0x32C, hp); self._w16(P + 0x2B8, maxhp); self._w16(P + 0x28, 7)
        self._w16(P + 0x2E4, 0)
        self._w32(FLOOR, floor); self._w32(0x805D6060, 0); self._w32(PLAYER, P)
        self.mem[self._o(P + 0x38):self._o(P + 0x38) + 12] = struct.pack(">3f", 1.5, 2.5, 3.5)
        if dolls:
            self.inv = [_doll(dolls)]

    def _o(self, a): return a - 0x80000000
    def _w16(self, a, v): self.mem[self._o(a):self._o(a) + 2] = struct.pack(">H", v)
    def _w32(self, a, v): self.mem[self._o(a):self._o(a) + 4] = struct.pack(">I", v)
    def read_memory(self, a, n): return bytes(self.mem[self._o(a):self._o(a) + n])
    def write_memory(self, a, data):
        self.writes.append((a, bytes(data))); self.mem[self._o(a):self._o(a) + len(data)] = data
    def u16(self, a): return struct.unpack(">H", self.read_memory(a, 2))[0]
    def u32(self, a): return struct.unpack(">I", self.read_memory(a, 4))[0]
    def read(self, a, n): return self.read_memory(a, n)
    def write(self, a, data): self.write_memory(a, data)
    def check(self, *a, **k): return P
    def inventory(self): return list(self.inv)
    def revive(self): self.revived += 1; self._w16(P + 0x32C, self.u16(P + 0x2B8))
    def give(self, code, n): self.given.append((code, n)); self.inv.append(_doll(n)); return {"verified": True, "created": n}
    def survival(self, on): self.surv = 1 if on else 0; self._w32(SURVIVAL, int(bool(on))); return {"verified": True}


@pytest.fixture(autouse=True)
def _tmp_log(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "_log_path", lambda: str(tmp_path / "deaths.jsonl"))


def test_scape_count_sums_stacks():
    assert S._scape_count([_doll(5), {"code": "000100", "data": "00" * 10}, _doll(3)]) == 8
    assert S._scape_count([]) == 0


def test_heavy_work_is_throttled_but_revive_is_every_tick():
    m = FakeM(hp=200, dolls=1)                      # low on dolls -> first (heavy) tick restocks
    out = S.apply_survival(m, 0, m=m, p=P)
    assert out["ok"] and out["scapedoll_ok"] and m.given and m.surv == 1
    m.given.clear()
    out2 = S.apply_survival(m, 0, m=m, p=P)         # within HEAVY_INTERVAL_S -> no native stock work
    assert not m.given and out2["scapedoll_ok"]


def test_hp_zero_is_logged_once_and_revived_instantly():
    m = FakeM(hp=0, maxhp=150, dolls=10)
    S.apply_survival(m, 0, m=m, p=P)
    assert m.u16(P + 0x32C) == 150 and m.revived >= 1          # instant revive
    recs = S.read_deaths(m)
    assert len(recs) == 1 and recs[-1]["cause"] == "hp_zero" and recs[-1]["max_hp"] == 150
    assert recs[-1]["x"] == 1.5 and recs[-1]["floor"] == 3
    S.apply_survival(m, 0, m=m, p=P)                           # alive now -> no duplicate death
    assert len(S.read_deaths(m)) == 1
    assert S.death_stats(m)["revives_p1"] == 1


def test_persistent_death_does_not_spam_the_log(monkeypatch):
    m = FakeM(hp=0, maxhp=150, dolls=10)
    monkeypatch.setattr(m, "revive", lambda: None)             # native revive no-op
    monkeypatch.setattr(m, "write_memory", lambda *a, **k: None)  # RAM backstop blocked -> stays dead
    for _ in range(5):
        S.apply_survival(m, 0, m=m, p=P)
    assert len(S.read_deaths(m)) == 1                          # one transition, not five


def test_scape_doll_consumption_logged_on_heavy_tick():
    m = FakeM(hp=200, dolls=10)
    S.apply_survival(m, 0, m=m, p=P)                           # baseline: 10 dolls
    m.inv = [_doll(9)]                                         # one consumed (auto-revived death)
    m._pso_survival["players"][0]["heavy_t"] = 0              # force the next heavy tick
    S.apply_survival(m, 0, m=m, p=P)
    assert any(r["cause"] == "scape_doll_consumed" for r in S.read_deaths(m))


def test_fail_soft_on_blank_adapter():
    from types import SimpleNamespace
    ad = SimpleNamespace(read_memory=lambda *a: b"\0" * (a[1] if len(a) > 1 else 8), write_memory=lambda *a: None)
    out = S.apply_survival(ad, 0)
    assert out["ok"] is False and "reason" in out


def test_log_persists_to_jsonl(tmp_path, monkeypatch):
    import json
    path = tmp_path / "d.jsonl"
    monkeypatch.setattr(S, "_log_path", lambda: str(path))
    m = FakeM(hp=0, maxhp=150, dolls=10)
    S.apply_survival(m, 0, m=m, p=P)
    line = json.loads(path.read_text().strip().splitlines()[-1])
    assert line["cause"] == "hp_zero" and line["run"] == "runX" and line["player"] == 0

"""Infinite Scape Dolls + never-die revive backstop + death logging: fail-soft, records
every down before reviving, and exposes the log for the nav agent."""
import struct
from types import SimpleNamespace

import pytest

from gbox import pso_survival as S


class FakeM:
    """Minimal stand-in for Extras/GC with the methods apply_survival uses."""
    def __init__(self, p, hp=200, maxhp=200, inv=None, floor=3):
        self.p = p; self.hp = hp; self.maxhp = maxhp; self.inv = inv or []
        self.floor = floor; self.revived = 0; self.surv = 0; self.given = []

    def u16(self, a):
        return {self.p + 0x32C: self.hp, self.p + 0x2B8: self.maxhp, self.p + 0x28: 7}.get(a, 0)

    def u32(self, a):
        if a == S.FLOOR: return self.floor
        return 0

    def read(self, a, n):
        if a == self.p + 0x38: return struct.pack(">3f", 1.5, 2.5, 3.5)
        return b"\0" * n

    def inventory(self):
        return self.inv

    def revive(self):
        self.revived += 1; self.hp = self.maxhp

    def give(self, code, n):
        self.given.append((code, n))
        self.inv.append({"code": code, "data": ("%s00000000000000000000" % code)[:24]})
        return {"verified": True, "created": n}

    def survival(self, on):
        self.surv = 1 if on else 0
        return {"verified": True}


def doll_row(count=1):
    data = bytearray(10); data[:3] = bytes.fromhex(S.SCAPE_DOLL); data[5] = count
    return {"code": S.SCAPE_DOLL, "data": data.hex()}


@pytest.fixture(autouse=True)
def _tmp_log(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "_log_path", lambda: str(tmp_path / "deaths.jsonl"))


def test_scape_count_sums_stacks():
    assert S._scape_count([doll_row(5), {"code": "000100", "data": "00" * 10}, doll_row(3)]) == 8
    assert S._scape_count([]) == 0


def test_hp_zero_is_recorded_then_revived():
    ad = SimpleNamespace(write_memory=lambda *a: None, session_id="run1")
    p = 0x80DA0000
    m = FakeM(p, hp=0, inv=[doll_row(10)], floor=11)        # floor 11 = Dragon (boss)
    out = S.apply_survival(ad, 0, m=m, p=p)
    assert out["downed"] is True and out["ok"] is True
    assert m.revived == 1                                    # native revive fired
    recs = S.read_deaths(ad)
    assert recs and recs[-1]["cause"] == "hp_zero"
    assert recs[-1]["player"] == 0 and recs[-1]["floor"] == 11 and recs[-1]["boss"] is True
    assert recs[-1]["area"] == "Dragon" and recs[-1]["x"] == 1.5 and recs[-1]["z"] == 3.5
    st = S.death_stats(ad)
    assert st["revives_p1"] == 1 and st["total"] == 1 and st["last_death"]["cause"] == "hp_zero"


def test_ram_backstop_writes_hp_when_native_revive_leaves_it_zero(monkeypatch):
    writes = []
    ad = SimpleNamespace(write_memory=lambda a, d: writes.append((a, d)), session_id="r")
    p = 0x80DA0000
    m = FakeM(p, hp=0, maxhp=150, inv=[doll_row(10)])
    monkeypatch.setattr(m, "revive", lambda: None)          # native revive fails to restore
    S.apply_survival(ad, 1, m=m, p=p)
    assert (p + 0x32C, struct.pack(">H", 150)) in writes     # last-resort RAM HP write


def test_scape_doll_consumption_between_ticks_is_logged():
    ad = SimpleNamespace(write_memory=lambda *a: None, session_id="r")
    p = 0x80DA0000
    m = FakeM(p, hp=200, inv=[doll_row(10)], floor=5)
    S.apply_survival(ad, 0, m=m, p=p)                        # baseline: 10 dolls
    m.inv = [doll_row(9)]                                    # one consumed (a death auto-revived)
    out = S.apply_survival(ad, 0, m=m, p=p)
    recs = S.read_deaths(ad)
    assert any(r["cause"] == "scape_doll_consumed" for r in recs)
    assert out["revives"] >= 1


def test_restock_tops_up_when_low_and_keeps_stocked():
    ad = SimpleNamespace(write_memory=lambda *a: None, session_id="r")
    p = 0x80DA0000
    m = FakeM(p, hp=200, inv=[doll_row(1)])                  # only 1 doll -> below LOW
    out = S.apply_survival(ad, 0, m=m, p=p)
    assert m.given and m.given[0][0] == S.SCAPE_DOLL         # gave Scape Dolls
    assert out["scapedoll_ok"] is True
    assert m.surv == 1                                        # P1 virtual Scape Doll enabled


def test_blank_adapter_is_fail_soft():
    ad = SimpleNamespace(read_memory=lambda *a: b"\0" * (a[1] if len(a) > 1 else 8),
                         write_memory=lambda *a: None)
    out = S.apply_survival(ad, 0)
    assert isinstance(out, dict) and out.get("ok") is False


def test_log_persists_to_jsonl(tmp_path, monkeypatch):
    import json
    path = tmp_path / "d.jsonl"
    monkeypatch.setattr(S, "_log_path", lambda: str(path))
    ad = SimpleNamespace(write_memory=lambda *a: None, session_id="run9")
    p = 0x80DA0000
    S.apply_survival(ad, 0, m=FakeM(p, hp=0, inv=[doll_row(10)]), p=p)
    lines = path.read_text().strip().splitlines()
    assert lines and json.loads(lines[-1])["cause"] == "hp_zero" and json.loads(lines[-1])["run"] == "run9"

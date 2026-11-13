"""Execute the actual native request guard and exercise stock/automatic-heal behavior."""
import struct
import threading
from types import SimpleNamespace as NS

import pytest

from gbox.mercs.native.re4_82c2a04a import code as C
from gbox.mercs.titles import re4_weapons as W, re4_switch_mods as M
from test_re4_dispatcher import machine, UNIT, RETURN, _dispose_engines


def aid_machine(**changes):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
                                     UC_ARM64_REG_X4, UC_ARM64_REG_LR, UC_ARM64_REG_PC)
    mu = machine()
    for at in (0x290000, 0xB10000, 0x1130000, 0x1240000, 0x1270000):
        mu.mem_map(at, 0x10000)
    mu.mem_write(C.FIRST_AID_AT, C.FIRST_AID[4])
    mu.mem_write(0x297AB0, bytes.fromhex("c0035fd6"))
    item = UNIT + 0x800
    values = dict(hp=500, maximum=2400, count=1, owner=0, flags=1, item=5, recipient=1,
                  generation=7, expected_generation=7, paused=0, mercs=True, slot=item)
    values.update(changes)
    def wr(at, fmt, *v): mu.mem_write(at, struct.pack("<" + fmt, *v))
    def rd(at, fmt): return struct.unpack("<" + fmt, mu.mem_read(at, struct.calcsize(fmt)))[0]
    wr(W.GAME_PTR_VAR, "Q", W.GAME_OBJ)
    wr(0x11310F0, "Q", UNIT)
    wr(W.GAME_OBJ + W.G_FLAGS, "I", W.MERCS_FLAG if values["mercs"] else 0)
    wr(W.GAME_OBJ + W.G_PAUSE, "B", values["paused"])
    wr(W.GAME_OBJ + W.G_HP, "HH", values["hp"], values["maximum"])
    wr(UNIT + 0x110, "I", values["generation"])
    wr(W.ITEM_MGR + W.M_ITEMS, "Q", item)
    wr(W.ITEM_MGR + W.M_SLOTS, "I", W.ITEM_SLOTS)
    wr(W.ITEM_MGR + 0x1A, "B", values["recipient"])
    wr(item, "HHBB", values["item"], values["count"], values["flags"], values["owner"])
    calls = []
    def native_use(uc, address, size, user):
        if address != 0x297AB0: return
        calls.append((uc.reg_read(UC_ARM64_REG_X0), uc.reg_read(UC_ARM64_REG_X1), rd(W.ITEM_MGR + 0x1A, "B")))
        wr(W.GAME_OBJ + W.G_HP, "H", min(rd(W.GAME_OBJ + W.G_HP, "H") + 2400, values["maximum"]))
        wr(item + 2, "H", rd(item + 2, "H") - 1)
        uc.reg_write(UC_ARM64_REG_X0, 1)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
    mu.hook_add(UC_HOOK_CODE, native_use)
    for reg, value in zip((UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4),
                          (W.ITEM_MGR, values["slot"], UNIT, values["expected_generation"], W.GAME_OBJ)):
        mu.reg_write(reg, value)
    mu.emu_start(C.FIRST_AID_AT, RETURN)
    return {"calls": calls, "result": mu.reg_read(UC_ARM64_REG_X0), "hp": rd(W.GAME_OBJ + W.G_HP, "H"),
            "count": rd(item + 2, "H"), "recipient": rd(W.ITEM_MGR + 0x1A, "B")}


def test_native_wrapper_uses_player_spray_and_restores_recipient_with_one_in_reserve():
    out = aid_machine()
    assert out["result"] == 1 and out["hp"] == 2400 and out["count"] == 1
    assert out["calls"] == [(W.ITEM_MGR, UNIT + 0x800, 0)]
    assert out["recipient"] == 1


@pytest.mark.parametrize("changes", [dict(hp=0), dict(hp=2400), dict(owner=1), dict(flags=0), dict(item=6),
                                    dict(count=0), dict(generation=8), dict(paused=1), dict(mercs=False),
                                    dict(slot=UNIT + 0x801), dict(slot=UNIT + 0x800 + 384 * 14)])
def test_invalid_or_stale_request_never_reaches_item_use(changes):
    out = aid_machine(**changes)
    assert out["result"] == 0 and not out["calls"]
    assert out["hp"] == changes.get("hp", 500) and out["count"] == changes.get("count", 1)


def test_threshold_healing_records_native_consumption_and_has_no_hp_write_fallback(monkeypatch):
    from gbox.mercs import interventions
    calls = []
    ctl = NS(lock=threading.RLock(), keep_spray=lambda: {"available": True, "count": 2},
             first_aid_now=lambda: calls.append("use") or {"verified": True, "consumed": True})
    monkeypatch.setattr(interventions, "native_controller", lambda ad: ctl)
    st = {"heal_below": .75}
    snap = {"game": {"phase": "playing"}, "player": {"ptr": UNIT, "hp": 500, "hp_max": 2400}}
    assert M._first_aid(object(), snap, st) == 1 and st["heals"] == 1
    assert M._first_aid(object(), snap, st) == 0 and calls == ["use"]
    st.pop("spray_retry_at")
    ctl.first_aid_now = lambda: {"verified": False, "consumed": False}
    assert M._first_aid(object(), snap, st) == 0 and st["heals"] == 1
    assert st["first_aid_last"]["verified"] is False

"""Native hourglass fields measured on Prison, cross-checked with FUN_00723e34."""
import struct

import pytest

from gbox.mercs.titles import re5_ps3 as R
from test_re5_mercs import HOURGLASS_VT, with_bonuses, world


@pytest.mark.parametrize("render_word,seconds",[(0x00801301,90),(0x00900001,60),(0x00900401,30),(0x00900501,120)])
def test_render_flags_never_turn_native_time_hourglasses_into_combo_chests(monkeypatch,render_word,seconds):
    monkeypatch.setattr(R,"HOURGLASS_VT",HOURGLASS_VT)
    m = with_bonuses(world(),[(100.,13.,200.)],kind=render_word)
    ptr = 0x30401000
    m.put(ptr+R.HG_SECONDS,struct.pack(">h",seconds))
    bonus, = R.bonuses(m)
    assert bonus["kind"]=="time" and bonus["seconds"]==seconds
    assert bonus["kind_word"]==render_word and bonus["collected"] is False


@pytest.mark.parametrize("flag,standing",[(0,True),(1,False),(2,True),(255,True)])
def test_native_credit_flag_removes_goal_before_actor_destruction_without_guessing_unknown_bytes(monkeypatch,flag,standing):
    monkeypatch.setattr(R,"HOURGLASS_VT",HOURGLASS_VT)
    m = with_bonuses(world(),[(100.,13.,200.)],kind=0x00900001)
    ptr = 0x30401000
    m.put(ptr+R.HG_SECONDS,struct.pack(">h",60))
    m.put(ptr+R.HG_COLLECTED,bytes([flag]))
    bonuses = R.bonuses(m)
    assert bool(bonuses) is standing
    if flag not in (0,1):
        assert bonuses[0]["collected"] is None


def test_remaining_time_count_excludes_optional_combo_goals_and_includes_temporarily_skipped_time(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    bot.bonus_skip[2] = 20.
    standing = [{"ptr":1,"kind":"time","pos":(100.,0.,0.)},
                {"ptr":2,"kind":"time","pos":(200.,0.,0.)},
                {"ptr":3,"kind":"combo","pos":(300.,0.,0.)}]
    bot._bonus({"pos":(0.,0.,0.),"rot":0.},[],standing,10.)
    assert bot.stats["time_bonuses_remaining"]==2
    assert bot.stats["combo_bonuses_remaining"]==1

import errno
import sys
from types import SimpleNamespace

import pytest

from gbox import mercs_bot as M


def setup(monkeypatch,screen,engine=None):
    name = "gbox.tests_boot_ram_menus"
    menus = SimpleNamespace(screen=screen,step=lambda _:None,wandered=lambda _:None)
    monkeypatch.setitem(sys.modules,name,menus)
    monkeypatch.setattr(M,"profile_for",lambda *_:{"map_id":"TEST","menus":name,"package":[],"early_ops":[]})
    monkeypatch.setattr(M,"title_engine",lambda _:SimpleNamespace(play_round=engine or (lambda *a,**kw:"stopped")))
    monkeypatch.setattr(M,"lessons_writer",lambda *a:None)
    monkeypatch.setattr(M,"tactical_publisher",lambda *a:None)
    now,sleeps = [0.],[]
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    return now,sleeps,sleep


@pytest.mark.parametrize("code",[errno.EIO,errno.EFAULT,errno.EAGAIN,errno.EINTR])
def test_unmapped_boot_ram_retries_without_inputs_then_enters_real_game(monkeypatch,code):
    calls,inputs,engine = [],[],[]
    def screen(m):
        calls.append(1)
        if len(calls)<3: raise OSError(code,"guest pages unavailable")
        return {"where":"playing"}
    now,sleeps,sleep = setup(monkeypatch,screen,lambda *a,**kw:engine.append(True) or "stopped")
    stats = M.play(None,inputs.extend,lambda:False,m=object(),sleep=sleep,clock=lambda:now[0])
    assert len(calls)==3 and engine==[True] and not inputs
    assert sleeps==[.25,.25] and stats["boot_ram_read_retries"]==2
    assert stats["boot_ram_status"]=="ready" and stats["rounds"]==1


def test_initial_ram_retry_has_finite_deadline_and_preserves_error(monkeypatch):
    def screen(m): raise OSError(errno.EIO,"guest pages unavailable")
    now,sleeps,sleep = setup(monkeypatch,screen)
    monkeypatch.setattr(M,"BOOT_RAM_READ_S",.5)
    stats = {}
    with pytest.raises(OSError) as error:
        M.play(None,lambda _:None,lambda:False,stats,m=object(),sleep=sleep,clock=lambda:now[0])
    assert error.value.errno==errno.EIO and stats["boot_ram_status"]=="timeout"
    assert stats["boot_ram_read_retries"]==3 and sum(sleeps)==.5
    assert stats["rounds"]==0 and not stats.get("ram_progress")


def test_retry_honors_stop_flag_and_sends_no_boot_guess(monkeypatch):
    def screen(m): raise OSError(errno.EFAULT,"unmapped")
    now,sleeps,sleep = setup(monkeypatch,screen)
    sent = []
    stats = M.play(None,sent.extend,lambda:now[0]>=.5,m=object(),sleep=sleep,clock=lambda:now[0])
    assert stats["boot_ram_status"]=="stopped" and len(sleeps)==2 and not sent


def test_established_reader_failure_is_never_hidden_even_inside_boot_deadline(monkeypatch):
    calls = []
    def screen(m):
        calls.append(1)
        if len(calls)==1:return {"where":"main_menu"}
        raise OSError(errno.EIO,"established read failed")
    now,sleeps,sleep = setup(monkeypatch,screen)
    with pytest.raises(OSError,match="established read failed"):
        M.play(None,lambda _:None,lambda:False,m=object(),sleep=sleep,clock=lambda:now[0])
    assert sleeps==[M.POLL_S]


def test_permanent_initial_error_is_not_retried_and_playing_failure_stays_visible(monkeypatch):
    def forbidden(m): raise OSError(errno.EACCES,"permission denied")
    now,sleeps,sleep = setup(monkeypatch,forbidden)
    with pytest.raises(OSError) as error:
        M.play(None,lambda _:None,lambda:False,m=object(),sleep=sleep,clock=lambda:now[0])
    assert error.value.errno==errno.EACCES and not sleeps
    def playing(*a,**kw):raise OSError(errno.EIO,"live round read failed")
    setup(monkeypatch,lambda _:{"where":"playing"},playing)
    with pytest.raises(OSError,match="live round read failed"):
        M.play(None,lambda _:None,lambda:False,m=object(),sleep=sleep,clock=lambda:now[0])


def test_nonadvancing_clock_cannot_make_boot_retry_unbounded(monkeypatch):
    calls = []
    def screen(m):
        calls.append(1)
        raise OSError(errno.EIO,"unmapped")
    _,sleeps,_ = setup(monkeypatch,screen)
    monkeypatch.setattr(M,"BOOT_RAM_READ_S",.5)
    with pytest.raises(OSError):
        M.play(None,lambda _:None,lambda:False,m=object(),sleep=sleeps.append,clock=lambda:0.)
    assert len(calls)==3 and len(sleeps)==2

"""A native read gap releases input and resumes the same round when reads recover."""
import errno
from types import SimpleNamespace

import pytest

from gbox.mercs import engine, read_retry


def run_round(fail, *, at='snapshot', stop=None, frozen_clock=False):
    now, calls, sent, decisions, saved = [0.],[],[],[],[]
    stats = {}
    def read():
        calls.append(now[0])
        error=fail(len(calls))
        if error is not None:raise error
    def snapshot(_):
        if at=='snapshot':read()
        return {'player':{'hp':100},'timer':100.-now[0]}
    def screen(*_):
        if at=='screen':read()
        return 'playing'
    driver=SimpleNamespace(snapshot=snapshot,screen=screen,prompt_source=lambda *a:None,
        prompt_keys=lambda _:[],progress=lambda snap:{'timer':snap['timer']},frame=None)
    brain=SimpleNamespace(tick=lambda snap:decisions.append(snap) or {'hold':{'l1','r1'}},
        save=lambda:saved.append(True),prompt_ok=lambda *a:True)
    def sleep(seconds):
        if not frozen_clock:now[0]+=seconds
    def stopped():
        return stop(now[0],calls,decisions) if stop else len(decisions)>=2
    def play():
        return engine.play_round({},object(),lambda rows:sent.extend(rows),stopped,stats,
                                 driver=driver,brain=brain,clock=lambda:now[0],sleep=sleep)
    return play,stats,calls,sent,decisions,saved,now


@pytest.mark.parametrize('at',['snapshot','screen'])
@pytest.mark.parametrize('code',[errno.EIO,errno.EFAULT,errno.EAGAIN,errno.EINTR])
def test_two_transient_samples_release_then_resume_the_same_brain(at,code):
    play,stats,calls,sent,decisions,saved,now=run_round(
        lambda count:OSError(code,'native page temporarily unavailable') if count in (2,3) else None,at=at)
    assert play()=='stopped'
    assert len(calls)==4 and len(decisions)==2 and saved==[True]
    assert sent==([{'key':key,'down':down} for down in (True,False,True,False) for key in ('l1','r1')])
    assert stats['native_read_status']=='ready' and stats['native_read_retries']==2
    assert stats['native_read_recoveries']==1 and stats['ram_progress']==2
    assert now[0]==pytest.approx(.6)


@pytest.mark.parametrize('frozen_clock',[False,True])
def test_persistent_read_failure_remains_visible_after_bounded_neutral_retry(monkeypatch,frozen_clock):
    monkeypatch.setattr(read_retry,'RETRY_S',.5)
    play,stats,calls,sent,decisions,saved,now=run_round(
        lambda count:OSError(errno.EIO,'persistent native failure') if count>1 else None,
        frozen_clock=frozen_clock)
    with pytest.raises(OSError,match='persistent native failure') as caught:play()
    assert caught.value.errno==errno.EIO
    assert len(calls)==4 and len(decisions)==1 and saved==[True]
    assert sent==[{'key':key,'down':down} for down in (True,False) for key in ('l1','r1')]
    assert stats['native_read_status']=='timeout' and stats['native_read_retries']==2


def test_permission_failure_is_not_retried():
    play,stats,calls,sent,decisions,saved,now=run_round(lambda _:OSError(errno.EACCES,'denied'))
    with pytest.raises(OSError) as caught:play()
    assert caught.value.errno==errno.EACCES and len(calls)==1 and not sent and not decisions
    assert stats['native_read_status']=='failed' and not stats.get('native_read_retries')


def test_operator_stop_during_read_gap_cancels_recovery_without_more_inputs():
    play,stats,calls,sent,decisions,saved,now=run_round(lambda _:OSError(errno.EIO,'read gap'),
        stop=lambda now,calls,decisions:now>=.25)
    assert play()=='stopped'
    assert len(calls)==1 and not sent and not decisions and saved==[True]
    assert stats['native_read_status']=='stopped'

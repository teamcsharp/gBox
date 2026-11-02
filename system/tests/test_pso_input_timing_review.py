from types import SimpleNamespace
import pytest
from gbox import pso_coop as C


def harness(monkeypatch, down_delay=None, up_delay=None, hook=None):
    clock=[10.0]; events=[]; stopped=[False]
    down_delay=down_delay or {}; up_delay=up_delay or {}
    ad=SimpleNamespace(autoplay_speed=2, _pso_timing_epoch=0)
    def send(rows, player=1, polite=False):
        down=any(row['down'] for row in rows)
        events.append((player, down, 'start', clock[0]))
        clock[0]+=(down_delay if down else up_delay).get(player, 0.)
        result=hook(player, down, ad, stopped) if hook else None
        events.append((player, down, 'ack', clock[0]))
        return {'sent':len(rows)} if result is None else result
    ad.send_input_player=send
    monkeypatch.setattr(C, 'time', SimpleNamespace(monotonic=lambda:clock[0]))
    def wait(secs, stop):
        assert not stop()
        clock[0]+=secs
    monkeypatch.setattr(C.solo, 'wait', wait)
    stats={}
    inputs=C.Inputs(ad,lambda:stopped[0],send_primary=lambda rows:send(rows),stats=stats)
    return inputs,ad,clock,events,stopped,stats


def test_releases_by_actual_deadline_not_nominal_duration(monkeypatch):
    inp,ad,clock,events,stopped,stats=harness(monkeypatch,{2:.08})
    # P1's longer nominal pulse still expires before P2's later acknowledgement.
    inp.hold([(1,['lup'],.12),(2,['a'],.04)])
    releases=[p for p,down,stage,t in events if not down and stage=='start']
    assert releases[:2]==[1,2]
    assert stats['input_p1_held_ms']==80
    assert stats['input_p2_held_ms']==20
    assert not stats['input_hold_timing_verified']


def test_slow_primary_release_does_not_shorten_second_and_disables_learning(monkeypatch):
    inp,ad,clock,events,stopped,stats=harness(monkeypatch,up_delay={1:.09})
    inp.hold([(1,['a'],.04),(2,['lup'],.12)])
    assert stats['input_p1_held_ms']==20
    assert stats['input_p1_release_delivery_ms']==90
    assert stats['input_p2_held_ms']==110
    assert not stats['input_hold_timing_verified'] and not inp.wall_learning_safe()


@pytest.mark.parametrize('fault',['held','partial','exception'])
def test_second_delivery_failure_releases_both_without_wait(fault,monkeypatch):
    def fail(player,down,ad,stopped):
        if player==2 and down:
            if fault=='exception':raise OSError('delivery uncertain')
            if fault=='held':return {'sent':0,'held':'human controller'}
            return {'sent':0}
    inp,ad,clock,events,stopped,stats=harness(monkeypatch,hook=fail)
    monkeypatch.setattr(C.solo,'wait',lambda *_:pytest.fail('Failed delivery cannot wait'))
    with pytest.raises(OSError if fault=='exception' else C.InputDeferred):
        inp.hold([(1,['a'],.12),(2,['lup'],.04)])
    assert {p for p,down,stage,t in events if not down and stage=='start'}=={1,2}
    assert not stats['input_hold_timing_verified']


@pytest.mark.parametrize('fault',['stop','epoch','pause','changing','unknown'])
def test_interrupt_during_wait_releases_all_and_refuses_learning(fault,monkeypatch):
    inp,ad,clock,events,stopped,stats=harness(monkeypatch)
    def wait(secs,predicate):
        clock[0]+=secs/2
        if fault=='stop':stopped[0]=True
        elif fault=='epoch':ad._pso_timing_epoch+=1
        elif fault=='pause':ad._pso_timing_paused=True
        elif fault=='changing':ad._autoplay_speed_changing=True
        else:ad._autoplay_speed_known=False
        assert predicate()
    monkeypatch.setattr(C.solo,'wait',wait)
    error=(InterruptedError if fault=='stop' else C.SpeedUnknown if fault=='unknown' else C.InputDeferred)
    with pytest.raises(error):inp.hold([(1,['a'],.12),(2,['lup'],.04)])
    assert {p for p,down,stage,t in events if not down and stage=='start'}=={1,2}
    assert not stats['input_hold_timing_verified'] and not inp.wall_learning_safe()


def test_uncertain_hold_then_new_fast_hold_can_recover_timing_eligibility(monkeypatch):
    delays={1:.08}
    inp,ad,clock,events,stopped,stats=harness(monkeypatch,down_delay=delays)
    ad.autoplay_speed=1
    inp.hold([(1,['a'],.04)])
    assert not inp.wall_learning_safe()
    delays.clear()
    inp.hold([(1,['a'],.04)])
    assert inp.wall_learning_safe() and stats['input_hold_timing_verified']


def test_stop_before_hold_never_sends_even_release(monkeypatch):
    inp,ad,clock,events,stopped,stats=harness(monkeypatch)
    stopped[0]=True
    with pytest.raises(InterruptedError):inp.hold([(1,['a'],.12),(2,['lup'],.04)])
    assert events==[]

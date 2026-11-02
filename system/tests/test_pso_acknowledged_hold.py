from types import SimpleNamespace
import pytest
from gbox import pso_coop as C

def setup(monkeypatch,delay=.08):
    clock=[10.];events=[];stopped=[False]
    ad=SimpleNamespace(autoplay_speed=2,_pso_timing_epoch=0)
    def send(rows,player=1,polite=False):
        down=any(r['down'] for r in rows)
        if down:clock[0]+=delay
        events.append((player,down,clock[0]))
        return {'sent':len(rows)}
    ad.send_input_player=send
    monkeypatch.setattr(C,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr(C.solo,'wait',lambda seconds,stop:clock.__setitem__(0,clock[0]+seconds))
    stats={};inputs=C.Inputs(ad,lambda:stopped[0],send_primary=lambda rows:send(rows),stats=stats)
    return inputs,ad,clock,events,stopped,stats

def test_delayed_primary_delivery_cannot_consume_short_pulse(monkeypatch):
    inputs,ad,clock,events,stopped,stats=setup(monkeypatch)
    inputs.hold([(1,['lup'],.04)])
    down=next(t for p,d,t in events if d);up=next(t for p,d,t in events if not d)
    assert up-down==pytest.approx(.02)
    assert stats['input_p1_delivery_ms']==80 and stats['input_p1_held_ms']==20
    assert stats['input_hold_timing_verified'] is False
    assert not inputs.wall_learning_safe()

def test_each_pad_gets_own_acknowledged_deadline(monkeypatch):
    inputs,ad,clock,events,stopped,stats=setup(monkeypatch,.05)
    inputs.hold([(1,['lup'],.04),(2,['lright'],.12)])
    for slot,minimum in ((1,.02),(2,.06)):
        down=next(t for p,d,t in events if p==slot and d)
        up=next(t for p,d,t in events if p==slot and not d)
        assert up-down>=minimum-1e-9
    assert stats['input_p1_held_ms']==50 and stats['input_p2_held_ms']==60
    assert not stats['input_hold_timing_verified']

def test_stop_during_primary_delivery_releases_and_never_presses_second(monkeypatch):
    inputs,ad,clock,events,stopped,stats=setup(monkeypatch)
    original=inputs.send_primary
    def stop(rows):
        result=original(rows)
        if any(r['down'] for r in rows):stopped[0]=True
        return result
    inputs.send_primary=stop
    with pytest.raises(InterruptedError):inputs.hold([(1,['lup'],.04),(2,['lup'],.04)])
    assert events[-1][0:2]==(1,False)
    assert not any(p==2 and down for p,down,t in events)

@pytest.mark.parametrize('fault',['paused','epoch','speed'])
def test_changed_timing_after_delivery_releases_without_waiting(fault,monkeypatch):
    inputs,ad,clock,events,stopped,stats=setup(monkeypatch)
    original=inputs.send_primary
    def change(rows):
        result=original(rows)
        if any(r['down'] for r in rows):
            if fault=='paused':ad._pso_timing_paused=True
            elif fault=='epoch':ad._pso_timing_epoch+=1
            else:ad._autoplay_speed_changing=True
        return result
    inputs.send_primary=change
    with pytest.raises(C.InputDeferred):inputs.hold([(1,['lup'],.04),(2,['lup'],.04)])
    assert events[-1][0:2]==(1,False)
    assert not any(p==2 and down for p,down,t in events)
    assert not stats['input_hold_timing_verified']

def test_fast_delivery_keeps_original_duration_and_learning_eligibility(monkeypatch):
    inputs,ad,clock,events,stopped,stats=setup(monkeypatch,0)
    ad.autoplay_speed=1
    inputs.hold([(1,['lup'],.04)])
    assert stats['input_p1_held_ms']==40
    assert stats['input_hold_timing_verified'] and inputs.wall_learning_safe()

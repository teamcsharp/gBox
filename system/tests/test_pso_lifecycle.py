import copy
from types import SimpleNamespace
import pytest
from test_pso_margin_controller import margin_state
from gbox import pso_coop as C
from gbox.pso_coop_nav import Maps

@pytest.mark.parametrize('failure',['stop','held','stopped'])
def test_fresh_margin_route_respects_stop_or_input_lease_without_counting_attempt(failure,tmp_path,monkeypatch):
    state=margin_state();events=[];stopped=[False]
    def send(batch,player):
        events.append((player,copy.deepcopy(batch)))
        if failure!='stop' and any(e['down'] and e['key']!='l' for e in batch):
            return {'sent':0,failure:'operator owns the controller'}
        return {'sent':len(batch)}
    def snapshot():
        if failure=='stop':stopped[0]=True
        return copy.deepcopy(state)
    inputs=C.Inputs(SimpleNamespace(send_input_player=send,autoplay_speed=2),lambda:stopped[0])
    c=C.Controller(SimpleNamespace(ad=None,snapshot=snapshot),inputs,Maps(tmp_path))
    monkeypatch.setattr(C.solo,'wait',lambda *_:None)
    with pytest.raises(InterruptedError if failure=='stop' else C.InputDeferred):c.tick(state)
    assert c.margin_attempts[2]['attempts']==0
    movement=[(p,e) for p,b in events for e in b if e['key']!='l']
    if failure=='stop':assert movement==[]
    else:
        assert movement and movement[-1][1]['down'] is False
        assert all(p==2 for p,_ in movement)

def test_stop_between_pad_presses_releases_first_without_pressing_second(monkeypatch):
    events=[];stopped=[False]
    def send(batch,player):
        events.append((player,copy.deepcopy(batch)))
        if any(e['down'] for e in batch):stopped[0]=True
        return {'sent':len(batch)}
    inputs=C.Inputs(SimpleNamespace(send_input_player=send),lambda:stopped[0])
    with pytest.raises(InterruptedError):inputs.hold([(1,['a'],.12),(2,['lup'],.04)])
    assert not any(p==2 for p,_ in events)
    assert events[-1]==(1,[{'key':'a','down':False}])

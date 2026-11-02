from copy import deepcopy
from types import SimpleNamespace
import pytest

from gbox import pso_coop as C, pso_coop_mapping as M
from gbox.registry import Unsupported

SID = 'worker-original'
GAME = {'game_id': '436e0bb84d5337d1'}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    user = tmp_path / 'User'; (user / 'Config').mkdir(parents=True)
    card = tmp_path / 'dolphin/A.USA.raw'; card.parent.mkdir(); card.write_bytes(b'unchanged card identity')
    rom = tmp_path / 'owned.gcz'; rom.write_bytes(b'fixture')
    config = user / 'Config/GCPadNew.ini'
    config.write_text(''.join(f'[GCPad{n}]\nDevice = DInput/0/Keyboard Mouse\nButtons/A = A{n}\n'
        'Main Stick/Up = UP\nMain Stick/Down = DOWN\nMain Stick/Left = LEFT\nMain Stick/Right = RIGHT\n' for n in (1, 2)))
    args = ['Dolphin.exe', '-u', str(user), '-e', str(rom)]
    for value in ('Dolphin.Core.SIDevice0=6','Dolphin.Core.SIDevice1=6','Dolphin.Core.SlotA=1',
                  'Dolphin.Core.MemcardAPath='+str(card)):
        args += ['-C', value]
    process = [42, 123456.0, 'Dolphin.exe', args]
    monkeypatch.setattr(M, '_process', lambda ad: tuple(process))
    stopped = [False]; reads = [0]; events = []
    state = {'verified': True, 'cooperative': True, 'phase': 14, 'floor': 0, 'episode': 1,
             'difficulty': 0, 'difficulty_verified': True, 'entities': [], 'players': {}}
    for slot in (1, 2):
        state['players'][slot] = {'ptr': f'{0x80100000 + slot * 0x2000:08X}', 'class': 'TObjPlayer',
            'entity_id': slot-1, 'controller': slot, 'hp': 50, 'hp_max': 50, 'x': 0., 'z': 0., 'room': 0}
    ad = SimpleNamespace(name='dolphin', coop_players=2, proc=SimpleNamespace(pid=42, poll=lambda:None),
        config=SimpleNamespace(runtime=tmp_path), gameplay_demo_user=user,
        _pso_coop_new_card={'session_id':SID,'isolated':True,'path':str(tmp_path)},
        memory_card_context={'slots':{'A':{'path':str(card)}}},
        send_input=lambda events:None, send_input_player=lambda events,player:None,
        read_memory=lambda a,n:b'GPOE8P\0\x02', _pso_verified_player_slots=set())
    def snapshot(): reads[0] += 1; return deepcopy(state)
    reader = SimpleNamespace(snapshot=snapshot)
    class Inputs:
        stopped = staticmethod(lambda:stopped[0])
        def hold(self, commands):
            events.extend(commands)
            for player, _, _ in commands: state['players'][player]['x'] += 3
        def speed(self): return 1
    inputs = Inputs()
    monkeypatch.setattr(C.solo, 'wait', lambda *args:None)
    def prove(): return M.prove(ad,reader,inputs,snapshot(),SID,GAME,lambda:stopped[0],C.mapping_probe)
    def restore(): return M.restore(ad,reader,SID,GAME,lambda:stopped[0])
    return SimpleNamespace(**locals())


def test_actual_two_pad_probe_attests_then_same_adapter_field_restart_needs_no_movement(rig):
    r=rig; rows=r.prove()
    assert len(r.events)==2 and rows[0]['moved']>=2 and rows[1]['other_moved']==0
    r.state['floor']=1
    # Normal area loading can recreate both actors while the mapped bot is alive.
    r.state['players'][1]['ptr']='80112000';r.state['players'][2]['ptr']='80114000'
    M.observe(r.ad,r.snapshot(),SID,GAME,lambda:False)
    r.ad._pso_verified_player_slots=set()  # Stop revokes active permission, not the attested history.
    r.events.clear(); result=r.restore()
    assert result and result['state']['floor']==1 and result['probe']==rows
    assert r.events==[] and r.ad._pso_verified_player_slots==set()
    assert M._receipt(r.ad).probe[0]['pointer'] != result['state']['players'][1]['ptr']


@pytest.mark.parametrize('change', ['process_object','birth','pid','session','game','private_user','card_path',
    'card_replaced','pad_config','port_disconnected','input_routing','player_slot','actor_changed','disc','reset'])
def test_changed_binding_refuses_restore_and_field_fallback_sends_nothing(rig, change):
    r=rig;r.prove();r.events.clear();r.state['floor']=1
    if change=='process_object':r.ad.proc=SimpleNamespace(pid=42,poll=lambda:None)
    elif change=='birth':r.process[1]+=1
    elif change=='pid':r.process[0]+=1
    elif change=='session':r.ad._pso_coop_new_card['session_id']='worker-replacement'
    elif change=='game':monkey_game=dict(GAME);monkey_game['game_id']='different'
    elif change=='private_user':r.ad.gameplay_demo_user=r.tmp_path
    elif change=='card_path':r.ad.memory_card_context['slots']['A']['path']=str(r.rom)
    elif change=='card_replaced':
        old=r.card.with_suffix('.old');r.card.rename(old);r.card.write_bytes(b'replacement')
    elif change=='pad_config':r.config.write_text(r.config.read_text().replace('A2','B2'))
    elif change=='port_disconnected':r.args[r.args.index('Dolphin.Core.SIDevice1=6')]='Dolphin.Core.SIDevice1=0'
    elif change=='input_routing':r.ad.send_input_player=lambda events,player:'changed routing'
    elif change=='player_slot':r.state['players'][2]['entity_id']=0
    elif change=='actor_changed':r.state['players'][2]['ptr']='80116000'
    elif change=='disc':r.ad.read_memory=lambda a,n:b'GPOE8P\0\x01'
    elif change=='reset':M.invalidate(r.ad)
    result=M.restore(r.ad,r.reader,SID,monkey_game if change=='game' else GAME,lambda:False)
    assert result is None and r.events==[]
    with pytest.raises(Unsupported,match='Pioneer 2'):
        C.mapping_probe(r.reader,r.inputs,r.snapshot())
    assert r.events==[]


def test_pause_speed_and_normal_card_save_retain_proof_but_stop_never_activates_it(rig):
    r=rig;r.prove();r.events.clear();r.state['floor']=1
    r.card.write_bytes(b'ordinary game save updated the same file')
    r.ad._pso_timing_epoch=5;r.ad.autoplay_speed=2
    assert r.restore() and not r.events
    r.stopped[0]=True
    assert r.restore() is None and r.ad._pso_verified_player_slots==set()
    assert not r.events and M._receipt(r.ad) is not None


def test_partial_probe_and_missing_identity_cannot_create_reusable_proof(rig):
    r=rig
    def failed(*args):
        r.inputs.hold([(1,['lup'],.45)])
        raise Unsupported('second pad failed')
    with pytest.raises(Unsupported):M.prove(r.ad,r.reader,r.inputs,r.state,SID,GAME,lambda:False,failed)
    assert M._receipt(r.ad) is None and r.restore() is None
    r.ad._pso_coop_new_card['session_id']='different'
    assert len(r.prove())==2 and M._receipt(r.ad) is None


def test_stop_during_revalidation_or_probe_never_activates_inputs(rig):
    r=rig;r.prove();r.events.clear()
    def race():r.stopped[0]=True;return r.snapshot()
    r.reader.snapshot=race
    assert r.restore() is None and not r.events
    with pytest.raises(InterruptedError):r.prove()


def test_serialized_or_copied_evidence_is_not_accepted(rig):
    r=rig;r.prove();original=M._receipt(r.ad)
    setattr(r.ad,M.ATTRIBUTE,vars(original).copy())
    assert r.restore() is None
    setattr(r.ad,M.ATTRIBUTE,original)
    copied=SimpleNamespace(**vars(r.ad));assert M.restore(copied,r.reader,SID,GAME,lambda:False) is None


def test_active_field_actor_refresh_refuses_a_changed_config(rig):
    r=rig;r.prove();r.state['floor']=1;r.state['players'][2]['ptr']='80116000'
    r.config.write_text(r.config.read_text()+'\n# changed\n')
    with pytest.raises(Unsupported,match='continuity'):
        M.observe(r.ad,r.snapshot(),SID,GAME,lambda:False)
    assert M._receipt(r.ad) is None and r.ad._pso_verified_player_slots==set()


def test_live_play_loop_restores_field_mapping_and_stop_clears_active_slots(rig, monkeypatch):
    r=rig;r.prove();r.events.clear();r.state['floor']=1
    class Inputs:
        polite=has_polite=False
        def __init__(self,*a,**kw):pass
        def speed(self):return 1
        def check_speed(self):pass
        def release(self):r.events.append('released')
        def hold(self,*a):pytest.fail('No mapping movement may be issued by field restart')
    class Controller:
        damage=kills=attacks=blocked=0;combat_status={}
        town=SimpleNamespace(status={});engagements=SimpleNamespace(recoveries=0,deferred=0,rows={})
        def __init__(self,*a):
            self.goals={};self.approaches={}
            self.weapon_ranges=SimpleNamespace(cache={},attempted={})
        def tick(self,state):
            assert r.ad._pso_verified_player_slots=={0,1};r.stopped[0]=True
    class Future:
        def done(self):return False
        def cancel(self):return True
        def add_done_callback(self,callback):pass
    class Executor:
        def __init__(self,*a,**kw):pass
        def submit(self,*a):return Future()
        def shutdown(self,**kw):pass
    monkeypatch.setattr(C,'Reader',lambda _:r.reader);monkeypatch.setattr(C,'Inputs',Inputs)
    monkeypatch.setattr(C,'Controller',Controller);monkeypatch.setattr(C,'ThreadPoolExecutor',Executor)
    monkeypatch.setattr(C,'Maps',lambda _:SimpleNamespace(save=lambda:None))
    monkeypatch.setattr(C,'SpeedSampler',lambda *a:SimpleNamespace(invalidate=lambda:None,observe=lambda st:None,failure=None))
    monkeypatch.setattr(C.solo,'Planner',lambda *a:SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(C,'observe_menu_controls',lambda *a:False)
    r.ad.get_frame=lambda:b'fresh native scene'
    result=C.play(r.ad,lambda _:pytest.fail('No direct input'),lambda:r.stopped[0],
                  driver=SimpleNamespace(),session_id=SID,game=GAME)
    assert result['controller_mapping_source']=='same_live_adapter_revalidated'
    assert result['controller_mapping_verified'] is True and r.ad._pso_verified_player_slots==set()
    assert M._receipt(r.ad) is not None and r.events==['released']


@pytest.mark.parametrize('windows,method',[(False,'load_state'),(False,'checkpoint_load'),
    (True,'load_state'),(True,'checkpoint_load'),(True,'reset')])
def test_adapter_reset_and_restore_invalidate_before_even_failed_hotkey(windows,method,monkeypatch):
    from gbox import adapters
    cls=adapters.DolphinWinAdapter if windows else adapters.DolphinAdapter
    ad=object.__new__(cls);old=object();setattr(ad,M.ATTRIBUTE,old)
    ad._pso_verified_player_slots={0,1};ad.ff_on=False
    def failed(*args):raise RuntimeError('interrupted native hotkey')
    ad._hotkey=failed;ad._xdo=failed
    with pytest.raises(RuntimeError,match='interrupted'):getattr(ad,method)()
    assert getattr(ad,M.ATTRIBUTE) is None and ad._pso_verified_player_slots==set()
    assert ad._pso_mapping_epoch==1


def test_timing_only_invalidation_preserves_attestation_and_active_mapping():
    from gbox.adapters import DolphinAdapter
    ad=object.__new__(DolphinAdapter);proof=object();setattr(ad,M.ATTRIBUTE,proof)
    ad._pso_verified_player_slots={0,1}
    ad._invalidate_pso_timing()
    assert getattr(ad,M.ATTRIBUTE) is proof and ad._pso_verified_player_slots=={0,1}
    assert not hasattr(ad,'_pso_mapping_epoch')


def test_process_witness_is_rechecked_after_reading_live_configuration(monkeypatch):
    import psutil
    from gbox import tools
    birth=iter([123.,124.])
    monkeypatch.setattr(tools,'_native_process_created',lambda ad,pid:next(birth))
    monkeypatch.setattr(psutil,'Process',lambda pid:SimpleNamespace(cmdline=lambda:['Dolphin'],exe=lambda:'Dolphin'))
    with pytest.raises(ValueError,match='changed'):
        M._process(SimpleNamespace(proc=SimpleNamespace(pid=42)))

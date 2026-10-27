"""A late RPCS3 renderer is raised once, only on the session's private display and owned process tree."""
from types import SimpleNamespace

from gbox import adapters
from gbox.config import Config


def harness(tmp_path, monkeypatch):
    ad=adapters.RPCS3LinuxAdapter(Config(data_dir=tmp_path/'data',cache_dir=tmp_path/'cache'))
    ad.proc=SimpleNamespace(pid=123,poll=lambda:None)
    ad.display=SimpleNamespace(name=':90',w=1280,h=720)
    state={'now':100.,'ready':True,'focus':'503'}
    calls=[]
    monkeypatch.setattr(adapters.time,'monotonic',lambda:state['now'])
    monkeypatch.setattr(adapters,'_proc_tree',lambda pid: [123,124] if pid==123 else [])
    class Thread:
        def __init__(self,target,**kwargs):self.target=target
        def start(self):self.target()
    monkeypatch.setattr(adapters.threading,'Thread',Thread)
    monkeypatch.setattr(ad,'_fit_window',lambda:None)   # the window fitter has its own tests (test_session_display)
    monkeypatch.setattr(ad,'_xdo',lambda *args:calls.append(('input',args)))
    def command(display,args,timeout):
        assert display is ad.display and display.name==':90' and 0<timeout<=.25
        calls.append(('focus',args))
        op=args[0]
        value=''
        if op=='search': value='501\n502\n' if args[4]=='123' else ('503\n' if state['ready'] else '')
        elif op=='getwindowpid': value={'501':'999','502':'123','503':'124'}[args[1]]
        elif op=='getwindowname':value='RPCS3 Loading' if args[1]=='502' else 'FPS: 29.99 | Vulkan | Resident Evil 5'
        elif op=='getwindowfocus':value=state['focus']+chr(10)
        return SimpleNamespace(returncode=0,stdout=value)
    monkeypatch.setattr(ad,'_focus_command',command)
    return ad,state,calls


def test_focus_selects_only_owned_visible_renderer_and_never_foreign_or_launcher(tmp_path,monkeypatch):
    ad,state,calls=harness(tmp_path,monkeypatch)
    ad._park_pointer()
    focus=[args for kind,args in calls if kind=='focus']
    searches=[args for args in focus if args[0]=='search']
    assert [args[4] for args in searches]==['123','124']
    assert all(args[1:4]==('--all','--onlyvisible','--pid') for args in searches)
    assert ('getwindowname','501') not in focus
    actions=[args for args in focus if args[0]=='windowmap']
    assert actions==[('windowmap','503','windowraise','503','windowfocus','503','mousemove','640','360')]
    assert ad._focus_done and ad._focus_window=='503'
    for _ in range(10):ad.send_input([{'key':'cross','down':True}])
    assert len([args for kind,args in calls if kind=='focus' and args[0]=='search'])==2


def test_late_renderer_retries_at_most_once_per_second_without_blocking_pad(tmp_path,monkeypatch):
    ad,state,calls=harness(tmp_path,monkeypatch)
    state['ready']=False
    ad._park_pointer()
    initial=len([args for kind,args in calls if kind=='focus'])
    state['ready']=True
    for when in [100.1,100.5,100.99]:
        state['now']=when
        ad.send_input([{'key':'cross','down':True}])
    assert len([args for kind,args in calls if kind=='focus'])==initial
    assert len([args for kind,args in calls if kind=='input' and args[0]=='keydown'])==3
    state['now']=101.
    ad.send_input([{'key':'cross','down':True}])
    assert ad._focus_done


def test_a_renderer_late_past_the_budget_is_still_found_every_few_seconds_and_input_never_waits(tmp_path,monkeypatch):
    # 2026-10-26: a warm-pool RE5 under nice 10 showed its window after the 60 s budget and was never focused: the bot's
    # keys went nowhere for two rounds (operator: "turning around nonsensically ignoring threats")
    ad,state,calls=harness(tmp_path,monkeypatch)
    state['ready']=False
    ad._park_pointer()
    initial=len(calls)
    state['now']=160.01
    state['ready']=True
    ad.send_input([{'key':'r1','down':False}])
    assert ad._focus_done and ad._focus_window=='503'
    assert calls[-1]==('input',('keyup','e'))                 # the key still went out, after the quick look
    state['now']=160.5
    before=len(calls)
    ad.send_input([{'key':'r1','down':True}])
    assert [c for c in calls[before:] if c[0]=='focus']==[]    # no look again inside FOCUS_RETRY_S / FOCUS_RECHECK_S


def test_a_focus_lost_after_a_swap_is_seen_within_seconds_and_made_again(tmp_path,monkeypatch):
    # 2026-10-26 13:10: XGetInputFocus on the RE5 session's Xvfb returned none after the warm swap; every key the bot
    # sent landed nowhere until the window was focused by hand
    ad,state,calls=harness(tmp_path,monkeypatch)
    ad._park_pointer()
    assert ad._focus_done
    state['focus']='1'                                         # none: the X server's PointerRoot answer
    state['now']=103.5
    before=len(calls)
    ad.send_input([{'key':'cross','down':True}])
    focus=[args for kind,args in calls[before:] if kind=='focus']
    assert focus[0]==('getwindowfocus',) and ('windowmap','503','windowraise','503','windowfocus','503','mousemove','640','360') in focus
    assert ad._focus_done and ad.focus_restores==1
    state['focus']='503'
    state['now']=107.
    before=len(calls)
    ad.send_input([{'key':'cross','down':False}])
    assert [args for kind,args in calls[before:] if kind=='focus']==[('getwindowfocus',)]   # held: a look, no more


def test_process_change_during_lookup_cannot_focus_a_previous_sessions_window(tmp_path,monkeypatch):
    ad,state,calls=harness(tmp_path,monkeypatch)
    original=ad._focus_command
    def command(display,args,timeout):
        result=original(display,args,timeout)
        if args==('getwindowname','503'):
            ad.proc=SimpleNamespace(pid=999,poll=lambda:None)
        return result
    monkeypatch.setattr(ad,'_focus_command',command)
    ad._park_pointer()
    assert not ad._focus_done
    assert not any(args[0]=='windowmap' for kind,args in calls if kind=='focus')


def test_pending_focus_lookup_runs_off_input_thread_and_cannot_queue_more_attempts(tmp_path,monkeypatch):
    ad,state,calls=harness(tmp_path,monkeypatch)
    deferred=[]
    class Thread:
        def __init__(self,target,**kwargs):self.target=target
        def start(self):deferred.append(self.target)
    monkeypatch.setattr(adapters.threading,'Thread',Thread)
    ad._park_pointer()
    state['now']=102.
    ad.send_input([{'key':'r1','down':True}])
    ad.send_input([{'key':'r1','down':False}])
    assert len(deferred)==1 and ad._focus_pending
    assert ('input',('keydown','e')) in calls and ('input',('keyup','e')) in calls
    assert not any(kind=='focus' for kind,args in calls)
    deferred[0]()
    assert ad._focus_done and not ad._focus_pending

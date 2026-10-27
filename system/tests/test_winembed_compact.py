"""Exercise compact caption/gesture decisions without touching a Windows HWND."""
import ast
import ctypes
from ctypes import wintypes
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]/'clients/desktop/winembed.py'


def functions(*names, **namespace):
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),namespace)
    return namespace


def test_compact_double_click_requires_same_scoped_game_and_system_distance_and_time():
    click=functions('compact_click')['compact_click']
    prev,double=click(None,(100,200),1000,7,True,500,(8,8))
    assert not double
    assert click(prev,(103,198),1400,7,True,500,(8,8))==(None,True)
    for point,when,window,enabled in [((105,200),1400,7,True),((100,200),1600,7,True),
                                      ((100,200),900,7,True),((100,200),1400,8,True),((100,200),1400,7,False)]:
        assert not click(prev,point,when,window,enabled,500,(8,8))[1]


def chrome_fixture():
    bits=0x00C00000|0x00080000|0x00030000
    class User:
        def __init__(self): self.styles={9:bits|0x00040000|0x10000000,7:0x40000000}; self.writes=[]; self.positions=[]
        def IsWindow(self,h): return h in self.styles
        def GetWindowThreadProcessId(self,h,pid): ctypes.cast(pid,ctypes.POINTER(wintypes.DWORD)).contents.value=42
        def GetWindowLongPtrW(self,h,index): return self.styles[h]
        def SetWindowLongPtrW(self,h,index,value): self.writes.append((h,value)); self.styles[h]=value
        def SetWindowPos(self,*args): self.positions.append(args)
    user=User(); state={'app':9,'parent':9,'app_chrome':None,'compact':False,'source_aspect':16/9}
    scope=functions('appchrome',state=state,u32=user,ctypes=ctypes,wintypes=wintypes,GWL_STYLE=-16,
        WS_CAPTION=0x00C00000,WS_SYSMENU=0x00080000,WS_MINMAX=0x00030000,SWP_NOZORDER=4,SWP_FRAMECHANGED=32)
    return scope['appchrome'],state,user,bits


def test_app_chrome_only_changes_the_registered_app_and_retains_resize_and_visibility():
    chrome,state,user,bits=chrome_fixture(); original=user.styles[9]
    assert chrome(9,42,True)=={'ok':True,'on':True,'aspect':16/9,'bits':bits}
    assert user.styles[9]&bits==0
    assert user.styles[9]&0x00040000 and user.styles[9]&0x10000000
    assert state['compact']
    chrome(9,42,True)  # repeated updates retain the first snapshot
    user.styles[9]|=0x01000000  # preserve an unrelated style added in the meantime
    assert chrome(9,42,False)['ok']
    assert user.styles[9]==original|0x01000000
    assert not state['compact'] and state['app_chrome'] is None
    assert {handle for handle,_ in user.writes}=={9}, 'never restyle the emulator child'


def test_app_chrome_rejects_unregistered_or_wrong_process_windows_before_writing():
    chrome,state,user,bits=chrome_fixture()
    assert not chrome(7,42,True)['ok']
    assert not chrome(9,43,True)['ok']
    assert not chrome(0,42,True)['ok']
    assert not user.writes


def test_a_restarted_helper_restores_chrome_from_the_trusted_main_process_snapshot():
    chrome,state,user,bits=chrome_fixture()
    chrome(9,42,True)
    state['app_chrome']=None
    assert chrome(9,42,False,bits)['ok']
    assert user.styles[9]&bits==bits


def test_a_helper_started_while_compact_keeps_the_original_bits_from_main_not_the_stripped_window():
    # operator 2026-10-27: a helper that stopped answering is replaced while the PiP stays open; the new helper sees the
    # window without its caption bits, and must still put back the ones main took away
    chrome,state,user,bits=chrome_fixture(); original=user.styles[9]
    user.styles[9]&=~bits
    assert chrome(9,42,True,bits)=={'ok':True,'on':True,'aspect':16/9,'bits':bits}
    assert user.styles[9]&bits==0
    assert chrome(9,42,False)['ok']
    assert user.styles[9]==original
    plain,state2,user2,_=chrome_fixture()                  # without main's bits a first hide snapshots the window as it is
    assert plain(9,42,True)['bits']==bits


def test_native_restore_gesture_is_activated_only_for_compact_scoped_plain_game_clicks():
    source=SOURCE.read_text(encoding='utf-8')
    assert "enabled and hit == 'game' and plain" in source
    assert "emit({'event': 'piprestore'})" in source
    assert "if code == 0 and wp == WM_LBUTTONUP and compact['release']:" in source
    assert "32 * u32.GetDpiForWindow" in source

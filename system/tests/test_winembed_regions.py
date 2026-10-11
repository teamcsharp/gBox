"""Exercise the actual native move implementation without touching a Windows HWND."""
import ast
from pathlib import Path


def native_move():
    source=Path(__file__).resolve().parents[1]/'clients'/'desktop'/'winembed.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    method=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='move')
    regions=[]
    class User:
        def IsWindow(self,window):return True
        def IsWindowVisible(self,window):return True
        def SetWindowPos(self,*args):pass
        def SetWindowRgn(self,window,region,repaint):regions.append(region)
    class Graphics:
        def CreateRectRgn(self,*bounds):return {'bounds':bounds,'holes':[]}
        def CombineRgn(self,result,base,cut,mode):result['holes'].append(cut['bounds'])
        def DeleteObject(self,region):pass
    namespace={'state':{'hwnd':7,'mode':'native','pid':None,'parent':None},'u32':User(),'g32':Graphics()}
    exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),namespace)
    return namespace['move'],regions


def test_resize_rebuilds_popup_region_even_when_its_cutout_coordinates_are_unchanged():
    move,regions=native_move()
    holes=[(10,10,100,100)]
    assert move(0,0,640,480,holes)['ok']
    assert regions[-1]['bounds']==(0,0,640,480)
    move(0,0,960,720,holes)
    assert len(regions)==2
    assert regions[-1]['bounds']==(0,0,960,720)
    assert regions[-1]['holes']==[(10,10,110,110)]
    move(0,0,960,720,holes)
    assert len(regions)==2


def test_removing_a_popup_clears_the_region_and_plain_resizes_stay_unclipped():
    move,regions=native_move()
    move(0,0,640,480,[(10,10,100,100)])
    move(0,0,640,480,[])
    assert regions[-1] is None
    move(0,0,960,720,[])
    assert regions[-1] is None

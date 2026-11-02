from pso_owned_evidence import original_test_path
import io
from pathlib import Path
import pytest
from PIL import Image
from gbox.pso_menu_observer import observe
from gbox.pso_coop_menu import MenuProgress,known_menu_command

BASE=original_test_path('field-navigation/tests/test_p2_panel.py').resolve().parents[2]
FRAME=(BASE/'raw-frame-1793623151226055100.png').read_bytes()
IDENTITY=(14,1,1,((1,'80DA62A0',16,True),(2,'80DA8590',16,True)))

def test_actual_six_label_p2_menu_recognized_and_one_b_cancel():
    observation=observe(FRAME)
    assert observation['recognized'] and observation['menu']=='ingame_p2_cancel'
    assert observation['player']==2 and observation['menu_visible']
    assert known_menu_command(observation)==(2,['b'],.08)
    menu=MenuProgress(players=2)
    assert menu.observe_frame(FRAME,native_gameplay=True,identity=IDENTITY)
    selected,reason=menu.review({'screen':'menu'},[(2,['b'],.08)],IDENTITY,frame=FRAME,fresh_frame=FRAME,native_gameplay=True)
    assert selected==[(2,['b'],.08)] and not reason

@pytest.mark.parametrize('command',[(1,['b'],.08),(2,['a'],.08),(2,['ddown'],.08),(2,['start'],.08)])
def test_wrong_owner_and_other_p2_actions_rejected(command):
    selected,reason=MenuProgress(players=2).review({'screen':'menu'},[command],IDENTITY,frame=FRAME,fresh_frame=FRAME,native_gameplay=True)
    assert not selected and reason

def test_not_native_or_saving_does_not_authorize_p2_cancel():
    for kwargs in ({'native_gameplay':False},{'native_gameplay':True,'finish_save':True}):
        selected,reason=MenuProgress(players=2).review({'screen':'menu'},[(2,['b'],.08)],IDENTITY,frame=FRAME,fresh_frame=FRAME,**kwargs)
        assert not selected and reason

def test_real_closed_field_is_not_p2_menu():
    frame=(BASE/'194-close_observed_ptwo_menu.png').read_bytes()
    observed=observe(frame)
    assert not observed['menu_visible'] and observed['menu']!='ingame_p2_cancel'

def test_missing_label_and_moved_panel_do_not_authorize_cancel():
    original=Image.open(io.BytesIO(FRAME)).convert('RGB').resize((960,540),Image.Resampling.LANCZOS)
    images=[]
    missing=original.copy();missing.paste((0,0,0),(188,362,270,379));images.append(missing)
    shifted=Image.new('RGB',(960,540));shifted.paste(original,(0,3));images.append(shifted)
    for image in images:
        output=io.BytesIO();image.save(output,format='PNG')
        assert observe(output.getvalue())['menu']!='ingame_p2_cancel'

from pso_owned_evidence import original_test_path
from pathlib import Path
import io
import numpy as np
import pytest
from PIL import Image,ImageDraw
from gbox import pso_menu_observer as V
from gbox.pso_coop_menu import MenuProgress,known_menu_command
HERE=original_test_path('transporter-expanded/test_expanded.py').resolve().parent;BASE=HERE.parent
RAW=(BASE/'raw-frame-1793630635809787600.png').read_bytes()

def normalized():return Image.open(io.BytesIO(RAW)).convert('RGB').resize((960,540),Image.Resampling.LANCZOS)
def encoded(image):
    result=io.BytesIO();image.save(result,format='PNG');return result.getvalue()

@pytest.mark.parametrize('frame',[RAW,encoded(normalized())])
def test_actual_expanded_panel_and_demonstrated_preview_recognize_only_p2_forest1(frame):
    result=V.observe(frame)
    assert result['recognized'] and result['menu_visible'] and not result['gameplay_visible']
    assert (result['menu'],result['player'],result['selected'],result['destination_floor'])==('transporter_forest',2,'FOREST 1',1)
    assert known_menu_command(result)==(2,['a'],.08)
    allowed,reason=MenuProgress(2).review({'screen':'menu'},[(2,['a'],.08)],(14,1,0),
       frame=frame,fresh_frame=frame,native_gameplay=True,target_episode=1)
    assert allowed==[(2,['a'],.08)] and not reason

@pytest.mark.parametrize('name',['w_forest_destination','w_expanded_forest2','w_expanded_cave1',
 'w_expanded_cave2','w_expanded_cave3','w_expanded_mine1','w_expanded_mine2','w_hud_p1_town','w_hud_p2'])
def test_each_observed_label_and_both_player_huds_are_required(name):
    image=normalized();ImageDraw.Draw(image).rectangle(V._TEXT[name]['box'],fill='black')
    observed=V.observe(encoded(image))
    assert not observed['recognized'] and observed['menu_visible']

@pytest.mark.parametrize('box',[(337,318,623,323),(337,486,623,490),(334,323,338,487),(623,323,626,487)])
def test_each_expanded_panel_edge_is_required(box):
    image=normalized();ImageDraw.Draw(image).rectangle(box,fill='white')
    assert not V.observe(encoded(image))['recognized']

def cursor_variant(*,keep_first=True,second=False):
    a=np.asarray(normalized()).copy()
    if not keep_first:
        r,g,b=a.astype(np.int16).transpose(2,0,1)
        a[(r>110)&(r>g+25)&(g>b+12)]=(0,48,65)
    if second:
        region=a[350:362,340:620];ink=V._ink(Image.fromarray(region))
        region[~ink]=(220,130,65)
    return Image.fromarray(a)

def test_missing_or_ambiguous_cursor_never_confirms():
    image=cursor_variant(second=True)
    assert V._text(image,'w_forest_destination')>=.85 and V._text(image,'w_expanded_forest2')>=.85
    assert not V.observe(encoded(image))['recognized']
    image=cursor_variant(keep_first=False)
    assert V._text(image,'w_forest_destination')>=.85
    assert not V.observe(encoded(image))['recognized']

def test_another_real_destination_selected_remains_visible_without_confirmation_authority():
    image=cursor_variant(keep_first=False,second=True)
    assert V._text(image,'w_forest_destination')>=.85 and V._text(image,'w_expanded_forest2')>=.85
    observed=V.observe(encoded(image))
    assert not observed['recognized'] and observed['menu_visible']
    assert known_menu_command(observed) is None
    actions,reason=MenuProgress(2).review({'screen':'menu'},[(2,['a'],.08)],(14,1,0),
      frame=RAW,fresh_frame=encoded(image),native_gameplay=True,target_episode=1)
    assert not actions and 'changed' in reason

@pytest.mark.parametrize('player,keys',[(1,['a']),(2,['b']),(2,['down']),(2,['a','down'])])
def test_new_visual_layout_does_not_expand_controller_or_key_authority(player,keys):
    actions,reason=MenuProgress(2).review({'screen':'menu'},[(player,keys,.1)],(14,1,0),
      frame=RAW,fresh_frame=RAW,native_gameplay=True,target_episode=1)
    assert not actions and reason

@pytest.mark.parametrize('players,identity,native,target,finish',[(1,(14,1,0),True,1,False),
 (2,(14,1,1),True,1,False),(2,(14,2,0),True,1,False),(2,(7,1,0),True,1,False),
 (2,(14,1,0),False,1,False),(2,(14,1,0),True,2,False),(2,(14,1,0),True,None,False),(2,(14,1,0),True,1,True)])
def test_existing_native_episode_town_and_save_guards_still_apply(players,identity,native,target,finish):
    actions,reason=MenuProgress(players).review({'screen':'menu'},[(2,['a'],.08)],identity,
      frame=RAW,fresh_frame=RAW,native_gameplay=native,target_episode=target,finish_save=finish)
    assert not actions and reason

def test_missing_fresh_frame_and_repeated_unchanged_menu_remain_bounded():
    guard=MenuProgress(2)
    args=dict(frame=RAW,native_gameplay=True,target_episode=1)
    assert not guard.review({'screen':'menu'},[(2,['a'],.08)],(14,1,0),fresh_frame=None,**args)[0]
    for _ in range(6):actions,reason=guard.review({'screen':'menu'},[(2,['a'],.08)],(14,1,0),fresh_frame=RAW,**args)
    assert not actions and guard.stalled and 'Six' in reason

def test_menu_pause_needs_native_departure_and_fresh_bot_run_recognizes_same_layout():
    for _ in range(2):
        guard=MenuProgress(2)
        assert guard.observe_frame(RAW,native_gameplay=True,identity=(14,1,0))
        assert guard.controls_paused
        assert guard.observe_frame(b'unknown',native_gameplay=True,identity=(14,1,0))
        assert not guard.observe_frame(b'unknown',native_gameplay=True,identity=(14,1,1))

@pytest.mark.parametrize('box',[(160,0,870,580),(0,0,1031,400)])
def test_cropped_panel_does_not_become_transport_evidence(box):
    assert not V.observe(encoded(Image.open(io.BytesIO(RAW)).crop(box)))['recognized']

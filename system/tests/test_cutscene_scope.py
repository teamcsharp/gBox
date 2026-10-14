"""A gameplay build cannot silently stand in for full character/cinematic coverage."""
import json
from types import SimpleNamespace
import pytest
from gbox import characters as C
from gbox.config import Config


@pytest.mark.parametrize('op',['use','live_use','match','cast_swap'])
def test_registered_replacement_requires_each_appearance_and_records_new_build(tmp_path,monkeypatch,op):
    cfg=Config(cache_dir=tmp_path/'cache',data_dir=tmp_path/'data')
    d=cfg.cache/'mods'/'game'/'new-build';d.mkdir(parents=True)
    marker=d/'.gbox-mod.json';marker.write_text(json.dumps({'name':'new-build','game_id':'game'}))
    response={'result':{'mod':'new-build','status':'built','gameplay_verified':True}}
    monkeypatch.setattr(C,'characters_tool',lambda *a:response)
    inp=C.CharIn(op=op,character='donor',game_id='game',target_game='game',feedback_ack={'prior-report':2})
    out=C.characters_recorded(inp,SimpleNamespace(config=cfg))
    scope=out['result']['replacement_scope']
    assert scope['requested']=='all_character_appearances'
    assert scope['required']==['gameplay','in_engine_cutscenes','prerecorded_cinematics']
    assert not scope['complete'],'gameplay verification is not cutscene verification'
    if op!='live_use':
        assert json.loads(marker.read_text())['replacement_scope']==scope
        assert json.loads(marker.read_text())['feedback_reviewed']=={'prior-report':2}


def test_writer_cinematic_limitations_are_preserved(tmp_path,monkeypatch):
    response={'result':{'mod':'new-build','status':'built_unverified','replacement_scope':{
        'in_engine_cutscenes':'written_unverified','prerecorded_movies':'unchanged','complete':False}}}
    monkeypatch.setattr(C,'characters_tool',lambda *a:response)
    out=C.characters_recorded(C.CharIn(op='use',character='donor',game_id='game'),SimpleNamespace(config=Config(cache_dir=tmp_path/'cache',data_dir=tmp_path/'data')))
    scope=out['result']['replacement_scope']
    assert scope['prerecorded_movies']=='unchanged' and scope['complete'] is False
    assert 'prerecorded_cinematics' in scope['required']


def test_reused_marker_is_not_relabelled_as_a_new_full_scope_build(tmp_path,monkeypatch):
    cfg=Config(cache_dir=tmp_path/'cache',data_dir=tmp_path/'data')
    d=cfg.cache/'mods'/'game'/'legacy';d.mkdir(parents=True)
    marker=d/'.gbox-mod.json';marker.write_text(json.dumps({'name':'legacy','game_id':'game','verified_in_game':True}))
    monkeypatch.setattr(C,'characters_tool',lambda *a:{'result':{'mod':'legacy','status':'ready'}})
    out=C.characters_recorded(C.CharIn(op='use',character='donor',game_id='game'),SimpleNamespace(config=cfg))
    assert out['result']['replacement_scope']['complete'] is False
    saved=json.loads(marker.read_text())
    assert 'replacement_scope' not in saved and saved['verified_in_game'] is True


def test_oot_cutscene_memory_budget_is_enabled_by_default():
    assert C.CharIn(op='cast_swap').strict_cutscenes is True
    assert C.CharIn(op='cast_swap',strict_cutscenes=False).strict_cutscenes is False


def test_rebuild_recipe_retains_explicit_gameplay_only_diagnostic():
    from gbox import special_builds as S
    inp={'op':'cast_swap','target_game':'game','source':'donors','strict_cutscenes':False}
    recipe=S.recipe_from_call(inp,{'mod':'diagnostic','status':'built'})
    assert recipe['input']['strict_cutscenes'] is False


def test_scope_record_keeps_writer_stage_receipts(tmp_path):
    from gbox import special_builds as S
    cfg=Config(cache_dir=tmp_path/'cache',data_dir=tmp_path/'data')
    d=cfg.cache/'mods'/'game'/'new';d.mkdir(parents=True)
    marker=d/'.gbox-mod.json'
    marker.write_text(json.dumps({'name':'new','replacement_scope':{
        'cutscene_stages':['demo01a'],'prerecorded_movies':'unchanged','complete':False}}))
    assert S.record(cfg,'game','new',{'tool':'characters','input':{}},
        {'replacement_scope':{'required':['gameplay','in_engine_cutscenes','prerecorded_cinematics'],'complete':False}})
    scope=json.loads(marker.read_text())['replacement_scope']
    assert scope['cutscene_stages']==['demo01a'] and scope['prerecorded_movies']=='unchanged'
    assert not scope['complete'] and len(scope['required'])==3

from types import SimpleNamespace
import copy
import pytest
from gbox import re5_sonic_writer as writer,re5_character_writer as native


def setup(tmp_path,monkeypatch):
    library=tmp_path/'library'; folder=library/'sonic'; folder.mkdir(parents=True)
    (folder/'sa2_sonic_0.glb').write_bytes(b'source fixture')
    romfs=tmp_path/'romfs'; target=romfs/writer.ARCHIVE_PATH; target.parent.mkdir(parents=True)
    target.write_bytes(b'original archive fixture')
    monkeypatch.setattr(writer.characters,'library_root',lambda _:library)
    monkeypatch.setattr(native,'_romfs',lambda _:romfs)
    calls=[]
    def build(data,source):
        calls.append((data,source.read_bytes()))
        return b'complete native replacement',{'live_verified':False,'source_sha256':writer.SOURCE_SHA256}
    monkeypatch.setattr(writer,'build',build)
    meta={'slug':'sonic','name':'Sonic','model':'sa2_sonic_0.glb','source':{'game_id':'d95ed7ed1e40552a',
          'platform':'dreamcast','files':['SONIC2/SONICMDL.PRS','SONIC2/SONICTEX.PRS']},
          'extraction_tool':'gbox.sa2_chars + gbox.ninja','rig':{'roles':writer.SOURCE_ROLES}}
    ctx=SimpleNamespace(config=SimpleNamespace(cache=tmp_path/'cache'))
    game={'platform':'switch','serial':writer.RE5_TITLE_ID}
    inp=SimpleNamespace(op='use',slot='player',target='chris')
    return ctx,game,inp,meta,calls


def test_exact_identity_and_named_chris_produce_one_overlay_plan(tmp_path,monkeypatch):
    ctx,game,inp,meta,calls=setup(tmp_path,monkeypatch)
    result=writer.plan(ctx,game,inp,meta)
    assert result['changes']=={'romfs/'+writer.ARCHIVE_PATH:{'bytes':b'complete native replacement'}}
    assert result['slots'][0]['slot']=='chris' and calls==[(b'original archive fixture',b'source fixture')]
    assert result['replacement_scope']['collection_model_used']
    assert not result['replacement_scope']['gameplay_verified']


@pytest.mark.parametrize('field,value',[('target','sheva'),('target',''),('op','cast_swap'),('props',['hat']),('scale',2.)])
def test_other_slots_and_additional_edits_fail_before_build(tmp_path,monkeypatch,field,value):
    ctx,game,inp,meta,calls=setup(tmp_path,monkeypatch)
    setattr(inp,field,value)
    assert 'reason' in writer.plan(ctx,game,inp,meta)
    assert not calls


@pytest.mark.parametrize('change',['slug','model','provenance','variant','rig_scale'])
def test_changed_metadata_is_refused_before_build(tmp_path,monkeypatch,change):
    ctx,game,inp,meta,calls=setup(tmp_path,monkeypatch)
    meta=copy.deepcopy(meta)
    if change=='slug':meta['slug']='shadow'
    elif change=='model':meta['model']='../sa2_sonic_0.glb'
    elif change=='provenance':meta['source']['game_id']='other'
    elif change=='variant':meta['variant_of']='sonic'
    elif change=='rig_scale':meta['rig']['scale']=2.
    assert 'reason' in writer.plan(ctx,game,inp,meta)
    assert not calls


def test_builder_refuses_unmeasured_source_or_native_archive(tmp_path,monkeypatch):
    import hashlib
    source=tmp_path/'source.glb';source.write_bytes(b'fixture')
    with pytest.raises(ValueError,match='source revision'):
        writer.build(b'archive',source)
    monkeypatch.setattr(writer,'SOURCE_SHA256',hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(ValueError,match='original Chris-normal'):
        writer.build(b'archive',source)

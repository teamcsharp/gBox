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


def test_experimental_recipe_pairs_reposed_root_with_own_motion_and_retains_acceptance_gate(tmp_path,monkeypatch):
    import hashlib
    import zlib
    from gbox import mt_arc,mtf_author
    source=tmp_path/'source.glb';source.write_bytes(b'measured source')
    entries=[mt_arc.Entry(f'unused{i}',1,1,0,0,zlib.compress(b'untouched')) for i in range(105)]
    for index,path,payload in ((35,r'pawn\pl\pl00\model\pl00Gear_MM',b'TEX mm'),
                               (36,r'pawn\pl\pl00\model\pl00Gear_NM',b'TEX nm'),
                               (97,'pl0000',b'MOD original'),(104,'pl00motion',b'LMT\0original')):
        entries[index]=mt_arc.Entry(path,1,len(payload),0,0,zlib.compress(payload))
    archive=mt_arc.build(mt_arc.Arc(7,entries))
    monkeypatch.setattr(writer,'SOURCE_SHA256',hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(writer,'ARCHIVE_SHA256',hashlib.sha256(archive).hexdigest())
    class Model:
        def __init__(self,height):self.height=height
        def bone_table(self):return {'anim_map':list(writer.TARGET_ANIMATION_IDS.values())}
        def bone_world(self):return [(0,0.,self.height,0.)]
    monkeypatch.setattr(writer.mt_model,'parse_mod',lambda raw:Model(60. if raw==b'MOD authored' else 120.))
    frames={'measured_frames':'finger+thumb proper rotations'}
    monkeypatch.setattr(writer,'_repose_frames',lambda source,model:frames)
    calls=[]
    def import_model(data,path,**kwargs):
        calls.append(kwargs)
        return mtf_author.replace_archive_model(data,97,b'MOD authored'),b'MOD authored',None,{'live_verified':False}
    monkeypatch.setattr(writer.re5_mesh_import,'build_archive',import_model)
    monkeypatch.setattr(writer.mtf_secondary,'constant_channels',lambda raw,channels:raw+b'neutral')
    def motion(raw,scale):
        assert raw==b'LMT\0original' and scale==.5
        return b'LMT\0scaled',{'tracks':1,'key_data_unchanged':True}
    monkeypatch.setattr(writer.mtf_motion_edit,'scale_root_y',motion)
    output,receipt=writer.build(archive,source)
    assert calls[0]['pose_mode']=='source_reposed' and calls[0]['height']==140.
    assert calls[0]['segments']==writer.SEGMENTS and calls[0]['repose_frames'] is frames
    assert calls[0]['retarget_root_translation'] and calls[0]['centre_hip']
    assert receipt['recipe_version']==2 and receipt['root_motion']['scale_y']==.5
    assert receipt['bind_skeleton']['animation_channels_changed']
    assert receipt['bind_skeleton']['root_translation_retarget_completed']
    assert receipt['changed_entry_indices']==[35,36,97,104]
    assert not receipt['gameplay_verified'] and not receipt['writer_registered']
    assert zlib.decompress(mt_arc.parse(output).entries[104].data)==b'LMT\0scaled'

import copy,json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from gbox import gta_lcs_cast as G,gta_stories_models as M,cast_swap as CS,retarget_profile as RP


def test_pedestrian_roster_is_not_player_outfits():
    rows=M.cast_slots()
    assert len(rows)==93 and len({r['slot'] for r in rows})==93
    assert all(r['kind']=='pedestrian' and r['slot'].startswith('ped:') for r in rows)
    assert 'cop' in {r['name'] for r in rows}


def test_gta_fit_bridges_forward_the_saved_profile(monkeypatch,tmp_path):
    from gbox import characters as C,re4gc_enemies as R,gta3_swap as III,gta_vc_swap as VC
    monkeypatch.setattr(C,'rig_from_gltf',lambda *a:{'source':'fixture'})
    seen=[]
    def fit(src,target,**kw):
        seen.append(kw['scale']);return [{'pos':np.array([[0.,0,0]]),'nrm':np.array([[0.,1,0]])}]
    monkeypatch.setattr(R,'retarget',fit)
    profile={'profile':{'head':.8,'ground':.02,'plant_feet':True,'lattice':{'offsets':{'13':[.01,0,0]}}}}
    rig=SimpleNamespace(roles={})
    III.retarget(rig,tmp_path/'source.glb',{},scale=profile)
    VC.retarget(rig,tmp_path/'source.glb',{},scale=profile)
    model=SimpleNamespace(bone_names=lambda:['head'],bone_world=lambda:[np.eye(4)],hier=[(0,0)])
    M.retarget_onto(model,tmp_path/'source.glb',{},scale=profile)
    assert seen==[profile]*3


def test_approved_texture_variant_is_used_in_source_pool_without_duplicating_character():
    original={'slug':'doa2_kas','name':'Kasumi','source':{'game_title':'Dead or Alive 2','platform':'dreamcast'}}
    approved={**original,'slug':'doa2_kas_tex_'+'a'*12,'variant_of':original['slug'],'name':'Kasumi · 1K',
              'texture_base_name':'Kasumi','texture_approval':{'candidate':'a'*64,'at':1}}
    unapproved={**original,'slug':'head_variant','variant_of':original['slug']}
    assert CS._candidates([original,approved,unapproved])==[approved]
    assert CS.base_name(approved)=='kasumi'
    assert CS.texture_assignment_aliases([{'slot':'ped:1','character':original['slug']}],
        [original,approved,unapproved],[approved])==[{'slot':'ped:1','character':approved['slug']}]
    assert CS.resolve_source('dead or alive',[original,approved])['entries']==[approved]


@pytest.fixture
def writer(tmp_path,monkeypatch):
    from gbox import characters as C
    base=tmp_path/'base.iso';base.write_bytes(bytes(M.SECTOR*20))
    cfg=SimpleNamespace(cache=tmp_path/'cache')
    disc=SimpleNamespace(img_lba=1,img_read=lambda s,n:bytes(n*M.SECTOR))
    monkeypatch.setattr(M,'LcsDisc',lambda _:disc)
    monkeypatch.setattr(M,'lcs_iso_from_rom',lambda *a:base)
    monkeypatch.setattr(C,'_blender',lambda _:None)
    monkeypatch.setattr(G,'slots',lambda _: [{'slot':'ped:1'},{'slot':'ped:2'}])
    monkeypatch.setattr(M,'read_chk',lambda b:[])
    monkeypatch.setattr(M,'ped_to_gltf',lambda model,tex,path,name:path.write_bytes(b'glTF'))
    calls=[]
    def swap(disc,model,roles,slot,work,blender,**kw):
        calls.append(slot);i=int(slot.split(':')[1]);return {'mdl':b'model'+bytes([i]),'chk':b'texture'+bytes([i]),
            'mdl_sector':2*i,'mdl_sectors':1,'chk_sector':2*i+1,'chk_sectors':1,'model':{},
            'stats':{'triangles':400},'tried':[{}]}
    monkeypatch.setattr(M,'swap_files',swap)
    donor={'slug':'donor','name':'Donor','model':'model.glb','rig':{'roles':{'head':'head'}}}
    return SimpleNamespace(cfg=cfg,base=base,calls=calls,donor=donor,root=tmp_path)


def test_all_peds_encode_before_one_immutable_disc_is_published(writer):
    before=writer.base.read_bytes()
    result=G.build_cast(writer.cfg,{'game_id':'g'},writer.base,[('ped:1',writer.donor),('ped:2',writer.donor)],'test',root=writer.root)
    assert writer.calls==['ped:1','ped:2'] and result['coverage']['complete']
    out=Path(result['dir']);marker=json.loads((out/'.gbox-mod.json').read_text())
    assert marker['validation']=={'encoded_and_read_back':True,'gameplay_verified':False}
    assert not marker['replacement_scope']['complete'] and writer.base.read_bytes()==before
    with pytest.raises(ValueError,match='already exists'):
        G.build_cast(writer.cfg,{'game_id':'g'},writer.base,[('ped:1',writer.donor)],'test',root=writer.root)


def test_failed_ped_does_not_publish_a_partial_build(writer,monkeypatch):
    previous=M.swap_files
    def fail(*a,**kw):
        if a[3]=='ped:2':raise ValueError('model budget failed')
        return previous(*a,**kw)
    monkeypatch.setattr(M,'swap_files',fail)
    with pytest.raises(ValueError,match='budget failed'):
        G.build_cast(writer.cfg,{'game_id':'g'},writer.base,[('ped:1',writer.donor),('ped:2',writer.donor)],'test',root=writer.root)
    assert not (writer.cfg.cache/'mods/g/test').exists()


def test_failed_disc_write_removes_only_the_new_partial_image(writer,monkeypatch):
    from gbox import filemods
    original=writer.base.read_bytes()
    def fail(*a):raise OSError('write failed')
    monkeypatch.setattr(M,'patch_iso',fail)
    with pytest.raises(OSError,match='write failed'):
        G.build_cast(writer.cfg,{'game_id':'g'},writer.base,[('ped:1',writer.donor)],'test',root=writer.root)
    parent=filemods.mod_dir(writer.cfg,'g','test').parent
    assert not list(parent.glob('**/*.iso')) and list(parent.glob('*/failure.json'))
    assert writer.base.read_bytes()==original and not (parent/'test').exists()


def test_native_reference_reads_the_exact_pedestrian(writer,monkeypatch):
    from gbox import char_coverage,filemods
    monkeypatch.setattr(char_coverage,'writer_for',lambda g:{'writer':'gbox.gta_stories_models'})
    base=filemods.base_dir(writer.cfg,'g');base.mkdir(parents=True);(base/'base.iso').write_bytes(b'base')
    monkeypatch.setattr(G,'entry',lambda d,s:{'sector':4,'txd_sector':(5,1)})
    monkeypatch.setattr(M,'LcsDisc',lambda p:SimpleNamespace(file_at=lambda s:bytes([s])))
    monkeypatch.setattr(M,'read_ped',lambda data: {'source_sector':data[0]})
    seen=[]
    monkeypatch.setattr(M,'ped_to_gltf',lambda model,tex,path,slot:seen.append((model,slot)) or path.write_bytes(b'glTF'))
    path=G.cached_reference(writer.cfg,{'game_id':'g'},'ped:1')
    assert path.read_bytes()==b'glTF' and seen==[({'source_sector':4},'ped:1')]
    assert G.cached_reference(writer.cfg,{'game_id':'g'},'ped:1')==path and len(seen)==1

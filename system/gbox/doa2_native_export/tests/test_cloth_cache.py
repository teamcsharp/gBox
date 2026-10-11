import hashlib,json,struct
from pathlib import Path
import numpy as np
import pytest
from .. import native_cloth_cache as N
from .. import acs_cloth_grids as V
from .. import actor_attachment_frame as A
from .test_cloth_grids import fixture


def make_cache(tmp_path,draw=1):
    original,acs,offsets=fixture(draw=draw)
    world=np.eye(4)[None].repeat(17,0)
    native=V.bake_world_grids(original,acs,world,{32:np.array([[[0,0,0],[1,2,3],[4,5,6]]])},pose_evidence='synthetic unit cache')
    native=bytearray(native['chr_data']);struct.pack_into('<3f',native,24+offsets[0]+12,0,1,0)
    out=tmp_path/'KAS00_32.bin';Path(str(out)+'.component.CHR').write_bytes(native)
    prefix=tmp_path/'KAS00_seed';prefix.with_suffix('.ACS').write_bytes(acs)
    studio=world.copy();studio[:,1,3]+=2
    prefix.with_suffix('.world').write_bytes(studio.transpose(0,2,1).astype('<f4').tobytes())
    row={'stem':'KAS00','descriptor':32,'generated':True,'changed_bytes_confined_to_source_model_vertices':True,
         'source_chr_sha256':hashlib.sha256(original).hexdigest(),'seed':str(prefix),'output':str(out),
         'cached_chr_sha256':hashlib.sha256(native).hexdigest(),'source_acs_sha256':hashlib.sha256(acs).hexdigest(),
         'pose':'synthetic neutral studio regression','floor':'synthetic floor'}
    (tmp_path/'verification.json').write_text(json.dumps({'grids':[row]}))
    return original,acs,offsets,world,row


def apply(original,acs,world,tmp_path,current=None):
    return N.apply_native_cache(original if current is None else current,acs,world,
                                 original_chr=original,stem='KAS00',cache_directory=tmp_path)


def test_native_snapshot_merges_positions_and_normals_preserves_unselected_changes(tmp_path):
    original,acs,offsets,world,_=make_cache(tmp_path)
    current=bytearray(original);struct.pack_into('<2f',current,24+offsets[2]+24,.8,.9)
    result=apply(original,acs,world,tmp_path,current)
    output=result['chr_data']
    np.testing.assert_allclose(struct.unpack_from('<3f',output,24+offsets[0]),[1,2,3],atol=1e-6)
    np.testing.assert_allclose(struct.unpack_from('<3f',output,24+offsets[0]+12),[0,1,0],atol=1e-6)
    assert output[24+offsets[2]+24:24+offsets[2]+32]==current[24+offsets[2]+24:24+offsets[2]+32]
    assert all(a==b or i in result['written_bytes'] for i,(a,b) in enumerate(zip(current,output)))
    assert result['instances'][0]['chr_data']==output
    assembled=N.assemble_cloth_instances(bytes(2048),result)
    assert assembled['report']['draw_instances']==1 and assembled['report']['triangles']==1
    assert assembled['prims'][0]['J'][:,0].tolist()==[1,1,1]


def test_tampered_native_component_hash_fails_before_application(tmp_path):
    original,acs,offsets,world,row=make_cache(tmp_path)
    path=Path(row['output']+'.component.CHR');data=bytearray(path.read_bytes());data[24+offsets[0]+24]^=1;path.write_bytes(data)
    with pytest.raises(ValueError,match='component hash'):apply(original,acs,world,tmp_path)


def test_even_rehashed_component_cannot_write_native_header(tmp_path):
    original,acs,offsets,world,row=make_cache(tmp_path)
    path=Path(row['output']+'.component.CHR');data=bytearray(path.read_bytes());data[24]^=1;path.write_bytes(data)
    row['cached_chr_sha256']=hashlib.sha256(data).hexdigest()
    (tmp_path/'verification.json').write_text(json.dumps({'grids':[row]}))
    with pytest.raises(ValueError):apply(original,acs,world,tmp_path)


def test_neutral_cache_rejects_arbitrary_fight_pose(tmp_path):
    original,acs,_,world,_=make_cache(tmp_path);world[1,0,3]=.1
    with pytest.raises(ValueError,match='neutral rig frame'):apply(original,acs,world,tmp_path)


def test_source_acs_controls_or_source_archive_mismatch_rejected(tmp_path):
    original,acs,offsets,world,_=make_cache(tmp_path)
    changed=bytearray(acs);struct.pack_into('<f',changed,40,.2)
    with pytest.raises(ValueError,match='cached controls'):apply(original,changed,world,tmp_path)
    changed_chr=bytearray(original);changed_chr[24+offsets[0]+24]^=1
    with pytest.raises(ValueError,match='source CHR hash'):apply(changed_chr,acs,world,tmp_path)


@pytest.mark.parametrize('foreign_prefix',('/private/on-another-host/',r'D:\private\on-another-host\\'))
def test_foreign_cache_artifact_paths_are_relocated_without_absolute_dependency(tmp_path,foreign_prefix):
    original,acs,offsets,world,row=make_cache(tmp_path)
    row['seed']=foreign_prefix+Path(row['seed']).name
    row['output']=foreign_prefix+Path(row['output']).name
    (tmp_path/'verification.json').write_text(json.dumps({'grids':[row]}))
    result=apply(original,acs,world,tmp_path)
    np.testing.assert_allclose(struct.unpack_from('<3f',result['chr_data'],24+offsets[0]),[1,2,3],atol=1e-6)


@pytest.mark.parametrize('value',(None,'','/','..',r'C:\private\..'))
def test_invalid_cache_path_cannot_escape_local_directory(value):
    with pytest.raises(ValueError,match='path'):N.cache_name(value)


def test_unverified_root_effect_does_not_get_fabricated_body_attachment(tmp_path):
    original,acs,offsets,world,row=make_cache(tmp_path)
    struct.pack_into('<B',acs,33,15)
    result=apply(original,acs,world,tmp_path)
    assert result['chr_data']==original and result['instances']==[]
    assert len(result['report']['unverified_actor_effects'])==1


def root_cache(tmp_path):
    original,acs,offsets,world,row=make_cache(tmp_path,draw=0)
    acs.extend(bytes(80));struct.pack_into('<B',acs,33,15)
    struct.pack_into('<4I',acs,8,4,352,255,0)
    struct.pack_into('<2BH',acs,352,11,0,0)
    struct.pack_into('<3f',acs,356,1,2,3)
    prefix=Path(row['seed']);prefix.with_suffix('.ACS').write_bytes(acs)
    row['source_acs_sha256']=hashlib.sha256(acs).hexdigest()
    frame=A.source_controller_frame(acs,world,0)
    row['native_actor_root_verified']={'maximum_matrix_error':0,
                                      'root_source':{k:v for k,v in frame.items() if k!='world'}}
    (tmp_path/'verification.json').write_text(json.dumps({'grids':[row]}))
    return original,acs,world,row


def test_verified_native_root_grid_draws_under_its_authored_controller_joint(tmp_path):
    original,acs,world,_=root_cache(tmp_path);result=apply(original,acs,world,tmp_path)
    assert result['instances'][0]['parent']==11
    np.testing.assert_allclose(result['instances'][0]['world'][:3,3],[1,2,3])
    assert result['report']['unverified_actor_effects']==[]
    assembled=N.assemble_cloth_instances(bytes(2048),result)
    assert assembled['prims'][0]['J'][:,0].tolist()==[11,11,11]


def test_actor_controller_comparison_and_source_mapping_must_be_verified(tmp_path):
    original,acs,world,row=root_cache(tmp_path)
    row['native_actor_root_verified']['maximum_matrix_error']=.01
    (tmp_path/'verification.json').write_text(json.dumps({'grids':[row]}))
    with pytest.raises(ValueError,match='comparison'):apply(original,acs,world,tmp_path)
    row['native_actor_root_verified']['maximum_matrix_error']=0
    row['native_actor_root_verified']['root_source']['parent']=2
    (tmp_path/'verification.json').write_text(json.dumps({'grids':[row]}))
    with pytest.raises(ValueError,match='source controller mismatch'):apply(original,acs,world,tmp_path)

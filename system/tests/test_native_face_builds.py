import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from gbox import twin_snakes_faces as W,ts_tex as T,ts_stage as S,doa2_faces as D
from test_twin_snakes import model_bytes,body_set,stage_blob,stage_dat,LAYER
from test_doa2_textures import fixture


def test_twin_faces_keeps_native_models_duplicate_keys_and_untouched_blocks():
    model=model_bytes();atlas=body_set();ts=T.TextureSet(atlas);img=ts.by_hash(LAYER[1]);sha=hashlib.sha256(ts.rgba(img).tobytes()).hexdigest()
    # Same resource hash twice in one native page: rebuilding by hash alone
    # changes the wrong file. Exact offset edits retain the second untouched.
    unrelated=body_set((20,160,90))
    raw=stage_dat([('r_sna',stage_blob([(S.MODEL,0xf7a622,model),(S.TEXTURES,0x413aa8,atlas),(S.TEXTURES,0x413aa8,unrelated),(6,0x180720,b'unchanged-script')]))])
    output,report=W.prepare_container(raw,Image.new('RGBA',(32,32),(10,30,200,255)),[{'model':'f7a622','texture':f'{LAYER[1]:06x}','sha256':sha}],crop=(0,0,1,1))
    assert len(output)==len(raw) and report['faces']
    old=S.StageDat.from_bytes(raw).stage(0).files();new=S.StageDat.from_bytes(output).stage(0).files()
    assert len(old)==len(new)
    for i in (0,2,3):assert old[i].data==new[i].data
    assert old[1].data!=new[1].data


def test_twin_cmpr_copies_untouched_4x4_blocks_exactly():
    ts=T.TextureSet(body_set());img=ts.by_hash(LAYER[1]);before=bytes(ts.data);rgba=ts.rgba(img);rgba[1,1]=[0,255,0,255]
    mask=np.zeros(rgba.shape[:2],bool);mask[1,1]=True
    after=W.replace_masked(ts,img,Image.fromarray(rgba),mask);start=ts.tpl+img.data_off
    assert after[start:start+8]!=before[start:start+8]
    assert after[:start]==before[:start] and after[start+8:]==before[start+8:]


def test_tight_native_compression_preserves_all_decoded_resources():
    raw=stage_blob([(6,123,b'original-script'*200),(19,456,body_set())])
    st=S.parse_stage(raw)
    before=[(f.page,f.key,f.offset,f.data)for f in st.files()]
    after=S.parse_stage(W._smallest_stage(st))
    assert [(f.page,f.key,f.offset,f.data)for f in after.files()]==before


def test_doa_source_guard_and_unrelated_native_bytes(monkeypatch):
    raw,bank=fixture([(8,8,2,1),(8,8,1,1)]);tex=D.T.descriptors(raw,bank)[0]
    base=Image.new('RGBA',(8,8),(80,90,100,255));bank=D.T.replace(raw,bank,{0:base})
    geom={'vertices':[(-1,1,1,0,0,1,0,0),(1,1,1,0,0,1,1,0),(1,-1,1,0,0,1,1,1),(-1,-1,1,0,0,1,0,1)],'triangles':[(0,1,2),(0,2,3)],'texture_id':0}
    monkeypatch.setattr(D.B,'resolve_archive_binding',lambda *a:{'sections':{'primary':[0,0]},'render_slot':1,'costume':0})
    monkeypatch.setattr(D.G,'decode_chr',lambda *a:{'models':[{'meshes':[geom]}]})
    class Disc:
        def read(self,key):return {'1ST_READ.BIN':b'executable','DOA2/TST00.CHR':raw,'DOA2/TST00.BIN':bank}[key]
    profile={'DOA2/TST00.CHR':{'head_model':0,'texture':0,'sha256':hashlib.sha256(bank[tex.offset:tex.offset+tex.size]).hexdigest()}}
    changes,reports=D.prepare(Disc(),Image.new('RGBA',(16,16),'red'),profile,crop=(0,0,1,1))
    result=changes['DOA2/TST00.BIN'];assert len(result)==len(bank)
    assert result[tex.offset+tex.size:]==bank[tex.offset+tex.size:] and reports[0]['geometry_modified'] is False
    profile['DOA2/TST00.CHR']['sha256']='0'*64
    with pytest.raises(ValueError,match='texture changed'):D.prepare(Disc(),base,profile)


def test_reviewed_profiles_are_lineage_bound_and_do_not_claim_approval():
    folder=Path(W.__file__).parent
    for name in ('doa2_face_profiles.json','twin_snakes_face_profiles.json'):
        doc=json.loads((folder/name).read_text());rows=doc['profiles'];rows=list(rows.values())if isinstance(rows,dict)else rows
        assert rows and all(len(p['sha256'])==64 for p in rows)
        assert 'unverified'in doc['review']


def test_preview_compaction_preserves_png_bytes_and_four_loader_pairs(tmp_path):
    from zipfile import ZipFile
    from gbox.native_face_projection import compact_previews
    folder=tmp_path/'face-previews';folder.mkdir();faces=[];originals={}
    for i in range(8):
        row={'native_actor':str(i)}
        for key in ('before','after'):
            name=f'face-previews/{i}-{key}.png';Image.new('RGB',(4,4),(i*20,0,0)).save(tmp_path/name);originals[name]=(tmp_path/name).read_bytes();row['preview_'+key]=name
        faces.append(row)
    result=compact_previews(tmp_path,faces)
    assert len(result['previews'])==4 and len(list(folder.iterdir()))==8
    with ZipFile(tmp_path/'face-previews.zip')as archive:
        for name in archive.namelist():assert archive.read(name)==originals[name]
    assert all(row['preview_before'].startswith('face-previews.zip!')for row in faces[4:])


def test_twin_plan_rejects_wrong_game_before_reading_or_unpacking(monkeypatch):
    import gbox.characters as characters
    monkeypatch.setattr(characters,'_api',lambda *a,**k:pytest.fail('Wrong game must not fetch catalog or unpack a ROM'))
    inp=W.BuildIn(op='plan',game_id='0'*16,photo='1'*64)
    with pytest.raises(ValueError,match='GGSEA4'):W.run(inp,object())

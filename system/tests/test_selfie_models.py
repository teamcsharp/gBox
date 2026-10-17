import base64
import json
from pathlib import Path

from PIL import Image
from gbox import photo_skin as P, characters as C, attachments as A, blender_roundtrip as RT
from tests.test_photo_skin import api


def accept(c,photo,name='Bla'):
    row=c.post('/api/characters/base/photo-skins',json={'name':name,'photo':photo,'maps':[0]}).json()
    return c.post('/api/photo-skins/'+row['id']+'/decision',json={'decision':'accept'}).json()['variant']


def test_groups_existing_approved_donors_edits_and_fitted_models_without_rewriting(api):
    c,s,root,photo=api;slug=accept(c,photo)
    meta=C.get(root,slug);meta.pop('selfie_photo');meta.pop('tags');C.put_meta(root,meta)
    # Old photo approvals remain discoverable, and later edits have only parent lineage.
    C.put_meta(root,{'slug':'edit','name':'Edited Bla','model':'edit.glb','variant_of':slug})
    (root/'edit/edit.glb').write_bytes((root/slug/'model.glb').read_bytes())
    C.put_meta(root,{'slug':'derived','name':'New rig Bla','model':'model.glb','derived_from':'edit'})
    (root/'derived/model.glb').write_bytes((root/slug/'model.glb').read_bytes())
    targets=root/slug/'targets';targets.mkdir();(targets/'pso.glb').write_bytes((root/slug/'model.glb').read_bytes());(targets/'pso_preview.png').write_bytes(b'preview')
    before=(root/slug/'meta.json').read_bytes()
    groups=c.get('/api/photo-skins/collections').json()
    assert len(groups)==1 and groups[0]['photo']==photo and groups[0]['label']=='Bla'
    assert {m['slug'] for m in groups[0]['models']}=={slug,'edit','derived'}
    m=next(m for m in groups[0]['models'] if m['slug']==slug)
    assert m['tags']==['selfie:'+photo] and [f['file'] for f in m['fitted_models']]==['targets/pso.glb']
    assert (root/slug/'meta.json').read_bytes()==before


def test_identity_is_exact_image_not_name_and_rename_preserves_it(api):
    c,s,root,photo=api;accept(c,photo)
    data='data:image/png;base64,'+base64.b64encode(P.png(Image.new('RGB',(20,30),'blue'))).decode()
    second=c.post('/api/photo-skins/photos',json={'data_url':data,'label':'Bla'}).json()['photo'];accept(c,second)
    assert len(c.get('/api/photo-skins/collections').json())==2
    assert c.post('/api/photo-skins/photos/'+photo+'/label',json={'label':'Bla portrait'}).status_code==200
    rows={g['photo']:g for g in c.get('/api/photo-skins/collections').json()}
    assert rows[photo]['label']=='Bla portrait' and rows[second]['label']=='Bla'
    c.post('/api/photo-skins/photos',json={'data_url':data,'label':'Must not replace my tag'})
    assert s.get('photo_source',second)['label']=='Bla'
    assert c.post('/api/photo-skins/photos/'+photo+'/label',json={'label':'  '}).status_code==422


def test_rejected_candidates_and_lineage_cycles_are_not_models(api):
    c,s,root,photo=api
    row=c.post('/api/characters/base/photo-skins',json={'photo':photo,'maps':[0]}).json()
    c.post('/api/photo-skins/'+row['id']+'/decision',json={'decision':'reject'})
    C.put_meta(root,{'slug':'a','name':'A','variant_of':'b'});C.put_meta(root,{'slug':'b','name':'B','variant_of':'a'})
    assert c.get('/api/photo-skins/collections').json()==[]


def test_export_contains_buffers_images_and_roundtrip_photo_parent(api,tmp_path):
    c,s,root,photo=api;slug=accept(c,photo)
    group=c.get('/api/photo-skins/collections').json()[0]
    assert group['models'][0]['tags']==['selfie:'+photo]
    prefix=f'/api/photo-skins/collections/{photo}/models/{slug}'
    reply=c.get(prefix+'/download');assert reply.status_code==200 and reply.content[:4]==b'glTF'
    file=tmp_path/'download.glb';file.write_bytes(reply.content);gl,blob=A.read_gltf(file)
    assert blob and not any(b.get('uri') for b in gl.get('buffers',[]))
    assert not any(i.get('uri') for i in gl.get('images',[]))
    assert RT.read_info(gl)['base']==slug  # not the original unmodified donor
    exported=c.post(prefix+'/export',json={}).json()
    file.write_bytes(s.read_artifact(exported['sha256']));export_gl,export_blob=A.read_gltf(file)
    assert RT.read_info(export_gl)['base']==slug and export_blob==blob
    assert c.get(f'/api/photo-skins/collections/{photo}/models/base/download').status_code==404
    assert c.get(prefix+'/download',params={'file':'../base/model.glb'}).status_code==404


def test_fitted_gltf_export_packs_companions_and_rejects_escape(api,tmp_path):
    c,s,root,photo=api;slug=accept(c,photo);directory=root/slug/'targets';directory.mkdir()
    gl,blob=A.read_gltf(root/slug/'model.glb');gl['buffers'][0]['uri']='mesh.bin'
    (directory/'mesh.bin').write_bytes(blob);(directory/'fit.gltf').write_text(json.dumps(gl))
    prefix=f'/api/photo-skins/collections/{photo}/models/{slug}'
    reply=c.get(prefix+'/download',params={'file':'targets/fit.gltf'});assert reply.status_code==200,reply.text
    path=tmp_path/'fit.glb';path.write_bytes(reply.content);packed,newblob=A.read_gltf(path)
    assert newblob==blob and not packed['buffers'][0].get('uri')
    gl['buffers'][0]['uri']='../../secret.bin';(directory/'escape.gltf').write_text(json.dumps(gl))
    assert c.get(prefix+'/download',params={'file':'targets/escape.gltf'}).status_code==422
    assert c.post('/api/photo-skins/photos/'+'a'*64+'/label',json={'label':'Unknown image'}).status_code==404

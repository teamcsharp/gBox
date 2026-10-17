"""Photo skins on existing UV maps. No face recognition or inferred 3-D head geometry."""
import base64
import copy
import hashlib
import io
from pathlib import Path
import time
import uuid
import re
from urllib.parse import quote

import numpy as np
from pydantic import BaseModel, Field, model_validator

MAX_PHOTO = 8 * 1024**2
CONTRACT_SOURCES={f'gbox/{name}':hashlib.sha256(Path(__file__).with_name(name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                  for name in ('characters.py','cast_swap.py','re4_photo_skin.py')}


def claim_reason(worker,job):
    """Old workers ignore unknown schema fields. Never let one drop a locked lead."""
    inp=job.get('input') or {}
    if job.get('tool')!='characters' or not (inp.get('lead_character') or '_photo_' in str(inp.get('character') or '')):return None
    if any((worker.get('build_sources') or {}).get(path)!=sha for path,sha in CONTRACT_SOURCES.items()):
        return 'Photo/locked-lead builds require a safely refreshed worker with the matching character contract; queued recipe retained.'
    return None


class PhotoUpload(BaseModel):
    data_url: str = Field(max_length=MAX_PHOTO*4//3+200)
    source_kind: str = Field(default='photo',pattern='^(photo|selfie|generated|internet)$')
    label: str = Field(default='',max_length=80)


class PhotoLabel(BaseModel):
    label: str = Field(min_length=1,max_length=80)


def photo_of(meta, entries):
    """Follow explicit asset lineage, never a person's name or a visual similarity."""
    seen=set()
    while meta and meta.get('slug') not in seen:
        seen.add(meta.get('slug'))
        photo=(meta.get('photo_skin_approval') or {}).get('source_photo') or meta.get('selfie_photo')
        if isinstance(photo,str) and re.fullmatch('[a-f0-9]{64}',photo):return photo
        parent=meta.get('variant_of') or meta.get('derived_from') or (meta.get('source') or {}).get('derived_from')
        meta=entries.get(parent)
    return None


def collections(store,K,root):
    entries={m['slug']:m for m in K.list_all(root)};groups={}
    for meta in entries.values():
        photo=photo_of(meta,entries)
        if not photo:continue
        artifact=store.get('artifact',photo) or {}
        if not (artifact.get('provenance') or {}).get('photo_skin_source'):continue
        label=store.get('photo_source',photo) or {}
        group=groups.setdefault(photo,{'photo':photo,'tag':'selfie:'+photo,
            'label':label.get('label') or 'Selfie '+photo[:8], 'url':'/api/artifacts/'+photo,
            'source_kind':artifact['provenance'].get('source_kind','photo'),'models':[]})
        if not label.get('label') and (meta.get('photo_skin_approval') or {}).get('settings',{}).get('name'):
            group['label']=meta['photo_skin_approval']['settings']['name']
        directory=(Path(root)/meta['slug']).resolve()
        if directory.parent!=Path(root).resolve():continue
        files=[]
        for path in sorted((directory/'targets').glob('*')):
            if path.suffix.lower() not in ('.glb','.gltf') or not path.is_file() or not path.resolve().is_relative_to(directory):continue
            files.append({'file':path.relative_to(directory).as_posix(),'name':path.stem,'bytes':path.stat().st_size})
        group['models'].append({'slug':meta['slug'],'name':meta['name'],'model':meta.get('model'),
            'preview_url':f"/api/characters/{quote(meta['slug'],safe='')}/preview",'source':meta.get('source') or {},
            'variant_of':meta.get('variant_of'),'stats':meta.get('stats') or {},'verification':meta.get('verification'),
            'tags':list(dict.fromkeys([*(meta.get('tags') or []),'selfie:'+photo])),
            'targets':meta.get('targets') or {},'fitted_models':files})
    for group in groups.values():group['models'].sort(key=lambda m:m['name'].casefold())
    return sorted(groups.values(),key=lambda g:(g['label'].casefold(),g['photo']))


class Placement(BaseModel):
    name: str = Field(default='Photo character',min_length=1,max_length=80)
    photo: str = Field(pattern='^[a-f0-9]{64}$')
    maps: list[int] = Field(min_length=1,max_length=16)
    crop: list[float] = Field(default_factory=lambda:[0,0,1,1],min_length=4,max_length=4)
    # Clockwise TL, TR, BR, BL in the source photo; destination can be rotated.
    quad: list[list[float]] = Field(default_factory=lambda:[[0,0],[1,0],[1,1],[0,1]],min_length=4,max_length=4)
    feather: float = Field(default=.04,ge=0,le=.2)
    opacity: float = Field(default=1,gt=0,le=1)

    @model_validator(mode='after')
    def valid(self):
        if any(not np.isfinite(x) or not 0<=x<=1 for x in self.crop):raise ValueError('Crop coordinates must be within the photo')
        l,t,r,b=self.crop
        if r-l<.01 or b-t<.01:raise ValueError('Select a nonempty photo crop')
        if any(len(p)!=2 or any(not np.isfinite(v) or not 0<=v<=1 for v in p) for p in self.quad):
            raise ValueError('Four destination UV corners must be inside the map')
        q=np.asarray(self.quad);edges=np.roll(q,-1,axis=0)-q
        cross=edges[:,0]*np.roll(edges,-1,axis=0)[:,1]-edges[:,1]*np.roll(edges,-1,axis=0)[:,0]
        if not (np.all(cross>.0001) or np.all(cross<-.0001)):raise ValueError('UV corners must form a convex, non-folded patch')
        if any(i<0 for i in self.maps) or len(set(self.maps))!=len(self.maps):raise ValueError('Choose unique color map indices')
        return self


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def normalize_photo(raw):
    from PIL import Image, ImageOps
    if len(raw)>MAX_PHOTO:raise ValueError('Photo must be no larger than 8 MiB')
    try:im=Image.open(io.BytesIO(raw))
    except Image.DecompressionBombError as e:raise ValueError('Photo exceeds the decode budget') from e
    if im.format not in ('PNG','JPEG','WEBP'):raise ValueError('Use a PNG, JPEG or WebP photo')
    if im.width*im.height>12_000_000:raise ValueError('Photo exceeds 12 megapixels')
    im=ImageOps.exif_transpose(im).convert('RGBA');im.thumbnail((2048,2048))
    clean=Image.new('RGBA',im.size);clean.paste(im)
    return png(clean)  # No EXIF, face embedding, or identity inference.


def project(original,photo,settings):
    """Inverse projective map into a selected UV patch; preserve the original alpha."""
    from PIL import Image, ImageDraw, ImageFilter, ImageChops
    original=original.convert('RGBA');photo=photo.convert('RGBA')
    if original.width*original.height>4_194_304:raise ValueError('Selected map exceeds the 4 megapixel preview budget')
    l,t,r,b=settings.crop
    src=np.asarray([[l,t],[r,t],[r,b],[l,b]])*np.asarray(photo.size)
    dst=np.asarray(settings.quad)*np.asarray(original.size)
    rows=[];values=[]
    for (x,y),(u,v) in zip(dst,src):
        rows.extend(([x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]));values.extend((u,v))
    coeff=np.linalg.solve(np.asarray(rows),np.asarray(values))
    warped=photo.transform(original.size,Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
    # An ellipse within the source crop avoids pasting a rectangular photo/background
    # over the hair/ears. UV corner placement is explicit; no automatic face detection.
    source_mask=Image.new('L',photo.size,0);draw=ImageDraw.Draw(source_mask)
    draw.ellipse((l*photo.width,t*photo.height,r*photo.width,b*photo.height),fill=255)
    if settings.feather:source_mask=source_mask.filter(ImageFilter.GaussianBlur(settings.feather*min((r-l)*photo.width,(b-t)*photo.height)))
    mask=source_mask.transform(original.size,Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
    mask=ImageChops.multiply(mask,warped.getchannel('A'))
    if settings.opacity!=1:mask=mask.point(lambda v:round(v*settings.opacity))
    result=Image.composite(warped,original,mask);result.putalpha(original.getchannel('A'))
    return result


def prepare(model,photo,settings,emit):
    from PIL import Image
    from . import attachments as A
    gl,blob=A.pack(Path(model));source=hashlib.sha256(A.glb_bytes(copy.deepcopy(gl),blob)).hexdigest()
    refs=[]
    for m in gl.get('materials',[]):
        tex=m.get('pbrMetallicRoughness',{}).get('baseColorTexture')
        if tex is not None:
            texture=gl['textures'][tex['index']]
            if 'source' in texture:refs.append((tex,tex['index'],texture['source']))
    if set(settings.maps)-{r[2] for r in refs}:raise ValueError('Select existing base-color maps; normal/data/emissive maps are not edited')
    out=bytearray(blob);images=[];story_maps=[]
    for index in settings.maps:
        im=gl['images'][index];view=gl['bufferViews'][im['bufferView']]
        raw=blob[view.get('byteOffset',0):view.get('byteOffset',0)+view['byteLength']]
        before=Image.open(io.BytesIO(raw));before.load();after=project(before,photo,settings)
        if len(settings.maps)<=4:story_maps.append((before,after))
        data=png(after)
        if len(out)+len(data)>64*1024**2:raise ValueError('Photo candidate exceeds 64 MiB')
        out.extend(bytes(-len(out)%4));offset=len(out);out.extend(data)
        gl['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(data)})
        new_image=len(gl['images']);gl['images'].append({'bufferView':len(gl['bufferViews'])-1,'mimeType':'image/png'})
        remap={}
        for ref,texture,image in refs:
            if image!=index:continue
            if texture not in remap:
                remap[texture]=len(gl['textures']);gl['textures'].append({**gl['textures'][texture],'source':new_image})
            ref['index']=remap[texture]
        images.append({'index':index,'before':emit('photo-before-'+str(index)+'.png',png(before),'image/png'),
                       'after':emit('photo-after-'+str(index)+'.png',data,'image/png'),'size':list(after.size)})
    story=None
    try:
        from .photo_story import record
        story=record(model,settings,story_maps,emit)
    except (ValueError,OSError,KeyError,IndexError):pass # Texture comparison still works when a mesh preview is unavailable.
    return {'source_sha256':source,'candidate':emit('photo-candidate.glb',A.glb_bytes(gl,bytes(out)),'model/gltf-binary'), 'story':story,
            'images':images,'settings':settings.model_dump(),'status':'pending',
            'notice':'Photo projected onto existing UV maps. Geometry, rig, weights and original alpha unchanged; not a reconstructed 3D head or a verified game build.'}


class Decision(BaseModel):
    decision: str = Field(pattern='^(accept|reject)$')


class DemoIn(BaseModel):
    game_ids: list[str] = Field(min_length=1,max_length=10)
    supporting_sources: list[str] = Field(default_factory=lambda:['Metal Gear Solid - The Twin Snakes','Dead or Alive 2'],min_length=1,max_length=20)
    seed: str = Field(default='photo-demo',max_length=120)


def demo_plan(game,chars,lead,source,seed,root=None):
    from . import cast_swap as CS, char_coverage as CC
    writer=CC.writer_for(game)
    base={'game_id':game['game_id'],'title':game.get('title'),'lead_character':lead,'seed':seed,
          'requested_scope':'Selected photo donor on the player; roulette supporting cast; gameplay and in-engine cinematics',
          'verification':'No native runtime validation yet'}
    if not writer or not writer.get('routed'):
        return base|{'state':'needs_native_writer','reason':'No routed replacement writer for this exact owned game/version.'}
    if writer.get('writer')=='gbox.gta_vc_swap':
        return base|{'state':'needs_install_validation','writer':writer,
            'reason':'This writer supports classic RenderWare PC installs only. Verify a classic models/gta3.img layout first; Definitive Edition and PS2 require different writers.'}
    try:p=CS.plan(game,chars,source,mapping='random',seed=seed,slots='all',root=root,lead_character=lead)
    except ValueError as e:return base|{'state':'blocked','reason':str(e),'writer':writer}
    if p['status']!='planned':
        return base|{'state':p['status'],'reason':p.get('message'),'writer':writer,
            'player_diagnostic':{'tool':'characters','input':{'op':'use','character':lead,'game_id':game['game_id'],'slot':'player','launch':False}},
            'notice':'Player-only diagnostic is not the requested combined cast build.'}
    if p.get('skipped'):
        return base|{'state':'partial_plan','plan':p,'reason':'Some requested cast slots are not buildable; do not call this a complete cast replacement.'}
    return base|{'state':'planned','plan':p,'recipe':{'tool':'characters','input':{'op':'cast_swap','target_game':game['game_id'],
        'source':source,'mapping':'random','seed':seed,'slots':'all','lead_character':lead,'lead_slot':p['locked_lead']['slot'],
        'assignments':[{'slot':r['slot'],'character':r['character']} for r in p['assignments']],'launch':False}},
        'notice':'Plan only. Review existing build reports before submitting; native gameplay and cinematic coverage still need verification.'}


def register(app,auth,store,chars):
    from fastapi import Depends,HTTPException
    from fastapi.responses import Response

    def source(photo):
        if not re.fullmatch('[a-f0-9]{64}',photo):raise HTTPException(404,'Source photo missing')
        artifact=store.get('artifact',photo) or {}
        if not (artifact.get('provenance') or {}).get('photo_skin_source'):raise HTTPException(404,'Source photo missing')
        return artifact

    @app.get('/api/photo-skins/collections')
    def library(actor=Depends(auth)):
        K,root=chars()
        return collections(store,K,root)

    @app.post('/api/photo-skins/photos/{photo}/label')
    def rename(photo:str,body:PhotoLabel,actor=Depends(auth)):
        source(photo);label=body.label.strip()
        if not label:raise HTTPException(422,'Enter a name for this image')
        with store.lock:
            row=(store.get('photo_source',photo) or {})|{'photo':photo,'label':label,'updated':time.time()}
            store.put('photo_source',photo,row)
        return row

    def export_model(photo,slug,file):
        from . import attachments as A
        source(photo);K,root=chars();entries={m['slug']:m for m in K.list_all(root)};meta=entries.get(slug)
        if not meta or photo_of(meta,entries)!=photo:raise HTTPException(404,'Model does not belong to this source image')
        directory=(Path(root)/slug).resolve();relative=file or meta.get('model','');path=(directory/relative).resolve()
        if directory.parent!=Path(root).resolve() or not path.is_relative_to(directory) or not path.is_file():raise HTTPException(404,'Model missing')
        if relative!=meta.get('model') and (not relative.startswith('targets/') or len(Path(relative).parts)!=2):raise HTTPException(422,'Select the donor or a fitted target model')
        if path.suffix.lower() not in ('.gltf','.glb'):raise HTTPException(422,'Select a GLB or glTF model')
        if path.stat().st_size>64*1024**2:raise HTTPException(422,'Model exceeds the 64 MiB export budget')
        # Validate companion paths before packing a glTF; no escaping the private model directory.
        try:
            gl,_=A.read_gltf(path);budget=path.stat().st_size
            for item in [*gl.get('buffers',[]),*gl.get('images',[])]:
                uri=item.get('uri','')
                if not uri or uri.startswith('data:'):continue
                from urllib.parse import unquote,urlsplit
                parsed=urlsplit(uri);external=(path.parent/unquote(parsed.path)).resolve()
                raw_external=(path.parent/uri).resolve()
                if parsed.scheme or parsed.netloc or not external.is_relative_to(directory) or not raw_external.is_relative_to(directory):raise ValueError('Model companion leaves its collection folder')
                budget+=external.stat().st_size
                if budget>64*1024**2:raise ValueError('Packed model exceeds the 64 MiB export budget')
            gl,blob=A.pack(path)
            from . import blender_roundtrip
            blender_roundtrip.tag(gl,meta)
            data=A.glb_bytes(gl,blob)
            if len(data)>64*1024**2:raise ValueError('Packed model exceeds the 64 MiB export budget')
        except (ValueError,OSError,KeyError) as e:raise HTTPException(422,str(e)) from e
        return data,path.stem+'.glb'

    @app.get('/api/photo-skins/collections/{photo}/models/{slug}/download')
    def download(photo:str,slug:str,file:str='',actor=Depends(auth)):
        data,name=export_model(photo,slug,file)
        return Response(data,media_type='model/gltf-binary',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(name,safe='')})

    @app.post('/api/photo-skins/collections/{photo}/models/{slug}/export')
    def export(photo:str,slug:str,file:str='',actor=Depends(auth)):
        data,name=export_model(photo,slug,file)
        ref=store.put_artifact(data,name,'model/gltf-binary',{'selfie_photo':photo,'character':slug,'file':file})
        return {'sha256':ref.sha256,'name':name,'url':'/api/artifacts/'+ref.sha256}

    @app.post('/api/photo-skins/photos')
    def upload(body:PhotoUpload,actor=Depends(auth)):
        try:
            header,encoded=body.data_url.split(',',1)
            if header not in ('data:image/jpeg;base64','data:image/png;base64','data:image/webp;base64'):raise ValueError('Use a PNG, JPEG or WebP photo')
            data=normalize_photo(base64.b64decode(encoded,validate=True))
        except (ValueError,OSError) as e:raise HTTPException(422,str(e)) from e
        ref=store.put_artifact(data,'photo-source.png','image/png',{'photo_skin_source':True,'source_kind':body.source_kind,'uploaded_by':str(actor)})
        with store.lock:
            if not store.get('photo_source',ref.sha256):
                store.put('photo_source',ref.sha256,{'photo':ref.sha256,'label':body.label.strip(),'created':time.time()})
        return {'photo':ref.sha256,'url':'/api/artifacts/'+ref.sha256}

    @app.post('/api/characters/{slug}/photo-skins')
    def create(slug:str,body:Placement,actor=Depends(auth)):
        from PIL import Image
        K,root=chars()
        try:meta=K.get(root,slug)
        except KeyError:raise HTTPException(404,'Character missing')
        if meta.get('photo_skin_approval'):
            raise HTTPException(409,'Prepare a fresh face from the original donor '+str(meta.get('variant_of'))+'; do not compound photo projections')
        artifact=store.get('artifact',body.photo) or {}
        if not (artifact.get('provenance') or {}).get('photo_skin_source') or artifact.get('size',0)>16*1024**2:
            raise HTTPException(422,'Upload the source through Photo skin first')
        raw=store.read_artifact(body.photo)
        if not raw:raise HTTPException(404,'Source photo missing')
        rid=uuid.uuid4().hex
        def emit(name,data,kind):return store.put_artifact(data,name,kind,{'photo_skin_review':rid,'character':slug}).sha256
        source=Path(root)/slug/meta['model']
        if source.stat().st_size>64*1024**2:raise HTTPException(422,'Source model exceeds 64 MiB; choose a lighter donor')
        try:result=prepare(source,Image.open(io.BytesIO(raw)),body,emit)
        except (ValueError,OSError,np.linalg.LinAlgError) as e:raise HTTPException(422,str(e)) from e
        row=result|{'id':rid,'character':slug,'created':time.time(),'by':str(actor),'source_kind':artifact['provenance'].get('source_kind')}
        store.put('photo_skin',rid,row);return row

    @app.get('/api/photo-skins/{rid}')
    def review(rid:str,actor=Depends(auth)):
        row=store.get('photo_skin',rid)
        if not row:raise HTTPException(404,'Photo skin review missing')
        return row

    @app.post('/api/photo-skins/{rid}/demo-plans')
    def demos(rid:str,body:DemoIn,actor=Depends(auth)):
        row=store.get('photo_skin',rid)
        if not row or row.get('status')!='accepted':raise HTTPException(409,'Accept a photo donor before planning builds')
        K,root=chars();all_chars=K.list_all(root);source=','.join(body.supporting_sources);plans=[]
        for gid in dict.fromkeys(body.game_ids):
            game=store.catalog_get(gid)
            if not game:raise HTTPException(404,'Target game missing: '+gid)
            plan=demo_plan(game,all_chars,row['variant'],source,body.seed+':'+gid,root)
            store.put('photo_demo_plan',rid+':'+gid,plan|{'review':rid,'created':time.time()});plans.append(plan)
        return {'review':rid,'plans':plans,'submitted':False}

    @app.post('/api/photo-skins/{rid}/decision')
    def decide(rid:str,body:Decision,actor=Depends(auth)):
        from . import attachments as A
        with store.lock:
            row=store.get('photo_skin',rid)
            if not row:raise HTTPException(404,'Photo skin review missing')
            state='accepted' if body.decision=='accept' else 'rejected'
            if row['status']!='pending':
                if row['status']==state:return row
                raise HTTPException(409,'Photo review already decided')
            if state=='accepted':
                K,root=chars();meta=K.get(root,row['character']);gl,blob=A.pack(Path(root)/meta['slug']/meta['model'])
                if hashlib.sha256(A.glb_bytes(gl,blob)).hexdigest()!=row['source_sha256']:
                    raise HTTPException(409,'Source model changed; prepare a new photo preview')
                artifact=store.get('artifact',row['candidate']) or {}
                if (artifact.get('provenance') or {}).get('photo_skin_review')!=rid:raise HTTPException(409,'Candidate ownership mismatch')
                data=store.read_artifact(row['candidate'])
                if not data or hashlib.sha256(data).hexdigest()!=row['candidate']:raise HTTPException(409,'Candidate missing or changed')
                variant=meta['slug'][:55]+'_photo_'+row['candidate'][:12];dest=Path(root)/variant
                if dest.exists():
                    try:existing=K.get(root,variant)
                    except KeyError:raise HTTPException(409,'Photo variant folder already exists without matching metadata')
                    if (existing.get('photo_skin_approval') or {}).get('candidate')!=row['candidate'] or hashlib.sha256((dest/existing['model']).read_bytes()).hexdigest()!=row['candidate']:
                        raise HTTPException(409,'Existing photo variant does not match this candidate')
                    row.update(variant=variant,name=existing['name'],status='accepted',decided=time.time(),decided_by=str(actor))
                    store.put('photo_skin',rid,row);return row
                dest.mkdir(parents=True,exist_ok=True);(dest/'model.glb').write_bytes(data)
                new=copy.deepcopy(meta)
                for key in ('targets','target_files','rigs','retarget_profiles','readiness','native_player','files','preview','preview_url','verification','verified','aliases','texture_approval','anims_file','animations'):
                    new.pop(key,None)
                new.update(slug=variant,name=row['settings']['name']+' on '+meta['name'],model='model.glb',variant_of=meta['slug'],
                    selfie_photo=row['settings']['photo'],tags=list(dict.fromkeys([*(meta.get('tags') or []),'selfie:'+row['settings']['photo']])),
                    photo_skin_approval={'review':rid,'source_photo':row['settings']['photo'],'source_sha256':row['source_sha256'],
                        'candidate':row['candidate'],'images':row['images'],'settings':row['settings'],'story':row.get('story'),'at':time.time(),'by':str(actor)},
                    verification={'status':'unverified','reason':'Photo skin approved; requires native build and gameplay verification'},files=['model.glb'])
                try:
                    if (new.get('stats') or {}).get('triangles',0)>50000:raise ValueError('Use the interactive 3D preview for this high-poly donor')
                    K.render_preview(dest/'model.glb',dest/'preview.png',size=256)
                    new['preview']='preview.png';new['files'].append('preview.png')
                except (ValueError,OSError,KeyError) as e:
                    new['preview_error']=str(e)[:200]
                K.put_meta(root,new);row.update(variant=variant,name=new['name'])
            row.update(status=state,decided=time.time(),decided_by=str(actor));store.put('photo_skin',rid,row)
            store.audit(actor,'photo_skin.'+state,rid,{'character':row['character'],'variant':row.get('variant')})
            return row


from .registry import tool
from .models import Permission as P


class PhotoIn(BaseModel):
    op: str = Field(description='upload, prepare, review or demo_plans. Never approves a preview or launches a game.')
    path: str = Field(default='',description='For upload: image file path supplied by the operator; no photo bytes in the language-model prompt.')
    character: str = ''
    review: str = ''
    value: dict = Field(default_factory=dict)


class PhotoOut(BaseModel):
    result: dict


@tool('photo_skin','1.0',PhotoIn,PhotoOut,capabilities=['asset'],permissions=[P.EXECUTE],timeout_s=180,retries=0)
def photo_tool(inp,ctx):
    """Prepare a selfie/photo skin on an extracted model. upload reads the operator-supplied image path, prepare
    uses value={photo,maps,crop,quad,name}, review reads its result, demo_plans records per-game gaps/locked-lead
    roulette plans after approval. Use the 3D editor to review and accept/reject. No face recognition, inferred
    3D reconstruction, automatic approval or claim of playable builds. Never put base64 photo bytes in chat."""
    import httpx
    from urllib.parse import quote
    if not ctx.server:raise ValueError('Control plane required')
    payload=inp.value
    if inp.op=='upload':
        from PIL import Image
        path=Path(inp.path)
        if path.stat().st_size>MAX_PHOTO:raise ValueError('Photo exceeds 8 MiB')
        raw=path.read_bytes();im=Image.open(io.BytesIO(raw))
        mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}.get(im.format)
        if not mime:raise ValueError('Use JPEG, PNG or WebP')
        payload={'data_url':'data:'+mime+';base64,'+base64.b64encode(raw).decode(),'source_kind':inp.value.get('source_kind','photo')}
        path='/api/photo-skins/photos'
    elif inp.op=='prepare':path='/api/characters/'+quote(inp.character,safe='')+'/photo-skins'
    elif inp.op in ('review','demo_plans'):
        path='/api/photo-skins/'+quote(inp.review,safe='')+('/demo-plans' if inp.op=='demo_plans' else '')
    else:raise ValueError('Use upload, prepare, review or demo_plans')
    r=(httpx.get(ctx.server+path,headers=ctx.headers,timeout=120) if inp.op=='review' else
       httpx.post(ctx.server+path,headers=ctx.headers,json=payload,timeout=120))
    r.raise_for_status();return {'result':r.json()}

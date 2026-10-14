"""Experimental color-map enhancement: prepare an immutable candidate; only explicit approval creates a donor."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import time
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from .registry import tool, Unsupported
from .models import Permission as P


class TextureIn(BaseModel):
    character: str
    size: Literal[1024, 2048, 4096] = 1024
    preset: Literal['conservative', 'smooth', 'detail'] = 'conservative'
    backend: Literal['ai', 'resample'] = 'ai'
    model: str = 'RealESRGAN_x4plus.safetensors'
    maps: list[int] = Field(default_factory=list,max_length=128)


class TextureOut(BaseModel):
    result: dict


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def upscalers(base):
    r=httpx.get(base+'/object_info/UpscaleModelLoader',timeout=5);r.raise_for_status()
    spec=r.json()['UpscaleModelLoader']['input']['required']['model_name']
    return spec[0] if isinstance(spec[0],list) else spec[1].get('options',[]) if len(spec)>1 else []


def ai_upscale(image, base, model, progress=lambda *_:None):
    """Use the installed local ComfyUI upscaler. Never silently substitute a resize for AI."""
    payload=png(image.convert('RGB'))
    r=httpx.post(base+'/upload/image',files={'image':('gbox-'+hashlib.sha256(payload).hexdigest()+'.png',payload,'image/png')},timeout=30)
    r.raise_for_status();uploaded=r.json()
    source='/'.join(p for p in (uploaded.get('subfolder',''),uploaded['name']) if p)
    workflow={'1':{'class_type':'LoadImage','inputs':{'image':source}},
              '2':{'class_type':'UpscaleModelLoader','inputs':{'model_name':model}},
              '3':{'class_type':'ImageUpscaleWithModel','inputs':{'upscale_model':['2',0],'image':['1',0]}},
              '4':{'class_type':'SaveImage','inputs':{'images':['3',0],'filename_prefix':'gbox_texture_review'}}}
    reply=httpx.post(base+'/prompt',json={'prompt':workflow},timeout=30);reply.raise_for_status();data=reply.json()
    if data.get('node_errors') or not data.get('prompt_id'):
        raise RuntimeError('ComfyUI rejected the upscaling graph: '+str(data)[:400])
    prompt=data['prompt_id'];end=time.monotonic()+900
    while time.monotonic()<end:
        progress('AI upscaling with '+model)
        r=httpx.get(base+'/history/'+prompt,timeout=15);r.raise_for_status();history=r.json().get(prompt)
        if history:
            status=history.get('status',{})
            if status.get('status_str')=='error':
                raise RuntimeError('AI enhancement failed: '+str(status.get('messages',[]))[-600:])
            images=history.get('outputs',{}).get('4',{}).get('images',[])
            if images and status.get('completed',True):
                response=httpx.get(base+'/view',params=images[0],timeout=60);response.raise_for_status()
                from PIL import Image
                im=Image.open(io.BytesIO(response.content));im.load();return im.convert('RGB')
        time.sleep(1)
    # Remove only this review's pending prompt; never cancel another user's active AI job.
    try:
        queue=httpx.get(base+'/queue',timeout=5);queue.raise_for_status()
        if any(row[1]==prompt for row in queue.json().get('queue_pending',[])):
            httpx.post(base+'/queue',json={'delete':[prompt]},timeout=5).raise_for_status()
    except httpx.HTTPError:
        pass
    raise TimeoutError('AI enhancement did not complete within 15 minutes (prompt '+prompt+'); no candidate was approved. Check the local AI queue before retrying.')


def enhance(image, settings, upscale):
    from PIL import Image, ImageFilter
    original=image.convert('RGBA')
    if original.width*original.height>16_777_216:
        raise ValueError('Source map exceeds 16 megapixels')
    factor=settings.size/max(original.size)
    dimensions=tuple(max(1,round(v*factor)) for v in original.size)
    base=original.convert('RGB').resize(dimensions,Image.Resampling.LANCZOS)
    if settings.backend=='resample':
        result=base
    else:
        result=original.convert('RGB')
        limit=min(settings.size,2048)
        if max(result.size)>limit:
            result=result.resize(tuple(max(1,round(v*limit/max(result.size))) for v in result.size),Image.Resampling.LANCZOS)
        first=True
        while first or max(result.size)<settings.size:
            first=False
            before=max(result.size);result=upscale(result)
            if max(result.size)<=before:
                raise ValueError('AI upscaler did not increase the image resolution')
            if result.width*result.height>67_108_864:
                raise ValueError('AI output exceeded the 64 megapixel intermediate budget')
        result=result.resize(dimensions,Image.Resampling.LANCZOS)
        strength={'conservative':.35,'smooth':.5,'detail':.8}[settings.preset]
        result=Image.blend(base,result,strength)
    if settings.preset=='smooth':
        result=result.filter(ImageFilter.SMOOTH)
    elif settings.preset=='detail':
        result=result.filter(ImageFilter.UnsharpMask(radius=1,percent=60,threshold=3))
    result=result.convert('RGBA')
    # The AI sees RGB only: never invent opacity or turn masked edges black.
    result.putalpha(original.getchannel('A').resize(dimensions,Image.Resampling.LANCZOS))
    return result


def prepare(src, settings, upscale, emit, progress=lambda *_:None):
    from PIL import Image
    from . import attachments as A
    gl,blob=A.pack(Path(src))
    original=hashlib.sha256(A.glb_bytes(copy.deepcopy(gl),blob)).hexdigest()
    images=set();references=[]
    for material in gl.get('materials',[]):
        for tex in [material.get('pbrMetallicRoughness',{}).get('baseColorTexture'),material.get('emissiveTexture')]:
            if tex:
                texture=gl['textures'][tex['index']]
                if 'source' in texture:
                    images.add(texture['source']);references.append((tex,tex['index'],texture['source']))
    if not images:
        raise ValueError('This model has no editable base-color or emissive maps')
    if settings.maps:
        if set(settings.maps)-images:raise ValueError('Selected map is not an editable color map')
        images=set(settings.maps)
    if len(images)>128:
        raise ValueError('Select at most 128 color maps at a time')
    rows=[];out=bytearray(blob)
    for k,index in enumerate(sorted(images)):
        image=copy.deepcopy(gl['images'][index]);view=gl['bufferViews'][image['bufferView']]
        raw=blob[view.get('byteOffset',0):view.get('byteOffset',0)+view['byteLength']]
        source=Image.open(io.BytesIO(raw));source.load()
        progress(k,len(images),f'Enhancing map {k+1}/{len(images)}')
        result=enhance(source,settings,upscale)
        before,after=png(source.convert('RGBA')),png(result)
        if len(out)+len(after)>256*1024*1024:
            raise ValueError('Candidate exceeds 256 MB; choose fewer maps or a lower resolution')
        before_sha,after_sha=emit(f'texture-{index}-before.png',before,'image/png'),emit(f'texture-{index}-after.png',after,'image/png')
        out.extend(bytes(-len(out)%4));offset=len(out);out.extend(after)
        image.pop('uri',None);image['bufferView']=len(gl['bufferViews']);image['mimeType']='image/png'
        gl['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(after)})
        new_image=len(gl['images']);gl['images'].append(image);textures={}
        for reference,old_texture,source_index in references:
            if source_index!=index:continue
            if old_texture not in textures:
                textures[old_texture]=len(gl['textures']);gl['textures'].append({**gl['textures'][old_texture],'source':new_image})
            reference['index']=textures[old_texture]
        rows.append({'index':index,'before':before_sha,'after':after_sha,'original_size':list(source.size),
                     'size':list(result.size),'alpha':'preserved from original','map':image.get('name',f'Map {index}')})
    candidate=A.glb_bytes(gl,bytes(out))
    return {'source_sha256':original,'candidate':emit('texture-candidate.glb',candidate,'model/gltf-binary'),
            'settings':settings.model_dump(),'images':rows,'status':'pending_approval',
            'notice':'Enhanced source maps; target writers may repack/downsample to native budgets. Normal/data maps are unchanged.'}


@tool('texture_review','1.0',TextureIn,TextureOut,capabilities=['assets'],permissions=[P.EXECUTE],timeout_s=3600,retries=0)
def texture_review(inp,ctx):
    """Prepare experimental 1K/2K/4K color-map previews. Never approves, overwrites a donor, builds or launches a game."""
    from . import characters as C
    root=C.library_root(ctx.config)
    try:meta=C.get(root,inp.character)
    except KeyError:meta=C._api(ctx,'GET','/api/characters/'+inp.character)
    src=C._local_or_fetch(ctx,meta,meta['model'])
    base=getattr(ctx.config,'texture_comfy_url','http://127.0.0.1:8188').rstrip('/')
    if inp.backend=='ai':
        try:models=upscalers(base)
        except Exception as e:raise Unsupported('Local AI upscaler unavailable. Start the configured ComfyUI service; resampling is a separate non-AI option.') from e
        if inp.model not in models:
            raise Unsupported('AI upscaler model is not installed: '+inp.model)
    def emit(name,data,kind):
        ctx.artifact(name,data,kind,texture_review=True,character=inp.character)
        return hashlib.sha256(data).hexdigest()
    result=prepare(src,inp,lambda im:ai_upscale(im,base,inp.model,lambda msg:ctx.progress(20,msg)),emit,
                   lambda k,n,msg:ctx.progress(5+85*k/n,msg))
    return {'result':result|{'character':inp.character,'name':meta['name']}}


class Decision(BaseModel):
    decision: Literal['accept','reject']


def register(app,auth,store,chars,submit,JobRequest):
    from fastapi import Depends,HTTPException
    from fastapi.responses import Response
    def maps(slug):
        from . import attachments as A
        K,root=chars()
        try:meta=K.get(root,slug)
        except KeyError:raise HTTPException(404,'Character missing')
        gl,blob=A.pack(Path(root)/slug/meta['model']);indices=set()
        for material in gl.get('materials',[]):
            for tex in (material.get('pbrMetallicRoughness',{}).get('baseColorTexture'),material.get('emissiveTexture')):
                if tex and 'source' in gl['textures'][tex['index']]:indices.add(gl['textures'][tex['index']]['source'])
        return gl,blob,indices
    @app.get('/api/characters/{slug}/texture-maps')
    def texture_maps(slug:str,actor=Depends(auth)):
        from PIL import Image
        gl,blob,indices=maps(slug);rows=[]
        for i in sorted(indices):
            im=gl['images'][i];v=gl['bufferViews'][im['bufferView']]
            image=Image.open(io.BytesIO(blob[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']]))
            rows.append({'index':i,'name':im.get('name',f'Map {i}'),'size':list(image.size),
                         'url':f'/api/characters/{slug}/texture-map/{i}'})
        return {'maps':rows}
    @app.get('/api/characters/{slug}/texture-map/{index}')
    def texture_map(slug:str,index:int,actor=Depends(auth)):
        gl,blob,indices=maps(slug)
        if index not in indices:raise HTTPException(404,'Color map missing')
        im=gl['images'][index];v=gl['bufferViews'][im['bufferView']]
        return Response(blob[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']],media_type=im.get('mimeType','image/png'))
    @app.post('/api/characters/{slug}/texture-review')
    def create(slug:str,body:TextureIn,actor=Depends(auth)):
        if body.character != slug:raise HTTPException(422,'Character must match the selected donor')
        K,root=chars()
        try:K.get(root,slug)
        except KeyError:raise HTTPException(404,'Character missing')
        return submit(JobRequest(tool='texture_review',input=body.model_dump(),require_os='linux'),actor)
    def view(job_id):
        job=store.get('job',job_id)
        if not job or job.get('tool')!='texture_review':raise HTTPException(404,'Texture review job missing')
        result=(job.get('output') or {}).get('result') or {}
        return job,result,store.get('texture_review',job_id) or {'state':'pending'}
    @app.get('/api/texture-reviews/{job_id}')
    def review(job_id:str,actor=Depends(auth)):
        job,result,decision=view(job_id)
        return {'job':job_id,'job_state':job['state'],'result':result,'decision':decision,
                'progress':job.get('progress') or {},'error':str(job.get('error') or '')[:800]}
    @app.post('/api/texture-reviews/{job_id}/decision')
    def decide(job_id:str,body:Decision,actor=Depends(auth)):
        from . import attachments as A
        job,result,decision=view(job_id)
        if job.get('state')!='succeeded' or not result.get('candidate'):raise HTTPException(409,'Candidate is not ready')
        if decision['state']!='pending':
            if decision['state']==body.decision+'ed' or (body.decision=='accept' and decision['state']=='accepted'):return decision
            raise HTTPException(409,'This review has already been decided')
        K,root=chars();slug=result['character']
        with store.lock:
            latest=store.get("texture_review",job_id)
            if latest and latest.get("state")!="pending":
                if latest["state"]==body.decision+"ed":return latest
                raise HTTPException(409,"This review has already been decided")
            if body.decision=='reject':
                row={'state':'rejected','character':slug,'at':time.time(),'by':str(actor)}
            else:
                meta=K.get(root,slug);gl,blob=A.pack(Path(root)/slug/meta['model'])
                if hashlib.sha256(A.glb_bytes(gl,blob)).hexdigest()!=result['source_sha256']:
                    raise HTTPException(409,'Source changed since this preview; prepare a fresh candidate')
                artifact=store.get('artifact',result['candidate']) or {}
                if (artifact.get('provenance') or {}).get('job')!=job_id:
                    raise HTTPException(409,'Candidate artifact is not owned by this review')
                data=store.read_artifact(result['candidate'])
                if not data or hashlib.sha256(data).hexdigest()!=result['candidate']:
                    raise HTTPException(409,'Candidate artifact missing or changed')
                variant=slug[:65]+'_tex_'+result['candidate'][:12];directory=Path(root)/variant
                with store.lock:
                    latest=store.get('texture_review',job_id)
                    if latest and latest.get('state')!='pending':return latest
                    directory.mkdir(parents=True,exist_ok=True)
                    (directory/'model.glb').write_bytes(data)
                    new=copy.deepcopy(meta)
                    for key in ('targets','target_files','preview_url','preview','verification','verified'):
                        new.pop(key,None)
                    new.update(slug=variant,name=meta['name']+f" · {result['settings']['size']//1024}K texture review",model='model.glb',texture_base_name=meta.get('texture_base_name',meta['name']),
                               variant_of=slug,texture_approval={'job':job_id,'source_sha256':result['source_sha256'],
                               'candidate':result['candidate'],'settings':result['settings'],'by':str(actor),'at':time.time()},
                               verification={'status':'unverified','reason':'Approved texture maps; requires in-game verification'})
                    new['files']=['model.glb']
                    preview=Path(root)/slug/'preview.png'
                    if preview.is_file():
                        (directory/'preview.png').write_bytes(preview.read_bytes());new['files'].append('preview.png')
                    K.put_meta(root,new)
                row={'state':'accepted','character':slug,'variant':variant,'name':new['name'],'at':time.time(),'by':str(actor)}
            store.put('texture_review',job_id,row)
            store.audit(actor,'character.texture_review',job_id,row)
            return row

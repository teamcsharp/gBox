"""Explicit photo/UV painting on verified resident PSO GameCube texture bytes.

No guessed pointers, model replacement, disk modification, or identity inference.
The operator selects a resident texture and one exact address; shared textures
can affect every mesh using that texture. GPU refresh is separate from RAM proof.
"""
import base64,hashlib,io,json,math,re,struct,time,uuid
from pathlib import Path
from typing import Literal
import httpx
import numpy as np
from PIL import Image,ImageChops,ImageDraw
from pydantic import BaseModel,Field,ConfigDict
from .registry import tool,Unsupported
from .models import Permission as P


def digest(data):return hashlib.sha256(data).hexdigest()


class FaceIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    op:Literal['inspect','apply','restore']='inspect'
    session_id:str
    character_class:str='HUnewearl'
    head:int=Field(default=0,ge=0,le=4)
    hair:int=Field(default=0,ge=0,le=9)
    target_kind:Literal['player','npc','all']='player'
    surface_id:str=Field(default='',pattern='^(?:[a-f0-9]{24})?$')
    x:float|None=Field(default=None,ge=0,le=1)
    y:float|None=Field(default=None,ge=0,le=1)
    window_aspect:float=Field(default=4/3,ge=.25,le=8)
    key:str=Field(default='',max_length=64)
    address:int=Field(default=0,ge=0,le=0x817fffff)
    candidate:str=Field(default='',pattern='^(?:[a-f0-9]{64})?$')


class FaceOut(BaseModel):result:dict


def upload(ctx,name,raw,kind,meta):
    response=httpx.post(ctx.server+'/api/artifacts',params={'name':name,'media_type':kind,'provenance':json.dumps(meta)},content=raw,headers=ctx.headers,timeout=15)
    response.raise_for_status();return response.json()['sha256']


def matches(ram,raw):
    if len(raw)<128 or len(set(raw))<8:return []
    found=[];offset=0
    while len(found)<9:
        pos=ram.find(raw,offset)
        if pos<0:break
        found.append(0x80000000+pos);offset=pos+len(raw)
    return found if len(found)<=8 else []


def baseline_chunk(source,row,current):
    """A face build carries native originals so editing never compounds baked photos."""
    from . import pso_gc as G
    folder=Path(source).parent
    marker=folder/'.gbox-mod.json'
    if not marker.is_file():return current
    metadata=json.loads(marker.read_text()).get('photo_faces') or {}
    if metadata.get('original_face_archive'):
        import zipfile
        if metadata['original_face_archive']!='face-originals.zip':raise ValueError('Unsupported native original archive')
        path=(folder/'face-originals.zip').resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or path.stat().st_size>128*2**20:raise ValueError('This face build is missing its bounded native originals archive')
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist())>2048:raise ValueError('Native original archive has too many entries')
            try:entry=archive.getinfo(row['id']+'.gvr')
            except KeyError as error:raise ValueError('The native face original is missing; re-download the complete build') from error
            if not 16<=entry.file_size<=256*2**10:raise ValueError('Native face original exceeds its size limit')
            original=archive.read(entry)
    elif metadata.get('original_face_dir')=='face-originals':
        path=(folder/'face-originals'/(row['id']+'.gvr')).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():raise ValueError('This face build is missing its native original; re-download the complete build')
        original=path.read_bytes()
    else:return current
    before,after=G.gvr_header(original),G.gvr_header(current)
    if len(original)!=len(current) or before!=after or original[:before['data']]!=current[:after['data']]:raise ValueError('The saved native face original does not match this build format')
    return original


def inspect(sid,ad,game,inp,ctx):
    from . import pso_gc as G,pso_face_build as B,pso_face_target as Target
    from .pso_gc_live import GC
    from .melee_models import tex_size
    m=GC(ad);m.check()
    source=game.get('_rom_path')
    if not source:raise Unsupported('The running owned PSO image path is unavailable')
    marker=Path(source).parent/'.gbox-mod.json'
    metadata=json.loads(marker.read_text()).get('photo_faces') if marker.is_file() else None
    metadata=metadata if isinstance(metadata,dict) else {}
    source_photo=metadata.get('source_photo','')
    if not isinstance(source_photo,str) or not re.fullmatch('[a-f0-9]{64}',source_photo):source_photo=''
    pinned=metadata.get('profiles') if source_photo else {}
    pinned=pinned if isinstance(pinned,dict) else {}
    if (inp.x is None)!=(inp.y is None):raise ValueError('A game point needs both x and y')
    captured=Target.capture(ad,sid,{'x':inp.x,'y':inp.y,'window_aspect':inp.window_aspect},ctx) if inp.x is not None else None
    disc=G.open_disc(source)
    try:
        surfaces=B.surface_catalog(disc)
        if inp.surface_id:surfaces=[r for r in surfaces if r['id']==inp.surface_id]
        elif not captured:
            surfaces=[r for r in surfaces if r['kind']==inp.target_kind] if inp.target_kind!='all' else surfaces
            if inp.target_kind=='player':surfaces=[r for r in surfaces if r['class_letter']==G.letter(inp.character_class) and r['head']==inp.head]
        if not surfaces:raise Unsupported('No named native face surface matches that selection')
        # The bytes actually resident in this game's MEM1 determine availability.
        ram=b''.join(ad.read_memory(0x80000000+offset,min(1024*1024,0x1800000-offset)) for offset in range(0,0x1800000,1024*1024))
        if len(ram)!=0x1800000:raise Unsupported('Incomplete PSO RAM snapshot')
        records={};rows=[]
        for surface in surfaces:
            try:
                if not surface['supported']:continue
                chunk=B.read_surface(disc,surface)
                hd=G.gvr_header(chunk)
                if hd['flags']&1 or hd['fmt'] not in (1,4,5,14):continue
                n=tex_size(hd['fmt'],hd['w'],hd['h']);raw=chunk[hd['data']:hd['data']+n]
                if not 128<=n<=131072 or len(raw)!=n:continue
                addresses=matches(ram,raw)
                if not addresses:continue
                bindings=Target.texture_binding(chunk,captured['textures']) if captured else []
                if captured and not bindings:continue
                name=surface['name'];key=uuid.uuid4().hex;original=baseline_chunk(source,surface,chunk)
                provenance={'pso_face_session':sid,'pso_face_key':key,'texture_name':name,'surface_id':surface['id']}
                chunk_sha=upload(ctx,name+'.gvr',original,'application/octet-stream',provenance)
                registered=httpx.post(ctx.server+'/api/pso/faces/inspections',json={'session_id':sid,'key':key,'chunk':chunk_sha,'surface_id':surface['id']},headers=ctx.headers,timeout=5)
                registered.raise_for_status()
                image=upload(ctx,name+'.png',G.png_bytes(G.gvr_decode(original)),'image/png',provenance)
                records[key]={'chunk':original,'original':raw,'current':raw,'addresses':addresses,'offset':hd['data'],'name':name,'chunk_sha':chunk_sha,'surface_id':surface['id']}
                profile=pinned.get(surface['id'])
                rows.append({'key':key,'name':name,'surface_id':surface['id'],'kind':surface['kind'],'class_name':surface.get('class_name'),'chunk':chunk_sha,'image':image,'addresses':addresses,'size':[hd['w'],hd['h']],'format':hd['fmt'],'bindings':bindings,'profile':profile if isinstance(profile,dict) else surface.get('profile'),'profile_source':'build' if isinstance(profile,dict) else 'default'})
                if len(rows)>=48:break
            except (ValueError,IndexError):continue
        m.check()
        if not rows:raise Unsupported('No writable native face texture from this selection is resident'+(' and verified against the clicked draw' if captured else '')+'. Enter offline gameplay or choose the correct class/NPC. No texture write was attempted.')
        work=ctx.config.data_dir/'pso-faces'/sid;work.mkdir(parents=True,exist_ok=True)
        model=info=None
        if captured:model=captured['model_path'];info=captured['evidence']
        elif inp.target_kind=='player' or inp.surface_id:
            surface=next(r for r in surfaces if r['id']==rows[0]['surface_id']);model,info=B.export_surface_reference(disc,surface,work,hair=inp.hair)
        if info and info.get('reference_face_materials'):
            for row in rows:row['reference_materials']=info['reference_face_materials']
        model_sha=upload(ctx,'pso-face-reference.glb',model.read_bytes(),'model/gltf-binary',{'pso_face_session':sid}) if model else None
        ad._pso_face_maps=records
        return {'session_id':sid,'maps':rows,'model':model_sha,'photo':source_photo,'class':inp.character_class,'head':inp.head,'hair':inp.hair,'target':info,'captured':bool(captured),
            'notice':('Captured geometry under your click, with matching native face texels. This is a static draw, not a verified actor identity. ' if captured else 'The model is an owned class/NPC reference, not the current animation. ')+('No verified 3D reference is available for this NPC; 2D native texture editing remains available. ' if not model else '')+'Choose one exact resident address. Shared textures can change other meshes. Apply is temporary; Save mapping retains edits for future face builds.'}
    finally:disc.f.close()


def apply(sid,ad,inp,ctx):
    from .pso_gc_live import GC
    from . import pso_gc as G
    GC(ad).check();row=getattr(ad,'_pso_face_maps',{}).get(inp.key)
    if not row or inp.address not in row['addresses']:raise ValueError('Inspect this live session and select one of its verified texture addresses')
    expected=row.setdefault('currents',{}).get(inp.address,row['original'])
    if ad.read_memory(inp.address,len(expected))!=expected:raise ValueError('The resident texture changed or was unloaded. Inspect again; no bytes were written')
    if inp.op=='restore':raw=row['original']
    else:
        meta=httpx.get(ctx.server+'/api/pso/faces/candidates/'+inp.candidate,params={'session_id':sid,'key':inp.key},headers=ctx.headers,timeout=5);meta.raise_for_status()
        p=meta.json()
        if p.get('session_id')!=sid or p.get('key')!=inp.key or p.get('original_gvr')!=row['chunk_sha']:
            raise ValueError('Candidate does not belong to this inspected texture and session')
        response=httpx.get(ctx.server+'/api/artifacts/'+inp.candidate,headers=ctx.headers,timeout=5);response.raise_for_status();chunk=response.content
        if digest(chunk)!=inp.candidate or len(chunk)!=len(row['chunk']) or chunk[:row['offset']]!=row['chunk'][:row['offset']]:raise ValueError('Native candidate format/header mismatch')
        raw=chunk[row['offset']:row['offset']+len(expected)]
        if chunk[row['offset']+len(expected):]!=row['chunk'][row['offset']+len(expected):]:raise ValueError('Candidate changed data outside the selected texture level')
    GC(ad).check()
    # Compare again after network IO. Never write a recycled texture allocation.
    if ad.read_memory(inp.address,len(expected))!=expected:raise ValueError('Texture allocation changed while preparing; inspect again')
    paused=False
    try:
        state=ad.query_runtime().get('state')
        if state not in ('PLAYING','PAUSED'):raise Unsupported('Cannot confirm the current emulator pause state')
        if state=='PLAYING':
            paused=True;ad.pause()
            if ad.query_runtime().get('state')!='PAUSED':raise Unsupported('The emulator did not confirm a paused texture write')
        if time.time()>=getattr(ctx,'pso_expires',float('inf')):raise ValueError('Face command expired before the texture write')
        GC(ad).check()
        if ad.read_memory(inp.address,len(expected))!=expected:raise ValueError('Texture changed before the paused write; inspect again')
        ad.write_memory(inp.address,raw)
        if ad.read_memory(inp.address,len(raw))!=raw:raise RuntimeError('Texture write readback failed; inspect before retrying')
        row['currents'][inp.address]=raw
    finally:
        if paused:ad.resume()
    return {'verified':True,'memory_verified':True,'key':inp.key,'address':inp.address,'candidate':inp.candidate,
        'restored':inp.op=='restore','notice':'Native texture bytes verified in RAM. The visible result appears when Dolphin reuploads the texture; no screenshot comparison has verified this frame.'}


@tool('pso_face','1.0',FaceIn,FaceOut,capabilities=['runtime','asset'],permissions=[P.READ,P.MEMORY_WRITE],timeout_s=180,retries=0)
def run(inp,ctx):
    """Inspect resident native PSO Plus US 3OE2 textures for the selected current class. Use the session face editor to crop, project, mask/paint and preview an existing photo; apply a reviewed native candidate or restore its exact original. No photo identity inference or ROM edit."""
    from .tools import SESSIONS
    from .pso_controls import session_lock
    ad,game=SESSIONS[inp.session_id]
    if game.get('platform')!='gamecube':raise Unsupported('Live face texture painting currently supports verified GameCube PSO Plus US 3OE2')
    with session_lock(inp.session_id):
        result=inspect(inp.session_id,ad,game,inp,ctx) if inp.op=='inspect' else apply(inp.session_id,ad,inp,ctx)
    return {'result':result}


def authorize(store,config,sid,body):
    if not isinstance(body,dict) or set(body)!={'command_id','expires','input'}:raise ValueError('Face command needs its ID, expiry and input')
    uuid.UUID(body['command_id'])
    if type(body['expires']) not in (int,float) or not time.time()<body['expires']<=time.time()+15:raise ValueError('Face command expired')
    inp=FaceIn.model_validate(body['input']|{'session_id':sid})
    if inp.op=='inspect':raise ValueError('Use the bounded pso_face inspect job before live editing')
    if 'memory_write' not in config.granted_permissions:raise PermissionError('memory_write permission required')
    session=store.get('session',sid) or {}
    if session.get('state')!='running':raise ValueError('Choose a running PSO session')
    worker=store.get('worker',session.get('worker_id') or sid.split('-')[0]) or {}
    for name in ('pso_faces.py','pso_face_build.py','pso_face_target.py','pso_gc.py','pso_gc_swap.py','tools.py','adapters.py'):
        if worker.get('build_sources',{}).get('gbox/'+name)!=digest(Path(__file__).with_name(name).read_bytes().replace(b'\r\n',b'\n')):raise ValueError('This worker needs an idle update for live face painting')
    return inp


def live(sid,body,ctx):
    if not time.time()<body.get('expires',0):raise ValueError('Face command expired before mutation')
    inp=FaceIn.model_validate(body['input']|{'session_id':sid})
    if inp.op not in ('apply','restore'):raise ValueError('Only apply/restore can use the live channel')
    if P.MEMORY_WRITE not in ctx.config.granted_permissions:raise PermissionError('memory_write permission required')
    from .registry import Ctx
    command=Ctx(ctx.config,'pso-face-'+body['command_id'],ctx.worker);command.server,command.headers=ctx.server,ctx.headers;command.pso_expires=body['expires']
    result=run(inp,command)['result']
    try:
        from . import gameplay_actions
        gameplay_actions.record(sid,{'op':'pso_face_'+inp.op,'candidate':inp.candidate,'key':inp.key,'address':inp.address},result,ctx,body['command_id'])
    except Exception:pass
    return result


class Stroke(BaseModel):
    x:float=Field(ge=0,le=1);y:float=Field(ge=0,le=1)
    radius:float=Field(default=.04,ge=.002,le=.3)
    erase:bool=True


def preview_image(chunk,photo,placement,strokes,mask=None,additional_patches=None):
    from . import pso_gc as G,pso_gc_swap as W,photo_skin
    if additional_patches and mask is None:raise ValueError('Face islands require an explicit photo mask')
    if mask is not None:
        from . import pso_face_build as B
        raw=B.paint(chunk,photo,placement.model_dump()|{'mask':mask.model_dump(),'strokes':[s.model_dump() for s in strokes],'additional_patches':additional_patches or []})
        return raw,G.png_bytes(G.gvr_decode(raw))
    hd=G.gvr_header(chunk)
    if not 0<hd['w']<=1024 or not 0<hd['h']<=1024 or hd['fmt'] not in (1,4,5,14) or hd['flags']&1:raise ValueError('Unsupported or oversized native face texture')
    original=Image.fromarray(G.gvr_decode(chunk));painted=photo_skin.project(original,photo,placement)
    mask=Image.new('L',original.size,255);draw=ImageDraw.Draw(mask)
    for s in strokes:
        x,y=s.x*mask.width,s.y*mask.height;r=s.radius*min(mask.size)
        draw.ellipse((x-r,y-r,x+r,y+r),fill=0 if s.erase else 255)
    out=Image.composite(painted,original,mask)
    candidate=bytearray(W.gvr_like(chunk,out));hd=G.gvr_header(chunk)
    # Keep untouched native blocks bit-identical, including original CMPR
    # endpoints. Only a touched compression block may quantize nearby pixels.
    changed=np.any(np.asarray(out)!=np.asarray(original),axis=2);w,h=original.size
    bw,bh=(8,8) if hd['fmt']==14 else (8,4) if hd['fmt']==1 else (4,4)
    for y in range(0,h,bh):
        for x in range(0,w,bw):
            base=hd['data']+((y//bh)*(w//bw)+x//bw)*32
            if hd['fmt']==14:
                for sub,(dx,dy) in enumerate(((0,0),(4,0),(0,4),(4,4))):
                    if not changed[y+dy:y+dy+4,x+dx:x+dx+4].any():candidate[base+sub*8:base+(sub+1)*8]=chunk[base+sub*8:base+(sub+1)*8]
            elif not changed[y:y+bh,x:x+bw].any():candidate[base:base+32]=chunk[base:base+32]
    candidate=bytes(candidate)
    return candidate,G.png_bytes(G.gvr_decode(candidate))


def routes(app,store,auth,config=None):
    from fastapi import Depends,HTTPException
    from .photo_skin import Placement
    class FaceMask(BaseModel):
        shape:Literal['ellipse','rectangle']='ellipse'
        inset:float=Field(default=0,ge=0,le=.45)
    class Preview(BaseModel):
        session_id:str;key:str;chunk:str=Field(pattern='^[a-f0-9]{64}$')
        settings:Placement
        strokes:list[Stroke]=Field(default_factory=list,max_length=4096)
        mask:FaceMask|None=None
        additional_patches:list[dict]=Field(default_factory=list,max_length=7)
    class Inspection(BaseModel):
        session_id:str;key:str=Field(pattern='^[a-f0-9]{32}$');chunk:str=Field(pattern='^[a-f0-9]{64}$')
        surface_id:str=Field(default='',pattern='^(?:[a-f0-9]{24})?$')
    class SaveRecipe(BaseModel):
        session_id:str;key:str;candidate:str=Field(pattern='^[a-f0-9]{64}$')
    @app.post('/api/pso/faces/inspections')
    def inspection(body:Inspection,actor=Depends(auth)):
        if not store.get('artifact',body.chunk):raise HTTPException(404,'Texture artifact missing')
        old=store.get('pso_face_inspection',body.key)
        if old and old!=body.model_dump():raise HTTPException(409,'Inspection identity already exists')
        store.put('pso_face_inspection',body.key,body.model_dump());return {'ok':True}
    @app.get('/api/pso/faces/candidates/{candidate}')
    def candidate_meta(candidate:str,session_id:str,key:str,actor=Depends(auth)):
        row=store.get('pso_face_candidate',session_id+':'+key+':'+candidate)
        if not row:raise HTTPException(404,'Candidate does not belong to this session inspection')
        return row
    @app.get('/api/pso/faces/photos')
    def photos(actor=Depends(auth)):
        return [{'photo':r['photo'],'label':r.get('label') or r['photo'][:8],'url':'/api/artifacts/'+r['photo']} for r in store.all('photo_source') if (store.get('artifact',r['photo']) or {}).get('provenance',{}).get('photo_skin_source')]
    @app.get('/api/pso/faces/surfaces')
    def surfaces(actor=Depends(auth)):
        if config is None:raise HTTPException(503,'Native surface catalogue is unavailable')
        from . import pso_face_build as B,pso_gc as G
        path=next((p for p in (config.cache/'gc/436e0bb84d5337d1/disc.iso',config.cache/'gc/psogc.iso') if p.is_file()),None)
        if path is None:raise HTTPException(404,'Prepare the owned GameCube PSO disc first')
        disc=G.open_disc(path)
        try:return B.surface_catalog(disc)
        finally:disc.f.close()
    @app.get('/api/pso/faces/recipes')
    def recipes(photo:str,actor=Depends(auth)):
        if not re.fullmatch('[a-f0-9]{64}',photo):raise HTTPException(422,'Choose a saved source photo')
        rows=[r for r in store.all('pso_face_recipe') if r.get('photo')==photo]
        return {'photo':photo,'profiles':{r['surface_id']:r['profile'] for r in rows},'mappings':rows}
    @app.post('/api/pso/faces/recipes')
    def save_recipe(body:SaveRecipe,actor=Depends(auth)):
        inspection=store.get('pso_face_inspection',body.key) or {}
        candidate=store.get('pso_face_candidate',body.session_id+':'+body.key+':'+body.candidate) or {}
        if inspection.get('session_id')!=body.session_id or not inspection.get('surface_id') or not candidate:
            raise HTTPException(422,'Preview a named native face surface in this session first')
        settings=candidate['settings'];surface=inspection['surface_id']
        if not (store.get('artifact',settings['photo']) or {}).get('provenance',{}).get('photo_skin_source'):
            raise HTTPException(422,'The source photo is unavailable')
        profile={**settings,'strokes':candidate.get('strokes',[]),'mask':candidate.get('mask') or {'shape':'rectangle','inset':0},'additional_patches':candidate.get('additional_patches',[])}
        row={'photo':settings['photo'],'surface_id':surface,'profile':profile,'native_original':inspection['chunk'],
             'candidate':body.candidate,'updated':time.time(),'source_session':body.session_id,'by':str(actor)}
        store.put('pso_face_recipe',settings['photo']+':'+surface,row)
        return {'saved':True,'surface_id':surface,'photo':settings['photo'],'notice':'Mapping and mask saved for future face builds. The running ROM was not rewritten.'}
    @app.post('/api/pso/faces/preview')
    def preview(body:Preview,actor=Depends(auth)):
        inspection=store.get('pso_face_inspection',body.key) or {}
        if inspection.get('session_id')!=body.session_id or inspection.get('chunk')!=body.chunk:raise HTTPException(422,'Inspect this session texture first')
        p={'pso_face_session':body.session_id,'pso_face_key':body.key}
        source=store.get('artifact',body.settings.photo) or {}
        if not source.get('provenance',{}).get('photo_skin_source'):raise HTTPException(422,'Choose a photo from Faces or upload a source photo')
        try:
            raw,image=preview_image(store.read_artifact(body.chunk),Image.open(io.BytesIO(store.read_artifact(body.settings.photo))),body.settings,body.strokes,body.mask,body.additional_patches)
        except (ValueError,OSError,np.linalg.LinAlgError) as error:raise HTTPException(422,str(error)) from error
        candidate=digest(raw)
        if not store.get('artifact',candidate):store.put_artifact(raw,'pso-face-candidate.gvr','application/octet-stream',p|{'original_gvr':body.chunk,'settings':body.settings.model_dump(),'strokes':[s.model_dump() for s in body.strokes]})
        store.put('pso_face_candidate',body.session_id+':'+body.key+':'+candidate,{'session_id':body.session_id,'key':body.key,'original_gvr':body.chunk,'candidate':candidate,'settings':body.settings.model_dump(),'strokes':[s.model_dump() for s in body.strokes],'mask':body.mask.model_dump() if body.mask else None,'additional_patches':body.additional_patches})
        view=digest(image)
        if not store.get('artifact',view):store.put_artifact(image,'pso-face-preview.png','image/png',{'pso_face_candidate':candidate})
        return {'candidate':candidate,'image':view,'native_quantized':True,'notice':'Preview decoded from the exact native encoded texture. Apply to update the selected resident game texture.'}

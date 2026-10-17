"""One-to-one Sonic 2 -> SMB1 animation alignment and exact native ROM snapshots."""
import base64,hashlib,io,json,math,threading,time
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw
from pydantic import BaseModel,Field,model_validator
from fastapi import Depends,HTTPException

WRITER_SOURCES={f'gbox/{name}':hashlib.sha256((Path(__file__).parent/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                for name in ('smb1_sprite_build.py','sprite_pair_editor.py')}


def claim_reason(worker,job,config):
    if job.get('tool')!='smb1_sprite_build' or not (job.get('input') or {}).get('candidate'):return None
    try:row=json.loads((config.data_dir/'sprite-pair-candidates'/job['input']['candidate']/'candidate.json').read_text())
    except (OSError,ValueError):return 'Sprite-pair preview is missing; create a fresh native preview.'
    if row.get('writer_sources')!=WRITER_SOURCES:return 'Sprite writer changed after this preview; prepare the edited preview again.'
    if any(worker.get('build_sources',{}).get(k)!=v for k,v in WRITER_SOURCES.items()):return 'Waiting for an idle worker to load the sprite editor writer.'
    return None


class FrameMap(BaseModel):
    clip:str=Field(default='',max_length=60,pattern='^[A-Za-z0-9_-]*$')
    frame:int=Field(default=0,ge=0,le=511)
    crop:list[float]=Field(default_factory=lambda:[0,0,1,1],min_length=4,max_length=4)
    mask:list[float]=Field(default_factory=lambda:[0,0,1,1],min_length=4,max_length=4)
    x:float=Field(default=0,ge=-32,le=32)
    y:float=Field(default=0,ge=-32,le=32)
    scale:float=Field(default=1,ge=.1,le=4)
    rotation:float=Field(default=0,ge=-180,le=180)
    flip:bool=False

    @model_validator(mode='after')
    def valid(self):
        for r in (self.crop,self.mask):
            if any(not math.isfinite(v) or not 0<=v<=1 for v in r) or r[2]-r[0]<.01 or r[3]-r[1]<.01:raise ValueError('Crop and mask need nonempty normalized rectangles')
        return self


class PairProfile(BaseModel):
    frames:dict[str,FrameMap]=Field(default_factory=dict,max_length=26)
    @model_validator(mode='after')
    def valid(self):
        if any(not k.isdigit() or int(k)>25 or str(int(k))!=k for k in self.frames):raise ValueError('Choose native Mario rows 0–25')
        return self


def transform(image,top,settings):
    from .tas_sprites import fit
    s=settings;w,h=image.size;l,t,r,b=s.crop
    cropped=image.crop((round(l*w),round(t*h),round(r*w),round(b*h)))
    if s.flip:cropped=ImageOps.mirror(cropped)
    base=fit(cropped,16,32-top)
    scaled=base.resize((max(1,round(base.width*s.scale)),max(1,round(base.height*s.scale))),Image.Resampling.NEAREST)
    rotated=scaled.rotate(s.rotation,Image.Resampling.NEAREST,expand=True)
    out=Image.new('RGBA',(16,32));out.alpha_composite(rotated,(round((16-rotated.width)/2+s.x),round(32-rotated.height+s.y)))
    mask=Image.new('L',(16,32));draw=ImageDraw.Draw(mask);l,t,r,b=s.mask
    draw.rectangle((round(l*16),max(top,round(t*32)),round(r*16)-1,round(b*32)-1),fill=255)
    import numpy as np
    a=np.array(out);a[:,:,3]=np.minimum(a[:,:,3],np.array(mask));return Image.fromarray(a)


GROUPS=[{'name':'Big Mario run','rows':[0,1,2]},{'name':'Small Mario run','rows':[12,13,14]},
 {'name':'Big Mario jump','rows':[4]},{'name':'Small Mario jump','rows':[16]},
 {'name':'Big Mario swim','rows':[5,6,7]},{'name':'Small Mario swim','rows':[17,18,19]},
 {'name':'Big Mario climb','rows':[8,9]},{'name':'Small Mario climb','rows':[20,21]},
 {'name':'Big Mario idle','rows':[11]},{'name':'Small Mario idle','rows':[23]},
 {'name':'Every native player frame','rows':list(range(26))}]


def routes(app,store,config,auth):
    from . import smb1_sprite_build as S,sprite_faces as F
    cached={};lock=threading.RLock();root=config.data_dir/'sprite-pair-candidates'
    def sources(gid):
        if gid!=S.GAME_ID:raise HTTPException(422,'The native one-to-one writer currently supports Sonic 2 into SMB1; other title pairs need their own writer')
        with lock:
            if not cached:
                from .tools import rom_path
                from .models import CatalogEntry
                from . import tas,sonic2d_sprites as D
                def path(id):
                    g=store.catalog_get(id)
                    if not g:raise HTTPException(404,'Both owned titles must be in the catalog')
                    return rom_path(CatalogEntry.model_validate(g),config)
                rom=tas.rom_bytes(path(gid));frames,source=S.sonic_frames(path(S.DONOR_ID))
                raw,meta=D.read_rom(path(S.DONOR_ID));ex=D.Extractor(raw,meta)
                cached.update(rom=rom,frames=frames,source=source,ex=ex,plans={p['name']:p for p in ex.plans('sonic')},clips={})
            return cached
    def clip(c,name):
        if name not in c['plans']:raise ValueError('Choose a decoded Sonic 2 animation')
        if name not in c['clips']:
            if len(c['clips'])>=8:c['clips'].pop(next(iter(c['clips'])))
            result=c['ex'].clip('sonic',c['plans'][name])
            if not result['images'] or len(result['images'])>512:raise ValueError('Clip exceeds the native editor frame budget')
            c['clips'][name]=result
        return c['clips'][name]
    def url(im):return 'data:image/png;base64,'+base64.b64encode(F.png(im)).decode()
    @app.get('/api/games/{gid}/sprite-pairs')
    def templates(gid:str,animation:str='walk',actor=Depends(auth)):
        c=sources(gid)
        try:
            with lock:source=clip(c,animation)
            target=F.decoded(c['rom'],gid)
            old=S.S._player_rows(c['rom'][16:32784])
            return {'game_id':gid,'donor_game_id':S.DONOR_ID,'target_size':[16,32],'groups':GROUPS,
                'target_top':[next(i//2*8 for i,t in enumerate(row) if t!=0xfc) for row in old],
                'target_frames':[url(Image.fromarray(f[0])) for f in target],
                'default_sources':[url(f) for f in c['frames']],
                'donor':{'title':'Sonic the Hedgehog 2','animation':animation,'clips':list(c['plans']),
                    'frames':[url(Image.fromarray(f)) for f in source['images']],
                    'timing':[f['duration_ms'] for f in source['index']['frames']]}}
        except (ValueError,OSError) as e:raise HTTPException(422,str(e)) from e
    class PreviewIn(BaseModel):profile:PairProfile=Field(default_factory=PairProfile)
    @app.post('/api/games/{gid}/sprite-pairs/preview')
    def preview(gid:str,body:PreviewIn,actor=Depends(auth)):
        c=sources(gid)
        try:
            with lock:
                selected={}
                for row,s in body.profile.frames.items():
                    if s.clip:
                        images=clip(c,s.clip)['images']
                        if s.frame>=len(images):raise ValueError('The selected source frame is outside this animation')
                        selected[int(row)]=Image.fromarray(images[s.frame])
                out,report,images=S.adapt(c['rom'],c['frames'],body.profile,selected)
                sha=hashlib.sha256(out).hexdigest();identity=[gid,c['source'],hashlib.sha256(c['rom']).hexdigest(),body.profile.model_dump(),WRITER_SOURCES]
                cid=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:32]
                folder=root/cid;folder.mkdir(parents=True,exist_ok=True)
                row={'id':cid,'game_id':gid,'rom_sha256':sha,'source':c['source'],'target_sha256':identity[2],
                    'profile':body.profile.model_dump(),'report':report,'created':time.time(),'writer_sources':WRITER_SOURCES}
                if not (folder/'candidate.json').exists():
                    (folder/'rom.bin').write_bytes(out);(folder/'candidate.json').write_text(json.dumps(row,indent=2))
                F.prune_candidates(root,store,keep=cid)
            decoded=F.decoded(out,gid,reference=c['rom'])
            return row|{'frames':[url(Image.fromarray(f[0])) for f in decoded]}
        except (ValueError,OSError) as e:raise HTTPException(422,str(e)) from e

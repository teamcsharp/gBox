"""Photo-to-sprite patches using native palettes and physical pattern-pixel ownership.

Shared pixels used outside a selected face mask are preserved. Preview is decoded
from the patched ROM, including shared-tile compromises, rather than a mock image.
"""
import base64
import collections
import hashlib
import io
import json
import math
import struct
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image,ImageOps,ImageDraw,ImageFilter
from pydantic import BaseModel,Field,model_validator
from fastapi import Depends,HTTPException
from fastapi.responses import FileResponse

SMB='49b6a2f65aca26a2'
SONIC=('938e4ca5b120e344','764582c25053f662')
N64=('b7aecee966090bfa','66062703301f4969')
SUPPORTED=(SMB,*SONIC,*N64)


class Layer(BaseModel):
    name:str=Field(default='Face layer',max_length=60)
    visible:bool=True
    rotation:float=Field(default=0,ge=-180,le=180)
    scale:float=Field(default=1,ge=.1,le=4)
    offset:list[float]=Field(default_factory=lambda:[0,0],min_length=2,max_length=2)
    opacity:float=Field(default=1,ge=0,le=1)
    blend:str=Field(default='normal',pattern='^(normal|multiply|screen|overlay|darken|lighten)$')
    photo:str=Field(default='',pattern='^(?:[a-f0-9]{64})?$')
    crop:list[float]|None=Field(default=None,min_length=4,max_length=4)

    @model_validator(mode='after')
    def valid(self):
        if any(not math.isfinite(v) or not -1<=v<=1 for v in self.offset):raise ValueError('Layer translation must remain in the normalized image bounds')
        if self.crop is not None and (any(not math.isfinite(v) or not 0<=v<=1 for v in self.crop) or self.crop[2]-self.crop[0]<.01 or self.crop[3]-self.crop[1]<.01):raise ValueError('Use a nonempty layer crop inside the photo')
        return self


class Projection(BaseModel):
    yaw:float=Field(default=0,ge=-60,le=60)
    pitch:float=Field(default=0,ge=-45,le=45)
    width:float=Field(default=250,ge=80,le=500)
    height:float=Field(default=210,ge=80,le=500)
    center_x:float=Field(default=0,ge=-150,le=150)
    center_y:float=Field(default=97,ge=-100,le=300)


class Mapping(BaseModel):
    crop:list[float]=Field(default_factory=lambda:[.12,.13,.70,.80],min_length=4,max_length=4)
    flip:bool=True
    opacity:float=Field(default=1,gt=0,le=1)
    feather:float=Field(default=.04,ge=0,le=.2)
    shape:str=Field(default='ellipse',pattern='^(ellipse|rectangle)$')
    # Normalized per-frame rectangles. Omitted frames use the native skin-color mask.
    rectangles:dict[str,list[float]]=Field(default_factory=dict,max_length=512)
    frames:list[int]|None=Field(default=None,max_length=512)
    layers:list[Layer]=Field(default_factory=lambda:[Layer()],min_length=1,max_length=8)
    projection:Projection=Field(default_factory=Projection)

    @model_validator(mode='after')
    def valid(self):
        for r in [self.crop,*self.rectangles.values()]:
            if len(r)!=4 or any(not math.isfinite(x) or not 0<=x<=1 for x in r) or r[2]-r[0]<.01 or r[3]-r[1]<.01:
                raise ValueError('Use nonempty crop/mask rectangles inside the image')
        if any(not k.isdigit() or int(k)>511 for k in self.rectangles):raise ValueError('Invalid native frame index')
        if self.frames is not None and (not self.frames or len(set(self.frames))!=len(self.frames) or any(i<0 or i>511 for i in self.frames)):
            raise ValueError('Choose unique native frames')
        return self


def png(im):
    b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()


def loading_preview(gid,name,meta):
    """Declare real, lazily decoded image URLs without slowing launch metadata."""
    from urllib.parse import quote
    if gid not in SUPPORTED or meta.get('writer') not in ('gbox.smb1_sprite_build','gbox.sprite_faces'):return None
    base=f'/api/builds/{quote(gid,safe="")}/{quote(name,safe="")}/native-sprite-preview/'
    character='Mario' if gid==SMB or gid in N64 else 'Sonic'
    result='Sonic adapted to NES' if meta['writer']=='gbox.smb1_sprite_build' else character+' with photo face'
    source={'name':'Sonic 2 source sprite','preview_url':base+'source.png'} if meta['writer']=='gbox.smb1_sprite_build' else (
        {'name':'Source selfie','preview_url':'/api/artifacts/'+meta['selfie_photo']} if meta.get('selfie_photo') else None)
    return {'original':{'name':character+(' original face texture' if gid in N64 else ' original sprite'),'preview_url':base+'before.png'},
            'source':source,'result':{'name':result+(' — gameplay face texture' if gid in N64 else ''),'preview_url':base+'after.png'}}


def decoded(rom,gid):
    """RGBA, physical pixel references and palette for every native player frame."""
    if gid in N64:
        from .sm64_photo_projection import atlas
        rgba=atlas(rom);return [(rgba,np.full(rgba.shape[:2],-1),None,np.zeros(rgba.shape[:2],np.uint8))]
    if gid==SMB:
        from . import tas,smb1_inventory as S
        tas.smb_identity(rom);p=rom[16:32784]
        palette=np.array([[(c>>16)&255,(c>>8)&255,c&255,255] for c in S.NES_PALETTE],dtype=np.uint8)
        colors=palette[S._area_palettes(p)['GroundPaletteData']['palettes'][4]].copy();colors[0,3]=0
        result=[]
        for row in S._player_rows(p):
            ids=np.zeros((32,16),dtype=np.uint8);refs=np.full((32,16),-1,dtype=np.int64)
            for slot,tile in enumerate(row):
                if tile==0xFC:continue
                for y in range(8):
                    for x in range(8):
                        off=32784+tile*16+y;v=((rom[off]>>(7-x))&1)|(((rom[off+8]>>(7-x))&1)<<1)
                        yy,xx=slot//2*8+y,slot%2*8+x;ids[yy,xx]=v
                        if v:refs[yy,xx]=tile*64+y*8+x
            result.append((colors[ids],refs,colors,ids))
        return result
    from . import sonic2d_sprites as D
    from .formats.sega_md import tiles_to_indices
    ex=D.Extractor(rom)
    if ex.game.key!='sonic2' or gid not in SONIC:raise ValueError('Only the owned Sonic 2 player layout is supported')
    ch=ex.chars['sonic'];pal=ex.palette('sonic');result=[]
    for f,pieces in enumerate(ch.maps):
        ps=D.piece_rects(pieces);box=D.frame_bbox(ps)
        if not box:result.append((np.zeros((1,1,4),np.uint8),np.full((1,1),-1),pal[:16],np.zeros((1,1),np.uint8)));continue
        x0,y0,x1,y1=box;ids=np.zeros((y1-y0,x1-x0),np.uint8);refs=np.full(ids.shape,-1,np.int64)
        tiles=tiles_to_indices(ch.tiles(rom,f));physical=[t for first,n in ch.dplc[f] for t in range(first,first+n)]
        for pc in reversed(ps):
            for py in range(pc['ph']):
                for px in range(pc['pw']):
                    sx=pc['pw']-1-px if pc['hf'] else px;sy=pc['ph']-1-py if pc['vf'] else py
                    tile=pc['tile']+(sx//8)*pc['h']+sy//8
                    if tile>=len(tiles) or not tiles[tile,sy%8,sx%8]:continue
                    yy,xx=pc['y']-y0+py,pc['x']-x0+px;ids[yy,xx]=tiles[tile,sy%8,sx%8]+pc['pal']*16
                    # The Sonic bank is uncompressed 4bpp; a key names one physical nibble.
                    address=ch.art+physical[tile]*32+(sy%8)*4+(sx%8)//2
                    if pc['pal']==0:refs[yy,xx]=address*2+(sx%2)
        result.append((pal[ids],refs,pal[:16],ids))
    return result


def default_rect(rgba,ids,gid):
    if gid in N64:return [.08,.04,.92,.96]
    a=np.asarray(rgba);alpha=a[:,:,3]>0
    points=np.argwhere(alpha)
    if not len(points):return None
    y0,x0=points.min(axis=0);y1,x1=points.max(axis=0)+1
    if gid==SMB:skin=(ids==2)
    else:
        r,g,b=[a[:,:,i].astype(int) for i in range(3)]
        skin=(r>g*1.2)&(g>b*1.1)&(g>75)&alpha
    skin[int(y0+(y1-y0)*.65):]=False
    # Hands can share the face palette. Keep one connected skin island rather
    # than stretching the face rectangle across every skin-colored pixel.
    remaining={tuple(p) for p in np.argwhere(skin)};components=[]
    while remaining:
        todo=[remaining.pop()];component=[]
        while todo:
            y,x=todo.pop();component.append((y,x))
            for point in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
                if point in remaining:remaining.remove(point);todo.append(point)
        components.append(component)
    points=np.asarray(max(components,key=len)) if components else np.empty((0,2))
    if len(points)<3:return None  # rolling/blank frames may not expose a face
    top,left=points.min(axis=0);bottom,right=points.max(axis=0)+1
    return [left/a.shape[1],top/a.shape[0],right/a.shape[1],bottom/a.shape[0]]


def composite(rgba,photo,mapping,rect,photos=None):
    h,w=rgba.shape[:2];x0,y0,x1,y1=[round(v*s) for v,s in zip(rect,(w,h,w,h))]
    if x1<=x0 or y1<=y0:raise ValueError('The face mask is empty at native resolution')
    mask=Image.new('L',(w,h),0);painter=ImageDraw.Draw(mask)
    getattr(painter,'ellipse' if mapping.shape=='ellipse' else 'rectangle')((x0,y0,x1-1,y1-1),fill=255)
    if mapping.feather:mask=mask.filter(ImageFilter.GaussianBlur(mapping.feather*min(x1-x0,y1-y0)))
    target=rgba[:,:,:3].astype(float);coverage=np.zeros((h,w),float)
    for layer in mapping.layers:
        if not layer.visible or not layer.opacity:continue
        chosen=(photos or {}).get(layer.photo,photo);l,t,r,b=layer.crop or mapping.crop
        src=chosen.convert('RGBA').crop((round(l*chosen.width),round(t*chosen.height),round(r*chosen.width),round(b*chosen.height)))
        if mapping.flip:src=ImageOps.mirror(src)
        lw=max(1,round((x1-x0)*layer.scale));lh=max(1,round((y1-y0)*layer.scale))
        patch=src.resize((lw,lh),Image.Resampling.LANCZOS).rotate(layer.rotation,Image.Resampling.BICUBIC,expand=True)
        pasted=Image.new('RGBA',(w,h));pasted.paste(patch,(round((x0+x1-patch.width)/2+layer.offset[0]*w),round((y0+y1-patch.height)/2+layer.offset[1]*h)))
        a=np.asarray(pasted);weight=np.asarray(mask).astype(float)/255*mapping.opacity*layer.opacity*a[:,:,3]/255
        top=a[:,:,:3].astype(float);base=target
        if layer.blend=='multiply':top=base*top/255
        elif layer.blend=='screen':top=255-(255-base)*(255-top)/255
        elif layer.blend=='overlay':top=np.where(base<128,2*base*top/255,255-2*(255-base)*(255-top)/255)
        elif layer.blend=='darken':top=np.minimum(base,top)
        elif layer.blend=='lighten':top=np.maximum(base,top)
        target=top*weight[:,:,None]+base*(1-weight[:,:,None]);coverage=np.maximum(coverage,weight)
    return target,coverage


def apply(rom,gid,photo,mapping,photos=None):
    if gid in N64:
        from .sm64_photo_projection import apply as project
        return project(rom,photo,mapping,photos)
    frames=decoded(rom,gid);selected=set(mapping.frames if mapping.frames is not None else range(len(frames)))
    if selected-set(range(len(frames))):raise ValueError('Frame is outside this ROM sprite table')
    votes=collections.defaultdict(collections.Counter);outside=set();touched=[];rectangles={}
    for i,(rgba,refs,colors,ids) in enumerate(frames):
        h,w=refs.shape;rect=mapping.rectangles.get(str(i)) or default_rect(rgba,ids,gid)
        mask=Image.new('L',(w,h),0)
        if i in selected and rect:
            x0,y0,x1,y1=[round(v*s) for v,s in zip(rect,(w,h,w,h))]
            if x1>x0 and y1>y0:
                target,weight=composite(rgba,photo,mapping,rect,photos)
                nearest=np.argmin(np.sum((target[:,:,None,:]-colors[None,None,1:,:3].astype(float))**2,axis=3),axis=2)+1
                inside=(weight>.05)&(refs>=0)&(rgba[:,:,3]>0)
                for yy,xx in np.argwhere(inside):votes[int(refs[yy,xx])][int(nearest[yy,xx])]+=1
                outside.update(int(v) for v in refs[(refs>=0)&~inside]);touched.append(i);rectangles[str(i)]=rect
                continue
        outside.update(int(v) for v in refs[refs>=0])
    output=bytearray(rom);changed=0;shared=0;conflicts=0
    for key,counts in votes.items():
        if key in outside:shared+=1;continue
        value=counts.most_common(1)[0][0];conflicts+=int(len(counts)>1)
        if gid==SMB:
            tile,cell=divmod(key,64);y,x=divmod(cell,8);off=32784+tile*16+y;bit=1<<(7-x)
            before=(output[off],output[off+8])
            for plane in (0,1):output[off+plane*8]=(output[off+plane*8]&~bit)|((value>>plane&1)<<(7-x))
            changed+=int(before!=(output[off],output[off+8]))
        else:
            off,nibble=divmod(key,2);shift=0 if nibble else 4
            if not 0x200<=off<len(output):raise ValueError('Sprite pixel escaped its ROM bank')
            before=output[off];output[off]=(before&~(15<<shift))|(value<<shift);changed+=int(before!=output[off])
    if not changed:raise ValueError('No safely owned face pixels changed; adjust the mask or select more related frames')
    if gid!=SMB:struct.pack_into('>H',output,0x18E,sum(struct.unpack('>'+str((len(output)-0x200)//2)+'H',output[0x200:]))&0xFFFF)
    return bytes(output),{'frames':touched,'rectangles':rectangles,'changed_pixels':changed,'shared_pixels_preserved':shared,
                         'shared_face_conflicts':conflicts,'native_palette':True,'mapping':mapping.model_dump()}


def routes(app,store,config,auth):
    cache={};lock=threading.RLock();root=config.data_dir/'sprite-face-candidates'
    def original(gid):
        if gid not in SUPPORTED:raise HTTPException(422,'Native face editing supports the owned SMB1, Sonic 2 and Mario 64 layouts. Other games need their own native writer.')
        with lock:
            if gid not in cache:
                from .tools import rom_path
                from .models import CatalogEntry
                from . import tas,sonic2d_sprites as D
                game=store.catalog_get(gid)
                if not game:raise HTTPException(404,'Game not in catalog')
                path=rom_path(CatalogEntry.model_validate(game),config)
                if gid in N64:
                    from .n64_rom import read
                    rom=read(path)
                else:rom=tas.rom_bytes(path) if gid==SMB else D.read_rom(path)[0]
                cache[gid]=(rom,decoded(rom,gid))
            return cache[gid]
    @app.get('/api/games/{gid}/sprite-faces')
    def templates(gid:str,frame:int=0,actor=Depends(auth)):
        rom,frames=original(gid)
        if not 0<=frame<len(frames):raise HTTPException(422,'Invalid native frame')
        rgba,refs,colors,ids=frames[frame]
        return {'game_id':gid,'frame':frame,'count':len(frames),'size':[rgba.shape[1],rgba.shape[0]],
            'image':'data:image/png;base64,'+base64.b64encode(png(Image.fromarray(rgba))).decode(),
            'rect':default_rect(rgba,ids,gid),'rom_sha256':hashlib.sha256(rom).hexdigest(),
            'projection_target':'gameplay' if gid in N64 else 'sprites',
            'boot_screen_supported':False if gid in N64 else None}

    @app.get('/api/builds/{gid}/{name}/native-sprite-preview/{filename}')
    def native_loading_image(gid:str,name:str,filename:str,actor=Depends(auth)):
        from .filemods import mod_dir
        from fastapi import Response
        if filename not in ('before.png','after.png','source.png'):raise HTTPException(404,'Native sprite preview not found')
        folder=mod_dir(config,gid,name)
        try:
            meta=json.loads((folder/'.gbox-mod.json').read_text())
            if meta.get('game_id')!=gid or not loading_preview(gid,name,meta):raise ValueError('Not a native sprite build')
            path=(folder/meta['image']).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file():raise ValueError('Build image is missing')
            if path.stat().st_size>32*1024**2:raise ValueError('Native preview exceeds the supported ROM size')
            out=path.read_bytes();rom,frames=original(gid)
            key=hashlib.sha256((gid+name).encode()+hashlib.sha256(out).digest()+hashlib.sha256(rom).digest()).hexdigest()
            with lock:
                row=store.get('sprite_loading_preview',key) or {}
                if filename not in row:
                    frame=0 if gid==SMB or gid in N64 else 1
                    rgba=frames[frame][0] if filename=='before.png' else decoded(out,gid)[frame][0]
                    if filename=='source.png':
                        if meta['writer']!='gbox.smb1_sprite_build':raise ValueError('No sprite donor for this photo build')
                        rgba=original(SONIC[0])[1][1][0]
                    im=Image.fromarray(rgba);scale=max(1,min(256//im.width,256//im.height))
                    im=im.resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST)
                    artifact=store.put_artifact(png(im),filename,'image/png',{'native_sprite_preview':True,'game_id':gid,'mod':name,
                        'output_sha256':hashlib.sha256(out).hexdigest(),'stage':filename})
                    row[filename]=artifact.sha256;store.put('sprite_loading_preview',key,row)
                data=store.read_artifact(row[filename])
            return Response(content=data,media_type='image/png',headers={'Cache-Control':'private, max-age=300'})
        except (KeyError,ValueError,OSError) as e:raise HTTPException(404,str(e)) from e
    class PreviewIn(BaseModel):
        photo:str=Field(pattern='^[a-f0-9]{64}$')
        mapping:Mapping=Field(default_factory=Mapping)
        frame:int=Field(default=0,ge=0,le=511)
    @app.post('/api/games/{gid}/sprite-faces/preview')
    def preview(gid:str,body:PreviewIn,actor=Depends(auth)):
        meta=store.get('artifact',body.photo) or {}
        if not (meta.get('provenance') or {}).get('photo_skin_source'):raise HTTPException(422,'Upload the original photo first')
        rom,frames=original(gid)
        if body.frame>=len(frames):raise HTTPException(422,'Invalid native frame')
        try:
            photo=Image.open(io.BytesIO(store.read_artifact(body.photo)));photos={}
            for layer in body.mapping.layers:
                if not layer.photo:continue
                artifact=store.get('artifact',layer.photo) or {}
                if not (artifact.get('provenance') or {}).get('photo_skin_source'):raise ValueError('Every layer needs an uploaded original photo')
                photos[layer.photo]=Image.open(io.BytesIO(store.read_artifact(layer.photo)))
            out,report=apply(rom,gid,photo,body.mapping,photos)
        except (ValueError,OSError) as e:raise HTTPException(422,str(e)) from e
        after=decoded(out,gid)[body.frame][0]
        cid=hashlib.sha256(json.dumps([gid,body.photo,body.mapping.model_dump(),hashlib.sha256(rom).hexdigest()],sort_keys=True).encode()).hexdigest()[:32]
        folder=root/cid;folder.mkdir(parents=True,exist_ok=True)
        row={'id':cid,'game_id':gid,'photo':body.photo,'source_sha256':hashlib.sha256(rom).hexdigest(),
             'rom_sha256':hashlib.sha256(out).hexdigest(),'report':report,'created':time.time(),'frame':body.frame}
        with lock:
            # Candidate directories are immutable. Repeating a live preview reuses the same bytes.
            if not (folder/'candidate.json').exists():
                (folder/'rom.bin').write_bytes(out)
                if gid in N64:
                    from . import sm64_mario as M
                    M.to_gltf(M.extract(rom,197),folder/'before.gltf')
                    M.to_gltf(M.extract(out,197),folder/'after.gltf')
                (folder/'candidate.json').write_text(json.dumps(row,indent=2))
            prune_candidates(root,store,keep=cid)
        return row|{'before':'data:image/png;base64,'+base64.b64encode(png(Image.fromarray(frames[body.frame][0]))).decode(),
                    'after':'data:image/png;base64,'+base64.b64encode(png(Image.fromarray(after))).decode(),
                    'models':{key:f'/api/games/{gid}/sprite-faces/candidates/{cid}/{key}.gltf' for key in ('before','after')} if gid in N64 else None}

    @app.get('/api/games/{gid}/sprite-faces/candidates/{cid}/{filename}')
    def model_file(gid:str,cid:str,filename:str,actor=Depends(auth)):
        import re
        if not re.fullmatch('[a-f0-9]{32}',cid) or filename not in ('before.gltf','after.gltf'):raise HTTPException(404,'Preview model not found')
        folder=root/cid
        try:row=json.loads((folder/'candidate.json').read_text())
        except (ValueError,OSError):raise HTTPException(404,'Preview expired; adjust a control to recreate it')
        if row['game_id']!=gid or not (folder/filename).is_file():raise HTTPException(404,'Preview model not found')
        return FileResponse(folder/filename,media_type='model/gltf+json')


def prune_candidates(root,store,keep):
    """Bound disposable live previews; submitted build snapshots remain pinned."""
    pinned={keep}
    for row in store.all('game_build_request'):
        candidate=(row.get('mapping') or {}).get('candidate')
        if candidate:pinned.add(candidate)
    for job in store.all('job'):
        if job.get('tool')=='photo_sprite_build':pinned.add((job.get('input') or {}).get('candidate'))
    disposable=[]
    for p in root.glob('*/candidate.json'):
        if p.parent.name in pinned:continue
        files=[p.parent/name for name in ('rom.bin','candidate.json','before.gltf','after.gltf')]
        disposable.append((p.stat().st_mtime,files,sum(f.stat().st_size for f in files if f.is_file())))
    disposable.sort(reverse=True);total=0
    for index,(_,files,size) in enumerate(disposable):
        total+=size
        if index<32 and total<=128*1024*1024:continue
        for f in files:
            if f.resolve().is_relative_to(root.resolve()) and f.is_file():f.unlink()
        try:files[0].parent.rmdir()
        except OSError:pass


class FaceBuildIn(BaseModel):
    game_id:str=Field(pattern='^[a-f0-9]{16}$')
    candidate:str=Field(pattern='^[a-f0-9]{32}$')
    request_id:str=Field(default='',pattern='^[a-f0-9]{0,32}$')
    request_number:int=Field(default=0,ge=0)


class FaceBuildOut(BaseModel):
    result:dict


from .registry import tool
from .models import Permission as P


@tool('photo_sprite_build','1.0',FaceBuildIn,FaceBuildOut,permissions=[P.EXECUTE,P.STAGE],timeout_s=180)
def build_candidate(inp,ctx):
    """Publish an explicitly selected photo/sprite preview as a portable native ROM; never launches a game."""
    from .filemods import mod_dir
    from . import build_record,characters as C
    folder=ctx.config.data_dir/'sprite-face-candidates'/inp.candidate
    row=json.loads((folder/'candidate.json').read_text());rom=(folder/'rom.bin').read_bytes()
    if row['game_id']!=inp.game_id or inp.game_id not in SUPPORTED or hashlib.sha256(rom).hexdigest()!=row['rom_sha256']:
        raise ValueError('Preview candidate identity differs; prepare a fresh preview')
    gid=inp.game_id;sha=row['rom_sha256'];name='sprite_face_'+sha[:12];out=mod_dir(ctx.config,gid,name)
    ext='.nes' if gid==SMB else '.z64' if gid in N64 else '.bin';image='Photo face '+gid+' '+sha[:10]+ext
    decoded_frames=decoded(rom,gid);picked=row['report']['frames'][:26]
    sheet=Image.new('RGBA',(8*128,math.ceil(len(picked)/8)*144),(25,25,32,255))
    for j,i in enumerate(picked):
        im=Image.fromarray(decoded_frames[i][0]);im.thumbnail((120,136),Image.Resampling.NEAREST)
        factor=max(1,min(120//im.width,136//im.height));im=im.resize((im.width*factor,im.height*factor),Image.Resampling.NEAREST)
        sheet.alpha_composite(im,((j%8)*128,(j//8)*144))
    if not (out/'.gbox-mod.json').exists():
        out.mkdir(parents=True,exist_ok=True);(out/image).write_bytes(rom);(out/'sprite-sheet.png').write_bytes(png(sheet))
        if gid in N64:
            from . import sm64_mario as M
            M.to_gltf(M.extract(rom,197),out/'mario-photo.gltf')
        title=('Super Mario Bros.' if gid==SMB else 'Super Mario 64' if gid in N64 else 'Sonic the Hedgehog 2')+' — photo face'
        meta=build_record.stamp({'name':name,'title':title,'game_id':gid,'image':image,'built':time.time(),
            'writer':'gbox.sprite_faces','selfie_photo':row['photo'],'sprite_face':row,'verified_in_game':False,
            'requests':[inp.request_number] if inp.request_number else [],'request_id':inp.request_id,
            'notes':('Original photo projected onto gameplay Mario; boot head unchanged; geometry preserved.' if gid in N64 else
                'Original source-photo pixels mapped into native sprite palettes; shared non-face pixels preserved.')},
            kind='character',job_id=ctx.job_id,build_call={'tool':'photo_sprite_build','input':inp.model_dump()})
        (out/'.gbox-mod.json').write_text(json.dumps(meta,indent=2))
    if hashlib.sha256((out/image).read_bytes()).hexdigest()!=sha:raise ValueError('Existing build bytes differ from this preview; refusing to reuse it')
    slug='sprite_photo_'+gid+'_'+sha[:10]
    C.add(C.library_root(ctx.config),slug,'Photo face — '+('Mario Bros.' if gid==SMB else 'Mario 64' if gid in N64 else 'Sonic 2'),
          [out/('mario-photo.gltf' if gid in N64 else 'sprite-sheet.png')],
          {'game_id':gid,'game_title':'Super Mario Bros.' if gid==SMB else 'Super Mario 64' if gid in N64 else 'Sonic the Hedgehog 2'},'gbox.sprite_faces',kind='character' if gid in N64 else 'sprites',
          targets={gid:[{'mod':name,'slot':'player'}]},extra={'selfie_photo':row['photo'],'tags':['selfie:'+row['photo']],
             'sprite_mapping':row['report']['mapping']})
    ctx.artifact('sprite-face-native-preview.png',png(sheet),'image/png',selfie_photo=row['photo'],game_id=gid,mod=name)
    return {'result':{'game_id':gid,'mod':name,'status':'built','rom_sha256':sha,'photo':row['photo'],'slug':slug,'verified':False}}

"""GTA III PS2 face-only photo builds on the original bodies and animations.

Face samples are projected through each native Shead geometry into its own UV
triangles. Non-head UV regions, DFFs and animation files remain intact. Palette
entries used outside the face are protected; only unused entries can receive
photo colors. The bounded writer updates all stored mip levels and verifies
every mirrored IMG copy. No mesh reduction occurs.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np
from pydantic import BaseModel,Field

from . import gta_rw as R
from .gta3_swap import mip_levels
from .models import Permission
from .registry import tool

GAME_ID='265819390074bb4e'


def sha(data):return hashlib.sha256(data).hexdigest()


def material_names(geometry):
    names=[]
    for material in geometry.first(R.MATLIST).find(R.MATERIAL):
        textures=material.find(R.TEXTURE)
        names.append(textures[0].find(R.STRING)[0].data.split(b'\0')[0].decode('ascii','replace').lower() if textures else '')
    return names


def actor_surfaces(dff):
    """Exact native head identity; do not mistake headquarters buildings for heads."""
    root,_=R.parse(dff);frames=R.frames_read(root.first(R.FRAMELIST))
    heads={i for i,f in enumerate(frames) if f['name'].casefold()=='shead'}
    if not heads:return None
    geoms=root.first(R.GEOMLIST).find(R.GEOMETRY);surfaces=[]
    for atomic in root.find(R.ATOMIC):
        fi,gi=struct.unpack_from('<II',atomic.first(R.STRUCT).data)
        geometry=R.geometry_read(geoms[gi])
        if geometry.pos is None or geometry.uv is None:continue
        matrix=frames[fi]['world']
        world=(np.c_[geometry.pos,np.ones(len(geometry.pos))]@matrix.T)[:,:3]
        normals=geometry.nrm@matrix[:3,:3].T if geometry.nrm is not None else None
        surfaces.append({'head':fi in heads,'frame':frames[fi]['name'],'pos':world,'nrm':normals,
                         'uv':geometry.uv,'tris':geometry.tris,'mat':geometry.mat,'textures':material_names(geoms[gi])})
    return surfaces if any(s['head'] for s in surfaces) else None


def triangles(surface,texture):
    for index,tri in enumerate(surface['tris']):
        material=int(surface['mat'][index]) if surface['mat'] is not None else 0
        if material<len(surface['textures']) and surface['textures'][material]==texture:
            yield tri


def raster_triangle(uv,width,height):
    """Pixel coordinates and barycentrics, including native repeating UV seams."""
    uv=np.asarray(uv,float)
    if not np.isfinite(uv).all() or np.ptp(uv,axis=0).max()>2:raise ValueError('Unsupported head UV span')
    uv=uv-np.floor(uv.mean(0))
    for sx in (-1,0,1):
        for sy in (-1,0,1):
            points=(uv+[sx,sy])*[width,height]
            left,top=np.maximum(0,np.floor(points.min(0)).astype(int))
            right,bottom=np.minimum([width-1,height-1],np.ceil(points.max(0)).astype(int))
            if right<left or bottom<top:continue
            basis=np.stack((points[1]-points[0],points[2]-points[0]),axis=1)
            if abs(np.linalg.det(basis))<1e-7:continue
            yy,xx=np.mgrid[top:bottom+1,left:right+1]
            bary=np.c_[xx.reshape(-1)+.5,yy.reshape(-1)+.5]-points[0]
            bary=bary@np.linalg.inv(basis).T;bary=np.c_[1-bary.sum(1),bary]
            keep=(bary>=-1e-6).all(1)
            if keep.any():yield yy.reshape(-1)[keep],xx.reshape(-1)[keep],bary[keep]


def project_face(original,surfaces,texture,photo,crop,opacity=1):
    """Frontal +Y head projection, protecting body and nonfacial head UV owners."""
    height,width=original.shape[:2];mask=np.zeros((height,width),bool)
    protected=np.zeros_like(mask);protected_head=np.zeros_like(mask);color=original[...,:3].astype(float).copy()
    headpoints=np.concatenate([s['pos'] for s in surfaces if s['head']])
    lower,upper=headpoints.min(0),headpoints.max(0)
    span=upper-lower
    if min(span[0],span[2])<.01:raise ValueError('Native head is degenerate')
    # Restrict the photo to the facial front; retain the upper hair/cap region.
    face_min_z=lower[2]+span[2]*.04;face_max_z=lower[2]+span[2]*.78
    photo=np.asarray(photo.convert('RGB'));ph,pw=photo.shape[:2]
    left,top,right,bottom=crop
    triangles_used=0
    for surface in surfaces:
        for tri in triangles(surface,texture):
            if not surface['head']:
                for yy,xx,_bary in raster_triangle(surface['uv'][tri],width,height):protected[yy,xx]=True
                continue
            points=surface['pos'][tri]
            if surface['nrm'] is not None:
                normal=surface['nrm'][tri].mean(0)
            else:normal=np.cross(points[1]-points[0],points[2]-points[0])
            length=np.linalg.norm(normal)
            frontal=length>=1e-8 and normal[1]/length>=.18
            # A native atlas can reuse the same pixels for hair/back-of-head
            # polygons and the face. Never recolor those shared pixels merely
            # because one of their owners is a front-facing triangle.
            if not frontal:
                for yy,xx,_bary in raster_triangle(surface['uv'][tri],width,height):protected_head[yy,xx]=True
                continue
            triangles_used+=1
            for yy,xx,bary in raster_triangle(surface['uv'][tri],width,height):
                world=bary@points
                nonface=(world[:,2]>face_max_z)|(world[:,2]<face_min_z)
                protected_head[yy[nonface],xx[nonface]]=True
                x=1-(world[:,0]-lower[0])/span[0]
                y=1-(world[:,2]-face_min_z)/(face_max_z-face_min_z)
                radius=((x-.5)/.47)**2+((y-.5)/.5)**2
                keep=(radius<1)&(x>=0)&(x<=1)&(y>=0)&(y<=1)
                if not keep.any():continue
                xx,yy,x,y,radius=xx[keep],yy[keep],x[keep],y[keep],radius[keep]
                px=np.clip(np.rint((left+x*(right-left))*(pw-1)).astype(int),0,pw-1)
                py=np.clip(np.rint((top+y*(bottom-top))*(ph-1)).astype(int),0,ph-1)
                weight=np.minimum(1,(1-radius)*12)*opacity
                color[yy,xx]=original[yy,xx,:3]*(1-weight[:,None])+photo[py,px]*weight[:,None]
                mask[yy,xx]=True
    mask&=~(protected|protected_head)
    out=original.copy();out[mask,:3]=np.clip(np.rint(color[mask]),0,255).astype(np.uint8)
    if mask.sum()<6:raise ValueError('No usable, nonoverlapping frontal face UV pixels')
    return out,mask,{'face_pixels':int(mask.sum()),'protected_body_pixels':int(protected.sum()),
                    'protected_nonfacial_head_pixels':int(protected_head.sum()),
                    'frontal_triangles':triangles_used,'head_bounds':[lower.tolist(),upper.tolist()]}


def palette_indices(pixels,palette,alpha):
    result=np.empty(len(pixels),np.uint8)
    for offset in range(0,len(pixels),2048):
        part=pixels[offset:offset+2048].astype(np.float32)
        distance=((part[:,None,:]-palette[None,:,:3].astype(np.float32))**2).sum(2)
        distance+=(alpha[offset:offset+2048,None].astype(float)-palette[None,:,3])**2*8
        result[offset:offset+len(part)]=distance.argmin(1)
    return result


def raster_projected(raster,painted,mask):
    """Preserve protected palette entries/header and every unmasked mip pixel."""
    from PIL import Image
    if raster.depth!=8:raise ValueError('Only native 8-bit paletted PS2 face rasters are supported')
    _top,palette=R.raster_indexed(raster);palette=palette.copy();data=bytearray(raster.data)
    changes=[];hdrs=bool(raster.fmt&0x20000);levels=[];protected=set()
    for start,width,height in mip_levels(raster):
        raw=np.frombuffer(raster.data,np.uint8,width*height,start).copy()
        rw,rh=struct.unpack_from('<II',raster.data,start-0x50+0x20) if hdrs else (width,height)
        swizzled=rw*rh*4==width*height and width>=16 and height>=4
        indices=raw[R._swz8_map(width,height)].reshape(height,width).copy() if swizzled else raw.reshape(height,width).copy()
        level_mask=np.asarray(Image.fromarray((mask*255).astype(np.uint8)).resize((width,height),Image.Resampling.BOX))>127
        levels.append((start,width,height,raw,indices,level_mask,swizzled))
        protected.update(int(i) for i in np.unique(indices[~level_mask]))
    # Allocate only palette entries that no unmasked pixel at any mip uses.
    # This permits the photo's own skin tones without recoloring clothing/hair.
    free=[i for i in range(256) if i not in protected and palette[i,3]>=240]
    colors=min(96,len(free),int(mask.sum()))
    if colors>=8:
        patch=Image.fromarray(painted[mask,:3].reshape(1,-1,3)).quantize(colors=colors,method=Image.Quantize.MEDIANCUT)
        new_colors=np.asarray(patch.getpalette(),np.uint8).reshape(-1,3)[:colors]
        palette[free[:colors],:3]=new_colors
        pix_bytes=struct.unpack_from('<I',raster.header,48)[0];palette_offset=pix_bytes+(0x50 if hdrs else 0)
        for i in free[:colors]:
            at=palette_offset+int(R._csm1(256)[i])*4
            data[at:at+3]=palette[i,:3].tobytes()
    else:colors=0
    for start,width,height,raw,indices,level_mask,swizzled in levels:
        target=np.asarray(Image.fromarray(painted).resize((width,height),Image.Resampling.LANCZOS))
        if level_mask.any():
            indices[level_mask]=palette_indices(target[level_mask,:3],palette,palette[indices[level_mask],3])
        encoded=indices.reshape(-1)
        if swizzled:
            value=np.empty_like(encoded);value[R._swz8_map(width,height)]=encoded;encoded=value
        data[start:start+width*height]=encoded.tobytes()
        changes.append({'width':width,'height':height,'face_pixels':int(level_mask.sum()),
                        'changed_bytes':int((raw!=encoded).sum()),'photo_palette_colors':colors})
    result=R.Ps2Raster(raster.name,raster.mask,raster.width,raster.height,raster.depth,raster.fmt,raster.header,bytes(data))
    before=R.raster_rgba(raster);after=R.raster_rgba(result)
    if not np.array_equal(before[~mask],after[~mask]):raise ValueError('An unmasked body pixel changed')
    if not np.any(before[mask]!=after[mask]):raise ValueError('Native palette cannot express a changed face')
    return result,changes


def actor_txd(dff,txd,photo,crop,opacity=1):
    surfaces=actor_surfaces(dff)
    if not surfaces:raise ValueError('Not a native rigid-head actor')
    names={name for s in surfaces if s['head'] for name in s['textures'] if name}
    root,tail=R.parse(txd);reports=[];previews=[]
    for native in root.find(R.TEXNATIVE):
        raster=R.texnative_read(native)
        if raster.name.casefold() not in names:continue
        if re.search(r'(^|_)(band|hat|hair|glasses|helmet|cap)($|_)',raster.name.casefold()):continue
        original=R.raster_rgba(raster)
        painted,mask,meta=project_face(original,surfaces,raster.name.casefold(),photo,crop,opacity)
        encoded,mips=raster_projected(raster,painted,mask)
        R.texnative_replace_data(native,encoded)
        reports.append({'texture':raster.name,'width':raster.width,'height':raster.height,'depth':raster.depth,
                        'mips':mips,**meta,'unmasked_pixels_unchanged':True,
                        'protected_palette_entries_unchanged':True,'photo_palette_colors':mips[0]['photo_palette_colors']})
        previews.append((raster.name,original,R.raster_rgba(encoded),mask))
    if not reports:raise ValueError('No matching editable native head material in this texture bank')
    written=root.to_bytes()+tail
    if len(written)!=len(txd):raise ValueError('Native texture bank size changed')
    return written,reports,previews


def head_snapshots(dff,previews,size=192):
    """Actual native head geometry/UVs, with only the texture changing across frames."""
    from PIL import Image
    from .photo_story import render_frames
    textures={name.casefold():(Image.fromarray(before),Image.fromarray(after)) for name,before,after,_mask in previews}
    geometry=[];maps=list(textures.values())
    for surface in actor_surfaces(dff):
        if not surface['head']:continue
        for texture,(before,after) in textures.items():
            for tri in triangles(surface,texture):
                points=surface['pos'][tri][:,[0,2,1]].copy();points[:,0]*=-1
                geometry.append((points,surface['uv'][tri],before,(255,255,255)))
    return render_frames(geometry,maps,[[0,0],[1,0],[1,1],[0,1]],size=size)


def inventory(disc):
    """All actual rigid-head actor models, including special/cutscene cast banks."""
    actors=[];unreadable=[]
    for name in disc.index:
        if not name.endswith('.dff'):continue
        try:surfaces=actor_surfaces(disc.entry(name))
        except (ValueError,StopIteration,struct.error,IndexError) as error:
            # Some placeholder DFFs (8ball.dff) are not a clump at all.
            unreadable.append({'model':name,'reason':type(error).__name__});continue
        if surfaces:
            texture=name[:-4]+'.txd'
            actors.append({'model':name,'txd':texture if texture in disc.index else None,
                'head_materials':sorted({n for s in surfaces if s['head'] for n in s['textures'] if n}),
                'dff_sha256':sha(disc.entry(name))})
    return actors,unreadable


def compact_previews(source,dest,rows):
    """Eight complete contact sheets and three standalone stories, not 1,000 launch files.

    Exhaustive originals stay in the work folder. Non-representative metadata
    references a sheet rectangle; consumers must crop that rectangle explicitly.
    """
    from PIL import Image,ImageDraw
    source,dest=Path(source),Path(dest);representatives={'player','cop','eight'}
    if source.resolve()==dest.resolve() and not dest.name.startswith('.'):
        raise ValueError('In-place preview compaction is allowed only in an unpublished staging folder')
    built=[r for r in rows if r.get('face_previews') and r.get('face_snapshots')]
    cols=8;count=(len(built)+cols-1)//cols;refs={}
    folder=dest/'previews';folder.mkdir(parents=True,exist_ok=True)
    for kind in ('before','after','mask',0,.25,.5,.75,1):
        atlas=isinstance(kind,str);size=256 if atlas else 128;stride=size+20
        sheet=Image.new('RGB',(cols*size,32+count*stride),'#181b23');draw=ImageDraw.Draw(sheet)
        label='Native face atlases '+kind if atlas else 'Native original heads — photo texture '+str(round(kind*100))+'%'
        draw.text((6,8),label,fill='white')
        filename='face-atlases-'+kind+'.png' if atlas else 'native-heads-'+str(round(kind*100))+'.png'
        for i,row in enumerate(built):
            relative=row['face_previews'][0][kind] if atlas else next(f['path'] for f in row['face_snapshots'] if f['fraction']==kind)
            x,y=i%cols*size,32+i//cols*stride
            with Image.open(source/relative) as image:sheet.paste(image.convert('RGB').resize((size,size),Image.Resampling.NEAREST),(x,y))
            draw.text((x+4,y+size+3),row['model'][:-4],fill='white')
            refs[(row['model'],kind)]={'path':(Path('previews')/filename).as_posix(),'rect':[x,y,size,size]}
            if row['model'][:-4] in representatives:
                target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True)
                if source.resolve()!=dest.resolve():shutil.copyfile(source/relative,target)
        sheet.save(folder/filename)
    for row in rows:
        if row not in built:continue
        if row['model'][:-4] in representatives:continue
        row['face_previews']=[{'texture':row['face_previews'][0]['texture'],
            **{k:refs[row['model'],k]['path'] for k in ('before','after','mask')},
            'sheet_rect':refs[row['model'],'before']['rect'],'presentation':'Crop sheet_rect; full per-actor originals retained in analysis work directory'}]
        row['face_snapshots']=[{'fraction':f,'kind':'texture_projection',**refs[row['model'],f]} for f in (0,.25,.5,.75,1)]
    if source.resolve()==dest.resolve():
        # Only generated per-actor files under this private staging directory.
        # Work artifacts were copied before compaction; published builds are never edited.
        for actor in folder.iterdir():
            if not actor.is_dir() or actor.name in representatives:continue
            for file in actor.iterdir():
                if file.is_file() and file.suffix=='.png':file.unlink()
            if not any(actor.iterdir()):actor.rmdir()
    return {'contact_sheets':8,'standalone_actors':sorted(representatives),'complete_actors':len(built)}


def build(cfg,base,photo,photo_sha,name,crop=(.22,.035,.79,.7),opacity=1,progress=None):
    from PIL import Image
    from . import filemods,gta3_inventory,build_record
    progress=progress or (lambda pct,msg:None)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',name):raise ValueError('Build name must be one safe folder name')
    if len(crop)!=4 or not 0<=crop[0]<crop[2]<=1 or not 0<=crop[1]<crop[3]<=1:raise ValueError('Choose a nonempty normalized face crop')
    base=Path(base)
    with base.open('rb') as stream:source_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    if source_sha!=gta3_inventory.ISO_SHA256:raise ValueError('Face takeover requires the exact owned unmodified GTA III PS2 image')
    out=filemods.mod_dir(cfg,GAME_ID,name)
    if out.exists():raise ValueError('This build name already exists; choose a unique name to preserve existing builds')
    staged=out.parent/('.'+name+'-'+__import__('uuid').uuid4().hex[:10]);staged.mkdir(parents=True)
    work=Path(cfg.cache)/'characters_build'/name;work.mkdir(parents=True,exist_ok=True)
    source=R.GtaDisc(base);actors,unreadable=inventory(source);rows=[];changes=[]
    try:
        # Each bank is staged independently; do not hold all atlas/archive data in RAM.
        for index,actor in enumerate(actors):
            progress(5+45*index/max(1,len(actors)),f'Projecting Bla onto native {actor["model"]} face UVs')
            row=dict(actor)
            try:
                if not actor['txd']:raise ValueError('Actor texture bank is missing')
                original=source.entry(actor['txd'])
                dff=source.entry(actor['model'])
                encoded,report,previews=actor_txd(dff,original,photo,crop,opacity)
                path=work/actor['txd'];path.write_bytes(encoded)
                changes.append((actor['txd'],path,sha(original),sha(encoded)))
                row.update(status='built',textures=report,new_txd_sha256=sha(encoded),source_txd_sha256=sha(original))
                row['face_previews']=[]
                for texture,before,after,mask in previews:
                    preview=Path('previews')/actor['model'][:-4]/texture
                    (staged/preview.parent).mkdir(parents=True,exist_ok=True)
                    refs={}
                    for label,pixels in (('before',before),('after',after),('mask',(mask*255).astype(np.uint8))):
                        relative=preview.with_name(preview.name+'-'+label+'.png')
                        Image.fromarray(pixels).save(staged/relative)
                        refs[label]=relative.as_posix()
                    row['face_previews'].append({'texture':texture,**refs})
                row['face_snapshots']=[]
                try:
                    for fraction,png in head_snapshots(dff,previews):
                        relative=Path('previews')/actor['model'][:-4]/('head-'+str(round(fraction*100))+'.png')
                        (staged/relative).write_bytes(png)
                        row['face_snapshots'].append({'fraction':fraction,'path':relative.as_posix(),'kind':'texture_projection'})
                except ValueError as error:row['preview_notice']=str(error)
            except (ValueError,NotImplementedError,IndexError,struct.error) as error:row.update(status='unsupported',reason=str(error))
            rows.append(row)
        if not changes:raise ValueError('No native actor faces could be mapped safely')
        progress(55,'Copying the verified original image; native geometry and animations stay intact')
        image=base.name;shutil.copyfile(base,staged/image)
        target=R.GtaDisc(staged/image,writable=True)
        try:
            writes=[]
            for index,(entry,path,_old,_new) in enumerate(changes):
                writes.append(target.replace(entry,path.read_bytes()))
                progress(65+20*index/len(changes),f'Writing {entry} into {len(target.imgs)} native IMG copies')
        finally:target.close()
        target=R.GtaDisc(staged/image)
        try:
            for entry,path,old,want in changes:
                if any(sha(target.entry(entry,copy))!=want for copy in range(len(target.imgs))):raise ValueError('A mirrored native texture bank failed hash read-back')
            if any(sha(target.entry(row['model']))!=row['dff_sha256'] for row in actors):raise ValueError('An original actor mesh changed')
            for entry in ('SLUS_200.62','ANIM/PED.IFP','ANIM/CUTS.IMG','ANIM/CUTS.DIR'):
                if sha(source.read_file(entry))!=sha(target.read_file(entry)):raise ValueError('Original executable/animations changed')
            copies=len(target.imgs)
        finally:target.close()
    finally:source.close()
    # Preserve exhaustive review files outside the downloadable game tree.
    for row in rows:
        for group in (row.get('face_previews',[]),row.get('face_snapshots',[])):
            for entry in group:
                for key in ('before','after','mask','path'):
                    if entry.get(key):
                        relative=Path(entry[key]);target=work/relative;target.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(staged/relative,target)
    presentation=compact_previews(staged,staged,rows)
    built=sum(r['status']=='built' for r in rows)
    coverage={'native_rigid_head_actors':len(actors),'faces_built':built,'complete':built==len(actors),
        'unsupported':[r for r in rows if r['status']!='built'],
        'scope':'Native rigid-head player outfits, pedestrians and special/cutscene cast; original bodies and animations',
        'cutscene_animation_archive':'unchanged; actor models and texture banks are streamed from GTA3.IMG',
        'prerecorded_movies':False,'all_cutscenes_visually_verified':False}
    photo.convert('RGB').save(staged/'source-photo.png')
    from PIL import ImageDraw
    selected=[row for row in rows if row['model'][:-4] in ('player','cop','eight') and row.get('face_snapshots')]
    contact=Image.new('RGB',(max(1,min(4,len(selected)))*192,214+28),'#181b23');draw=ImageDraw.Draw(contact)
    draw.text((6,6),'Bla face on original native heads; texture projection, geometry unchanged',fill='white')
    for i,row in enumerate(selected):
        x,y=i%4*192,28+i//4*214
        with Image.open(staged/row['face_snapshots'][-1]['path']) as thumb:contact.paste(thumb.convert('RGB'),(x,y))
        draw.text((x+5,y+195),row['model'][:-4],fill='white')
    contact.save(staged/'preview.png')
    marker={'name':name,'title':'GTA III — Bla faces on original cast and pedestrians','game_id':GAME_ID,'image':image,'built':time.time(),
        'writer':'gbox.gta3_face_takeover','files':['MODELS/GTA3.IMG'],'source_iso_sha256':source_sha,
        'selfie_photo':photo_sha,'donor_name':'Bla face','donor_photo_sha256':photo_sha,
        'geometry':'original bodies, skeletons and animations unchanged',
        'cast':[{'slot':r['model'][:-4],'target_name':r['model'][:-4],'donor':'Bla face',
                 'donor_name':'Bla face','donor_photo_sha256':photo_sha,'replacement_scope':'face texture only',
                 'face_previews':r.get('face_previews',[]),'face_snapshots':r.get('face_snapshots',[]),
                 'status':r['status'],'reason':r.get('reason','')} for r in rows],
        'coverage':coverage,'face_uv_profiles':rows,'source_placeholders':unreadable,'presentation':presentation,
        'validation':{'native_texture_banks_read_back':True,'img_copies':copies,'all_dff_unchanged':True,
            'executable_and_animations_unchanged':True,'unmasked_pixels_and_protected_palette_entries_unchanged':True,'gameplay_verified':False},
        'photo_mapping':{'crop':list(crop),'opacity':opacity,'method':'native frontal head triangles, barycentric UV projection, body and nonfacial head UV protected'}}
    marker.update(tags=['selfie:'+photo_sha,'face-only','original-bodies'],previews=['preview.png','source-photo.png'],
        photo_faces={'version':1,'source_photo':photo_sha,'source_image':'source-photo.png','coverage_file':'face-coverage.json',
                     'geometry_unchanged':True,'verification':'unverified_in_game','tag':'selfie:'+photo_sha,
                     'previews':[{'before':r['face_snapshots'][0]['path'],'after':r['face_snapshots'][-1]['path'],
                                  'label':{'player':'Claude','cop':'Police officer','eight':'8-Ball'}[r['model'][:-4]]}
                                 for r in rows if r['model'][:-4] in ('player','cop','eight') and r.get('face_snapshots')]})
    marker=build_record.stamp(marker,kind='cast',slots=[{'slot':r['model'][:-4],'slot_name':r['model'][:-4],
        'donor':'Bla face','donor_name':'Bla face','source':photo_sha} for r in rows if r['status']=='built'],
        verified_in_game=False,replacement_scope={'gameplay':str(len(actors))+' native rigid-head actor banks; original bodies',
            'supporting_cast':'native special and cutscene heads in GTA3.IMG','prerecorded_cinematics':'unchanged'})
    (staged/'face-coverage.json').write_text(json.dumps(coverage|{'actors':rows},indent=2))
    (staged/'.gbox-mod.json').write_text(json.dumps(marker,indent=2))
    staged.replace(out)
    (work/'coverage.json').write_text(json.dumps(marker,indent=2))
    progress(100,f'Built {built}/{len(actors)} original-body face overlays; native gameplay review pending')
    return {'mod':name,'dir':str(out),'image':image,'coverage':coverage,'validation':marker['validation'],'preview_dir':str(work)}


class FacesIn(BaseModel):
    game_id:str=GAME_ID
    photo:str=Field(pattern='^[a-f0-9]{64}$')
    name:str=Field(pattern='^[a-zA-Z0-9_-]{1,100}$')
    crop:list[float]=Field(default_factory=lambda:[.22,.035,.79,.7],min_length=4,max_length=4)
    opacity:float=Field(default=1,gt=0,le=1,allow_inf_nan=False)


class FacesOut(BaseModel):
    result:dict


@tool('gta3_faces','1.0',FacesIn,FacesOut,capabilities=['asset','build'],permissions=[Permission.READ,Permission.STAGE],timeout_s=1800,retries=0)
def gta3_faces(inp,ctx):
    """Build GTA III PS2 face-only takeover: project the selected registered selfie onto
    each native rigid head, retain every original body/rig/animation and unmasked
    texture pixel. The exact owned base is required. Reports per-actor coverage,
    mirrored-archive read-back and pending native gameplay verification honestly.
    """
    import httpx
    from PIL import Image
    from . import characters,filemods
    from .gta3_swap import iso_from_rom
    if inp.game_id!=GAME_ID:raise ValueError('This writer supports the owned GTA III PS2 SLUS-20062 build')
    if not ctx.server:raise ValueError('Connect to Spark for the registered selfie source')
    response=httpx.get(ctx.server+'/api/artifacts/'+inp.photo,headers=ctx.headers,timeout=15);response.raise_for_status()
    raw=response.content
    if len(raw)>8<<20:raise ValueError('Photo exceeds 8 MiB')
    if sha(raw)!=inp.photo:raise ValueError('Photo artifact failed hash verification')
    game=characters._api(ctx,'GET','/api/catalog/'+GAME_ID)
    base=iso_from_rom(characters._rom(ctx,game),filemods.base_dir(ctx.config,GAME_ID)/'Grand Theft Auto III (USA, Canada).iso',ctx.progress)
    photo=Image.open(io.BytesIO(raw));photo.load()
    return {'result':build(ctx.config,base,photo,inp.photo,inp.name,inp.crop,inp.opacity,ctx.progress)}

"""Native, texture-only PSO photo faces. Original bodies, meshes and rigs remain intact.

Named face surfaces are catalogued explicitly; unrelated ears, hair, costume maps
and secondary glow maps are never selected by a generic whole-atlas replacement.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import struct
import time
import uuid
import zipfile
from typing import Literal

import numpy as np
from PIL import Image,ImageChops,ImageDraw,ImageFilter
from pydantic import BaseModel,Field,ConfigDict

from . import pso_gc as G,pso_gc_swap as W

ANDROID=set('CEFJ')
DEFAULT_CROP=[.22,.08,.76,.70]
MAX_CONTAINER=64*1024**2
MAX_ORIGINAL=256*1024
# These mixed head/body maps were inspected on the owned GPOE8P source. Only
# the face/visor islands below are painted; clothing and hair remain original.
ATLAS_FACE_BOXES={
    'pxtUh_00z_t_head':[(.50,.25,.99,.51)],
    'pxtVh_00z_t_head':[(.01,.25,.49,.49)],
    'pxtWh_00z_t_head':[(.01,.25,.49,.51)],
    'pxtYh_00z_t_head':[(.06,.75,.41,.99)],
    's256_nights':[(.79,.19,.995,.405),(.78,.46,.995,.675)],
    'al_eye01':[(.18,.18,.82,.82)],
}
HUMANOID_ANDROID_BOXES={
    # HUcaseal's five heads use different UV islands; keep helmet/hair regions.
    0:(.42,.03,.98,.66),1:(.24,.12,.76,.90),2:(.48,.34,.99,.98),
    3:(.34,.06,.99,.98),4:(.51,.51,.99,.98),
}


class Stroke(BaseModel):
    x:float=Field(ge=0,le=1)
    y:float=Field(ge=0,le=1)
    radius:float=Field(default=.04,ge=.002,le=.3)
    erase:bool=True


def sha(raw):return hashlib.sha256(raw).hexdigest()


def _names(disc,letter):
    """Read named AFS entries for normal and extra NPC player-bank slots."""
    standard=G.tables(disc).get(letter)
    if standard:return standard['afs']
    dol=G.Dol(disc.read('PsoV3.dol'))
    for address in dol.find_strings(f'PL{letter}TEX.AFS'):
        for ref in dol.data_refs(address):
            try:
                count,pointer=dol.u32(ref-4),dol.u32(ref+4)
                if 0<count<4096:return [dol.cstr(dol.u32(pointer+4*i)) for i in range(count)]
            except (ValueError,UnicodeDecodeError):continue
    return []


def _face_name(name):
    low=name.lower()
    if name in ATLAS_FACE_BOXES:return True
    if any(word in low for word in ('mimi','hair','kami','glass','glow','huku','body','te1')):return False
    # kao2/3 are ears, glowing eyes or separate helmet details in these native
    # banks. A primary face map is kao/kao1, or an explicitly named NPC face.
    return bool(re.search(r'(?:_kao1?$|_face\d*$)',low))


def _native_kind(path):
    if re.fullmatch(r'n_[A-Z]\d\d.*\.gvm',path,re.I):return 'gvm'
    if re.fullmatch(r'bm_(?:ene_)?npc_.*\.bml',path,re.I):return 'bml'
    return None


def _gsl_index(disc,path):
    """Read only a bounded archive table, not every area's packed data."""
    base,size=disc.files[path]
    data=disc._r(base,min(size,4096*0x30)) if hasattr(disc,'_r') else disc.read(path)[:4096*0x30]
    rows=[]
    for i in range(min(4096,len(data)//0x30)):
        name=data[i*0x30:i*0x30+0x20].split(b'\0')[0]
        if not name:return rows
        off,n=struct.unpack_from('>II',data,i*0x30+0x20);off*=0x800
        if off+n>size:raise ValueError('NPC GSL entry runs past its native archive')
        rows.append((name.decode('latin-1'),off,n))
    raise ValueError('NPC GSL table exceeds 4096 entries')


def _containers(disc):
    """(disc path, optional archive entry, kind, size), including area copies."""
    for path,(_offset,size) in sorted(disc.files.items()):
        kind=_native_kind(path)
        if kind:yield path,None,kind,size
        if path.lower().endswith('.gsl'):
            for entry,_off,n in _gsl_index(disc,path):
                kind=_native_kind(entry)
                if kind:yield path,entry,kind,n


def _container_bytes(disc,locator):
    path=locator['path'];entry=locator.get('archive_entry')
    if not entry:
        if disc.files[path][1]>MAX_CONTAINER:raise ValueError('NPC container exceeds 64 MiB')
        return disc.read(path)
    for name,offset,size in _gsl_index(disc,path):
        if name==entry:
            if size>MAX_CONTAINER:raise ValueError('NPC container exceeds 64 MiB')
            if hasattr(disc,'_r'):return disc._r(disc.files[path][0]+offset,size)
            return disc.read(path)[offset:offset+size]
    raise ValueError('NPC archive entry is no longer on this disc')


def default_profile(letter='',head=0,android=False):
    # Each original human face is its own map, not a costume/body atlas. Android
    # primary maps are helmet panels: use a restricted patch and label that scope.
    # The source crop's eye line is around 28%; native humanoid maps put it
    # around 40%. This baseline avoids tucking the photo's eyes under the hair.
    quad=[[.12,.14],[.88,.14],[.88,.995],[.12,.995]]
    if letter=='D':quad=[[.08,.01],[.92,.01],[.92,.995],[.08,.995]]
    if android and letter!='F':quad=[[.32,.16],[.68,.16],[.68,.77],[.32,.77]]
    if letter=='J' and android:
        l,t,r,b=HUMANOID_ANDROID_BOXES[head]
        quad=[[l,t],[r,t],[r,b],[l,b]]
    return {'version':1,'crop':list(DEFAULT_CROP),'quad':quad,'opacity':1.0,'feather':.025,
            'mask':{'shape':'ellipse','inset':0 if letter=='D' else .035},'class_letter':letter,'head':head,
            'scope':'experimental photo on original android helmet face panel' if android else 'original separate face map only',
            'geometry_changed':False,'alignment_verified_in_game':False}


def _row(locator,name,chunk,letter='',kind='npc',model=None):
    hd=G.gvr_header(chunk);android=letter in ANDROID
    m=re.search(r'_[0-9]{2}',name)
    head=max(0,int(m.group()[1:])-1) if android and m else 0
    reason=None
    if hd['fmt'] not in (1,4,5,14) or hd['flags']&1:reason='Palette or mipmapped native face format is not written by this bounded encoder'
    if hd['w']>512 or hd['h']>512:reason='Face map exceeds the 512-pixel native build bound'
    if len(chunk)>MAX_ORIGINAL:reason='Native face chunk exceeds the 256 KiB portable-original bound'
    profile=default_profile(letter,head,android)
    if name in ATLAS_FACE_BOXES:
        patches=[]
        for l,t,r,b in ATLAS_FACE_BOXES[name]:
            patch=default_profile(letter,head,android);patch['quad']=[[l,t],[r,t],[r,b],[l,b]]
            patch['scope']='Explicit face/visor island on original NPC atlas; geometry retained'
            patches.append(patch)
        profile=patches[0]
        if len(patches)>1:profile['additional_patches']=patches[1:]
    return {'id':sha(json.dumps(locator,sort_keys=True).encode())[:24],'locator':locator,'name':name,
            'class_letter':letter,'class_name':G.CLASSES[G.LETTERS.index(letter)] if letter and letter in G.LETTERS else None,
            'kind':kind,'head':head,'android':android,'format':hd['fmt'],'width':hd['w'],'height':hd['h'],
            'supported':reason is None,'reason':reason,'model_binding':model,
            'profile':profile,'source_gvr_sha256':sha(chunk)}


def surface_catalog(disc):
    """Stable named player/NPC face maps; no guessed resident pointers or mesh identities."""
    rows=[]
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        path=f'pl{letter}tex.afs'
        if path not in disc.files:continue
        names=_names(disc,letter);entries=G.afs(disc.read(path))
        if not names or len(names)!=len(entries):continue
        for index,(name,chunk) in enumerate(zip(names,entries)):
            if _face_name(name):rows.append(_row({'kind':'afs','path':path,'index':index},name,chunk,letter,
                            'player' if letter in G.LETTERS else 'npc',{'kind':'player','class_letter':letter} if letter in G.LETTERS else None))
    for path,archive_entry,kind,size in _containers(disc):
        loc={'kind':kind,'path':path}
        if archive_entry:loc['archive_entry']=archive_entry
        raw=_container_bytes(disc,loc)
        if kind=='gvm':
            # C/F/etc NPC banks still contain original android helmets.
            match=re.match(r'n_([A-L])',archive_entry or path,re.I)
            letter=match.group(1).upper() if match else ''
            for index,(name,chunk) in enumerate(G.gvm_entries(raw)):
                if _face_name(name):rows.append(_row(loc|{'index':index},name,chunk,letter))
        elif kind=='bml':
            for entry in G.bml_files(raw):
                name=entry['name'].split(b'\0')[0].decode('latin-1')
                if entry['fields'][2]>MAX_CONTAINER or entry['fields'][4]>MAX_CONTAINER:raise ValueError('NPC decompression exceeds 64 MiB')
                _body,texture=G.bml_entry(raw,name)
                if texture is None:continue
                for index,(texname,chunk) in enumerate(G.gvm_entries(texture)):
                    if _face_name(texname):rows.append(_row(loc|{'entry':name,'index':index},texname,chunk,
                        model=loc|{'entry':name}))
    return rows


def read_surface(disc,surface):
    row=surface if isinstance(surface,dict) else next((row for row in surface_catalog(disc) if row['id']==surface),None)
    if not row:raise ValueError('Choose a named PSO face surface from this owned disc')
    loc=row['locator'];raw=_container_bytes(disc,loc)
    if loc['kind']=='afs':return G.afs(raw)[loc['index']]
    if loc['kind']=='bml':raw=G.bml_entry(raw,loc['entry'])[1]
    if loc['kind'] in ('gvm','bml'):return G.gvm_entries(raw)[loc['index']][1]
    raise ValueError('Unknown native PSO face surface container')


def export_surface_reference(disc,row,out,*,hair=0):
    """Export only an explicit native model binding, never an invented NPC avatar."""
    binding=row.get('model_binding')
    if not binding:return None,{'reason':'This NPC texture has no verified exported model binding; use an exact captured draw mesh'}
    if binding['kind']=='player':
        letter=binding['class_letter'];head=row.get('head',0);tables=G.tables(disc)[letter]
        default=next((name for name in tables['heads'][head] if _face_name(name)),None)
        if not default:raise ValueError('The selected native head has no named face texture binding')
        # Color/skin variants have distinct AFS entries. Put exactly the selected
        # face map into the default reference head's material, not a nearby skin.
        view=disc
        if default!=row['name']:
            raw=bytearray(disc.read(tables['afs_file']));index=tables['afs'].index(default)
            offset,size=struct.unpack_from('<II',raw,8+index*8);chunk=read_surface(disc,row)
            if len(chunk)!=size:raise ValueError('Selected face variant does not fit its native reference material')
            raw[offset:offset+size]=chunk;view=W.Overlay(disc,{tables['afs_file']:bytes(raw)})
        model,info=G.export_player(view,letter,out,head=head,hair=hair)
        materials=[f'tex{slot}' for slot,name in info.get('textures',{}).items() if name==default]
        return model,info|{'reference_face_surface':row['id'],'reference_face_materials':materials,
                          'reference':'Selected native face variant on its original class/head mesh'}
    from . import ninja,uap
    body,texture=G.bml_entry(_container_bytes(disc,binding),binding['entry'])
    nj=G.read_nj(body);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    files=[]
    for index,(name,chunk) in enumerate(G.gvm_entries(texture)):
        rel=f'textures/{index:03d}.png';target=out/rel;target.parent.mkdir(exist_ok=True)
        target.write_bytes(G.png_bytes(G.gvr_decode(chunk)));files.append(rel)
    manifest=ninja.to_manifest(nj,'pso_npc_'+row['id'],{'game':'PSO GC','source':binding},files)
    target=out/'reference.glb';target.write_bytes(uap.to_glb(manifest,out))
    materials=[mat.name for mat in manifest.materials if mat.source.get('ninja_texture_id')==row['locator']['index']]
    return target,{'binding':binding,'reference_face_surface':row['id'],'reference_face_materials':materials,
                   'reference':'explicit native BML body with its own GVM'}


def paint_image(original,photo,profile):
    """Same source projection and destination stroke semantics as the live editor."""
    from .photo_skin import Placement
    if not isinstance(profile,dict) or not {'crop','quad'}.issubset(profile):raise ValueError('Each face island needs an explicit crop and UV quadrilateral')
    settings=Placement(photo='0'*64,maps=[0],crop=profile['crop'],quad=profile['quad'],
                       opacity=profile.get('opacity',1),feather=profile.get('feather',.025))
    original=original.convert('RGBA');photo=photo.convert('RGBA');l,t,r,b=settings.crop
    src=np.asarray([[l,t],[r,t],[r,b],[l,b]])*np.asarray(photo.size)
    dst=np.asarray(settings.quad)*np.asarray(original.size);rows=[];values=[]
    for (x,y),(u,v) in zip(dst,src):
        rows.extend(([x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]));values.extend((u,v))
    coeff=np.linalg.solve(np.asarray(rows),np.asarray(values))
    warped=photo.transform(original.size,Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
    mask_config=profile.get('mask') or {'shape':'ellipse','inset':0}
    shape=mask_config.get('shape','ellipse');inset=float(mask_config.get('inset',0))
    if shape not in ('ellipse','rectangle') or not np.isfinite(inset) or not 0<=inset<=.45:raise ValueError('Choose an ellipse/rectangle mask with inset 0–0.45')
    source_mask=Image.new('L',photo.size,0);draw=ImageDraw.Draw(source_mask)
    box=((l+(r-l)*inset)*photo.width,(t+(b-t)*inset)*photo.height,
         (r-(r-l)*inset)*photo.width,(b-(b-t)*inset)*photo.height)
    (draw.ellipse if shape=='ellipse' else draw.rectangle)(box,fill=255)
    if settings.feather:source_mask=source_mask.filter(ImageFilter.GaussianBlur(settings.feather*min((r-l)*photo.width,(b-t)*photo.height)))
    mask=source_mask.transform(original.size,Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
    mask=ImageChops.multiply(mask,warped.getchannel('A'))
    strokes=profile.get('strokes') or []
    if len(strokes)>4096:raise ValueError('Face mask exceeds 4096 paint strokes')
    stroke_mask=Image.new('L',original.size,255);draw=ImageDraw.Draw(stroke_mask)
    for value in strokes:
        s=value if isinstance(value,Stroke) else Stroke.model_validate(value)
        x,y=s.x*original.width,s.y*original.height;radius=s.radius*min(original.size)
        draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=0 if s.erase else 255)
    mask=ImageChops.multiply(mask,stroke_mask)
    if settings.opacity!=1:mask=mask.point(lambda value:round(value*settings.opacity))
    result=Image.composite(warped,original,mask);result.putalpha(original.getchannel('A'))
    patches=profile.get('additional_patches') or []
    if len(patches)>7 or any(p.get('additional_patches') for p in patches):raise ValueError('A native face map supports at most eight explicit atlas patches')
    for patch in patches:result=paint_image(result,photo,patch)
    return result


def paint(chunk,photo,profile):
    from .melee_models import tex_size
    try:hd=G.gvr_header(chunk)
    except struct.error as error:raise ValueError('Malformed native face texture header') from error
    if not 0<hd['w']<=1024 or not 0<hd['h']<=1024 or hd['fmt'] not in (1,4,5,14) or hd['flags']&1:raise ValueError('Unsupported or oversized native face format')
    size=tex_size(hd['fmt'],hd['w'],hd['h'])
    if hd['data']+size>len(chunk) or hd['size']<8+size or hd['gvrt']+8+hd['size']>len(chunk):raise ValueError('Native face texture payload is truncated or inconsistent')
    original=Image.fromarray(G.gvr_decode(chunk));painted=paint_image(original,photo,profile)
    # Restore every untouched native compression block exactly. No body/hair map
    # is selected; CMPR endpoint quantization is limited to touched face blocks.
    data=bytearray(W.gvr_like(chunk,painted));changed=np.any(np.asarray(painted)!=np.asarray(original),axis=2)
    w,h=original.size;bw,bh=(8,8) if hd['fmt']==14 else (8,4) if hd['fmt']==1 else (4,4)
    for y in range(0,h,bh):
        for x in range(0,w,bw):
            base=hd['data']+((y//bh)*((w+bw-1)//bw)+x//bw)*32
            if hd['fmt']==14:
                for sub,(dx,dy) in enumerate(((0,0),(4,0),(0,4),(4,4))):
                    if not changed[y+dy:y+dy+4,x+dx:x+dx+4].any():data[base+sub*8:base+(sub+1)*8]=chunk[base+sub*8:base+(sub+1)*8]
            elif not changed[y:y+bh,x:x+bw].any():data[base:base+32]=chunk[base:base+32]
    data=bytes(data)
    if len(data)!=len(chunk) or data[:hd['data']]!=chunk[:hd['data']]:raise ValueError('Native face format or dimensions changed')
    return data


def _patch_gvm(raw,replacements):
    out=bytearray(raw);offset=8+struct.unpack_from('<I',raw,4)[0]
    for index,(_name,chunk) in enumerate(G.gvm_entries(raw)):
        replacement=replacements.get(index)
        if replacement is not None:
            if len(replacement)!=len(chunk):raise ValueError('Face GVR cannot grow')
            out[offset:offset+len(chunk)]=replacement
        offset+=len(chunk)
    return bytes(out)


def patch_files(disc,photo,profiles=None,progress=None):
    profiles=profiles or {};catalog=surface_catalog(disc);groups={};coverage=[]
    for index,row in enumerate(catalog):
        if progress and index%50==0:progress(index/max(1,len(catalog)),row['name'])
        record={k:row[k] for k in ('id','locator','name','class_letter','class_name','kind','head','android','supported','reason')}
        if not row['supported']:coverage.append(record|{'changed':False});continue
        before=read_surface(disc,row);profile=profiles.get(row['id'],row['profile']);after=paint(before,photo,profile)
        groups.setdefault((row['locator']['path'],row['locator'].get('archive_entry')),[]).append((row,after))
        coverage.append(record|{'changed':before!=after,'profile':profile,'before_sha256':sha(before),'after_sha256':sha(after),
                               'native_bytes':len(before),'format':row['format'],'size':[row['width'],row['height']]})
    files={};archives={}
    for (path,archive_entry),entries in groups.items():
        original=_container_bytes(disc,entries[0][0]['locator']);kind=entries[0][0]['locator']['kind']
        if kind=='afs':
            out=bytearray(original)
            for row,after in entries:
                off,size=struct.unpack_from('<II',original,8+8*row['locator']['index'])
                if size!=len(after):raise ValueError('Native AFS face length changed')
                out[off:off+size]=after
            candidate=bytes(out)
        elif kind=='gvm':candidate=_patch_gvm(original,{row['locator']['index']:after for row,after in entries})
        else:
            replacements={}
            for row,after in entries:replacements.setdefault(row['locator']['entry'],{})[row['locator']['index']]=after
            textures={}
            for entry,replaced in replacements.items():
                _body,old=G.bml_entry(original,entry);textures[entry.lower()]=_patch_gvm(old,replaced)
            candidate=G.bml_build(original,{},textures)
            for entry in G.bml_files(original):
                name=entry['name'].split(b'\0')[0].decode('latin-1')
                if G.bml_entry(original,name)[0]!=G.bml_entry(candidate,name)[0]:raise ValueError('An NPC native mesh or animation changed')
        if archive_entry:archives.setdefault(path,{})[archive_entry]=candidate
        else:files[path]=candidate
    for path,replacements in archives.items():
        if disc.files[path][1]>256*1024**2:raise ValueError('NPC area archive exceeds 256 MiB rebuild bound')
        original=disc.read(path);candidate=G.gsl_build(original,replacements)
        reread=G.gsl_files(candidate)
        for name,offset,size in G.gsl_entries(original):
            if reread[name]!=(replacements[name] if name in replacements else original[offset:offset+size]):raise ValueError('An unrelated NPC area resource changed')
        files[path]=candidate
    if sum(map(len,files.values()))>512*1024**2:raise ValueError('Native face changes exceed the 512 MiB assembly bound')
    return files,coverage


def coverage_gaps(disc,catalog):
    """Actual unmodified containers, rather than an unqualified all-NPC promise."""
    covered={(r['locator']['path'],r['locator'].get('archive_entry')) for r in catalog}
    gaps=[]
    for path,entry,kind,size in _containers(disc):
        if (path,entry) not in covered:gaps.append({'path':path,'archive_entry':entry,'reason':'No explicitly named primary face map in this NPC container; no guessed body-atlas painting'})
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        path=f'pl{letter}tex.afs'
        if path in disc.files and (path,None) not in covered:gaps.append({'path':path,'reason':'No named primary face map resolved from this native player/NPC bank'})
    # Some NPC geometry is in RELs. Their separate GVMs are painted when named;
    # geometry-only REL files intentionally remain original, not a coverage gap.
    for path in sorted(disc.files):
        if not path.lower().endswith('.gsl'):continue
        for entry,_offset,_size in _gsl_index(disc,path):
            if ('npc' in entry.lower() or re.match(r'n_[A-Z]\d\d',entry,re.I)) and entry.lower().endswith(('.gvm','.bml','.afs')) and not _native_kind(entry):
                gaps.append({'path':path,'archive_entry':entry,'reason':'NPC texture container has no verified named face-bank reader'})
    return gaps


def write_originals(folder,originals):
    """One bounded archive avoids hundreds of network requests during staging."""
    if len(originals)>2048:raise ValueError('Native originals exceed 2048 surfaces')
    for key,raw in originals.items():
        if not re.fullmatch('[a-f0-9]{24}',key) or not 0<len(raw)<=MAX_ORIGINAL:raise ValueError('Invalid or oversized native original')
        G.gvr_header(raw)
    target=Path(folder)/'face-originals.zip'
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,allowZip64=False) as archive:
        for key,raw in sorted(originals.items()):archive.writestr(key+'.gvr',raw)
    return target


def build(ctx,game,source,photo_raw,photo_sha,profiles=None,label='Bla'):
    """Construct a unique owned copy; no existing build name is overwritten."""
    from . import filemods,build_record
    if not re.fullmatch('[a-f0-9]{64}',photo_sha) or sha(photo_raw)!=photo_sha:raise ValueError('Source photo hash mismatch')
    source=Path(source)
    if shutil.disk_usage(ctx.config.cache).free<source.stat().st_size+4*2**30:raise ValueError('Not enough private build disk headroom')
    photo=Image.open(io.BytesIO(photo_raw))
    if photo.width*photo.height>12_000_000:raise ValueError('Source photo exceeds 12 megapixels')
    photo=photo.convert('RGBA')
    disc=G.open_disc(source)
    try:
        source_dol=sha(disc.read('PsoV3.dol'))
        files,coverage=patch_files(disc,photo,profiles,lambda n,name:ctx.progress(5+55*n,'Photo face: '+name))
        if not files:raise ValueError('No supported native face surfaces were found')
        changed={r['id'] for r in coverage if r.get('changed')}
        originals={r['id']:read_surface(disc,r) for r in surface_catalog(disc) if r['id'] in changed}
        report={'source_game_id':disc.game_id,'catalog_game_id':game['game_id'],'source_dol_sha256':source_dol,'surfaces':coverage,
                'classes':sorted({r['class_name'] for r in coverage if r.get('class_name') and r.get('changed')}),
                'npc_containers':sorted({r['locator']['path'] for r in coverage if r['kind']=='npc' and r.get('changed')}),
                'changed_surfaces':sum(bool(r.get('changed')) for r in coverage),'unsupported_surfaces':[r for r in coverage if not r['supported']],
                'unmodified_containers':coverage_gaps(disc,coverage),
                'uncatalogued_scope':'Named primary faces in player/NPC banks, loose GVM/BML packs and their area GSL copies. Generic body atlases and unnamed quest-only resources are not automatically identified as faces.',
                'geometry':'all native meshes, skeletons, head/hair models, NPC models and motions unchanged',
                'android_scope':'Experimental photo on restricted primary helmet-face panels; original robot head geometry remains',
                'verification':'native file parse and unchanged-mesh checks; not yet verified in game'}
    finally:disc.f.close()
    name='pso_bla_faces_'+photo_sha[:8]+'_'+uuid.uuid4().hex[:10]
    if filemods.mod_dir(ctx.config,game['game_id'],name).exists():raise FileExistsError('Unique photo-build name already exists; no existing build was touched')
    ctx.progress(65,'Assembling separate PSO native-face build')
    result=filemods.build_image(ctx.config,game['game_id'],source,name,{path:{'bytes':raw} for path,raw in files.items()},ctx.progress)
    folder=Path(result['dir']);marker=folder/'.gbox-mod.json';meta=json.loads(marker.read_text())
    write_originals(folder,originals)
    photo.save(folder/'source-photo.png')
    preview=Image.new('RGB',(1024,4*174+30),'#181b23');draw=ImageDraw.Draw(preview)
    draw.text((8,5),'Native face textures: original / photo result. Original bodies retained. Alignment needs in-game review.',fill='white')
    chosen=[next(r for r in coverage if r['kind']=='player' and r['class_letter']==letter and r.get('changed')) for letter in G.LETTERS]
    chosen+=list(r for r in coverage if r['kind']=='npc' and r.get('changed'))[:4]
    for i,row in enumerate(chosen):
        x,y=i%4*256,30+i//4*174
        draw.text((x+4,y+3),row['class_name'] or row['name'][:30],fill='white')
        before=originals[row['id']];after=paint(before,photo,row['profile'])
        for j,raw in enumerate((before,after)):
            image=Image.fromarray(G.gvr_decode(raw)).convert('RGB').resize((124,124),Image.Resampling.NEAREST)
            preview.paste(image,(x+j*128,y+20))
    preview.save(folder/'preview.png')
    meta.update(title=label+' — native PSO class and NPC faces',photo_faces={'version':1,'source_photo':photo_sha,
                'tag':'selfie:'+photo_sha,'base_image':str(source),'profiles':{r['id']:r['profile'] for r in coverage if r.get('changed')},
                'original_face_archive':'face-originals.zip','coverage_file':'face-coverage.json','geometry_unchanged':True,'verification':'unverified_in_game'},
                selfie_photo=photo_sha,tags=['selfie:'+photo_sha,'face-only','original-bodies'],previews=['preview.png','source-photo.png'])
    meta['photo_faces']['source_image']='source-photo.png'
    meta=build_record.stamp(meta,kind='character',slots=[{'slot':'class:'+name,'slot_name':name,'donor':label,'donor_name':label+' face'} for name in report['classes']],
                           verified_in_game=False,replacement_scope={'gameplay':'named native face maps','supporting_cast':report['npc_containers'],
                           'prerecorded_cinematics':'unchanged'},**build_record.from_ctx(ctx))
    marker.write_text(json.dumps(meta,indent=2));(folder/'face-coverage.json').write_text(json.dumps(report,indent=2))
    return result|{'coverage':report,'source_photo':photo_sha}


def register_models(ctx,result,label):
    """Publish real native exports in the existing central selfie collection."""
    from . import characters as C
    gallery=C.library_root(ctx.config)
    if not gallery.is_dir():return {'registered':False,'reason':'The central character collection is not mounted on this worker'}
    disc=G.open_disc(result['image']);rows=surface_catalog(disc);selected=[];seen=set();registered=[];slots=[]
    try:
        for letter in G.LETTERS:
            for head in range(5 if letter in ANDROID else 1):
                row=next(r for r in rows if r['kind']=='player' and r['class_letter']==letter and r['head']==head)
                selected.append((row,letter.lower()+'_h'+str(head),row['class_name']+(' head '+str(head+1) if letter in ANDROID else '')))
        for row in rows:
            binding=row.get('model_binding') or {}
            if row['kind']!='npc' or binding.get('kind')!='bml':continue
            key=(binding.get('archive_entry') or binding['path'],binding['entry'])
            if key in seen:continue
            seen.add(key);selected.append((row,'npc_'+sha(json.dumps(key).encode())[:12],binding['entry'].removesuffix('.nj').replace('_',' ')))
        for index,(row,suffix,title) in enumerate(selected):
            slug='pso_photo_'+result['source_photo'][:8]+'_'+result['mod'].rsplit('_',1)[1]+'_'+suffix
            work=ctx.config.data_dir/'pso-face-exports'/slug
            model,info=export_surface_reference(disc,row,work)
            if model is None:raise ValueError('A selected native model binding unexpectedly became unavailable')
            files=[model]+[p for p in (work/'textures',work/'manifest.json') if p.exists()]
            C.add(gallery,slug,label+' face on '+title,files,source={'game_id':result['coverage'].get('catalog_game_id'),
                  'game_title':'Phantasy Star Online Episode I & II Plus','custom_build':result['mod'],'native_surface':row['id']},
                  tool='gbox.pso_face_build',notes='Original native mesh, rig and weights. Photo face alignment requires in-game review.',
                  extra={'selfie_photo':result['source_photo'],'tags':['selfie:'+result['source_photo'],'face-only','original-bodies'],
                         'verification':'native_export; face_alignment_unverified'})
            registered.append(slug)
            if row['kind']=='player' and row['head']==0:
                slots.append({'slot':'class:'+row['class_name'].lower(),'slot_name':row['class_name'],
                              'donor':slug,'donor_name':label+' face on '+row['class_name'],
                              'source':{'character':G.slug_of(row['class_name']),'scope':'native face texture only'}})
            if index%8==0:ctx.progress(90+9*index/len(selected),'Exporting native photo-face models')
        folder=Path(result['dir']);meta_path=folder/'.gbox-mod.json';meta=json.loads(meta_path.read_text())
        meta['photo_faces']['exported_models']=registered
        meta['slots']=slots;meta['characters']=[row['donor'] for row in slots];meta['replaces']=[row['slot'] for row in slots]
        if registered:
            shutil.copy2(gallery/registered[0]/'preview.png',folder/'model-preview.png')
            meta['previews']=['model-preview.png',*meta.get('previews',[])]
        meta_path.write_text(json.dumps(meta,indent=2))
        return {'registered':True,'models':registered,'count':len(registered),'native_reference_gaps':
                [r['id'] for r in rows if r['kind']=='npc' and not r.get('model_binding')]}
    finally:disc.f.close()


def write_face_previews(ctx,result):
    """Static before/after on the actual unchanged native meshes, saved portably."""
    from . import characters as C,photo_story
    folder=Path(result['dir']);marker=folder/'.gbox-mod.json';meta=json.loads(marker.read_text())
    source=G.open_disc(meta['photo_faces']['base_image']);built=G.open_disc(result['image']);pairs=[]
    try:
        rows=surface_catalog(source)
        selected=[next(r for r in rows if r['kind']=='player' and r['class_letter']==letter and r['head']==0) for letter in 'ABDFJ']
        selected+=next(([r] for r in rows if r['kind']=='npc' and (r.get('model_binding') or {}).get('kind')=='bml'),[])
        directory=folder/'previews';directory.mkdir(exist_ok=True)
        for row in selected:
            model,info=export_surface_reference(source,row,ctx.config.data_dir/'pso-face-preview'/result['mod']/row['id'])
            if model is None:continue
            before=Image.fromarray(G.gvr_decode(read_surface(source,row)));after=Image.fromarray(G.gvr_decode(read_surface(built,row)))
            profile=meta['photo_faces']['profiles'][row['id']]
            frames=photo_story.render_frames(C._triangles(model),[(before,after)],profile['quad'],size=384)
            saved=[]
            for fraction,raw in frames:
                name='previews/'+row['id']+'-'+str(round(fraction*100))+'.png';(folder/name).write_bytes(raw)
                saved.append({'fraction':fraction,'file':name})
            pairs.append({'before':saved[0]['file'],'after':saved[-1]['file'],
                          'label':(row['class_name'] if row['kind']=='player' else row['name'])+' original mesh',
                          'frames':saved,'geometry':'unchanged','alignment':'needs_review'})
        meta['photo_faces']['previews']=pairs;marker.write_text(json.dumps(meta,indent=2))
        return pairs
    finally:source.f.close();built.f.close()


class BuildIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    op:Literal['plan','build']='build'
    game_id:str=Field(pattern='^[a-f0-9]{16}$')
    photo:str=Field(pattern='^[a-f0-9]{64}$')
    profiles:dict[str,dict]=Field(default_factory=dict,max_length=2048)
    name:str=Field(default='Bla',min_length=1,max_length=80)


class BuildOut(BaseModel):
    result:dict


from .registry import tool
from .models import Permission as P


@tool('pso_face_build','1.0',BuildIn,BuildOut,permissions=[P.READ,P.EXECUTE,P.STAGE],platforms=['linux'],timeout_s=1800,retries=0,
      side_effects=['creates a separate owned PSO GameCube native-face disc; originals remain intact'])
def run(inp,ctx):
    """Plan or build native PSO class and NPC photo faces, preserving all original meshes and rigs. Applies reviewed per-surface crop, UV projection and paint masks. NPC coverage is explicit, not inferred."""
    import httpx
    from .characters import _api
    game=_api(ctx,'GET','/api/catalog/'+inp.game_id)
    if game.get('platform')!='gamecube':raise ValueError('Choose an owned GameCube PSO game')
    source=G.disc_path(ctx,game)
    disc=G.open_disc(source)
    try:
        rows=surface_catalog(disc);gaps=coverage_gaps(disc,rows)
    finally:disc.f.close()
    if inp.op=='plan':return {'result':{'game_id':inp.game_id,'surfaces':rows,'unmodified_containers':gaps,'geometry_unchanged':True}}
    response=httpx.get(ctx.server+'/api/artifacts/'+inp.photo,headers=ctx.headers,timeout=30);response.raise_for_status()
    photo=response.content
    if len(photo)>8*1024**2 or sha(photo)!=inp.photo:raise ValueError('Source photo artifact differs or exceeds 8 MiB')
    saved=_api(ctx,'GET','/api/pso/faces/recipes',params={'photo':inp.photo}).get('profiles') or {}
    unknown=set(inp.profiles)-{row['id'] for row in rows}
    if unknown:raise ValueError('A requested face profile does not belong to the owned native surface catalog')
    profiles={row['id']:row['profile']|saved.get(row['id'],{})|inp.profiles.get(row['id'],{}) for row in rows}
    result=build(ctx,game,source,photo,inp.photo,profiles,inp.name)
    result['coverage']['catalog_game_id']=inp.game_id
    result['model_collection']=register_models(ctx,result,inp.name)
    result['previews']=write_face_previews(ctx,result)
    ctx.progress(100,'Native face build and source-photo model collection ready for inspection')
    return {'result':result}

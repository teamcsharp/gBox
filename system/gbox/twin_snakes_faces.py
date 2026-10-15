"""Texture-only Twin Snakes native stage/cinematic face builds.

Only reviewed native head materials are projected. Original KMS, motion,
collision, scripts and executable remain byte-identical. Codec face/video
containers are deliberately not claimed by the stage writer.
"""
from __future__ import annotations
import hashlib
import json
import struct
import time
import zlib
from pathlib import Path
import numpy as np
from PIL import Image
from . import twin_snakes as TS,ts_stage as S,ts_kms as K,ts_tex as T
from .native_face_projection import project,compact_previews


def _smallest_stage(st):
    """Try bounded standard zlib strategies; decoded resources never change."""
    for page in st.pages:
        candidates=[]
        if page.packed:
            try:
                if zlib.decompress(page.packed)==page.data:candidates.append(page.packed)
            except zlib.error:pass
        for strategy in (zlib.Z_DEFAULT_STRATEGY,zlib.Z_FILTERED,zlib.Z_RLE,zlib.Z_HUFFMAN_ONLY,zlib.Z_FIXED):
            obj=zlib.compressobj(9,zlib.DEFLATED,zlib.MAX_WBITS,9,strategy)
            packed=obj.compress(page.data)+obj.flush()
            if zlib.decompress(packed)!=page.data:raise AssertionError('Native zlib round trip changed decoded page')
            candidates.append(packed)
        page.packed=min(candidates,key=len)
    return S.build_stage(st)


def replace_masked(ts,img,candidate,mask):
    """Write touched native compression blocks; untouched atlas blocks retain bytes."""
    if img.fmt not in (1,3,4,5,6,14):raise ValueError(f'Face texture format {img.fmt} needs an explicit palette/mipmap profile')
    before=bytes(ts.data);ts.replace_image(img,np.asarray(candidate));start=ts.tpl+img.data_off
    bw,bh,bpp=T.TILE[img.fmt];stride=(img.w+bw-1)//bw;block_bytes=bw*bh*bpp//8
    for y in range(0,img.h,bh):
        for x in range(0,img.w,bw):
            offset=start+((y//bh)*stride+x//bw)*block_bytes
            if img.fmt==14:
                for sub,(dx,dy) in enumerate(((0,0),(4,0),(0,4),(4,4))):
                    if not mask[y+dy:y+dy+4,x+dx:x+dx+4].any():
                        ts.data[offset+sub*8:offset+(sub+1)*8]=before[offset+sub*8:offset+(sub+1)*8]
            elif not mask[y:y+bh,x:x+bw].any():ts.data[offset:offset+block_bytes]=before[offset:offset+block_bytes]
    return bytes(ts.data)


def prepare_container(raw,photo,profiles,*,crop=(.22,.035,.79,.7),preview_dir=None,label='Bla',progress=lambda p,m:None):
    """Return an unchanged-size stage.dat plus per-stage coverage.

    Profiles use source decoded texture SHA, native model hash and material
    hash. A source mismatch fails closed instead of painting a different atlas.
    """
    sd=S.StageDat.from_bytes(raw)
    if not sd.entries:raise ValueError('No verified native stage directory')
    output=bytearray(raw);reports=[];skipped=[]
    allowed={(str(p['model']),str(p['texture']),p['sha256']):p for p in profiles}
    for si in range(len(sd.entries)):
        st=sd.stage(si);files=st.files();sets=[];set_files={}
        for f in files:
            if f.type!=S.TEXTURES:continue
            try:ts=T.TextureSet(f.data)
            except (ValueError,KeyError,IndexError):continue
            sets.append(ts);set_files[id(ts)]=f
        changed_sets={};stage_reports=[]
        for f in files:
            if f.type!=S.MODEL:continue
            try:model=K.parse(f.data)
            except (ValueError,IndexError):continue
            if [b['parent'] for b in model.bones][:21]!=K.PARENTS:continue
            by_texture={}
            for p in K.decode(model):
                if p['mesh']==12:by_texture.setdefault(p['tex'],[]).append(p)
            for th,primitives in by_texture.items():
                ordered=sorted(sets,key=lambda ts:(set_files[id(ts)].hash!=model.tex_set,set_files[id(ts)].page!=f.page))
                ts,img=TS.find_image(ordered,th,model.tex_set)
                if img is None:continue
                base=ts.rgba(img);sha=hashlib.sha256(base.tobytes()).hexdigest();key=(f'{f.hash:06x}',f'{th:06x}',sha)
                profile=allowed.get(key)
                if not profile:continue
                table=struct.unpack_from('>I',ts.data,ts.tpl+8)[0]
                image_header=struct.unpack_from('>I',ts.data,ts.tpl+table+img.index*8)[0]
                min_lod,max_lod=ts.data[ts.tpl+image_header+0x21:ts.tpl+image_header+0x23]
                if min_lod or max_lod:
                    skipped.append({'stage':st.name,'model':key[0],'texture':key[1],'reason':'Native mipmapped face needs an explicit full-chain writer','min_lod':min_lod,'max_lod':max_lod});continue
                candidate=project(Image.fromarray(base),photo,primitives,crop=profile.get('crop',crop),bounds=profile.get('bounds'),
                                  opacity=profile.get('opacity',1.),feather=profile.get('feather',.12),respect_alpha=False,mirror_x=True)
                if candidate.report['masked_pixels']<4:
                    skipped.append({'stage':st.name,'model':key[0],'texture':key[1],'reason':'empty face mask'});continue
                try:baked=replace_masked(ts,img,candidate.image,candidate.mask>0)
                except ValueError as error:
                    skipped.append({'stage':st.name,'model':key[0],'texture':key[1],'reason':str(error)});continue
                projection=candidate.report
                geometry_sha=hashlib.sha256(b''.join(np.asarray(p[k]).tobytes()for p in primitives for k in ('pos','nrm','uv','tris'))).hexdigest()
                stem=f'{key[0]}-{key[1]}-{sha[:8]}-{geometry_sha[:8]}'
                if preview_dir:
                    out=Path(preview_dir);out.mkdir(parents=True,exist_ok=True)
                    Image.fromarray(base).save(out/f'{stem}-before.png');Image.fromarray(ts.rgba(img)).save(out/f'{stem}-after.png')
                tf=set_files[id(ts)];changed_sets[(tf.page,tf.offset,tf.key)]=bytes(ts.data)
                actor=next((c['name'] for c in TS.CAST if TS.model_hash(c['key'])==f.hash),f'Native actor {key[0]}')
                stage_reports.append({'stage':st.name,'model':key[0],'native_actor':actor,'face_label':f'{label} face on {actor}',
                    'preview_before':f'face-previews/{stem}-before.png','preview_after':f'face-previews/{stem}-after.png',
                    'bones':len(model.bones),'texture':key[1],'geometry_sha256':geometry_sha,'native_min_lod':min_lod,'native_max_lod':max_lod,
                    'texture_set':f'{tf.hash:06x}','source_texture_pixels_sha256':sha,'geometry_modified':False,'projection':projection})
        if not changed_sets:continue
        # File hashes can repeat even within a native page. Same-size face
        # edits address the exact page/offset, never a lossy hash dictionary.
        touched=set()
        for page in st.pages:
            edits=[(offset,data)for (number,offset,key),data in changed_sets.items()if number==page.number]
            if not edits:continue
            payload=bytearray(page.data)
            for offset,data in edits:
                original=next(f for f in files if f.page==page.number and f.offset==offset)
                if len(data)!=len(original.data):raise AssertionError('Native texture set resized')
                payload[offset:offset+len(data)]=data
            page.data=bytes(payload);touched.add(page.number)
        updated=S.build_stage(st,touched,9);off,span=sd.span(si)
        if len(updated)>span:
            # The stock uses zlib level 6. Recompressing its other pages at
            # level 9 can recover room without touching any decoded resource.
            updated=S.build_stage(st,{p.number for p in st.pages},9)
        if len(updated)>span:updated=_smallest_stage(st)
        if len(updated)>span:
            skipped.append({'stage':st.name,'reason':'Projected textures exceed native stage slot','extra_bytes':len(updated)-span})
            continue
        output[off:off+span]=updated+raw[off+len(updated):off+span]
        # Re-read the rewritten page archive and assert every native model,
        # motion and other unselected resource still has its original bytes.
        verified=S.parse_stage(bytes(output[off:off+span]),st.name,st.sector,span)
        lookup={(f.page,f.offset,f.key):f.data for f in verified.files()}
        for original in files:
            key=(original.page,original.offset,original.key)
            if key not in changed_sets and lookup.get(key)!=original.data:
                raise AssertionError(f'{st.name}: unrelated native resource changed: {key}')
        reports.extend(stage_reports);progress(70*(si+1)/len(sd.entries),f'Projected native heads in {st.name}')
    if len(output)!=len(raw):raise AssertionError('Stage archive resized')
    return bytes(output),{'faces':reports,'skipped':skipped,'source_archive_sha256':hashlib.sha256(raw).hexdigest(),
                          'result_archive_sha256':hashlib.sha256(output).hexdigest(),'native_nontexture_resources_unchanged':True}


def build(cfg,game_id,iso,name,photo,profiles,*,photo_sha256='',label='Bla',progress=lambda p,m:None):
    from .gcdisc import GCDisc
    from . import filemods
    out=filemods.mod_dir(cfg,game_id,name)
    if out.exists():raise FileExistsError('Face build destination must be new')
    disc=GCDisc(iso)
    try:
        if disc.game_id!=TS.DISC_ID:raise ValueError('Only the verified GGSEA4 native disc layout is supported')
        source=disc.read('stage.dat');new,report=prepare_container(source,photo,profiles,preview_dir=out/'face-previews',label=label,progress=progress)
        disc_number=disc.read_header()[6]+1 if hasattr(disc,'read_header') else disc._r(6,1)[0]+1
    finally:disc.f.close()
    if not report['faces']:raise ValueError('No reviewed native faces matched this disc')
    # filemods.build_image creates its own destination. Keep the verified
    # previews in a separate temporary directory until the image is copied.
    previews=out.with_name(out.name+'-face-previews')
    import shutil
    if previews.exists():raise FileExistsError('Preview staging destination already exists')
    shutil.move(str(out/'face-previews'),str(previews));out.rmdir()
    result=filemods.build_image(cfg,game_id,Path(iso),name,{'stage.dat':{'bytes':new}},progress)
    shutil.move(str(previews),str(out/'face-previews'))
    rebuilt=GCDisc(result['image'])
    try:
        if rebuilt.read('stage.dat')!=new:raise AssertionError('Native stage archive reintegration failed')
    finally:rebuilt.f.close()
    coverage={'disc':disc_number,'face_material_instances':len(report['faces']),
        'models':sorted({r['model']for r in report['faces']}),'stages':sorted({r['stage']for r in report['faces']}),
        'cinematic_models':sorted({r['model']for r in report['faces']if r['bones']>21}),
        'complete':False,'not_covered':['codec portraits in shared/face.dat','demo.dat streamed resources','pre-rendered movies','unreviewed or fully helmeted face materials'],
        'models_rigs_animations_unchanged':True,'gameplay_verified':False}
    report.update({'format':'twin-snakes-native-face-build-v1','photo_sha256':photo_sha256,'coverage':coverage})
    report['preview_storage']=compact_previews(out,report['faces'])
    (out/'build-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    marker=out/'.gbox-mod.json';record=json.loads(marker.read_text());record.update({'title':f'{label} faces · Twin Snakes disc {disc_number} original bodies',
        'kind':'cast','selfie_photo':photo_sha256,'selfie_tag':label,'photo_sha256':photo_sha256,
        'photo_faces':{'source_photo':photo_sha256,'tag':'selfie:'+photo_sha256,'geometry_unchanged':True,
            'previews':report['preview_storage']['previews']},
        'slots':[{'slot':r['model'],'slot_name':r['native_actor'],'donor':label+' face','donor_name':label+' face'}for r in report['faces']],
        'report':report,'gameplay_verified':False})
    marker.write_text(json.dumps(record),encoding='utf-8')
    return result|{'coverage':coverage,'status':'built_unverified'}


from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from .registry import tool
from .models import Permission as P


class BuildIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    op:Literal['plan','build']='build'
    game_id:str=Field(pattern='^[a-f0-9]{16}$')
    photo:str=Field(pattern='^[a-f0-9]{64}$')
    profiles:dict[str,dict]=Field(default_factory=dict,max_length=512)
    label:str=Field(default='Bla',min_length=1,max_length=80)


class BuildOut(BaseModel):
    result:dict


@tool('twin_snakes_face_build','1.0',BuildIn,BuildOut,permissions=[P.READ,P.EXECUTE,P.STAGE],timeout_s=1800,retries=0,
      side_effects=['creates a separate owned GGSEA4 native face disc; preserves original bodies and source disc'])
def run(inp,ctx):
    """Plan/build reviewed Twin Snakes native head photo faces. Exact model/material/source-image lineage gates writes; original meshes, scripts and motions remain unchanged. Codec sprites, streamed demos and tight native stage slots are reported as gaps."""
    import io,uuid
    from .characters import _api,_gc_iso
    from . import filemods
    if inp.game_id not in TS.GAME_IDS:raise ValueError('Choose an owned verified GGSEA4 Twin Snakes disc')
    game=_api(ctx,'GET','/api/catalog/'+inp.game_id)
    if game.get('platform')!='gamecube':raise ValueError('Choose an owned Twin Snakes GameCube disc')
    source=_gc_iso(ctx,game)
    profiles=json.loads(Path(__file__).with_name('twin_snakes_face_profiles.json').read_text())['profiles']
    keyed={p['model']+':'+p['texture']+':'+p['sha256']:p for p in profiles}
    if set(inp.profiles)-set(keyed):raise ValueError('Face profile does not belong to this native model/material catalog')
    for key,settings in inp.profiles.items():
        if set(settings)-{'crop','bounds','opacity','feather'}:raise ValueError('Only native face crop, head-space bounds and blend settings are editable')
        keyed[key]=keyed[key]|settings
    if inp.op=='plan':return {'result':{'game_id':inp.game_id,'profiles':keyed,'geometry_unchanged':True,
        'coverage_gaps':['codec portrait/eye/mouth sprites','demo.dat streamed resources','unreviewed/helmeted faces','compressed stages exceeding their native slot'],
        'inventory':'Official Dolphin GGSEA4 AR candidates exist but are not independently verified for this owned revision'}}
    photo=_api(ctx,'GET','/api/artifacts/'+inp.photo)
    if not isinstance(photo,bytes)or len(photo)>8*1024**2 or hashlib.sha256(photo).hexdigest()!=inp.photo:raise ValueError('Photo artifact differs or exceeds 8 MiB')
    im=Image.open(io.BytesIO(photo))
    if im.width*im.height>16*1024**2:raise ValueError('Photo dimensions exceed 16 megapixels')
    name='tts_photo_faces_'+inp.photo[:8]+'_'+uuid.uuid4().hex[:10]
    result=build(ctx.config,inp.game_id,source,name,im.convert('RGBA'),list(keyed.values()),photo_sha256=inp.photo,label=inp.label,progress=ctx.progress)
    ctx.artifact('native-face-build.json',json.dumps(result,indent=2).encode(),'application/json',photo=inp.photo,source_game=inp.game_id)
    return {'result':result}

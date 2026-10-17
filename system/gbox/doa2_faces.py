"""Face-only DOA2 LE builds: verified native head bindings, original CHRs intact."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image
from . import doa2_bindings as B, doa2_geometry as G, doa2_textures as T
from .native_face_projection import project,compact_previews


def prepare(disc, photo, profiles, *, crop=(.22,.035,.79,.7), preview_dir=None,label='Bla',progress=lambda p,m:None,expected_payloads=None):
    """Return same-size BIN edits for explicitly reviewed native face profiles.

    A profile binds an archive/head material to the source texture payload SHA.
    No model, motion, executable, shadow, or accessory stream is rewritten.
    """
    executable=disc.read('1ST_READ.BIN');changes={};reports=[]
    for i,(name,profile) in enumerate(sorted(profiles.items())):
        progress(70*i/max(1,len(profiles)),f'Projecting face: {name}')
        binding=B.resolve_archive_binding(executable,name)
        raw=disc.read(name);bankname=name[:-4]+'.BIN';bank=disc.read(bankname)
        head=binding['sections']['primary'][1]
        if head!=profile['head_model']:raise ValueError(f'{name}: native head binding changed')
        archive=G.decode_chr(raw);textures=T.descriptors(raw,bank);ti=int(profile['texture']);tex=textures[ti]
        original_sha=hashlib.sha256(bank[tex.offset:tex.offset+tex.size]).hexdigest()
        if original_sha!=profile['sha256']:raise ValueError(f'{name}: reviewed face texture changed')
        primitives=[]
        for mesh in archive['models'][head]['meshes']:
            if mesh['texture_id']!=ti or not mesh['triangles']:continue
            a=np.asarray(mesh['vertices'],dtype=float)
            primitives.append({'pos':a[:,:3],'nrm':a[:,3:6],'uv':a[:,6:8],'tris':mesh['triangles']})
        base=T.decode(tex,bank)
        candidate=project(base,photo,primitives,crop=profile.get('crop',crop),bounds=profile.get('bounds'),
                          opacity=profile.get('opacity',1.),feather=profile.get('feather',.12),
                          deformation=profile.get('deformation'))
        if candidate.report['masked_pixels']<4:raise ValueError(f'{name}: empty native face mask')
        payload=T.encode(tex,candidate.image)
        if expected_payloads is not None and hashlib.sha256(payload).hexdigest()!=expected_payloads.get(name):
            raise ValueError(f'{name}: native face differs from the exact accepted editor preview')
        if len(payload)>tex.capacity:raise ValueError(f'{name}: face payload exceeds native allocation')
        edited=bytearray(bank);edited[tex.offset:tex.offset+len(payload)]=payload
        if len(edited)!=len(bank):raise AssertionError('Native BIN resized')
        # Unselected native payloads and all native descriptor/geometry bytes
        # remain intact. VQ changes can quantize pixels inside this one texture.
        allowed=(tex.offset,tex.offset+len(payload))
        if edited[:allowed[0]]!=bank[:allowed[0]] or edited[allowed[1]:]!=bank[allowed[1]:]:
            raise AssertionError('Face bake touched unrelated native bytes')
        decoded=T.decode(tex,bytes(edited))
        if preview_dir:
            out=Path(preview_dir);out.mkdir(parents=True,exist_ok=True);stem=Path(name).stem
            base.save(out/f'{stem}-before.png');decoded.save(out/f'{stem}-after.png')
            Image.fromarray((candidate.mask*255).astype(np.uint8)).save(out/f'{stem}-mask.png')
        changes[bankname]=bytes(edited)
        from .doa2_chars import FIGHTERS
        family=Path(name).stem[:-2];actor=next((label for key,label,_ in FIGHTERS if key==family),family)
        reports.append({'archive':name,'native_actor':actor,'face_label':f'{label} face on {actor}',
            'preview_before':f'face-previews/{Path(name).stem}-before.png','preview_after':f'face-previews/{Path(name).stem}-after.png',
            'bank':bankname,'render_slot':binding['render_slot'],'costume':binding['costume'],
            'head_model':head,'texture':ti,'dimensions':[tex.width,tex.height],'native_format':tex.format,'native_pixel':tex.pixel,
            'source_texture_sha256':original_sha,'result_texture_sha256':hashlib.sha256(bytes(edited)[tex.offset:tex.offset+tex.size]).hexdigest(),
            'source_chr_sha256':hashlib.sha256(raw).hexdigest(),'geometry_modified':False,'unselected_bytes_unchanged':True,
            'projection':candidate.report})
    return changes,reports


def build(gdi,out_dir,name,photo,profiles,*,game_id='1de2e7634f3161ff',photo_sha256='',label='Bla',progress=lambda p,m:None,expected_payloads=None):
    from .gdrom import GDRom,patch_gdi
    out=Path(out_dir)
    if out.exists():raise FileExistsError('Face build destination must be new; originals and previous builds are preserved')
    disc=GDRom(gdi)
    # Previews are produced only after all source lineage is validated.
    changes,reports=prepare(disc,photo,profiles,preview_dir=out/'face-previews',label=label,progress=progress,expected_payloads=expected_payloads)
    if not changes:raise ValueError('No reviewed native faces selected')
    image=patch_gdi(gdi,out,name,changes,progress)
    rebuilt=GDRom(image)
    for key,data in changes.items():
        if rebuilt.read(key)!=data:raise AssertionError(f'Native GDI verification mismatch: {key}')
    for key in disc.files:
        if key.upper().endswith(('.CHR','.MOT','.SUP')) and rebuilt.read(key)!=disc.read(key):
            raise AssertionError(f'Original native model/motion changed: {key}')
    coverage={'native_fighter_costumes':len(reports),'archives':[r['archive'] for r in reports],
        'scope':'reviewed native fighter/costume face textures; native in-engine scenes reuse these archives',
        'not_covered':['pre-rendered videos','unbound story archive YTI00','roster portraits not bound to native head materials'],
        'complete':False,'all_models_rigs_animations_unchanged':True,'gameplay_verified':False}
    report={'format':'doa2-native-face-build-v1','photo_sha256':photo_sha256,'coverage':coverage,'faces':reports,
            'inventory':'No RPG inventory. No unverified roster/costume unlock patch is applied.'}
    report['preview_storage']=compact_previews(out,reports)
    (out/'build-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'.gbox-mod.json').write_text(json.dumps({'name':name,'game_id':game_id,'image':image.name,'files':list(changes),
        'built':time.time(),'kind':'cast','selfie_photo':photo_sha256,'selfie_tag':label,'title':label+' faces · DOA2 original cast bodies',
        'photo_sha256':photo_sha256,'photo_faces':{'source_photo':photo_sha256,'tag':'selfie:'+photo_sha256,'geometry_unchanged':True,
            'previews':report['preview_storage']['previews']},
        'slots':[{'slot':r['archive'],'slot_name':r['native_actor'],'donor':label+' face','donor_name':label+' face'}for r in reports],
        'report':report,'gameplay_verified':False}),encoding='utf-8')
    return {'mod':name,'image':str(image),'coverage':coverage,'status':'built_unverified'}


from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from .registry import tool
from .models import Permission as P


class BuildIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    op:Literal['plan','build']='build'
    game_id:str=Field(pattern='^[a-f0-9]{16}$')
    photo:str=Field(pattern='^[a-f0-9]{64}$')
    profiles:dict[str,dict]=Field(default_factory=dict,max_length=256)
    label:str=Field(default='Bla',min_length=1,max_length=80)


class BuildOut(BaseModel):
    result:dict


@tool('doa2_face_build','1.0',BuildIn,BuildOut,permissions=[P.READ,P.EXECUTE,P.STAGE],timeout_s=1800,retries=0,
      side_effects=['creates a separate owned DOA2 LE face-only GDI; preserves original bodies and source disc'])
def run(inp,ctx):
    """Plan/build reviewed native DOA2 LE head photo faces, retaining original bodies, rigs, costumes and animations. Exact source texture hashes gate writes; coverage gaps and native-quantized previews are included."""
    import io,uuid
    from .characters import _api,_dc_gdi
    from . import filemods
    if inp.game_id!='1de2e7634f3161ff':raise ValueError('Verified face profiles currently require the owned DOA2 LE Japan revision')
    game=_api(ctx,'GET','/api/catalog/'+inp.game_id)
    source=_dc_gdi(ctx,game)
    profiles=json.loads(Path(__file__).with_name('doa2_face_profiles.json').read_text())['profiles']
    unknown=set(inp.profiles)-set(profiles)
    if unknown:raise ValueError('Face profile does not belong to this owned native head catalog')
    for key,settings in inp.profiles.items():
        if set(settings)-{'crop','bounds','opacity','feather','deformation'}:raise ValueError('Only native face crop, head-space bounds, blend and deformation settings are editable')
        profiles[key]=profiles[key]|settings
    if inp.op=='plan':return {'result':{'game_id':inp.game_id,'profiles':profiles,'geometry_unchanged':True,
        'coverage_gaps':['unbound story YTI00','roster portraits','prerendered videos'],'inventory':'No RPG inventory; no unverified unlock patch'}}
    photo=_api(ctx,'GET','/api/artifacts/'+inp.photo)
    if not isinstance(photo,bytes)or len(photo)>8*1024**2 or hashlib.sha256(photo).hexdigest()!=inp.photo:raise ValueError('Photo artifact differs or exceeds 8 MiB')
    im=Image.open(io.BytesIO(photo))
    if im.width*im.height>16*1024**2:raise ValueError('Photo dimensions exceed 16 megapixels')
    name='doa2_photo_faces_'+inp.photo[:8]+'_'+uuid.uuid4().hex[:10]
    result=build(source,filemods.mod_dir(ctx.config,inp.game_id,name),name,im.convert('RGBA'),profiles,
                 game_id=inp.game_id,photo_sha256=inp.photo,label=inp.label,progress=ctx.progress)
    ctx.artifact('native-face-build.json',json.dumps(result,indent=2).encode(),'application/json',photo=inp.photo,source_game=inp.game_id)
    return {'result':result}

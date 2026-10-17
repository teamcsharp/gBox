"""RE4 GC photo skins: patch matching native CMPR pixels; never retarget/decimate Leon."""
import hashlib
import io
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from . import re4gc_models as R

PACKS=('em/pl00.drs','em/pl08.drs','em/pl09.drs','em/pl10.drs')


def pixels(image):return (image.size,image.convert('RGBA').tobytes())


def patch_tpl(raw,replacements):
    """Keep native headers/offsets/padding; encode every existing mip at the same size."""
    count,table=struct.unpack_from('>II',raw,4);out=bytearray(raw);changed=[]
    for i,image in enumerate(R.tpl_read(raw)):
        replacement=replacements.get(((image.w,image.h),image.rgba().tobytes()))
        if replacement is None:continue
        if image.fmt!=14:raise ValueError('Photo skin currently requires a native CMPR color map')
        if replacement.size!=(image.w,image.h):raise ValueError('Photo texture dimensions changed')
        header=struct.unpack_from('>I',raw,table+8*i)[0]
        offset=struct.unpack_from('>I',raw,header+8)[0]
        levels=image.hdr[34]+1
        if not 1<=levels<=13:raise ValueError('Unsupported native mip count')
        encoded=bytearray()
        for level in range(levels):
            size=(max(1,image.w>>level),max(1,image.h>>level))
            im=replacement.convert('RGBA').resize(size,Image.Resampling.LANCZOS)
            encoded.extend(R.cmpr_encode(np.asarray(im)))
        if len(encoded)>len(image.data):raise ValueError('Native mip chain would grow')
        out[offset:offset+len(encoded)]=encoded
        changed.append({'texture':i,'size':[image.w,image.h],'mips':levels,'bytes':len(encoded)})
    assert len(out)==len(raw)
    return bytes(out),changed


def patch_pack(raw,replacements):
    pack=R.ModelPack(raw);out=raw;changes=[]
    for index,(kind,data) in enumerate(pack.items):
        if kind!='TPL':continue
        patched,rows=patch_tpl(data,replacements)
        if not rows:continue
        if not data or not raw.count(data):raise ValueError('Texture container not located in the native pack')
        out=out.replace(data,patched);changes.extend(dict(row,tpl=index) for row in rows)
    # All non-texture bytes, including bones, weights, animations and every BIN,
    # must survive byte-for-byte. Container sizes and native offsets cannot grow.
    reread=R.ModelPack(out)
    assert len(out)==len(raw) and len(pack.items)==len(reread.items)
    for (kind,a),(newkind,b) in zip(pack.items,reread.items):
        if kind!=newkind or (kind!='TPL' and a!=b):raise ValueError('A non-texture native resource changed')
    return out,changes


def build(ctx,meta,game,base,progress):
    import httpx
    from . import filemods,build_record
    from .gcdisc import GCDisc
    approval=meta['photo_skin_approval'];replacements={}
    def artifact(digest):
        r=httpx.get(ctx.server+'/api/artifacts/'+digest,headers=ctx.headers,timeout=30);r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=digest:raise ValueError('Photo map hash mismatch')
        return Image.open(io.BytesIO(r.content)).convert('RGBA')
    for row in approval['images']:replacements[pixels(artifact(row['before']))]=artifact(row['after'])
    if not replacements:raise ValueError('Approved photo has no texture replacements')
    gid=game['game_id'];name='re4_'+meta['slug']+('_d2' if gid=='e42c9b780c07c437' else '')
    work=Path(ctx.config.cache)/'characters_build'/meta['slug']/'native-photo';work.mkdir(parents=True,exist_ok=True)
    report={};changes={};disc=GCDisc(Path(base))
    try:
        for index,path in enumerate(PACKS):
            progress(30+index*8,'Photo skin: preserving native Leon geometry in '+path)
            original=disc.read(path);data,rows=patch_pack(original,replacements)
            report[path]={'textures':rows,'bytes':len(data),'geometry':'native non-TPL resources byte-identical'}
            if rows:
                target=work/Path(path).name;target.write_bytes(data);changes[path]={'from':str(target)}
    finally:disc.f.close()
    if not changes:raise ValueError('No native Leon textures matched the approved source maps')
    progress(70,'Building separate RE4 photo-skin disc; no decimation')
    result=filemods.build_image(ctx.config,gid,Path(base),name,changes)
    folder=filemods.mod_dir(ctx.config,gid,name);image='RE4 '+meta['slug']+'.iso'
    Path(result['image']).replace(folder/image)
    marker=folder/'.gbox-mod.json';m=json.loads(marker.read_text());m.update(image=image,character=meta['slug'],
        photo_skin={'review':approval['review'],'geometry':'unchanged','decimated':False},verification={'status':'unverified'})
    m=build_record.stamp(m,kind='character',slots=[{'slot':'player','slot_name':'Leon','donor':meta['slug'],'donor_name':meta['name']}],
        verified_in_game=False,replacement_scope={'gameplay':'matching Leon face maps','in_engine_cutscenes':'matching pack textures only',
            'prerecorded_cinematics':'unchanged','supporting_cast':'not included'},**build_record.from_ctx(ctx))
    marker.write_text(json.dumps(m))
    return {'mod':name,'image':image,'packs':report,'how':'native texture-only photo skin','decimated':False,
            'verification':'not yet verified in gameplay','scope':'matching Leon costume/face textures; prerecorded cinematics unchanged'}

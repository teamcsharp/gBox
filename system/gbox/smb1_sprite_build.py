"""Portable SMB1 player CHR replacement from the owned Sonic 2 animation decoder."""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from . import smb1_inventory as S, tas
from .models import Permission as P
from .registry import tool

GAME_ID='49b6a2f65aca26a2'
DONOR_ID='938e4ca5b120e344'
PALETTE=(0x0F,0x12,0x30,0x16)


def sonic_frames(path):
    from . import sonic2d_sprites as D
    raw,meta=D.read_rom(path);ex=D.Extractor(raw,meta)
    if ex.game.key!='sonic2':raise ValueError('The donor must be Sonic the Hedgehog 2')
    plans={p['name']:p for p in ex.plans('sonic')};cache={}
    def frame(names,n=0):
        name=next((x for x in names if x in plans),None)
        if name is None:raise ValueError('Required Sonic 2 pose is missing')
        if name not in cache:cache[name]=ex.clip('sonic',plans[name])['images']
        return Image.fromarray(cache[name][n%len(cache[name])]).convert('RGBA')
    walk=[frame(('walk',),n*2) for n in range(3)]
    skid=frame(('skid',));jump=frame(('jump',));swim=[frame(('float','walk'),n) for n in range(3)]
    climb=[frame(('hang','push','walk'),n) for n in range(2)]
    stand=frame(('wait','walk'));duck=frame(('duck',));dead=frame(('death','hurt'))
    return walk+[skid,jump]+swim+climb+[duck,stand]+walk+[skid,jump]+swim+climb+[dead,stand,stand,stand],{'game_id':DONOR_ID,'slug':'sonic2_sonic','rom_sha256':hashlib.sha256(raw).hexdigest(),'reader':'gbox.sonic2d_sprites'}


def encode_tile(indices):
    a=np.asarray(indices,dtype=np.uint8)
    if a.shape!=(8,8) or np.any(a>3):raise ValueError('NES tiles need 8x8 two-bit pixels')
    return bytes(sum(int((a[y,x]>>bit)&1)<<(7-x) for x in range(8)) for bit in (0,1) for y in range(8))


def quantize_sonic(image):
    a=np.asarray(image.convert('RGBA'));r,g,b=[a[:,:,i].astype(int) for i in range(3)]
    out=np.ones(a.shape[:2],dtype=np.uint8)
    out[(r+g+b>430)&(np.maximum.reduce([r,g,b])-np.minimum.reduce([r,g,b])<110)]=2
    # The NES allows three opaque sprite colors. Skin highlights become white,
    # shoes remain red, and blue/black outlines share blue.
    out[(r>g*1.2)&(r>b*1.2)]=2
    yy=np.indices(out.shape)[0]
    out[(r>g*1.4)&(r>b*1.4)&(yy>out.shape[0]*.62)]=3
    out[a[:,:,3]<128]=0
    return out


def validate_output(original,output):
    """Allow only the native writer's graphics/table/palette changes against an owned source."""
    tas.smb_identity(original)
    prg=original[16:32784];old=S._player_rows(prg)
    enemy={t for row in S._enemy_rows(prg) for t in row}
    pool={t for row in old for t in row}-enemy-{0xFC}
    start=16+S.OFFSETS['PlayerGraphicsTable']
    allowed=set(range(start,start+208))|{a for t in pool for a in range(32784+t*16,32784+(t+1)*16)}
    for name in ('GroundPaletteData','WaterPaletteData','UndergroundPaletteData','CastlePaletteData'):
        allowed.update(range(16+S.OFFSETS[name]+19,16+S.OFFSETS[name]+23))
    allowed.update(range(16+S.OFFSETS['Palette3Data'],16+S.OFFSETS['Palette3Data']+16))
    player_colors=bytes.fromhex('221627182230271922372716')
    if original.count(player_colors)!=1:raise ValueError('The native player color table differs')
    color_at=original.index(player_colors)
    allowed.update(range(color_at,color_at+4));allowed.update(range(color_at+8,color_at+12))
    if len(output)!=len(original) or any(a not in allowed for a,(x,y) in enumerate(zip(original,output)) if x!=y):
        raise ValueError('The writer changed data outside player graphics and palettes')
    rows=S._player_rows(output[16:32784])
    if any(t not in pool|{0xFC} for row in rows for t in row):raise ValueError('Player graphics reference a tile outside the native allocation')


def adapt(rom,frames,profile=None,selected=None):
    from .tas_sprites import fit
    tas.smb_identity(rom)
    if len(frames)!=26:raise ValueError('All 26 native Mario player rows are required')
    prg=rom[16:32784];old=S._player_rows(prg);enemy={t for row in S._enemy_rows(prg) for t in row}
    pool=sorted({t for row in old for t in row}-enemy-{0xFC})
    output=bytearray(rom);tiles={};newrows=[];pictures=[]
    for index,(original,image) in enumerate(zip(old,frames)):
        top=next(i//2*8 for i,t in enumerate(original) if t!=0xFC)
        settings=profile.frames.get(str(index)) if profile is not None else None
        if settings:
            from .sprite_pair_editor import transform
            canvas=transform((selected or {}).get(index,image),top,settings)
        else:
            canvas=Image.new('RGBA',(16,32));canvas.alpha_composite(fit(image,16,32-top),(0,top))
        indices=quantize_sonic(canvas);pictures.append(indices)
        row=[]
        for i,t in enumerate(original):
            if t==0xFC:row.append(t);continue
            x,y=i%2*8,i//2*8;data=encode_tile(indices[y:y+8,x:x+8])
            if not any(data):row.append(0xFC);continue
            if data not in tiles:
                if len(tiles)>=len(pool):raise ValueError('Sprite tile budget exceeded; no lossy tile merging was applied')
                tiles[data]=pool[len(tiles)]
            row.append(tiles[data])
        newrows.extend(row)
    for data,tile in tiles.items():output[32784+tile*16:32784+(tile+1)*16]=data
    start=16+S.OFFSETS['PlayerGraphicsTable'];output[start:start+208]=bytes(newrows)
    for name in ('GroundPaletteData','WaterPaletteData','UndergroundPaletteData','CastlePaletteData'):
        off=16+S.OFFSETS[name]+3+4*4;output[off:off+4]=bytes(PALETTE)
    off=16+S.OFFSETS['Palette3Data'];output[off:off+16]=bytes(PALETTE)*4
    # GetPlayerColors rewrites palette 4 after loading the area's palette.
    # Guard the complete Mario/Luigi/fire table before changing Mario and fire.
    player_colors=bytes.fromhex('221627182230271922372716')
    if rom.count(player_colors)!=1:raise ValueError('The native player color table differs')
    color_at=rom.index(player_colors)
    output[color_at:color_at+4]=bytes(PALETTE);output[color_at+8:color_at+12]=bytes(PALETTE)
    validate_output(rom,output)
    return bytes(output),{'tiles_used':len(tiles),'tile_budget':len(pool),'palette':list(PALETTE),'rows':26,'allowed_ranges_verified':True},pictures


def preview(pictures):
    from .photo_skin import png
    rgba=np.array([[(v>>16)&255,(v>>8)&255,v&255,255 if i else 0] for i,v in enumerate(S.NES_PALETTE)])
    colors=rgba[list(PALETTE)];sheet=Image.new('RGBA',(13*72,2*136),(28,28,34,255))
    for i,a in enumerate(pictures):sheet.alpha_composite(Image.fromarray(colors[a].astype(np.uint8)).resize((64,128),Image.Resampling.NEAREST),((i%13)*72,(i//13)*136))
    return png(sheet)


class SpriteBuildIn(BaseModel):
    game_id: str=Field(default=GAME_ID,pattern='^49b6a2f65aca26a2$')
    request_id: str=Field(default='',pattern='^[a-f0-9]{0,32}$')
    request_number: int=Field(default=0,ge=0)
    candidate:str=Field(default='',pattern='^(?:[a-f0-9]{32})?$')


class SpriteBuildOut(BaseModel):
    result: dict


@tool('smb1_sprite_build','1.0',SpriteBuildIn,SpriteBuildOut,permissions=[P.EXECUTE,P.STAGE],timeout_s=180)
def run(inp,ctx):
    """Build a native portable Super Mario Bros. ROM with Sonic 2's player sprites. Never launches a game."""
    from .characters import _api
    from .tools import rom_path
    from .models import CatalogEntry
    from .filemods import mod_dir
    from . import build_record
    ctx.progress(5,'Reading the owned Mario and Sonic 2 ROMs')
    game=_api(ctx,'GET','/api/catalog/'+GAME_ID);donor=_api(ctx,'GET','/api/catalog/'+DONOR_ID)
    original=tas.rom_bytes(rom_path(CatalogEntry.model_validate(game),ctx.config))
    frames,source=sonic_frames(rom_path(CatalogEntry.model_validate(donor),ctx.config))
    ctx.progress(45,'Fitting Sonic 2 poses into native NES player tiles')
    pair=None
    if inp.candidate:
        folder=ctx.config.data_dir/'sprite-pair-candidates'/inp.candidate
        pair=json.loads((folder/'candidate.json').read_text());rom=(folder/'rom.bin').read_bytes()
        if pair['game_id']!=GAME_ID or pair['target_sha256']!=hashlib.sha256(original).hexdigest() or pair['source']!=source or hashlib.sha256(rom).hexdigest()!=pair['rom_sha256']:
            raise ValueError('This sprite-pair snapshot differs from its owned source or output; preview again')
        from .sprite_faces import decoded
        from .sprite_pair_editor import WRITER_SOURCES
        if pair.get('writer_sources')!=WRITER_SOURCES:raise ValueError('Sprite writer changed after this preview; prepare it again')
        pictures=[f[3] for f in decoded(rom,GAME_ID,reference=original)];report=pair['report']
    else:rom,report,pictures=adapt(original,frames)
    sha=hashlib.sha256(rom).hexdigest()
    name='smb1_sonic2_'+sha[:10];folder=mod_dir(ctx.config,GAME_ID,name)
    if not (folder/'.gbox-mod.json').exists():
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'Sonic in Super Mario Bros.nes').write_bytes(rom)
        (folder/'preview.png').write_bytes(preview(pictures))
        meta=build_record.stamp({'name':name,'game_id':GAME_ID,'image':'Sonic in Super Mario Bros.nes','title':'Super Mario Bros. — Sonic 2 player sprites',
            'writer':'gbox.smb1_sprite_build','character':'sonic2_sonic','built':time.time(),'source':source,'sprite_report':report,
            'sprite_pair_edit':pair,
            'requests':[inp.request_number] if inp.request_number else [],'request_id':inp.request_id,'rom_sha256':sha,'verified_in_game':False,
            'changes':[{'donor':'sonic2_sonic','slot':'player'}],'notes':'Native NES three-color adaptation. Original Mario physics, levels and enemies retained.'},
            kind='character',job_id=ctx.job_id,build_call={'tool':'smb1_sprite_build','input':inp.model_dump()})
        (folder/'.gbox-mod.json').write_text(json.dumps(meta,indent=2))
    if hashlib.sha256((folder/'Sonic in Super Mario Bros.nes').read_bytes()).hexdigest()!=sha:
        raise ValueError('Existing build bytes differ from this recipe; refusing to reuse it')
    ctx.artifact('sonic2-nes-player-preview.png',preview(pictures),'image/png',game_id=GAME_ID,mod=name)
    ctx.progress(100,'Portable NES sprite build completed; gameplay verification is separate')
    return {'result':{'game_id':GAME_ID,'mod':name,'status':'built','rom_sha256':sha,'verified':False,'sprite_report':report}}

"""LCS streamed pedestrian slots, fitted individually into one immutable disc build."""
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path

from . import gta_stories_models as M


def cached_reference(cfg, game, slot):
    """Read an exact pedestrian from an already staged base disc; never download or launch."""
    from . import char_coverage, filemods
    writer=char_coverage.writer_for(game) or {}
    if writer.get('writer')!='gbox.gta_stories_models' or not slot.startswith('ped:'):
        return None
    index=int(slot.split(':',1)[1])
    if index<1 or index>10000:raise ValueError('Invalid pedestrian model index')
    candidates=sorted(filemods.base_dir(cfg,game['game_id']).glob('*.iso'))
    if not candidates:return None
    base=candidates[0];stat=base.stat()
    key=hashlib.sha256(f'{base.resolve()}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:12]
    target=Path(cfg.cache)/'retarget_reference'/game['game_id']/f'ped_{index}_{key}.glb'
    if not target.is_file():
        disc=M.LcsDisc(base);e=entry(disc,slot)
        model=M.read_ped(disc.file_at(e['sector']));ts,_=e['txd_sector']
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.stem+'-'+uuid.uuid4().hex[:8]+'.glb')
        M.ped_to_gltf(model,M.read_chk(disc.file_at(ts)),temporary,slot)
        temporary.replace(target)
    return target


def slots(disc):
    from .gta_lcs_inventory import ped_model_infos
    return [{'slot':f"ped:{r['index']}", 'name':r['txd'], 'kind':'pedestrian',
             'writer':'gbox.gta_stories_models', 'native':r}
            for r in ped_model_infos(disc) if r['index'] and r['model_sector'] and r['model_sectors']
            and r.get('txd_sector') and r.get('txd_sectors')]


def entry(disc, slot):
    index = int(slot.split(':',1)[1])
    info = disc.model_info(index)
    if not info or info['type'] != 7 or index == 0:
        raise ValueError(f'{slot} is not a streamed pedestrian')
    sector, sectors = disc.streaming(index)
    if not sector or not sectors or info['txd_slot'] < 0:
        raise ValueError(f'{slot} has no owned streamed model/texture allocation')
    return {'name':info['txd'], 'sector':sector, 'sectors':sectors, 'index':index,
            'txd_sector':disc.streaming(4900+info['txd_slot'])}


def cast_slots_live(ctx, game):
    from . import characters as C, filemods
    rom=C._rom(ctx,game)
    iso=M.lcs_iso_from_rom(rom,filemods.base_dir(ctx.config,game['game_id'])/(Path(rom).stem+'.iso'))
    return [{'slot':'player','name':'Toni — every outfit','kind':'player','writer':'gbox.gta_stories_models'}]+slots(M.LcsDisc(iso))


def build_cast(cfg, game, rom, pairs, name, progress=None, root=None):
    from . import characters as C, filemods, fit_events as FE
    progress=progress or (lambda *_:None)
    root=Path(root or C.library_root(cfg))
    base=M.lcs_iso_from_rom(rom,filemods.base_dir(cfg,game['game_id'])/(Path(rom).stem+'.iso'),progress)
    disc=M.LcsDisc(base)
    available={s['slot'] for s in slots(disc)}
    if len({s for s,_ in pairs}) != len(pairs) or any(s not in available|{'player'} for s,_ in pairs):
        raise ValueError('Cast must contain unique streamed pedestrian slots')
    out=filemods.mod_dir(cfg,game['game_id'],name)
    if out.exists():
        raise ValueError('This build already exists; use a new build name to preserve it')
    work=Path(cfg.cache)/'characters_build'/name
    work.mkdir(parents=True,exist_ok=True)
    blender=C._blender(cfg)
    files={}; rows=[]
    FE.plan([(s,m['slug'],f"{m['name']} → {s}") for s,m in pairs])
    expanded=[(slot,entry,meta) for slot,meta in pairs for entry in (list(M.OUTFITS) if slot=='player' else [slot])]
    for k,(slot,native_slot,meta) in enumerate(expanded):
        progress(5+70*k/max(len(expanded),1),f"Fitting model {k+1}/{len(expanded)}: {native_slot} ← {meta['name']}")
        FE.model(slot)
        model=root/meta['slug']/meta['model']
        own=work/native_slot.replace(':','_');own.mkdir(exist_ok=True)
        fit=M.swap_files(disc,model,meta['rig']['roles'],native_slot,own,blender,
                        scale=meta['rig'].get('scale'))
        for sector,sectors,data in [(fit['mdl_sector'],fit['mdl_sectors'],fit['mdl']),
                                    (fit['chk_sector'],fit['chk_sectors'],fit['chk'])]:
            if sector in files and files[sector] != (sectors,data):
                raise ValueError('Two pedestrians require conflicting changes to a shared allocation; build not published')
            files[sector]=(sectors,data)
        M.ped_to_gltf(fit['model'],M.read_chk(fit['chk']),own/'fitted.glb',slot)
        rows.append({'slot':slot,'native_model':native_slot,'character':meta['slug'],'name':meta['name'],'status':'built',
                     'triangles':fit['stats']['triangles'],'mdl_bytes':len(fit['mdl']),
                     'budget_bytes':fit['mdl_sectors']*M.SECTOR,'decimated':len(fit['tried'])>1,
                     'profile':meta.get('retarget_profile_digest','')})
    if not rows:
        raise ValueError('No pedestrian assignments')
    # All slots must fit before a playable build is published. No source image is modified.
    out.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(out.parent).free < base.stat().st_size+256*1024*1024:
        raise ValueError('Not enough free space for one new disc build; no original was changed')
    staged=out.parent/('.'+name+'-staging-'+uuid.uuid4().hex[:8]);staged.mkdir(exist_ok=False)
    image=f'LCS {name}.iso'
    progress(80,'Copying the base disc after every pedestrian passed encoding checks')
    try:
        shutil.copyfile(base,staged/image)
        M.patch_iso(staged/image,disc,[(s,n,d) for s,(n,d) in files.items()])
        with open(staged/image,'rb') as handle:
            for sector,(_n,data) in files.items():
                handle.seek((disc.img_lba+sector)*M.SECTOR)
                if handle.read(len(data)) != data:
                    raise ValueError('Written disc did not match the encoded pedestrian data')
    except Exception as error:
        # Only this attempt's staging image is disposable. Keep the small diagnostic,
        # not a multi-gigabyte broken disc, and never touch the base or another build.
        partial=staged/image
        if partial.resolve().parent != staged.resolve() or staged.resolve().parent != out.parent.resolve():
            raise RuntimeError('Unexpected staging path; cleanup refused') from error
        partial.unlink(missing_ok=True)
        (staged/'failure.json').write_text(json.dumps({'error':str(error),'build':name,'published':False}))
        raise
    marker={'name':name,'game_id':game['game_id'],'image':image,'built':time.time(),
            'kind':'cast swap','writer':'gbox.gta_stories_models','files':['MODELS/GTA3PS2.IMG'],
            'cast':rows,'cast_slots':'pedestrians','coverage':{'requested':len(pairs),'built':len(pairs),
            'native_pedestrians':len(available),'complete':available.issubset({s for s,_ in pairs})},
            'source_allocations':{str(s):hashlib.sha256(disc.img_read(s,n)).hexdigest() for s,(n,_d) in files.items()},
            'replacement_scope':{'gameplay':True,'scripted_pedestrians':'same streamed model replacements',
                'special_cutscene_models':False,'prerecorded_movies':False,'complete':False},
            'validation':{'encoded_and_read_back':True,'gameplay_verified':False}}
    (staged/'.gbox-mod.json').write_text(json.dumps(marker,indent=2))
    staged.replace(out)
    progress(100,f'Built {len(rows)} pedestrian replacements in one disc; gameplay verification pending')
    return {'mod':name,'dir':str(out),'image':image,'slots':{r['slot']:r for r in rows},'coverage':marker['coverage']}

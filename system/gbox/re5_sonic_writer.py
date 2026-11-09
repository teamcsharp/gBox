"""Unregistered, bounded SA2 Sonic -> RE5 Chris-normal recipe.

Only the measured source GLB and native archive bytes are accepted. This module
returns an overlay plan; registration and gameplay acceptance are separate.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import zlib

from . import characters, mt_arc, mt_model, mtf_author, mtf_secondary, re5_mesh_import
from .re_switch import RE5_TITLE_ID

SOURCE_SHA256 = '5dd7cc07f3116a8f1f59ccc9bde8da5ccae65338cbf83d8c7151608c2ae74df4'
ARCHIVE_SHA256 = '8ab0dc181d1f6ec155e193c5820d1756d877acf711424863b16f7850b592f6c8'
ARCHIVE_PATH = 'nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc'
RECIPE_VERSION = 1
SOURCE_ROLES = {'hip':'node002', 'chest':'node033', 'head':'node044',
                'l_upper':'node037', 'l_fore':'node038', 'l_hand':'node039',
                'r_upper':'node056', 'r_fore':'node057', 'r_hand':'node058',
                'l_thigh':'node017', 'l_shin':'node019', 'l_foot':'node023',
                'r_thigh':'node007', 'r_shin':'node009', 'r_foot':'node013'}
TARGET_ANIMATION_IDS = {'hip':0, 'chest':2, 'head':4, 'l_upper':11, 'l_fore':12, 'l_hand':14,
                        'r_upper':6, 'r_fore':7, 'r_hand':9, 'l_thigh':20, 'l_shin':21, 'l_foot':22,
                        'r_thigh':16, 'r_shin':17, 'r_foot':18}


def build(archive: bytes, source: Path):
    """Return (complete native archive, receipt) without writing or launching anything."""
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('Sonic needs the exact measured sa2_sonic_0.glb; this source revision is unsupported')
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Sonic needs the exact measured original Chris-normal Switch archive')
    parsed = mt_arc.parse(archive)
    model = mt_model.parse_mod(zlib.decompress(parsed.entries[97].data))
    mapping = {animation:i for i,animation in enumerate(model.bone_table()['anim_map'])}
    roles = {name:mapping[animation] for name,animation in TARGET_ANIMATION_IDS.items()}
    authored, _, _, receipt = re5_mesh_import.build_archive(archive,source,model_name='pl0000',
        source_roles=SOURCE_ROLES,target_roles=roles,segments={},scale=1.,material_index=108,template_index=0,
        pose_mode='source_proportions',height=180.,centre_hip=True)
    secondary = []
    for path,channels in ((r'pawn\pl\pl00\model\pl00Gear_MM',(0,)),
                          (r'pawn\pl\pl00\model\pl00Gear_NM',(128,128))):
        entries = [(i,e) for i,e in enumerate(parsed.entries) if e.name == path]
        if len(entries) != 1:
            raise ValueError('the measured Gear secondary texture must have one exact native entry')
        index,entry = entries[0]
        payload = mtf_secondary.constant_channels(zlib.decompress(entry.data),channels)
        authored = mtf_author.replace_archive_model(authored,index,payload)
        secondary.append({'path':path,'channels':list(channels)})
    final = mt_arc.parse(authored)
    receipt.update(recipe_version=RECIPE_VERSION, target_archive_sha256=ARCHIVE_SHA256,
                   source_sha256=SOURCE_SHA256, secondary_maps=secondary,
                   changed_entry_indices=[i for i,(a,b) in enumerate(zip(parsed.entries,final.entries)) if a.data != b.data],
                   written_sha256=hashlib.sha256(authored).hexdigest())
    return authored,receipt


def plan(ctx,game:dict,inp,meta:dict|None):
    """An explicit Chris-normal slot and original library identity produce one tracked overlay edit."""
    from . import re5_character_writer as native, skin_swap, switch_mods
    try:
        tid = switch_mods.title_id_for(None,game.get('serial') or (game.get('launch') or {}).get('title_id'))
        if game.get('platform') != 'switch' or tid != RE5_TITLE_ID:
            raise ValueError('The Sonic recipe supports only the measured RE5 Switch title')
        if (getattr(inp,'op','use') == 'cast_swap' or getattr(inp,'pairs',None) or getattr(inp,'assignments',None)
                or getattr(inp,'head_scale',0) or getattr(inp,'scale',None) or getattr(inp,'props',None)):
            raise ValueError('The Sonic recipe replaces one explicit Chris-normal slot without additional edits')
        arcs = skin_swap.CHARACTER_ARCS[RE5_TITLE_ID]
        if native._target(inp,arcs) != 'chris':
            raise ValueError('The Sonic recipe currently supports Chris normal only')
        if not isinstance(meta,dict):
            raise ValueError('Choose the original Sonic library model')
        origin,rig = meta.get('source') or {},meta.get('rig') or {}
        if (not isinstance(origin,dict) or not isinstance(rig,dict)
                or meta.get('slug') != 'sonic' or meta.get('model') != 'sa2_sonic_0.glb'
                or origin.get('game_id') != 'd95ed7ed1e40552a' or origin.get('platform') != 'dreamcast'
                or origin.get('files') != ['SONIC2/SONICMDL.PRS','SONIC2/SONICTEX.PRS']
                or meta.get('extraction_tool') != 'gbox.sa2_chars + gbox.ninja'
                or any(meta.get(k) for k in ('variant_of','variant','props','derived_from'))
                or origin.get('variant_of') or rig.get('scale')):
            raise ValueError('The Sonic recipe requires the original SA2 library provenance, without variants or props')
        library = characters.library_root(ctx.config).resolve()
        folder = (library/'sonic').resolve()
        source = (folder/'sa2_sonic_0.glb').resolve()
        if not folder.is_relative_to(library) or not source.is_relative_to(folder) or not source.is_file():
            raise ValueError('The original Sonic GLB must exist inside its local library folder')
        root = native._romfs(ctx.config).resolve()
        target = (root/ARCHIVE_PATH).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError('The original Chris-normal archive must exist inside the owned extracted RomFS')
        payload,receipt = build(target.read_bytes(),source)
        scope = {'route':'measured_sonic_mesh_recipe', 'complete':False, 'gameplay_verified':False,
                 'source_platform':'dreamcast','written_platform':'switch','collection_model_used':True,
                 'requested_character':{'slug':'sonic','name':meta.get('name') or 'Sonic'},
                 'target_archive':ARCHIVE_PATH,'recipe':receipt,
                 'notes':['Only this source hash and Chris normal are supported; other donors and costumes are unverified',
                          'The title restarts to load the archive; the current round is not preserved']}
        return {'changes':{'romfs/'+ARCHIVE_PATH:{'bytes':payload}}, 'kind':'character',
                'replacement_scope':scope, 'slots':[{'slot':'chris','donor':'sonic','archive':ARCHIVE_PATH}],
                'note':f'measured Sonic mesh recipe v{RECIPE_VERSION}: Chris normal'}
    except (ValueError,OSError,KeyError) as exc:
        return {'reason':str(exc)}

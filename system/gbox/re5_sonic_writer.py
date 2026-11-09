"""Unregistered, bounded SA2 Sonic -> RE5 Chris-normal recipe.

Only the measured source GLB and native archive bytes are accepted. This module
returns an overlay plan; registration and gameplay acceptance are separate.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import zlib
import numpy as np

from . import characters, mt_arc, mt_model, mtf_author, mtf_secondary, mtf_motion_edit, re5_mesh_import
from . import re5_sonic_residue
from .re_switch import RE5_TITLE_ID

SOURCE_SHA256 = '5dd7cc07f3116a8f1f59ccc9bde8da5ccae65338cbf83d8c7151608c2ae74df4'
ARCHIVE_SHA256 = '8ab0dc181d1f6ec155e193c5820d1756d877acf711424863b16f7850b592f6c8'
ARCHIVE_PATH = 'nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc'
RECIPE_VERSION = 2
HEIGHT = 140.
SOURCE_ROLES = {'hip':'node002', 'chest':'node033', 'head':'node044',
                'l_upper':'node037', 'l_fore':'node038', 'l_hand':'node039',
                'r_upper':'node056', 'r_fore':'node057', 'r_hand':'node058',
                'l_thigh':'node017', 'l_shin':'node019', 'l_foot':'node023',
                'r_thigh':'node007', 'r_shin':'node009', 'r_foot':'node013'}
TARGET_ANIMATION_IDS = {'hip':0, 'chest':2, 'head':4, 'l_upper':11, 'l_fore':12, 'l_hand':14,
                        'r_upper':6, 'r_fore':7, 'r_hand':9, 'l_thigh':20, 'l_shin':21, 'l_foot':22,
                        'r_thigh':16, 'r_shin':17, 'r_foot':18}
SEGMENTS = {'l_upper':'l_fore','l_fore':'l_hand','r_upper':'r_fore','r_fore':'r_hand',
            'l_thigh':'l_shin','l_shin':'l_foot','r_thigh':'r_shin','r_shin':'r_foot'}
# The accepted v15 archive, and the SHA-256 of each uncompressed payload the recipe recomputes so a miss can name
# its cause. Every other entry is the native archive's own compressed bytes.
GRIP_ARCHIVE_SHA256 = 'd96c9c9e8efaee4cf3a0eda9f10ff12ef1515e1efd604f9c34d081cd3a80cb8a'
GRIP_PAYLOADS = (('model pl0000',97,'45f130636f32c7a403d8fb68687f19994ebf9093a55ca2d988b308f30c3c7fb9'),
                 ('BC7 albedo atlas pl00Gear_BM',34,'8a2075180a192cd2294e39f2a9d715549b8426d6bd8e40f3c3b14248b7157b8d'),
                 ('neutral mask pl00Gear_MM',35,'9e5064238b62df8d0fe9b1a3ecac2e51ac8cac9548045b337ab97fe01750b5c7'),
                 ('neutral normal pl00Gear_NM',36,'be58a3c9fd4e5b0772bc08ec1ec3c7c652724c5b5e747c3e541dbd86e8a03d85'))
# Over the SHA-256 digests of all 51 LMT payloads in entry order: 50 carry the scaled root track.
GRIP_MOTION_SHA256 = 'e7abaf818ce4985df61c5bdbf4c13a5f320b2c816d0f53b404b4c5144c513ce2'


def _repose_frames(source, model):
    """Measured source finger/thumb axes paired with native finger/thumb bases."""
    gltf,_,_,world = characters._load(source)
    names = {node.get('name'):i for i,node in enumerate(gltf['nodes'])}
    mapping = {animation:i for i,animation in enumerate(model.bone_table()['anim_map'])}
    targets = {role:mapping[animation] for role,animation in TARGET_ANIMATION_IDS.items()}
    points = {i:np.array((x,y,z)) for i,x,y,z in model.bone_world()}
    frames = {role:((0,0,1),(0,1,0),(0,0,1),(0,1,0))
              for role in ('hip','chest','head','l_foot','r_foot')}
    for side,finger_id,thumb_id in (('l',46,101),('r',30,100)):
        hand = targets[side+'_hand']
        thumb = points[mapping[thumb_id]]-points[hand]
        for part,next_part in (('upper','fore'),('fore','hand'),('hand',None)):
            role = side+'_'+part
            matrix = world[names[SOURCE_ROLES[role]]]
            direction = (points[targets[side+'_'+next_part]]-points[targets[role]]) if next_part else \
                        points[mapping[finger_id]]-points[hand]
            frames[role] = (matrix[:3,0],-matrix[:3,1],direction,thumb)
    return frames


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
    authored, authored_model, _, receipt = re5_mesh_import.build_archive(archive,source,model_name='pl0000',
        source_roles=SOURCE_ROLES,target_roles=roles,segments=SEGMENTS,scale=1.,material_index=108,template_index=0,
        pose_mode='source_reposed',height=HEIGHT,centre_hip=True,repose_frames=_repose_frames(source,model),
        retarget_root_translation=True)
    # The bind tables carry BLAS rounding residue; the reviewed v12 bytes are the authoring kernel's.
    settled = re5_sonic_residue.settle(authored_model)
    if settled != authored_model:
        authored, authored_model = mtf_author.replace_archive_model(authored,97,settled), settled
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
    root_before = model.bone_world()[0][2]
    root_after = mt_model.parse_mod(authored_model).bone_world()[0][2]
    if root_before <= 0 or root_after <= 0:
        raise ValueError('the measured root height must remain positive')
    scale = root_after/root_before
    motion = []
    for index,entry in enumerate(parsed.entries):
        payload = zlib.decompress(entry.data)
        if payload[:4] != b'LMT\0':
            continue
        edited,report = mtf_motion_edit.scale_root_y(payload,scale)
        motion.append({'entry':index,'name':entry.name,**report})
        if edited != payload:
            authored = mtf_author.replace_archive_model(authored,index,edited)
    final = mt_arc.parse(authored)
    receipt.setdefault('bind_skeleton',{}).update(animation_channels_changed=True,
                                                root_translation_retarget_completed=True)
    receipt.update(recipe_version=RECIPE_VERSION, target_archive_sha256=ARCHIVE_SHA256,
                   source_sha256=SOURCE_SHA256, secondary_maps=secondary,
                   root_motion={'scale_y':scale,'root_bind_before':root_before,'root_bind_after':root_after,
                                'resources':motion},
                   acceptance='experimental; live hand, weapon, leg and camera checks incomplete',
                   gameplay_verified=False,writer_registered=False,
                   changed_entry_indices=[i for i,(a,b) in enumerate(zip(parsed.entries,final.entries)) if a.data != b.data],
                   written_sha256=hashlib.sha256(authored).hexdigest())
    return authored,receipt


def build_finger_candidate(archive:bytes,source:Path,*,correct_wrist:bool=False):
    """Unregistered next experiment: v12 body plus a measured five-digit glove rig.

    This is intentionally separate from build()/plan(): runtime grip, native
    weapon attachment and foot checks have not accepted the finger candidate.
    """
    from . import re5_sonic_hands
    authored,receipt = build(archive,source)
    model = zlib.decompress(mt_arc.parse(authored).entries[97].data)
    model,fingers = re5_sonic_hands.author(model,source,receipt['skin'],correct_wrist=correct_wrist)
    authored = mtf_author.replace_archive_model(authored,97,model)
    return authored,receipt | {'finger_recipe_version':2 if correct_wrist else 1,'finger_rig':fingers,
                              'envelope_count':fingers['envelope_count'],
                              'written_sha256':hashlib.sha256(authored).hexdigest(),
                              'acceptance':'experimental finger rig; native weapon grip and live animation unverified',
                              'gameplay_verified':False,'writer_registered':False}


def build_grip_candidate(archive:bytes,source:Path):
    """Unregistered v15 experiment; the default recipe remains unchanged."""
    from . import re5_sonic_grip
    authored,receipt = build_finger_candidate(archive,source,correct_wrist=True)
    model = zlib.decompress(mt_arc.parse(authored).entries[97].data)
    native = zlib.decompress(mt_arc.parse(archive).entries[97].data)
    model,grip = re5_sonic_grip.author(model,native,source,receipt['skin'])
    authored = mtf_author.replace_archive_model(authored,97,model)
    written = hashlib.sha256(authored).hexdigest()
    return authored,receipt | {'grip_recipe_version':1,'grip_fit':grip,
                              'envelope_count':grip['envelope_count'],
                              'written_sha256':written,'reviewed_sha256':GRIP_ARCHIVE_SHA256,
                              'reproduces_reviewed':written == GRIP_ARCHIVE_SHA256,
                              'acceptance':'experimental v15 grip fit; runtime weapon contact remains unverified',
                              'gameplay_verified':False,'writer_registered':False}


def grip_reproduction(archive:bytes):
    """Whether ``archive`` is the accepted v15 archive; a miss names the recomputed payloads that differ.

    The model is rebuilt identically under every BLAS kernel measured (see ``re5_sonic_residue``). The atlas blocks
    come from the native BC7 encoder and the entry framing from the linked zlib, which this recipe cannot make
    portable, so an unmeasured platform can still miss the archive hash; this separates those causes without the
    artifact at hand.
    """
    written = hashlib.sha256(archive).hexdigest()
    report = {'reviewed_sha256':GRIP_ARCHIVE_SHA256,'written_sha256':written,'exact':written == GRIP_ARCHIVE_SHA256}
    if report['exact']:
        return report
    payloads = [zlib.decompress(entry.data) for entry in mt_arc.parse(archive).entries]
    differing = [name for name,index,expected in GRIP_PAYLOADS
                 if index >= len(payloads) or hashlib.sha256(payloads[index]).hexdigest() != expected]
    motion = hashlib.sha256(b''.join(hashlib.sha256(p).digest() for p in payloads if p[:4] == b'LMT\0'))
    if motion.hexdigest() != GRIP_MOTION_SHA256:
        differing.append('root motion LMT')
    return report | {'differing_payloads':differing,
                     'cause':'recomputed payloads differ: '+', '.join(differing) if differing else
                             'every recomputed payload matches; zlib framing or a native entry differs'}


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
                 'notes':['Experimental recipe; visible animation, weapon attachment and camera acceptance remain incomplete',
                          'Only this source hash and Chris normal are supported; other donors and costumes are unverified',
                          'The title restarts to load the archive; the current round is not preserved']}
        return {'changes':{'romfs/'+ARCHIVE_PATH:{'bytes':payload}}, 'kind':'character',
                'replacement_scope':scope, 'slots':[{'slot':'chris','donor':'sonic','archive':ARCHIVE_PATH}],
                'note':f'experimental Sonic mesh recipe v{RECIPE_VERSION}: Chris normal'}
    except (ValueError,OSError,KeyError) as exc:
        return {'reason':str(exc)}

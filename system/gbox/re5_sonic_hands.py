"""Experimental digit rig for the measured SA2 Sonic / RE5 v12 model only.

This does not register a writer, change weapon attachment offsets, or claim engine
IK parity. The source has five geometric digits but no separate finger weights.
"""
from __future__ import annotations

import collections
import hashlib
import heapq
import math
from pathlib import Path
import numpy as np

from . import characters, mt_model, mtf_author, mtf_materials, mtf_motion, mtf_retarget, re5_sonic_residue

SOURCE_SHA256 = '5dd7cc07f3116a8f1f59ccc9bde8da5ccae65338cbf83d8c7151608c2ae74df4'
BASE_MOD_SHA256 = 'b87ecc87d3fb414f4692dd1d237f949d7b7db6bd969c028e43669ea5d199d3fb'
CHAINS = {
    'left': {'index': (43,44,45), 'middle': (46,47,48), 'ring': (50,51,52),
             'little': (53,54,55), 'thumb': (40,41,42)},
    'right': {'index': (27,28,29), 'middle': (30,31,32), 'ring': (34,35,36),
              'little': (37,38,39), 'thumb': (24,25,26)},
}


def _smooth(value):
    t = float(np.clip(value,0.,1.))
    return t*t*(3-2*t)


def _components(nodes, adjacency):
    remaining, result = set(nodes), []
    while remaining:
        pending = [remaining.pop()]
        component = set(pending)
        while pending:
            found = set(adjacency[pending.pop()]) & remaining
            remaining -= found
            component |= found
            pending.extend(found)
        result.append(sorted(component))
    return result


def _distances(points, adjacency, seeds):
    distances = np.full(len(points),np.inf)
    pending = []
    for i in seeds:
        distances[i] = 0.
        heapq.heappush(pending,(0.,i))
    while pending:
        distance,i = heapq.heappop(pending)
        if distance != distances[i]:
            continue
        for j in adjacency[i]:
            updated = distance + float(np.linalg.norm(points[j]-points[i]))
            if updated < distances[j]:
                distances[j] = updated
                heapq.heappush(pending,(updated,j))
    return distances


def _landmarks(points, adjacency, side):
    """Four separate distal lobes; the fifth digit is the measured side thumb."""
    components = _components(np.flatnonzero(points[:,0] > 2.35),adjacency)
    if len(components) != 4:
        raise ValueError('measured Sonic glove must expose exactly four finger lobes')
    components.sort(key=lambda c:float(points[c,1].mean()))
    palm_sign = 1 if side == 'left' else -1
    layouts = {}
    for name,component in zip(('index','middle','ring','little'),components):
        boundary = {j for i in component for j in adjacency[i] if j not in component and points[j,0] <= 2.35}
        if len(boundary) < 4:
            raise ValueError('finger base ring is incomplete')
        # The curved little fingertip returns below the X cutoff. Its distal
        # vertices must not be mistaken for the MCP ring beside the palm.
        boundary = sorted(boundary,key=lambda i:points[i,2]*palm_sign,reverse=True)[:4]
        signed = points[component,2]*palm_sign
        split = np.median(signed)
        proximal = np.asarray(component)[signed >= split]
        distal = np.asarray(component)[signed < split]
        landmarks = np.array((points[boundary].mean(0),points[proximal].mean(0),points[distal].mean(0)))
        if (np.linalg.norm(np.diff(landmarks,axis=0),axis=1) < .15).any():
            raise ValueError('finger landmarks collapse a phalanx')
        layouts[name] = {'points':landmarks,'seeds':component,
                         'distances':_distances(points,adjacency,component)}
    thumb = np.flatnonzero((points[:,1] < -.65) & (points[:,0] > 1.1) & (points[:,0] < 2.05))
    if len(thumb) != 6:
        raise ValueError('measured Sonic thumb must have two three-vertex rings')
    thumb = sorted(thumb,key=lambda i:points[i,0])
    base,tip = points[thumb[:3]].mean(0),points[thumb[3:]].mean(0)
    layouts['thumb'] = {'points':np.array((base,base+(tip-base)*.6,tip)), 'seeds':thumb,
                       'distances':_distances(points,adjacency,thumb)}
    return layouts


def _chain_weights(point, anchors):
    """Blend at the two measured joints; retain one to two adjacent influences."""
    lengths = np.linalg.norm(np.diff(anchors,axis=0),axis=1)
    if (lengths < 1e-8).any():
        raise ValueError('digit chain contains a zero-length segment')
    options = []
    for i in range(2):
        vector = anchors[i+1]-anchors[i]
        t = float(np.clip((point-anchors[i])@vector/(vector@vector),0.,1.))
        projected = anchors[i]+t*vector
        options.append((float(np.linalg.norm(point-projected)),sum(lengths[:i])+t*lengths[i]))
    distance = min(options)[1]
    radius = min(lengths)*.3
    if distance < lengths[0]-radius:
        return [(0,1.)]
    if distance <= lengths[0]+radius:
        amount = _smooth((distance-lengths[0]+radius)/(2*radius))
        return [(0,1-amount),(1,amount)]
    amount = _smooth((distance-sum(lengths)+radius)/(2*radius))
    return [(1,1-amount),(2,amount)]


def _proper_rotation(direction, across, target_direction, target_across):
    source = mtf_retarget.direction_frame(direction,across)
    target = mtf_retarget.direction_frame(target_direction,target_across)
    rotation = target @ source.T
    if abs(np.linalg.det(rotation)-1.) > 1e-8:
        raise ValueError('digit repose must not reflect the source surface')
    return rotation


def author(model_bytes:bytes, source:Path, skin_receipt:dict, *, correct_wrist:bool=False):
    """Return an unregistered experimental MOD and a complete measured rig receipt."""
    if hashlib.sha256(model_bytes).hexdigest() != BASE_MOD_SHA256:
        raise ValueError('digit experiment requires the exact reviewed v12 MOD')
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('digit experiment requires the exact measured Sonic GLB')
    model = mt_model.parse_mod(model_bytes)
    records = model.meshes()
    if len(records) != 1 or records[0]['vertex_format'] != 0x2000D414:
        raise ValueError('digit experiment requires the measured single four-weight mesh')
    original,triangles,_,_ = mtf_materials.source_mesh(source)
    positions,normals,uvs = model.positions(0),model.normals(0),model.uvs(0)
    if len(original) != len(positions) or len(original) != 1422:
        raise ValueError('source seam ordering differs from the reviewed v12 mesh')
    raw,record = model.mesh_bytes(0)
    bindings = mtf_motion._influences(raw,record,model.header()['bone_count'])
    vertices = [dict(position=p,normal=n,uv=uv,bones=[b for b,w in row],weights=[w for b,w in row])
                for p,n,uv,row in zip(positions,normals,uvs,bindings)]
    table = model.bone_table()
    mapping = {aid:i for i,aid in enumerate(table['anim_map']) if aid != 255}
    world = np.asarray(model.bone_world_matrices()).reshape(-1,4,4)
    anchors = {i:matrix[3,:3].copy() for i,matrix in enumerate(world)}
    gltf,_,_,source_world = characters._load(source)
    scale = float(skin_receipt['total_uniform_scale'])
    edited,weight_only,details,wrist_changes = set(),set(),{},[]
    for side,hand_node,glove_node,hand_id,base_id,meta_id in (
            ('left',43,46,14,101,49),('right',62,65,9,100,33)):
        role = 'l_hand' if side == 'left' else 'r_hand'
        hand = mapping[hand_id]
        rotation = np.asarray(skin_receipt['rotations'][role])
        transform = rotation @ source_world[hand_node][:3,:3]*scale
        origin = world[hand,3,:3]
        inverse = np.linalg.inv(source_world[hand_node])
        unique,indices = {},{}
        for i,vertex in enumerate(original):
            if glove_node not in vertex['source_joints']:
                continue
            if tuple(vertex['source_joints']) != (glove_node,) or tuple(vertex['source_weights']) != (1.,):
                raise ValueError('glove source weights differ from the measured rigid source')
            point = (inverse @ np.array((*vertex['position'],1.)))[:3]
            key = tuple(np.round(point,5))
            indices[i] = unique.setdefault(key,len(unique))
            if np.linalg.norm(origin+transform@point-np.asarray(positions[i])) > .01:
                raise ValueError('source hand transform does not match the reviewed v12 geometry')
        points = np.asarray(list(unique))
        if len(points) != 66:
            raise ValueError('glove topology differs from the measured 66 welded positions')
        adjacency = collections.defaultdict(set)
        for triangle in triangles:
            if all(i in indices for i in triangle):
                for a,b in zip(triangle,(*triangle[1:],triangle[0])):
                    adjacency[indices[a]].add(indices[b]);adjacency[indices[b]].add(indices[a])
        layouts = _landmarks(points,adjacency,side)
        if correct_wrist:
            # 039/058 carries forearm skin. Its child040/059 is the actual
            # glove/cuff pivot, .596828 source units farther along the arm.
            cuff_node = hand_node+1
            cuff = (inverse @ np.array((*source_world[cuff_node][:3,3],1.)))[:3]
            if abs(cuff[0]-.5968279838562012)>1e-6 or np.linalg.norm(cuff[1:])>1e-6:
                raise ValueError('measured Sonic cuff pivot differs')
            twist = mapping[8 if side=='right' else 13]
            if table['parents'][hand] != twist:
                raise ValueError('native wrist no longer follows the measured forearm twist bone')
            if np.linalg.norm(world[twist,3,:3]-origin)>1e-5:
                raise ValueError('reviewed forearm twist must remain at the old wrist pivot')
            anchors[hand] = origin+transform@cuff
            moved_weights = 0
            for i,vertex in enumerate(original):
                if hand_node not in vertex['source_joints']:
                    continue
                row = [(twist if bone==hand else bone,weight)
                       for bone,weight in zip(vertices[i]['bones'],vertices[i]['weights'])]
                merged = collections.defaultdict(float)
                for bone,weight in row:
                    merged[bone]+=weight
                vertices[i].update(bones=list(merged),weights=list(merged.values()))
                edited.add(i);weight_only.add(i);moved_weights+=1
            wrist_changes.append({'side':side,'native_wrist_id':hand_id,
                                  'source_forearm_node':hand_node,'source_cuff_node':cuff_node,
                                  'old_position':origin.tolist(),'new_position':anchors[hand].tolist(),
                                  'advance_cm':float(np.linalg.norm(anchors[hand]-origin)),
                                  'twist_position_unchanged':True,
                                  'forearm_vertices_reweighted':moved_weights,
                                  'forearm_twist_animation_id':8 if side=='right' else 13})
        target_across = world[mapping[CHAINS[side]['little'][0]],3,:3]-world[mapping[CHAINS[side]['index'][0]],3,:3]
        source_across = transform @ np.array((0.,1.,0.))
        changes,weights_by_point,side_details = {},{},{}
        for name,layout in layouts.items():
            ids = [mapping[aid] for aid in CHAINS[side][name]]
            source_anchors = np.array([origin+transform@point for point in layout['points']])
            new = [source_anchors[0]]
            rotations = []
            for j in range(3):
                k = min(j,1)
                direction = source_anchors[k+1]-source_anchors[k]
                target_direction = world[ids[k+1],3,:3]-world[ids[k],3,:3]
                rot = _proper_rotation(direction,source_across,target_direction,target_across)
                rotations.append(rot)
                if j < 2:
                    new.append(new[-1]+rot@direction)
            for bone,anchor,source_anchor,rot in zip(ids,new,source_anchors,rotations):
                anchors[bone] = anchor
                changes[bone] = (source_anchor,anchor,rot)
            side_details[name] = {'animation_ids':list(CHAINS[side][name]),
                                  'source_local_landmarks':layout['points'].tolist(),
                                  'native_bind_anchors':[a.tolist() for a in new],
                                  'rotation_determinants':[float(np.linalg.det(r)) for r in rotations]}
        # These native branch parents must move with the enlarged source palm;
        # they keep their original orientations and hierarchy.
        anchors[mapping[base_id]] = origin+transform@np.array((1.,-.45,0.))
        anchors[mapping[meta_id]] = origin+transform@np.array((1.2,.3,0.))
        for index,point in enumerate(points):
            if point[1] < -.65 and 1.1 < point[0] < 2.05:
                digit,amount = 'thumb',_smooth((-point[1]-.55)/.25)*_smooth((point[0]-1.05)/.25)
            elif point[0] > 1.95:
                digit = min(('index','middle','ring','little'),key=lambda d:layouts[d]['distances'][index])
                amount = _smooth((point[0]-1.95)/.4)
            else:
                weights_by_point[index] = [(hand,1.)]
                continue
            digit_weights = _chain_weights(point,layouts[digit]['points'])
            row = [(hand,1-amount)]+[(mapping[CHAINS[side][digit][j]],weight*amount) for j,weight in digit_weights]
            weights_by_point[index] = [(bone,weight) for bone,weight in row if weight > 1e-12]
        for i,index in indices.items():
            row = weights_by_point[index]
            point,normal = np.asarray(positions[i]),np.asarray(normals[i])
            moved,turned = np.zeros(3),np.zeros(3)
            for bone,weight in row:
                if bone == hand:
                    moved += point*weight;turned += normal*weight
                else:
                    before,after,rotation = changes[bone]
                    moved += (after+rotation@(point-before))*weight
                    turned += rotation@normal*weight
            turned /= np.linalg.norm(turned)
            vertices[i].update(position=tuple(moved),normal=tuple(turned),bones=[b for b,w in row],weights=[w for b,w in row])
            if any(b != hand for b,w in row):
                edited.add(i)
        details[side] = side_details
    rebuilt,bind = mtf_retarget.reposition_bind_pose(model,anchors)
    low = np.min([v['position'] for v in vertices],axis=0);high = np.max([v['position'] for v in vertices],axis=0)
    centre = (low+high)/2
    bounds = {'min':dict(zip('xyz',low)),'max':dict(zip('xyz',high)),
              'sphere':dict(zip('xyz',centre))|{'r':max(float(np.linalg.norm(np.asarray(v['position'])-centre)) for v in vertices)}}
    output = mtf_author.build_one_mesh(rebuilt,vertices,triangles,material_index=record['material_index'],four_weights=True)
    output = mt_model.rebuild_mod(mt_model.parse_mod(output),bounds=bounds)
    parsed = mt_model.parse_mod(output)
    # Preserve every non-digit attribute byte, including v12 source normals,
    # tangent handedness, UVs and quantized body skin weights.
    buffer = bytearray(parsed.mesh_bytes(0)[0])
    for i in range(len(vertices)):
        if i not in edited:
            buffer[i*28:(i+1)*28] = raw[i*28:(i+1)*28]
        elif i in weight_only:
            for start,end in ((0,6),(8,16),(20,24)):
                buffer[i*28+start:i*28+end] = raw[i*28+start:i*28+end]
    output = mt_model.rebuild_mod(parsed,vertex_buffer=bytes(buffer))
    parsed = mt_model.parse_mod(output)
    local = mtf_author.bone_local_points(parsed,0,parsed.positions(0))
    centre = (np.min(local,axis=0)+np.max(local,axis=0))/2
    radius = max(float(np.linalg.norm(np.asarray(p)-centre)) for p in local)
    import struct
    data = bytearray(output)
    struct.pack_into('<4f',data,parsed.header()['offsets']['groups']+16,*centre,radius)
    # The rebuilt bind tables carry BLAS rounding residue; the reviewed v14 bytes are the authoring kernel's.
    output = re5_sonic_residue.settle(bytes(data))
    return output,{'experimental':True,'writer_registered':False,'gameplay_verified':False,
                   'source_sha256':SOURCE_SHA256,'base_mod_sha256':BASE_MOD_SHA256,
                   'written_mod_sha256':hashlib.sha256(output).hexdigest(),'edited_vertices':len(edited),
                   'body_vertex_attributes_unchanged':not weight_only,'body_geometry_unchanged':True,
                   'forearm_weight_only_vertices':len(weight_only),'digits':details,'bind':bind,
                   'wrist_pivot_correction':wrist_changes,
                   'envelope_count':parsed.header()['weight_bound_count'],
                   'weapon_attachment_changed':False,'feet_changed':False,
                   'limitations':['Native weapon grip offset and procedural IK are unverified']}

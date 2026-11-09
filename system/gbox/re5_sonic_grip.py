"""Experimental native grip fit for the exact reviewed Sonic v14 gloves.

The arm, wrist pivot, proximal cuff and animation channels stay unchanged. A
measured palm fit and native finger anchors reduce the oversized contact space.
This module neither registers a writer nor claims runtime weapon contact.
"""
from __future__ import annotations

import collections
import hashlib
from pathlib import Path
import numpy as np

from . import characters, mt_model, mtf_author, mtf_materials, mtf_motion, mtf_retarget, re5_sonic_residue
from .re5_sonic_hands import CHAINS, SOURCE_SHA256

V14_MOD_SHA256 = '426ac8adbad137b8ad42e1b3748d1fb56e5b1f87664ac0acc6626ad6ad241d56'
NATIVE_MOD_SHA256 = '447c2b7f537a062f5ab4049d673411bff78707cd24b21a7cfcf2552894f4b09c'
CUFF_START, CUFF_END = .45, .95


def _similarity(source, target):
    """Wrist-centered proper rotation and uniform scale; never reflect a hand."""
    source, target = np.asarray(source, float), np.asarray(target, float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ValueError('palm anchors must be matching XYZ rows')
    if not np.isfinite(source).all() or not np.isfinite(target).all() or np.linalg.matrix_rank(source) < 3:
        raise ValueError('palm anchors must span a finite three-dimensional frame')
    u, _, vt = np.linalg.svd(source.T @ target)
    if np.linalg.det(u @ vt) < 0:
        u[:, -1] *= -1
    rotation = (u @ vt).T
    scale = float(np.sum((source @ rotation.T)*target)/np.sum(source*source))
    if not np.isfinite(scale) or scale <= 0 or abs(np.linalg.det(rotation)-1) > 1e-8:
        raise ValueError('palm fit must have positive scale and a proper rotation')
    return scale, rotation


def _segment_matrix(before, after, transverse_scale):
    """Fit native phalanx length while preserving its already native direction."""
    before, after = np.asarray(before, float), np.asarray(after, float)
    a, b = np.linalg.norm(before), np.linalg.norm(after)
    if min(a, b, transverse_scale) <= 1e-8:
        raise ValueError('finger segment must retain positive length and width')
    direction = before/a
    if float(direction @ (after/b)) < 1-1e-8:
        raise ValueError('grip fit must retain the measured native phalanx direction')
    return transverse_scale*np.eye(3)+(b/a-transverse_scale)*np.outer(direction, direction)


def _cuff_map(point, origin, matrix, source_x, source_x_gradient):
    """Smooth cuff taper and its Jacobian, including the changing blend weight."""
    point, origin, matrix = np.asarray(point), np.asarray(origin), np.asarray(matrix)
    u = float(np.clip((source_x-CUFF_START)/(CUFF_END-CUFF_START), 0, 1))
    amount = u*u*(3-2*u)
    gradient = 6*u*(1-u)/(CUFF_END-CUFF_START)*np.asarray(source_x_gradient)
    displacement = (matrix-np.eye(3)) @ (point-origin)
    jacobian = np.eye(3)+amount*(matrix-np.eye(3))+np.outer(displacement, gradient)
    if np.linalg.det(jacobian) <= 1e-8:
        raise ValueError('cuff transition folds or collapses the glove')
    return point+amount*displacement, jacobian


def author(model_bytes: bytes, native_bytes: bytes, source: Path, skin_receipt: dict):
    """Return a bounded, unregistered v15 MOD and measured deformation receipt."""
    if hashlib.sha256(model_bytes).hexdigest() != V14_MOD_SHA256:
        raise ValueError('grip fit requires the exact reviewed v14 MOD')
    if hashlib.sha256(native_bytes).hexdigest() != NATIVE_MOD_SHA256:
        raise ValueError('grip fit requires the exact original Chris-normal MOD')
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('grip fit requires the exact measured Sonic GLB')
    model, native = mt_model.parse_mod(model_bytes), mt_model.parse_mod(native_bytes)
    if len(model.meshes()) != 1 or model.meshes()[0]['vertex_format'] != 0x2000D414:
        raise ValueError('grip fit requires the measured v14 vertex layout')
    table, native_table = model.bone_table(), native.bone_table()
    if table['parents'] != native_table['parents'] or table['anim_map'] != native_table['anim_map']:
        raise ValueError('grip fit requires the measured native bone hierarchy')
    mapping = {a:i for i,a in enumerate(table['anim_map']) if a != 255}
    world = np.asarray(model.bone_world_matrices()).reshape(-1,4,4)
    native_world = np.asarray(native.bone_world_matrices()).reshape(-1,4,4)
    anchors = {i:m[3,:3].copy() for i,m in enumerate(world)}
    original, triangles, _, _ = mtf_materials.source_mesh(source)
    if len(original) != 1422 or triangles != mtf_author.mesh_triangles(model,0):
        raise ValueError('source seam ordering differs from v14')
    raw, record = model.mesh_bytes(0)
    influences = mtf_motion._influences(raw, record, table['bone_count'])
    vertices = [dict(position=p, normal=n, uv=uv, bones=[b for b,w in row], weights=[w for b,w in row])
                for p,n,uv,row in zip(model.positions(0),model.normals(0),model.uvs(0),influences)]
    _, _, _, source_world = characters._load(source)
    edited, proximal, details, descendants = set(), set(), {}, set()
    for side, source_hand, glove, wrist_id, base_id, meta_id in (
            ('right',62,65,9,100,33), ('left',43,46,14,101,49)):
        wrist = mapping[wrist_id]
        origin, native_origin = world[wrist,3,:3], native_world[wrist,3,:3]
        if np.max(abs(world[wrist,:3,:3]-native_world[wrist,:3,:3])) > 1e-6:
            raise ValueError('wrist orientation differs from the native animation frame')
        chains = CHAINS[side]
        palm_ids = [chains[d][0] for d in ('index','middle','ring','little','thumb')]
        old = np.array([world[mapping[a],3,:3]-origin for a in palm_ids])
        target = np.array([native_world[mapping[a],3,:3]-native_origin for a in palm_ids])
        scale, rotation = _similarity(old,target)
        if not .40 < scale < .43:
            raise ValueError('measured palm fit lies outside the reviewed size range')
        palm_matrix = scale*rotation
        bones = {mapping[a] for chain in chains.values() for a in chain} | {mapping[base_id],mapping[meta_id]}
        pending = [i for i,parent in enumerate(table['parents']) if parent == wrist]
        actual = set()
        while pending:
            i = pending.pop(); actual.add(i)
            pending.extend(j for j,parent in enumerate(table['parents']) if parent == i)
        if actual != bones:
            raise ValueError('native wrist descendants differ from measured digit chains')
        descendants |= bones
        for bone in bones:
            anchors[bone] = origin+native_world[bone,3,:3]-native_origin
        matrices = {}
        for chain in chains.values():
            for j, aid in enumerate(chain):
                k = min(j,1); a,b = (mapping[chain[k]],mapping[chain[k+1]])
                matrices[mapping[aid]] = _segment_matrix(world[b,3,:3]-world[a,3,:3],
                    anchors[b]-anchors[a],scale)
        role = 'r_hand' if side == 'right' else 'l_hand'
        transform = np.asarray(skin_receipt['rotations'][role]) @ source_world[source_hand][:3,:3]
        transform *= float(skin_receipt['total_uniform_scale'])
        gradient = np.linalg.inv(transform)[0]
        inverse_source = np.linalg.inv(source_world[source_hand])
        selected = [i for i,v in enumerate(original) if glove in v['source_joints']]
        if len(selected) != (194 if side == 'right' else 190):
            raise ValueError('source glove corner count differs')
        min_det = float('inf')
        kept = 0
        for i in selected:
            source_point = (inverse_source @ np.array((*original[i]['position'],1)))[:3]
            point, normal = np.array(vertices[i]['position']), np.array(vertices[i]['normal'])
            if source_point[0] <= CUFF_START:
                if influences[i] != [(wrist,1.)]:
                    raise ValueError('proximal cuff must follow only the unchanged wrist')
                proximal.add(i); kept += 1
                continue
            moved, jacobian = np.zeros(3), np.zeros((3,3))
            for bone, weight in influences[i]:
                if bone == wrist:
                    transformed, matrix = _cuff_map(point,origin,palm_matrix,source_point[0],gradient)
                elif bone in matrices:
                    matrix = matrices[bone]
                    transformed = anchors[bone]+matrix@(point-world[bone,3,:3])
                elif bone == 0 and weight < .0002:
                    # The measured four-weight encoding leaves a tiny implicit
                    # rounding remainder on zero-padded bone0. Preserve it.
                    matrix, transformed = np.eye(3), point
                else:
                    raise ValueError('glove has an unreviewed influence')
                moved += weight*transformed
                jacobian += weight*matrix
            determinant = float(np.linalg.det(jacobian))
            if determinant <= 1e-8:
                raise ValueError('finger blend folds or collapses the surface')
            min_det = min(min_det,determinant)
            turned = np.linalg.solve(jacobian.T,normal)
            turned /= np.linalg.norm(turned)
            vertices[i].update(position=tuple(moved),normal=tuple(turned))
            edited.add(i)
        details[side] = {'palm_uniform_scale':scale,'palm_rotation':rotation.tolist(),
            'palm_rotation_degrees':float(np.degrees(np.arccos(np.clip((np.trace(rotation)-1)/2,-1,1)))),
            'native_palm_anchor_fit_residual_cm':np.linalg.norm(old@rotation.T*scale-target,axis=1).tolist(),
            'proximal_cuff_corners_unchanged':kept,'minimum_deformation_jacobian_determinant':min_det,
            'finger_animation_ids':[a for chain in chains.values() for a in chain],
            'native_digit_anchors_exact':True,'native_phalanx_directions_preserved':True}
    rebound, bind = mtf_retarget.reposition_bind_pose(model,anchors)
    output = mtf_author.build_one_mesh(rebound,vertices,triangles,material_index=record['material_index'],four_weights=True)
    parsed = mt_model.parse_mod(output)
    buffer = bytearray(parsed.mesh_bytes(0)[0])
    for i in range(len(vertices)):
        if i not in edited:
            buffer[i*28:(i+1)*28] = raw[i*28:(i+1)*28]
    # The rebuilt bind tables carry BLAS rounding residue; the reviewed v15 bytes are the authoring kernel's.
    output = re5_sonic_residue.settle(mt_model.rebuild_mod(parsed,vertex_buffer=bytes(buffer)))
    parsed = mt_model.parse_mod(output)
    positions = np.asarray(parsed.positions(0)); old_positions = np.asarray(model.positions(0))
    faces = np.asarray(triangles)
    cross = np.cross(positions[faces[:,1]]-positions[faces[:,0]],positions[faces[:,2]]-positions[faces[:,0]])
    old_cross = np.cross(old_positions[faces[:,1]]-old_positions[faces[:,0]],old_positions[faces[:,2]]-old_positions[faces[:,0]])
    areas = np.linalg.norm(cross,axis=1)/2
    orientation = np.einsum('ij,ij->i',cross,old_cross)/(np.linalg.norm(cross,axis=1)*np.linalg.norm(old_cross,axis=1))
    if min(areas) < 1e-5 or min(orientation) <= 0:
        raise ValueError('grip fit collapses or reverses a source triangle')
    seams = collections.defaultdict(list)
    for i,p in enumerate(old_positions):
        seams[tuple(p)].append(i)
    seam_error = max(float(np.max(np.linalg.norm(positions[group]-positions[group[0]],axis=1))) for group in seams.values())
    if seam_error > 1e-5:
        raise ValueError('grip fit opens a welded source seam')
    new_world = np.asarray(parsed.bone_world_matrices()).reshape(-1,4,4)
    unchanged = sorted(set(range(len(world)))-descendants)
    if np.max(abs(new_world[unchanged]-world[unchanged])) > 2e-5:
        raise ValueError('grip fit changed an arm or wrist transform')
    return output, {'experimental':True,'writer_registered':False,'gameplay_verified':False,
        'source_sha256':SOURCE_SHA256,'base_mod_sha256':V14_MOD_SHA256,'native_mod_sha256':NATIVE_MOD_SHA256,
        'written_mod_sha256':hashlib.sha256(output).hexdigest(),'hands':details,'bind':bind,
        'edited_glove_corners':len(edited),'unchanged_proximal_cuff_corners':len(proximal),
        'body_arm_wrist_unchanged':True,'animation_channels_changed':False,
        'minimum_triangle_area_cm2':float(min(areas)),'minimum_triangle_orientation_cosine':float(min(orientation)),
        'source_seam_max_gap_cm':seam_error,'envelope_count':parsed.header()['weight_bound_count'],
        'limitations':['Native palm dimensions are fitted; outer glove size changes substantially',
                       'Runtime weapon contact and layered finger animation remain unverified']}

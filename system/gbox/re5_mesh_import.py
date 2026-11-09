"""Experimental, unregistered RE5 donor-mesh import with explicit rig correspondence.

Returns archive bytes and evidence for review. It never installs an overlay or
claims live acceptance; arbitrary collection writers remain gated elsewhere.
"""
from __future__ import annotations

from pathlib import Path
import zlib
import math
import struct
import hashlib

from . import characters, mt_arc, mt_model, mtf_author, mtf_materials, mtf_mrl, mtf_retarget, mtf_tex


def build_archive(archive: bytes, source: Path, *, model_name: str, source_roles: dict[str, str],
                  target_roles: dict[str, int], segments: dict[str, str], scale: float,
                  material_index: int = 0, template_index: int = 0, continuous: bool = False,
                  pose_mode: str = 'native_segments', height: float = 180., centre_hip: bool = False,
                  repose_frames: dict | None = None, retarget_root_translation: bool = False,
                  role_scales: dict[str, float] | None = None, role_offsets: dict[str, tuple] | None = None,
                  orphan_role: str | None = None):
    """Return (archive, MOD, atlas, receipt), using caller-reviewed roles and native material.

    Source roles name GLB nodes; target roles name native bone indices. Every source
    influence must resolve through an explicit ancestor. Geometry and all positive
    influences survive; native four-weight encoding refuses a larger merged set.
    ``source_proportions`` preserves the donor surface at explicit height and edits
    existing child bind translations. It retains root0 and every native animation.
    """
    if pose_mode not in ('native_segments','source_proportions','source_reposed'):
        raise ValueError('choose an explicit measured experimental pose mode')
    if repose_frames and pose_mode != 'source_reposed':
        raise ValueError('explicit repose frames require the source_reposed mode')
    if retarget_root_translation and pose_mode != 'source_reposed':
        raise ValueError('root translation retargeting requires the source_reposed mode')
    if (role_scales or role_offsets or orphan_role) and pose_mode != 'native_segments':
        raise ValueError('per-role scales, offsets and the orphan role require the native_segments mode')
    parsed = mt_arc.parse(archive)
    matches = {}
    for index, entry in enumerate(parsed.entries):
        if entry.name.replace('\\', '/').rsplit('/', 1)[-1] != model_name:
            continue
        raw = zlib.decompress(entry.data)
        if raw[:4] in (b'MOD\0', b'MRL\0'):
            if raw[:4] in matches:
                raise ValueError('the named native model has ambiguous MOD/MRL entries')
            matches[raw[:4]] = index, raw
    if set(matches) != {b'MOD\0', b'MRL\0'}:
        raise ValueError('the named native model needs exactly one MOD and paired MRL')
    model_index, raw = matches[b'MOD\0']
    mrl_index, mrl = matches[b'MRL\0']
    model = mt_model.parse_mod(raw)
    original_bounds = model.bounds()
    if model.position_transform() is None:
        raise ValueError('the target needs a verified skeleton position transform')
    material = next((row for row in mtf_mrl.inspect_bindings(mrl, model) if row['mod_index'] == material_index), None)
    if material is None:
        raise ValueError('the selected native material does not exist')
    albedo = next((b for b in material['bindings'] if b['shader_hash'] == 0xcd06f), None)
    if albedo is None:
        raise ValueError('the selected native material has no measured albedo binding')
    texture_matches = [(i, zlib.decompress(e.data)) for i,e in enumerate(parsed.entries) if e.name == albedo['path']]
    texture_matches = [(i, data) for i,data in texture_matches if data[:4] == b'TEX\0']
    if len(texture_matches) != 1:
        raise ValueError('the native albedo path must identify one existing TEX entry')
    texture_index, texture = texture_matches[0]
    surface = mtf_tex.parse(texture)
    vertices, triangles, atlas, appearance = mtf_materials.source_mesh(source, atlas_size=(surface.width,surface.height))
    gltf, _, _, world = characters._load(source)
    names = {}
    for index, node in enumerate(gltf['nodes']):
        if node.get('name') in source_roles.values():
            if node['name'] in names:
                raise ValueError('source role node names must be unique')
            names[node['name']] = index
    if set(source_roles) != set(target_roles) or any(name not in names for name in source_roles.values()):
        raise ValueError('source and target must name the same complete anatomical roles')
    roles = {role: (names[name], target_roles[role]) for role, name in source_roles.items()}
    parents = {child: i for i, node in enumerate(gltf['nodes']) for child in node.get('children', [])}
    source_points = {i: tuple(map(float, matrix[:3, 3])) for i, matrix in enumerate(world)}
    target_points = {i: (x, y, z) for i, x, y, z in model.bone_world()}
    bind = None
    if pose_mode in ('source_proportions','source_reposed'):
        if continuous or not math.isfinite(height) or height <= 0:
            raise ValueError('source proportions require a finite positive height without a spatial warp')
        if not 0 <= template_index < len(model.meshes()) or model.meshes()[template_index]['group_index'] != 0:
            raise ValueError('source proportions currently support the measured player body group0 only')
        low = [min(v['position'][i] for v in vertices) for i in range(3)]
        high = [max(v['position'][i] for v in vertices) for i in range(3)]
        if high[1]-low[1] < 1e-8:
            raise ValueError('source proportions require a nonzero source height')
        scale = height/(high[1]-low[1])
        origin = ((low[0]+high[0])/2, low[1], low[2])
        translation = (0., model.bounds()['min']['y'], model.bounds()['min']['z'])
        if centre_hip:
            if 'hip' not in roles or roles['hip'][1] != 0:
                raise ValueError('centred source proportions require an explicit hip role mapped to root0')
            source_hip = source_points[roles['hip'][0]]
            origin = (source_hip[0], low[1], source_hip[2])
            translation = (target_points[0][0], translation[1], target_points[0][2])
        def fit(point):
            return tuple((point[i]-origin[i])*scale+translation[i] for i in range(3))
        if pose_mode == 'source_reposed':
            if not centre_hip:
                raise ValueError('source repose requires the explicit centred hip convention')
            fitted, anchors, skin = mtf_retarget.repose(vertices,source_points,parents,target_points,roles,segments,
                scale=scale,root_role='hip',root_position=fit(source_points[roles['hip'][0]]),frames=repose_frames)
            # Reposing feet can change the floor and overall height slightly. One
            # final uniform scale retains proportions and all segment directions.
            floor = min(v['position'][1] for v in fitted)
            ceiling = max(v['position'][1] for v in fitted)
            if not math.isfinite(ceiling-floor) or ceiling-floor < 1e-8:
                raise ValueError('reposed source must retain a finite nonzero height')
            correction = height/(ceiling-floor)
            pivot = anchors[0]
            def final_fit(point):
                return ((point[0]-pivot[0])*correction+pivot[0],
                        (point[1]-floor)*correction+translation[1],
                        (point[2]-pivot[2])*correction+pivot[2])
            fitted = [v | {'position':final_fit(v['position'])} for v in fitted]
            anchors = {index:final_fit(point) for index,point in anchors.items()}
            skin['final_geometry_anchors'] = {str(index):point for index,point in anchors.items()}
            if not retarget_root_translation:
                anchors.pop(0)
            skin.update(final_uniform_scale=correction, total_uniform_scale=scale*correction)
        else:
            fitted = [vertex | {'position':fit(vertex['position'])} for vertex in vertices]
            anchors = {target:fit(source_points[source_joint]) for source_joint,target in roles.values() if target != 0}
            fitted, skin = mtf_retarget.map_weights(fitted, parents, roles)
        model, bind = mtf_retarget.reposition_bind_pose(model, anchors,
            retarget_root_translation=retarget_root_translation)
        skin.update(scale=scale, height=height, centre_hip=centre_hip)
    else:
        fitted, skin = mtf_retarget.transfer(vertices, source_points, parents, target_points, roles, segments,
                                           scale=scale, continuous=continuous, role_scales=role_scales,
                                           role_offsets=role_offsets, orphan_role=orphan_role)
    import numpy as np
    if pose_mode == 'native_segments':
        normals = np.zeros((len(fitted), 3))
        for face in triangles:
            points = np.asarray([fitted[i]['position'] for i in face])
            normal = np.cross(points[1] - points[0], points[2] - points[0])
            if np.linalg.norm(normal) < 1e-8:
                raise ValueError('retarget collapsed a source triangle')
            for i in face:
                normals[i] += normal
        for vertex, normal in zip(fitted, normals):
            length = np.linalg.norm(normal)
            if length < 1e-8:
                raise ValueError('retarget produced an undefined surface normal')
            vertex['normal'] = tuple(map(float, normal / length))
    low = tuple(min(v['position'][i] for v in fitted) for i in range(3))
    high = tuple(max(v['position'][i] for v in fitted) for i in range(3))
    centre = tuple((a+b)/2 for a,b in zip(low, high))
    bounds = {'min': dict(zip('xyz', low)), 'max': dict(zip('xyz', high)),
              'sphere': dict(zip('xyz', centre)) | {'r': max(sum((v['position'][i]-centre[i])**2 for i in range(3))**.5
                                                           for v in fitted)}}
    for vertex in fitted:
        vertex.update(bounds=bounds)
    authored = mtf_author.build_one_mesh(model, fitted, triangles, material_index=material_index,
                                        template_index=template_index, four_weights=True)
    authored = mt_model.rebuild_mod(mt_model.parse_mod(authored), bounds=bounds)
    if pose_mode in ('source_proportions','source_reposed'):
        # Group0 is the root-attached player body in the measured archive. Other groups remain untouched.
        points = mtf_author.bone_local_points(model, 0, [v['position'] for v in fitted])
        centre = [(min(p[i] for p in points)+max(p[i] for p in points))/2 for i in range(3)]
        radius = max(sum((p[i]-centre[i])**2 for i in range(3))**.5 for p in points)
        info = mt_model.parse_mod(authored).header()
        offset = info['offsets']['groups']
        if (info['offsets']['materials']-offset != info['group_count']*32
                or not info['group_count'] or struct.unpack_from('<I',authored,offset)[0] != 0):
            raise ValueError('the target player group table does not match the measured layout')
        data = bytearray(authored)
        struct.pack_into('<4f',data,offset+16,*centre,radius)
        authored = bytes(data)
    checked = mt_model.parse_mod(authored)
    error = max(abs(a-b) for v,p in zip(fitted, checked.positions(0)) for a,b in zip(v['position'],p))
    if not checked.split_valid() or len(mtf_author.mesh_triangles(checked, 0)) != len(triangles) or error > .01:
        raise ValueError('authored geometry does not round-trip the complete retargeted source')
    edited_texture = mtf_tex.replace_image(texture, atlas)
    edited_mrl, binding = mtf_mrl.bind_albedo(mrl, authored, [material_index], albedo['path'])
    result = archive
    for index, payload in ((model_index, authored), (mrl_index, edited_mrl), (texture_index, edited_texture)):
        result = mtf_author.replace_archive_model(result, index, payload)
    receipt = {'model': model_name, 'triangles': len(triangles), 'vertices': len(fitted), 'skin': skin,
               'source_roles': source_roles, 'target_roles': target_roles, 'segments': segments,
               'appearance': appearance, 'material': binding, 'original_bounds': original_bounds, 'bounds': bounds,
               'pose_mode':pose_mode, 'bind_skeleton':bind, 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
               'tangent_frames':'UV derivatives with handedness; authored occlusion1',
               'position_roundtrip_max_error': error, 'envelope_count': checked.header()['weight_bound_count'],
               'mesh_id': checked.meshes()[0]['mesh_id'], 'changed_entry_indices': [model_index, texture_index],
               'live_verified': False, 'writer_registered': False}
    return result, authored, atlas, receipt

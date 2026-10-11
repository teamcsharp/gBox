"""Read-only DOA2 stage archive decomposition into editable, unassembled parts.

CHR model IDs are retained. This does not infer stage selection, object
placement, collision, procedural animation or a native stage reimport route.
Original CHR/BIN and complete PVR mip chains accompany the interchange export.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from . import doa2_geometry as G, doa2_textures as T, uap

# Only this exact owned source has the observed non-float V encoding. Its
# renderer semantics are unproved: zero is a clearly reported preview value.
_STAGE03_SHA256 = 'fb739149dcd3150d2e28de8c003c3780656f91845da9bb6b135b1031e5b64a82'
_STAGE03_V_OFFSETS = (0x25220, 0x25240, 0x25260, 0x25290, 0x252b0, 0x252d8,
                       0x25310, 0x25338, 0x25380, 0x253b0, 0x253e0, 0x25428,
                       0x25470, 0x254a0, 0x254d0, 0x25518)


def stage_name(value: str) -> str:
    name = value.strip().upper().removeprefix('DOA2/').removesuffix('.CHR')
    if name.isdecimal() and len(name) <= 2:
        name = 'STAGE' + name.zfill(2)
    if not re.fullmatch(r'STAGE[0-9]{2}', name):
        raise ValueError('Environment must be an explicit STAGE00..STAGE99 archive or all')
    return name


def inventory(files: dict) -> list[dict]:
    return [{'name': name[5:-4], 'geometry': name,
             'textures': name[:-4] + '.BIN', 'available': name[:-4] + '.BIN' in files}
            for name in sorted(files) if re.fullmatch(r'DOA2/STAGE[0-9]{2}\.CHR', name)]


def select(files: dict, environment: str = 'all') -> list[dict]:
    rows = inventory(files)
    if environment.casefold() != 'all':
        name = stage_name(environment)
        rows = [row for row in rows if row['name'] == name]
    if not rows:
        raise ValueError('Requested environment archive is absent from the owned disc')
    return rows


def decode_archive(chr_data: bytes, name: str) -> dict:
    name = stage_name(name)
    offsets = (_STAGE03_V_OFFSETS if name == 'STAGE03'
               and hashlib.sha256(chr_data).hexdigest() == _STAGE03_SHA256 else ())
    archive = G.decode_chr(chr_data, preview_v_sentinel_offsets=offsets)
    if G.roundtrip_chr(archive) != chr_data:
        raise ValueError('Environment CHR identity reconstruction changed source bytes')
    return archive


def _decoded(chr_data: bytes, bin_data: bytes, name: str):
    archive = decode_archive(chr_data, name)
    textures = T.descriptors(chr_data, bin_data)
    for model in archive['models']:
        for mesh in model['meshes']:
            if not -1 <= mesh['texture_id'] < len(textures):
                raise ValueError(f"Invalid environment texture slot {mesh['texture_id']}")
    return archive, textures


def _report(chr_data, bin_data, name, archive, textures):
    return {
        'name': stage_name(name), 'status': 'source_records_verified',
        'chr_sha256': hashlib.sha256(chr_data).hexdigest(),
        'bin_sha256': hashlib.sha256(bin_data).hexdigest(),
        'chr_bytes': len(chr_data), 'bin_bytes': len(bin_data),
        'reconstruction': 'byte_exact', 'models': len(archive['models']),
        'submeshes': sum(len(m['meshes']) for m in archive['models']),
        'vertices': sum(len(s['vertices']) for m in archive['models'] for s in m['meshes']),
        'triangles': sum(len(s['triangles']) for m in archive['models'] for s in m['meshes']),
        'texture_count': len(textures),
        'textures': [asdict(t) | {'payload_bytes': t.payload_size,
                                'base_level_offset': T.base_level_offset(t.width, t.height, t.format),
                                'alignment_bytes': t.size - t.payload_size} for t in textures],
        'shader_counts': dict(Counter(s['shader'] for m in archive['models'] for s in m['meshes'])),
        'preview_uv_substitutions': archive['preview_uv_substitutions'],
        'gameplay_verified': False, 'native_reimport_supported': False,
        'limits': {
            'assembly': 'unassembled native model coordinates; executable stage placement/draw selection not inferred',
            'materials': 'base images and approximate alpha preview; native lighting/blending headers preserved separately',
            'motion_collision': 'stage animation, collision, transitions and procedural effects not reconstructed',
            'uv_sentinels': 'pinned STAGE03 V=7fbfffff displayed as zero only; runtime semantics unverified; raw bytes retained',
            'reimport': 'editable interchange export; no verified native stage writer or gameplay acceptance',
        },
    }


def inspect_archive(chr_data: bytes, bin_data: bytes, name: str) -> dict:
    archive, textures = _decoded(chr_data, bin_data, name)
    return _report(chr_data, bin_data, name, archive, textures)


def export_assets(chr_data: bytes, bin_data: bytes, out_dir: str | Path,
                  name: str, *, source: dict | None = None) -> dict:
    """Create a new source package; refuse existing paths rather than overwrite."""
    name = stage_name(name)
    archive, textures = _decoded(chr_data, bin_data, name)
    report = _report(chr_data, bin_data, name, archive, textures)
    # Decode every image before creating output, so corrupt image data cannot
    # masquerade as a completed exported package.
    images = [T.decode(tex, bin_data) for tex in textures]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'native').mkdir()
    (out / 'textures').mkdir()
    files = []
    for extension, body in (('CHR', chr_data), ('BIN', bin_data)):
        rel = f'native/{name}.{extension}'
        (out / rel).write_bytes(body)
        files.append(rel)
    alpha = []
    for tex, image in zip(textures, images):
        rel = f'textures/tex{tex.index:03d}.png'
        image.save(out / rel)
        native = f'native/tex{tex.index:03d}.pvr'
        (out / native).write_bytes(T.pvr_chunk(tex, bin_data))
        files.extend([rel, native])
        values = set(image.getchannel('A').getdata())
        alpha.append('opaque' if values == {255} else 'mask' if values <= {0, 255} else 'blend')
    meshes, materials, nodes = [], [], []
    provenance = []
    for model in archive['models']:
        for mesh_index, mesh in enumerate(model['meshes']):
            if not mesh['triangles']:
                continue
            tid, vertices = mesh['texture_id'], mesh['vertices']
            part = f"{name}_model{model['id']:03d}_mesh{mesh_index:03d}"
            materials.append({'name': part + '_material',
                              'texture': f'textures/tex{tid:03d}.png' if tid >= 0 else None,
                              'source': {'native_texture_id': tid, 'shader': mesh['shader'],
                                         'header_hex': mesh['header'].hex(),
                                         'preview_only': True}})
            meshes.append({'name': part, 'positions': [list(v[:3]) for v in vertices],
                           'normals': [list(v[3:6]) for v in vertices],
                           'uvs': [list(v[6:8]) for v in vertices],
                           'indices': [i for tri in mesh['triangles'] for i in tri],
                           'material': len(materials) - 1})
            nodes.append({'name': part, 'mesh': len(meshes) - 1, 'skinned': False})
            provenance.append({'part': part, 'model_id': model['id'], 'mesh_index': mesh_index,
                               'native_offset': mesh['offset'], 'native_texture_id': tid,
                               'global_flags': list(model['global_flags']),
                               'sphere': list(model['centroid']),
                               'polygon_flags': sorted({s['flags'] for s in mesh['strips']})})
    manifest = {
        'uap_version': '0.1', 'name': name,
        'source': (source or {}) | {'resource_ids': [f'DOA2/{name}.CHR', f'DOA2/{name}.BIN'],
                                    'extraction_method': 'gbox.doa2_environments native source parts',
                                    'part_coordinates': report['limits']['assembly']},
        'coordinate_system': {'up': 'Y', 'forward': '-Z', 'handedness': 'right'},
        'meshes': meshes, 'materials': materials, 'nodes': nodes, 'roots': list(range(len(nodes))),
        'skeleton': [], 'animations': [], 'collision': [],
        'confidence': {'entity': 'verified', 'geometry': 'verified', 'materials': 'partial',
                       'textures': 'verified', 'skeleton': 'missing', 'skin_weights': 'missing',
                       'animations': 'missing', 'collision': 'missing',
                       'runtime_linkage': 'missing', 'source_identity': 'verified'},
        'provenance': [{'file': f'DOA2/{name}.{ext}', 'bytes': len(body),
                        'sha256': hashlib.sha256(body).hexdigest()}
                       for ext, body in (('CHR', chr_data), ('BIN', bin_data))],
    }
    validated = uap.Manifest.model_validate(manifest)
    issues = uap.validate(validated, out)
    if issues:
        raise ValueError('Environment interchange validation: ' + '; '.join(issues))
    gltf = uap.to_gltf(validated)
    for material, mesh in zip(gltf.get('materials', []), meshes):
        tid = materials[mesh['material']]['source']['native_texture_id']
        material['doubleSided'] = True
        if tid >= 0 and alpha[tid] != 'opaque':
            material['alphaMode'] = 'MASK' if alpha[tid] == 'mask' else 'BLEND'
            if alpha[tid] == 'mask':
                material['alphaCutoff'] = 0.5
    # The same approximate preview material flags must survive the GLB path.
    glb = bytearray(uap.to_glb(validated, out))
    old_length = struct.unpack_from('<I', glb, 12)[0]
    glb_json = json.loads(glb[20:20 + old_length])
    glb_json['materials'] = gltf.get('materials', [])
    encoded = json.dumps(glb_json, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    binary = bytes(glb[20 + old_length:])
    glb = struct.pack('<III', 0x46546c67, 2, 20 + len(encoded) + len(binary)) + struct.pack('<II', len(encoded), 0x4e4f534a) + encoded + binary
    (out / f'{name}_parts.gltf').write_text(json.dumps(gltf, separators=(',', ':')), encoding='utf-8')
    (out / f'{name}_parts.glb').write_bytes(glb)
    (out / 'manifest.json').write_text(json.dumps(manifest, separators=(',', ':')), encoding='utf-8')
    report['parts'] = provenance
    report['images_decoded'] = len(images)
    report['files'] = files + [f'{name}_parts.gltf', f'{name}_parts.glb', 'manifest.json', 'environment-report.json']
    (out / 'environment-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report | {'path': str(out)}

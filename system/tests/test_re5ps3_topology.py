import os
from pathlib import Path
import struct

import numpy as np
import pytest

from gbox.re5ps3_arc import sha
from gbox.re5ps3_models import Model
from gbox.re5ps3_roles import role_evidence
from gbox.re5ps3_topology import replace_body, _tangents


@pytest.fixture(params=['uPl00ChrisNormal', 'uPl01ShebaNormal'])
def owned(request):
    root = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home()/'gbox-pr-audit-20261017/re-export-evidence')))
    path = root / (request.param + '-model.bin')
    if not path.exists(): pytest.skip('owned RE5 source unavailable')
    data = path.read_bytes(); model = Model(data)
    at = struct.unpack_from('>I', data, 56)[0]
    template = next(m['index'] for m in model.meshes if m['visible'] and m['group'] == 0 and
                    model.materials[m['material']]['vertex_type'] == 0 and data[at+m['index']*52+9] == 0 and
                    model.materials[m['material']]['texture'] >= 0)
    roles = role_evidence(model)['native_joint_ids']
    geometry = {'positions': np.array([[-1,150,0],[1,150,0],[1,152,0],[-1,152,0.]]),
                'normals': np.tile([0.,0.,1.], (4,1)), 'uv': np.array([[0.,0],[1,0],[1,1],[0,1]]),
                'joints': np.tile([roles['head'],roles['chest'],0,0], (4,1)),
                'weights': np.tile([.7,.3,0,0], (4,1)), 'triangles': np.array([[0,1,2],[0,2,3]])}
    return data, model, template, geometry


def test_body_rebuild_retains_native_skeleton_and_unknown_original_mesh_payloads(owned):
    data, original, template, geometry = owned
    output, receipt = replace_body(data, geometry, template_mesh=template, expected_sha256=sha(data))
    result = Model(output); mesh = result.meshes[0]
    assert len(result.meshes) == 1 and mesh['lod'] == 255 and mesh['visible']
    assert np.array_equal(mesh['triangles'], geometry['triangles'])
    assert np.allclose(mesh['positions'], geometry['positions'], atol=.0001)
    assert np.allclose(mesh['weights'], geometry['weights'], atol=1/255)
    assert np.array_equal(mesh['joints'][mesh['weights']>0], geometry['joints'][mesh['weights']>0])
    bones, groups, mats, meshes = struct.unpack_from('>4I', data, 44)
    nb = len(original.parents)
    assert output[bones:bones+nb*152+256] == data[bones:bones+nb*152+256]
    assert output[mats:meshes] == data[mats:meshes]
    assert output[meshes:len(data)] == data[meshes:]
    assert result.parents == original.parents and result.anim_map == original.anim_map
    assert np.array_equal(result.local, original.local) and np.array_equal(result.inverse_bind, original.inverse_bind)
    assert role_evidence(result) is None
    assert receipt['native_skeleton_matrices_unchanged'] and not receipt['gameplay_verified']


def test_bone_envelopes_independently_enclose_written_quantized_vertices(owned):
    data, original, template, geometry = owned
    output, _ = replace_body(data, geometry, template_mesh=template, expected_sha256=sha(data))
    m = Model(output); mesh = m.meshes[0]
    at = struct.unpack_from('>I', output, 56)[0] + 52
    count = struct.unpack_from('>I', output, at)[0]
    assert count == len(set(mesh['joints'][mesh['weights']>0].tolist()))
    for i in range(count):
        raw = output[at+4+i*144:at+4+(i+1)*144]
        joint = struct.unpack_from('>I', raw)[0]
        points = mesh['positions'][np.any((mesh['joints']==joint)&(mesh['weights']>0), axis=1)]
        local = np.column_stack((points,np.ones(len(points)))) @ m.inverse_bind[joint].T
        sphere = np.array(struct.unpack_from('>4f',raw,16))
        lo, hi = np.array(struct.unpack_from('>3f',raw,32)),np.array(struct.unpack_from('>3f',raw,48))
        obb = np.array(struct.unpack_from('>16f',raw,64)).reshape(4,4).T
        dimensions = np.array(struct.unpack_from('>3f',raw,128))
        assert np.all(local[:,:3]>=lo) and np.all(local[:,:3]<=hi)
        assert np.all(np.linalg.norm(local[:,:3]-sphere[:3],axis=1)<=sphere[3])
        box = local @ np.linalg.inv(obb).T
        assert np.all(np.abs(box[:,:3])<=dimensions+.0001)


@pytest.mark.parametrize('change', ['nonfinite','overflow','uv','weights','missing_vertex','helper_joint'])
def test_reject_invalid_replacement_before_returning_native_bytes(owned, change):
    data, model, template, geometry = owned
    geometry = {k:v.copy() for k,v in geometry.items()}
    if change=='nonfinite':geometry['positions'][0,0]=float('nan')
    if change=='overflow':
        with np.errstate(over='ignore',invalid='ignore'): geometry['positions']*=1e308
    if change=='uv':geometry['uv'][0,0]=1e308
    if change=='weights':geometry['weights'][0,0]=0
    if change=='missing_vertex':geometry['triangles'][0,0]=9999
    if change=='helper_joint':geometry['joints'][0,0]=0
    with np.errstate(over='ignore',invalid='ignore'),pytest.raises(ValueError):
        replace_body(data,geometry,template_mesh=template,expected_sha256=sha(data))


def test_changed_or_wrong_source_cannot_inherit_topology_permission(owned):
    data, model, template, geometry = owned
    with pytest.raises(ValueError,match='hash'):
        replace_body(data,geometry,template_mesh=template,expected_sha256='0'*64)
    edited=data+b'unknown trailer'
    with pytest.raises(ValueError,match='exact verified original'):
        replace_body(edited,geometry,template_mesh=template,expected_sha256=sha(edited))


def test_uv_tangents_are_orthogonal_and_zero_uv_area_has_defined_fallback():
    positions=np.array([[0.,0,0],[1,0,0],[0,1,0]])
    normals=np.tile([0.,0,1],(3,1));faces=np.array([[0,1,2]])
    for uv in (positions[:,:2],np.zeros((3,2))):
        tangent=_tangents(positions,normals,uv,faces)
        assert np.isfinite(tangent).all() and np.allclose(np.linalg.norm(tangent,axis=1),1)
        assert np.allclose((normals*tangent).sum(1),0)


def test_finite_but_unrepresentable_float32_enclosures_fail_closed(owned):
    data, model, template, geometry = owned
    geometry = {k: v.copy() for k, v in geometry.items()}
    geometry['positions'] *= 1e12
    with pytest.raises(ValueError, match='enclose native readback'):
        replace_body(data, geometry, template_mesh=template, expected_sha256=sha(data))

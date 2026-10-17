import os
from pathlib import Path

import numpy as np
import pytest

from gbox.re5ps3_models import Model, export_glb
from gbox.re5ps3_roles import role_evidence
from test_re5ps3_models import model, texture, glb


def test_unverified_model_keeps_numeric_identity_without_semantic_guessing(tmp_path):
    source = Model(model())
    assert role_evidence(source) is None
    out = tmp_path / 'synthetic.glb'
    receipt = export_glb(source, {'pawn\\test\\body': texture()}, out)
    assert receipt['role_evidence'] is None
    doc, _, _ = glb(out)
    assert doc['extras']['role_evidence'] is None
    assert [doc['nodes'][j]['name'] for j in doc['skins'][0]['joints']] == ['j000', 'j001']


@pytest.fixture(params=[('uPl00ChrisNormal', 4, 114), ('uPl01ShebaNormal', 23, 4)])
def owned_model(request):
    root = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home()/'gbox-pr-audit-20261017/re-export-evidence')))
    tag, head, foot = request.param
    path = root / (tag + '-model.bin')
    if not path.exists():
        pytest.skip('owned RE5 PS3 native model unavailable')
    return Model(path.read_bytes()), head, foot


def test_owned_roles_use_literal_per_target_ids_and_verified_body_chains(owned_model):
    source, head, foot = owned_model
    evidence = role_evidence(source)
    roles = evidence['native_joint_ids']
    # Same numeric ID 4 controls Chris's head and Sheva's right foot. Mapping
    # by numeric name or copying the other target's table would fail this.
    assert roles['head'] == head and roles['r_foot'] == foot
    assert source.anim_map[head] == 4 and source.anim_map[foot] == 18
    assert source.world[head, 1, 3] > source.world[foot, 1, 3] + 100
    assert len(roles) == 18 and len(set(roles.values())) == 18
    assert evidence['roles']['head'] == f'j{head:03d}'
    assert not evidence['gameplay_verified'] and not evidence['animation_compatibility_verified']
    def ancestor(child, parent):
        at = source.parents[child]
        while at != 255:
            if at == parent: return True
            at = source.parents[at]
        return False
    assert ancestor(roles['head'], roles['neck']) and ancestor(roles['neck'], roles['chest'])
    for side, sign in [('l', 1), ('r', -1)]:
        arm = [roles[side + '_' + r] for r in ('clav', 'upper', 'fore', 'hand')]
        leg = [roles[side + '_' + r] for r in ('thigh', 'shin', 'foot')]
        assert ancestor(arm[0], roles['chest']) and ancestor(leg[0], roles['hip'])
        assert all(ancestor(b, a) for chain in (arm, leg) for a, b in zip(chain, chain[1:]))
        assert all(sign * source.world[j, 0, 3] > 0 for j in arm + leg)
        assert source.world[leg[0], 1, 3] > source.world[leg[1], 1, 3] > source.world[leg[2], 1, 3]
        # Direct hand/foot weights must actually occupy their named side.
        for joint in (arm[-1], leg[-1]):
            points = np.concatenate([m['positions'][(m['weights'] * (m['joints'] == joint)).sum(1) > .5]
                                     for m in source.meshes if m['visible'] and m['lod'] & 1])
            assert len(points) and np.all(sign * points[:, 0] > 0)


def test_changed_owned_model_does_not_inherit_roles_from_matching_skeleton(owned_model):
    source, _head, _foot = owned_model
    changed = Model(source.data + b'unknown preserved trailer')
    assert changed.parents == source.parents and changed.anim_map == source.anim_map
    assert role_evidence(source) and role_evidence(changed) is None

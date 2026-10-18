import os
from pathlib import Path
import struct

import numpy as np
import pytest

from gbox.re5ps3_arc import Arc, sha
from gbox.re5ps3_models import Model, export_glb, export_archive
from gbox.re5ps3_roles import role_evidence
from test_re5ps3_models import model, texture, glb


def test_sparse_native_group_id_is_not_its_table_ordinal(tmp_path):
    data = bytearray(model()); groups, _, meshes = struct.unpack_from('>3I', data, 48)
    struct.pack_into('>I', data, groups, 9)
    struct.pack_into('>H', data, meshes, 9)
    parsed = Model(bytes(data))
    assert parsed.group_ids == (9,) and parsed.meshes[0]['group'] == 9
    output = tmp_path / 'sparse.glb'
    export_glb(parsed, {r'pawn\test\body': texture()}, output)
    document, _, _ = glb(output)
    assert document['meshes'][0]['primitives'][0]['extras']['group'] == 9
    assert parsed.data == bytes(data)


def test_group_ordinal_without_matching_native_id_is_rejected(tmp_path):
    data = bytearray(model()); groups = struct.unpack_from('>I', data, 48)[0]
    struct.pack_into('>I', data, groups, 9)  # mesh still refers to 0; ordinal 0 is not ID 9
    output = tmp_path / 'missing.glb'
    with pytest.raises(ValueError, match='absent material/group/palette'):
        export_glb(Model(data), {r'pawn\test\body': texture()}, output)
    assert not output.exists()


def test_duplicate_group_ids_are_ambiguous_and_rejected():
    data = bytearray(model()); header = list(struct.unpack_from('>4H15I', data, 4))
    data[header[13] + 32:header[13] + 32] = bytes(32)
    header[10] = 2
    for i in range(14, 19): header[i] += 32
    struct.pack_into('>4H15I', data, 4, *header)
    with pytest.raises(ValueError, match='duplicate MOD group IDs'):
        Model(data)


OWNED = [
    ('uPl04Josh.arc', '3eb562b66d044b4595e8c5f94b78cb6d9acdda70ef48a50ee8066004222e425b',
     r'pawn\em\em88\model\em8800', '1deebf4b56cf2b99da6f085589fa3a2946695dd50ac9e401f0e068b76d815ede', (0, 1, 3, 5, 20)),
    ('uPl06BarryNormal.arc', 'c8d40ee81cf2492f0d4917d47a02de84c7d0957861d7182eb1db1a836368ed47',
     r'pawn\pl\pl1c\model\pl1c00', '198be92da417d814ec3127f30e5186b0461fe0e891b671717737cd515daabd81', (0, 4, 5)),
    ('uPl07RebeccaNormal.arc', '68ad74447f7d1ed09858de08baea636df457b4f8e1b423ec8f5fed5c1ccb43ee',
     r'pawn\pl\pl1d\model\pl1d00', 'c033cc2bf1c3e0bfe4df0d976c614315ca8252e4ab7fdc2b787d6e833de2eaec', (0, 8, 9, 10, 11)),
]


def owned_pack(name):
    evidence = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home() / 'gbox-pr-audit-20261017/re-export-evidence')))
    path = evidence / 're5-expanded-cast-v1/packs' / name
    if not path.exists(): pytest.skip('owned expanded RE5 player pack unavailable')
    return path


@pytest.mark.parametrize('name,arc_hash,member,model_hash,expected_groups', OWNED)
def test_owned_sparse_groups_export_all_lods_without_relabeling_or_source_mutation(tmp_path, name, arc_hash, member, model_hash, expected_groups):
    path = owned_pack(name); data = path.read_bytes(); assert sha(data) == arc_hash
    arc = Arc(data); entry = next(e for e in arc.entries if e.name == member)
    native = arc.read(entry); assert sha(native) == model_hash
    parsed = Model(native); assert parsed.group_ids == expected_groups
    mesh_at = struct.unpack_from('>I', native, 56)[0]
    assert any(m['group'] >= len(expected_groups) for m in parsed.meshes)
    assert all(m['group'] == struct.unpack_from('>H', native, mesh_at + m['index'] * 52)[0] for m in parsed.meshes)
    assert role_evidence(parsed) is None
    for lod in (1, 2, 4):
        output = tmp_path / f'{path.stem}-{lod}.glb'
        receipt = export_archive(arc, member, output, lod=lod)
        document, _, accessor = glb(output)
        selected = [m for m in parsed.meshes if m['visible'] and m['lod'] & lod and len(m['triangles'])]
        primitives = document['meshes'][0]['primitives']
        assert len(primitives) == len(selected)
        for primitive, source in zip(primitives, selected):
            assert primitive['extras']['group'] == source['group']
            assert primitive['extras']['index'] == source['index']
            assert np.array_equal(accessor(primitive['indices']).reshape(-1, 3), source['triangles'])
            assert np.allclose(accessor(primitive['attributes']['POSITION']), source['positions'] * .01, atol=1e-6, rtol=0)
        assert receipt['source_sha256'] == model_hash and not receipt['gameplay_verified']
        assert [n['name'] for n in document['nodes'][2:]] == [f'j{i:03d}' for i in range(len(parsed.parents))]
    assert path.read_bytes() == data and arc.read(entry) == native


@pytest.mark.parametrize('name,member,error', [
    ('uPl02JillCos1.arc', r'pawn\pl\pl02\model\Pl0200', 'mesh vertex range or stride'),
    ('uPl03WeskerCos1.arc', r'pawn\pl\pl15\model\pl1500', 'MOD UVs has a non-finite'),
    ('uPl05ExcellaNormal.arc', r'pawn\pl\pl1e\model\pl1e00', 'MOD UVs has a non-finite'),
    ('uPl86Irving.arc', r'pawn\em\em86\model\em8600', 'material vertex/shader declaration'),
    ('uPl03WeskerCos1.arc', r'effect\mod\0058\md0058', 'header counts'),
])
def test_other_owned_layout_failures_stay_explicit_and_create_no_output(tmp_path, name, member, error):
    path = owned_pack(name); data = path.read_bytes(); output = tmp_path / 'unsupported.glb'
    with pytest.raises(ValueError, match=error):
        export_archive(Arc(data), member, output)
    assert not output.exists() and path.read_bytes() == data

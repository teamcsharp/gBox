"""The global MOD envelope count must shrink with an authored mesh table."""
import struct

import pytest

from gbox import mt_model, mtf_author
from tests.test_mtf_author import make_target, import_triangle


def large_envelope_model():
    target = mt_model.parse_mod(make_target(341))
    records = target.meshes()
    # The measured em1000 has 341 parts and 3799 weight bounds. Reproduce that
    # allocation without depending on game assets in the test suite.
    base, extra = divmod(3799, len(records))
    records = [record | {'vertex_group_count': base + (i < extra)} for i, record in enumerate(records)]
    bound = mtf_author.pack_weight_bound(0, [(0., 0., 0.), (1., 1., 1.)])
    source = mt_model.rebuild_mod(target, mesh_records=records, mesh_trailer=bound * 3799)
    assert struct.unpack_from('<I', source, 0xA0)[0] == 3799
    return mt_model.parse_mod(source)


def test_restructured_model_updates_global_3799_envelope_count_to_one():
    source = large_envelope_model()
    vertices = [v | {'bones': [0], 'bone': 0, 'bounds': source.bounds()} for v in import_triangle()]
    result = mtf_author.build_one_mesh(source, vertices, [(0, 1, 2)])
    model = mt_model.parse_mod(result)
    header = model.header()
    offsets = header['offsets']
    assert header['weight_bound_count'] == 1
    assert struct.unpack_from('<I', result, 0xA0)[0] == 1
    assert sum(record['vertex_group_count'] for record in model.meshes()) == 1
    assert offsets['vertex_buffer'] - offsets['meshes'] - 56 * header['mesh_count'] == 144


@pytest.mark.parametrize('count, extra_byte', [(3798, False), (3799, True)])
def test_envelope_table_must_match_part_counts_and_complete_records(count, extra_byte):
    source = large_envelope_model()
    trailer = bytes(count * 144) + (b'\0' if extra_byte else b'')
    with pytest.raises(mt_model.ModelError):
        mt_model.rebuild_mod(source, mesh_trailer=trailer)

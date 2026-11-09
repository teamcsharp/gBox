import pytest
from gbox import mt_model, mtf_import, mtf_author
from tests.test_mtf_author import make_target


def test_legacy_import_entrypoint_uses_complete_author_tables():
    model = mt_model.parse_mod(make_target(2))
    mesh = mtf_author.combine(model)
    result = mt_model.parse_mod(mtf_import.build_model(model, mesh['vertices'], mesh['triangles']))
    assert result.split_valid()
    assert result.header()['weight_bound_count'] == result.meshes()[0]['vertex_group_count'] == 2
    assert len(result.weight_bounds()) == 2
    assert len(mtf_author.mesh_triangles(result, 0)) == 2


def test_import_refuses_geometry_outside_preserved_culling_bounds():
    model = mt_model.parse_mod(make_target(1))
    mesh = mtf_author.combine(model)
    mesh['vertices'][0]['position'] = (10000., 0., 0.)
    with pytest.raises(mtf_import.ImportError_, match='does not fit'):
        mtf_import.build_model(model, mesh['vertices'], mesh['triangles'])

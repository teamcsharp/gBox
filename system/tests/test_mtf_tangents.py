import struct
import math
import pytest
from gbox import mt_model, mtf_author
from tests.test_mtf_author import make_target


def quad(mirrored=False, degenerate=False):
    return [{'position':(x,y,0.), 'normal':(0.,0.,1.),
             'uv':(0.,0.) if degenerate else (-x if mirrored else x,y), 'bones':[0]}
            for x,y in [(0.,0.),(1.,0.),(1.,1.),(0.,1.)]]


@pytest.mark.parametrize('mirrored,expected,sign', [(False,(1.,0.,0.),1.),(True,(-1.,0.,0.),-1.)])
def test_uv_derivatives_produce_orthogonal_quad_frames_and_handedness(mirrored,expected,sign):
    vertices=quad(mirrored)
    derived=mtf_author.tangent_frames(vertices,[(0,1,2),(0,2,3)])
    for vertex in derived:
        assert vertex['tangent']==pytest.approx(expected)
        assert vertex['tangent_sign']==sign
        assert sum(a*b for a,b in zip(vertex['tangent'],vertex['normal']))==pytest.approx(0.)
    assert all('tangent' not in v for v in vertices)


def test_degenerate_uvs_have_a_finite_unit_frame_even_for_x_facing_normals():
    vertices=[v|{'normal':(1.,0.,0.)} for v in quad(degenerate=True)]
    derived=mtf_author.tangent_frames(vertices,[(0,1,2),(0,2,3)])
    for vertex in derived:
        t=vertex['tangent']
        assert all(math.isfinite(x) for x in t)
        assert sum(x*x for x in t)==pytest.approx(1.)
        assert t[0]==pytest.approx(0.)


def test_new_author_emits_occlusion_and_handedness_without_changing_base_only_packs():
    model=mt_model.parse_mod(make_target(1))
    vertices=[v|{'bounds':model.bounds()} for v in quad(mirrored=True)]
    authored=mt_model.parse_mod(mtf_author.build_one_mesh(model,vertices,[(0,1,2),(0,2,3)]))
    raw,record=authored.mesh_bytes(0)
    assert raw[11]==127 and struct.unpack_from('<b',raw,15)[0]==-127
    base=bytes([73]*20)
    packed=mt_model.pack_vertices([{'normal':(0.,0.,1.),'tangent':(1.,0.,0.)}],0x18B0FAA8,20,base=base)
    assert packed[11]==73 and packed[15]==73

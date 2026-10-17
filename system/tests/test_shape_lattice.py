import numpy as np
import pytest
from gbox import shape_lattice as L, retarget_profile as RP


def test_cage_translation_preserves_normals_and_original():
    points=np.array([[0,0,0],[1,1,1],[.5,.5,.5]],float);normal=np.tile([0.,1.,0.],(3,1))
    cage={'offsets':{str(i):[.1,.02,0] for i in range(27)}}
    moved,norm=L.deform(points,cage,np.zeros(3),np.ones(3),1,normal)
    np.testing.assert_allclose(moved,points+[.1,.02,0]);np.testing.assert_allclose(norm,normal,atol=1e-12)
    np.testing.assert_allclose(points[1],[1,1,1])
    assert RP.digest({'lattice':cage}) and not RP.is_identity({'lattice':cage})


def test_cage_local_influence_and_fold_rejection():
    points=np.array([[.5,.5,.5],[0,0,0],[1,1,1]],float)
    moved,_=L.deform(points,{'offsets':{'13':[.1,0,0]}},np.zeros(3),np.ones(3),1)
    assert moved[0,0]>.5
    np.testing.assert_array_equal(moved[1:],points[1:])
    with pytest.raises(ValueError,match='index'):
        L.normalize({'offsets':{'27':[0,0,0]}})
    with pytest.raises(ValueError,match='finite'):
        L.normalize({'offsets':{'0':[float('nan'),0,0]}})
    # Tiny cage width and large opposing offsets invert its Jacobian.
    with pytest.raises(ValueError,match='folds'):
        L.deform(np.array([[.05,.5,.5]]),{'offsets':{str(i):[.25 if i%3==0 else -.25,0,0] for i in range(27)}},
                 np.zeros(3),np.array([.1,1,1]),1,np.array([[0.,1.,0.]]))


def test_plant_feet_uses_mesh_vertices_and_leaves_uv_weights_intact():
    prim={'pos':np.array([[0.,-.1,0],[0,1.7,0]]),'nrm':np.array([[0.,1,0],[0,1,0]]),
          'J':np.array([[0],[1]]),'W':np.ones((2,1)),'uv':np.array([[0.,0],[1,1]])}
    result,report=RP.apply_roles([prim],{'hip':[0,1,0],'head':[0,1.6,0],'l_foot':[0,0,0]},
                                {0:'l_foot',1:'head'},{'plant_feet':True},0)
    assert result[0]['pos'][0,1]==pytest.approx(0)
    assert report['feet']['applied']
    np.testing.assert_array_equal(result[0]['uv'],prim['uv'])
    np.testing.assert_array_equal(result[0]['W'],prim['W'])
    assert prim['pos'][0,1]==-.1

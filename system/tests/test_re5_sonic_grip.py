from pathlib import Path
from types import SimpleNamespace
import hashlib
import zlib

import numpy as np
import pytest

from gbox import re5_sonic_grip as grip, re5_sonic_writer as writer


@pytest.mark.parametrize('side', [-1, 1])
def test_palm_fit_recovers_proper_rotation_and_scale_without_reflection(side):
    points = np.array([[2, 1, 0], [3, -1, 1], [2, 0, -1], [1, 1, 2], [0, 1, 1]],float)
    points[:,0] *= side
    angle = np.deg2rad(15)
    rotation = np.array([[np.cos(angle),-np.sin(angle),0],
                         [np.sin(angle),np.cos(angle),0],[0,0,1]])
    scale, actual = grip._similarity(points, .414*(points@rotation.T))
    assert scale == pytest.approx(.414)
    np.testing.assert_allclose(actual,rotation,atol=1e-14)
    assert np.linalg.det(actual) == pytest.approx(1)


def test_palm_fit_refuses_undefined_frame():
    with pytest.raises(ValueError,match='span'):
        grip._similarity(np.zeros((5,3)),np.ones((5,3)))


def test_segment_fit_preserves_native_direction_and_transverse_width():
    matrix = grip._segment_matrix([7,0,0],[3,0,0],.41)
    np.testing.assert_allclose(matrix@np.array([7,0,0]),[3,0,0])
    np.testing.assert_allclose(matrix@np.array([0,1,0]),[0,.41,0])
    assert np.linalg.det(matrix) > 0
    with pytest.raises(ValueError,match='direction'):
        grip._segment_matrix([7,0,0],[0,3,0],.41)


@pytest.mark.parametrize('x',[.35,.45,.60,.75,.90,.95,1.2])
def test_cuff_jacobian_matches_deformation_and_joins_without_a_seam(x):
    angle = np.deg2rad(15)
    matrix = .414*np.array([[np.cos(angle),-np.sin(angle),0],
                           [np.sin(angle),np.cos(angle),0],[0,0,1]])
    origin = np.array([.596828,0,0])
    point = np.array([x,.1,-.2])
    moved,jacobian = grip._cuff_map(point,origin,matrix,x,[1,0,0])
    numeric = np.zeros((3,3))
    for axis in range(3):
        delta = np.eye(3)[axis]*1e-7
        plus = grip._cuff_map(point+delta,origin,matrix,x+delta[0],[1,0,0])[0]
        minus = grip._cuff_map(point-delta,origin,matrix,x-delta[0],[1,0,0])[0]
        numeric[:,axis] = (plus-minus)/2e-7
    np.testing.assert_allclose(jacobian,numeric,atol=2e-6)
    assert np.linalg.det(jacobian) > 0
    if x <= grip.CUFF_START:
        np.testing.assert_array_equal(moved,point)
        np.testing.assert_array_equal(jacobian,np.eye(3))
    elif x >= grip.CUFF_END:
        np.testing.assert_allclose(moved,origin+matrix@(point-origin))
        np.testing.assert_allclose(jacobian,matrix)


def test_cuff_refuses_inverted_surface():
    with pytest.raises(ValueError,match='folds'):
        grip._cuff_map([1,0,0],[0,0,0],-np.eye(3),1,[1,0,0])


def test_author_refuses_unreviewed_model_before_reading_source():
    with pytest.raises(ValueError,match='exact reviewed v14'):
        grip.author(b'wrong',b'wrong',Path('does-not-exist.glb'),{})


def test_grip_candidate_uses_corrected_cuff_and_preserves_unverified_gate(monkeypatch):
    source = Path('sonic.glb')
    base = {'skin':{'measured':True},'recipe_version':2,'gameplay_verified':False}
    calls = []
    def fingers(archive,path,*,correct_wrist):
        assert archive == b'native-arc' and path == source and correct_wrist is True
        return b'v14-arc',base
    def parse(archive):
        entries = [None]*98
        entries[97] = SimpleNamespace(data=zlib.compress(b'v14-mod' if archive == b'v14-arc' else b'native-mod'))
        return SimpleNamespace(entries=entries)
    def author(mod,native,path,skin):
        calls.append((mod,native,path,skin))
        return b'grip-mod',{'envelope_count':47}
    def replace(archive,index,mod):
        assert (archive,index,mod) == (b'v14-arc',97,b'grip-mod')
        return b'v15-arc'
    monkeypatch.setattr(writer,'build_finger_candidate',fingers)
    monkeypatch.setattr(writer.mt_arc,'parse',parse)
    monkeypatch.setattr(grip,'author',author)
    monkeypatch.setattr(writer.mtf_author,'replace_archive_model',replace)
    output,report = writer.build_grip_candidate(b'native-arc',source)
    assert calls == [(b'v14-mod',b'native-mod',source,base['skin'])]
    assert output == b'v15-arc'
    assert report['written_sha256'] == hashlib.sha256(output).hexdigest()
    assert report['grip_recipe_version'] == 1 and report['envelope_count'] == 47
    assert report['gameplay_verified'] is False and report['writer_registered'] is False
    assert 'grip_fit' not in base

import collections
import numpy as np
import pytest

from gbox import re5_sonic_hands as H


def hand_points():
    points,adjacency = [],collections.defaultdict(set)
    for centre in (-.45,-.1,.25,.6):
        start=len(points)
        points.extend([(2.2,centre-.08,.25),(2.2,centre+.08,.25),
                       (2.2,centre-.08,.1),(2.2,centre+.08,.1),
                       (2.6,centre-.06,.08),(2.6,centre+.06,.08),
                       (2.6,centre-.06,.02),(2.6,centre+.06,.02),
                       (2.7,centre-.06,-.4),(2.7,centre+.06,-.4),(2.75,centre,-.45)])
        for i in range(start,start+11):
            for j in range(start,start+11):
                if i!=j:
                    adjacency[i].add(j)
    points.extend([(1.2,-.8,-.1),(1.25,-.9,.0),(1.3,-.8,.1),
                   (1.7,-.9,-.1),(1.8,-1.,.0),(1.9,-.9,.1)])
    start=len(points)-6
    for i in range(start,len(points)):
        adjacency[i].update(j for j in range(start,len(points)) if j!=i)
    return np.asarray(points),adjacency


def test_opposite_source_palm_chirality_keeps_proximal_and_distal_order():
    points,adjacency=hand_points()
    left=H._landmarks(points,adjacency,'left')
    mirrored=points*np.array((1,1,-1))
    right=H._landmarks(mirrored,adjacency,'right')
    assert set(left)=={'index','middle','ring','little','thumb'}
    for digit in left:
        np.testing.assert_allclose(right[digit]['points'],left[digit]['points']*np.array((1,1,-1)))
    assert left['index']['points'][1,2] > left['index']['points'][2,2]


def test_joined_distal_lobes_are_refused_instead_of_inventing_digits():
    points,adjacency=hand_points()
    adjacency[4].add(15);adjacency[15].add(4)
    with pytest.raises(ValueError,match='exactly four'):
        H._landmarks(points,adjacency,'left')


def test_chain_blends_are_normalized_adjacent_and_continuous_through_knuckles():
    anchors=np.array(((0.,0,0),(1.,0,0),(1.,0,-1.)))
    before=None
    for t in np.linspace(0,2,1001):
        point=np.array((t,0,0)) if t<=1 else np.array((1,0,1-t))
        row=H._chain_weights(point,anchors)
        assert all(0<=i<=2 and 0<=w<=1 for i,w in row)
        assert sum(w for i,w in row)==pytest.approx(1.)
        weights=np.array([dict(row).get(i,0) for i in range(3)])
        if before is not None:
            assert max(abs(weights-before))<.02
        before=weights
    with pytest.raises(ValueError,match='zero-length'):
        H._chain_weights(np.zeros(3),np.zeros((3,3)))


@pytest.mark.parametrize('sign',[-1,1])
def test_repose_rotation_straightens_both_hands_without_reflecting(sign):
    direction=np.array((.5,0,sign*.8));across=np.array((0,1,0))
    target=np.array((sign,0,0));target_across=np.array((0,0,-1))
    rotation=H._proper_rotation(direction,across,target,target_across)
    np.testing.assert_allclose(rotation@direction/np.linalg.norm(direction),target,atol=1e-12)
    np.testing.assert_allclose(rotation.T@rotation,np.eye(3),atol=1e-12)
    assert np.linalg.det(rotation)==pytest.approx(1.)


def test_recipe_rejects_unreviewed_base_before_touching_source(tmp_path):
    with pytest.raises(ValueError,match='exact reviewed v12'):
        H.author(b'other MOD',tmp_path/'absent.glb',{})


def test_finger_candidate_is_separate_from_current_recipe_and_remains_unregistered(tmp_path,monkeypatch):
    from gbox import re5_sonic_writer as W
    from types import SimpleNamespace
    import zlib
    source=tmp_path/'sonic.glb'
    receipt={'skin':{'total_uniform_scale':12.6},'recipe_version':2,'gameplay_verified':False}
    monkeypatch.setattr(W,'build',lambda archive,path:(b'v12 ARC',receipt))
    entries=[None]*98;entries[97]=SimpleNamespace(data=zlib.compress(b'v12 MOD'))
    monkeypatch.setattr(W.mt_arc,'parse',lambda archive:SimpleNamespace(entries=entries))
    calls=[]
    monkeypatch.setattr(H,'author',lambda model,path,skin,**kwargs:(calls.append((model,path,skin,kwargs)) or b'finger MOD',{'experimental':True,'envelope_count':47}))
    def replace(archive,index,model):
        assert (archive,index,model)==(b'v12 ARC',97,b'finger MOD')
        return b'finger ARC'
    monkeypatch.setattr(W.mtf_author,'replace_archive_model',replace)
    output,report=W.build_finger_candidate(b'original ARC',source,correct_wrist=True)
    assert calls==[(b'v12 MOD',source,receipt['skin'],{'correct_wrist':True})] and output==b'finger ARC'
    assert report['finger_recipe_version']==2 and not report['gameplay_verified'] and not report['writer_registered']
    assert report['envelope_count']==47
    assert 'finger_rig' not in receipt and 'finger_recipe_version' not in receipt

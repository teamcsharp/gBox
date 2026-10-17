import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from gbox.face_warp import apply_layer, inverse_points, is_identity, normalize_deformation, recipe_report


def grid(columns=3, rows=3):
    return {'columns':columns,'rows':rows,'points':[
        {'x':col/(columns-1),'y':row/(rows-1)} for row in range(rows) for col in range(columns)]}


def recipe(lattice=None, strokes=None):
    return {'version':1,'lattice':lattice,'strokes':strokes or []}


def test_identity_keeps_every_channel_exact_without_mutating_input():
    rng=np.random.default_rng(12);source=rng.integers(0,256,(31,27,4),dtype=np.uint8);before=source.copy()
    for deformation in (None,{},recipe(),recipe(grid())):
        actual=apply_layer(source,deformation)
        assert np.array_equal(actual,source) and is_identity(deformation)
    assert np.array_equal(source,before)


def test_liquify_push_follows_the_cursor_and_is_local():
    s={'x':.5,'y':.5,'dx':.08,'dy':-.03,'radius':.4};deformation=recipe(strokes=[s])
    x,y,valid=inverse_points(np.array([.58,.05]),np.array([.47,.05]),deformation)
    assert valid.all() and x[0]==pytest.approx(.5,abs=1e-9) and y[0]==pytest.approx(.5,abs=1e-9)
    assert x[1]==.05 and y[1]==.05
    # Use a colour gradient so the sampled old position is observable, rather
    # than asserting that the implementation called its own inverse helper.
    source=np.zeros((101,101,4));source[...,0]=(np.arange(101)+.5)/101*255;source[...,3]=255
    out=apply_layer(source,deformation)
    assert out[47,58,0]<source[47,58,0]-15
    assert np.array_equal(out[0,0],source[0,0])


def test_lattice_moves_the_landmark_and_inverse_uses_forward_positions():
    g=grid();g['points'][4]={'x':.65,'y':.45}
    x,y,valid=inverse_points(np.array([.65,.0,1.]),np.array([.45,.0,1.]),recipe(g))
    assert valid.all() and x[0]==pytest.approx(.5) and y[0]==pytest.approx(.5)
    assert x[1]==pytest.approx(0,abs=1e-12) and y[2]==pytest.approx(1)
    assert not is_identity(recipe(g))


def test_lattice_then_strokes_are_inverted_in_reverse_order():
    g=grid();g['points'][4]={'x':.6,'y':.5}
    s={'x':.6,'y':.5,'dx':0,'dy':.05,'radius':.3}
    x,y,valid=inverse_points(.6,.55,recipe(g,[s]))
    assert valid and x==pytest.approx(.5,abs=1e-8) and y==pytest.approx(.5,abs=1e-8)


def test_real_bilinear_sampling_and_premultiplied_transparent_edges():
    source=np.array([[[255,0,0,255],[0,0,255,0]],[[255,0,0,255],[0,0,255,0]]],float)
    g=grid(2,2)
    for p in g['points']:p['x']+=.25
    out=apply_layer(source,recipe(g))
    # Destination right pixel maps halfway between opaque red and invisible
    # blue. Invisible blue must not contaminate the visible photo colour.
    assert out[0,1,0]==pytest.approx(255)
    assert out[0,1,2]==pytest.approx(0)
    assert out[0,1,3]==pytest.approx(127.5)


def test_destination_coverage_clips_warped_layer_and_soft_alpha():
    source=np.full((16,16,4),[255,20,10,255],float)
    coverage=np.zeros((16,16));coverage[4:12,4:12]=.5
    s={'x':.5,'y':.5,'dx':.05,'dy':0,'radius':.3}
    out=apply_layer(source,recipe(strokes=[s]),coverage)
    assert not out[coverage==0].any()
    assert np.all(out[coverage>0,3]==127.5)
    assert np.array_equal(source,np.full((16,16,4),[255,20,10,255],float))


@pytest.mark.parametrize('bad',[
    {'version':True}, {'version':2}, {'version':1,'unknown':0},
    {'version':1,'strokes':[{'x':.5,'y':.5,'dx':.3,'dy':0,'radius':1}]},
    {'version':1,'strokes':[{'x':.5,'y':.5,'dx':.1,'dy':0,'radius':.1}]},
    {'version':1,'strokes':[{'x':float('nan'),'y':.5,'dx':0,'dy':0,'radius':.1}]},
    {'version':1,'strokes':[{'x':.5,'y':.5,'dx':0,'dy':0,'radius':0}]},
    {'version':1,'strokes':[{'x':.5,'y':.5,'dx':0,'dy':0,'radius':.1}]*257},
    recipe({'columns':10,'rows':2,'points':[]}),
    recipe({'columns':True,'rows':2,'points':[]}),
    recipe({'columns':2,'rows':2,'points':[{'x':0,'y':0}]*4}),
    recipe({'columns':2,'rows':2,'points':[{'x':0,'y':0},{'x':1,'y':0},{'x':1,'y':1},{'x':0,'y':1}]}),
])
def test_invalid_or_folded_recipes_fail_before_render(bad):
    with pytest.raises(ValueError):normalize_deformation(bad)


def test_nonfinite_images_and_invalid_coverage_rejected():
    source=np.zeros((4,4,4));source[0,0,0]=float('nan')
    with pytest.raises(ValueError):apply_layer(source)
    with pytest.raises(ValueError):apply_layer(np.zeros((4,4,4)),clipmask=np.ones((2,2)))
    with pytest.raises(ValueError):apply_layer(np.zeros((4,4,4)),clipmask=np.full((4,4),2))


def test_canonical_recipe_and_digest_are_stable_and_not_aliased():
    raw=recipe(grid(),[{'x':.5,'y':.5,'dx':.01,'dy':0,'radius':.1}]);before=copy.deepcopy(raw)
    a=recipe_report(raw);b=recipe_report(raw)
    assert a==b and len(a['sha256'])==64 and raw==before
    a['recipe']['lattice']['points'][0]['x']=1
    assert raw==before


@pytest.mark.skipif(not shutil.which('node'),reason='Browser renderer parity requires Node')
def test_browser_and_native_bake_sample_the_same_combined_edit():
    g=grid();g['points'][4]={'x':.65,'y':.45}
    deformation=recipe(g,[{'x':.6,'y':.4,'dx':.05,'dy':-.02,'radius':.3}])
    source=np.array([[[x*25,y*31,(x+y)*17,255 if x<4 else 75]
                      for x in range(6)] for y in range(5)],dtype=np.uint8)
    script="""let raw='';process.stdin.on('data',v=>raw+=v).on('end',()=>{
      const p=JSON.parse(raw),m=require('./clients/web/viz/face-warp-editor.js');
      process.stdout.write(JSON.stringify(Array.from(m.warpPixels(p.source,6,5,p.deformation))));
    });"""
    output=subprocess.run([shutil.which('node'),'-e',script],
                          input=json.dumps({'source':source.ravel().tolist(),'deformation':deformation}),
                          text=True,capture_output=True,check=True,timeout=15,cwd=Path(__file__).parents[1])
    browser=np.array(json.loads(output.stdout),dtype=np.uint8)
    baked=np.rint(np.clip(apply_layer(source,deformation),0,255)).astype(np.uint8).ravel()
    assert np.array_equal(browser,baked)


def test_shared_editor_fixture_has_stable_baked_pixels():
    g=grid();g['points'][4]={'x':.58,'y':.46}
    deformation=recipe(g,[{'x':.5,'y':.5,'dx':.025,'dy':-.015,'radius':.35}])
    source=np.array([[[x*31,y*29,(x+y)*15,255 if (x+y)%3 else 64]
                      for x in range(8)] for y in range(8)],dtype=np.uint8)
    actual=np.rint(np.clip(apply_layer(source,deformation),0,255)).astype(np.uint8)
    assert hashlib.sha256(actual.tobytes()).hexdigest()=='959fc83976a656799ce25de943d5efe009df2da0af8e986f78def31c8000566d'

"""A click must bind actual captured pixels; an unavailable capture never selects a guessed person."""
import struct
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from gbox import pso_face_target as T, pso_gc_swap as W, pso_gc as G


def chunk():
    image=np.asarray(Image.new('RGBA',(32,32),(60,120,180,255)))
    native=W.gx_encode(image,4);header=bytearray(16);header[:4]=b'GVRT'
    struct.pack_into('<I',header,4,len(native)+8);header[11]=4;struct.pack_into('>HH',header,12,32,32)
    return bytes(header)+native


def test_captured_texture_binding_requires_native_dimensions_alpha_and_full_pixel_agreement():
    native=chunk();pixels=G.gvr_decode(native)
    row={'name':'actual','w':32,'h':32,'rgba':pixels.tobytes(),'materials':['face']}
    assert T.texture_binding(native,[row])[0]['materials']==['face']
    changed=pixels.copy();changed[0,0,0]^=128
    assert not T.texture_binding(native,[row|{'rgba':changed.tobytes()}])
    assert not T.texture_binding(native,[row|{'w':16}])
    changed=pixels.copy();changed[:,:,3]=0
    assert not T.texture_binding(native,[row|{'rgba':changed.tobytes()}])


@pytest.mark.parametrize('owned',[True,False])
def test_failed_character_cut_releases_only_the_capture_owned_pause(tmp_path,monkeypatch,owned):
    from gbox import scene_capture as SC,characters as C
    calls=[];ad=SimpleNamespace(resume=lambda:calls.append('resume'))
    monkeypatch.setattr(SC,'capture_session',lambda *a,**kw:{'scene_draws':1,'resume_on_leave':owned})
    def no_person(*a):raise LookupError('only level geometry')
    monkeypatch.setattr(C,'cut_scene',no_person)
    ctx=SimpleNamespace(config=SimpleNamespace(runtime=tmp_path),job_id='test',progress=lambda *a:None)
    with pytest.raises(LookupError,match='level geometry'):T.capture(ad,'session',{'x':.5,'y':.5},ctx)
    assert calls==(['resume'] if owned else [])


def test_letterbox_click_cannot_launch_a_capture(tmp_path,monkeypatch):
    from gbox import scene_capture as SC
    monkeypatch.setattr(SC,'capture_session',lambda *a,**kw:pytest.fail('letterbox cannot become a guessed model'))
    ctx=SimpleNamespace(config=SimpleNamespace(runtime=tmp_path),job_id='test')
    with pytest.raises(ValueError,match='letterbox'):T.capture(None,'s',{'x':0,'y':.5,'window_aspect':2},ctx)

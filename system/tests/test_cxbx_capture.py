"""Owned synthetic windows only: no emulator, desktop capture, or process control."""
import ctypes
from ctypes import wintypes as w
import hashlib
import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageGrab

from gbox import adapters, cxbx_capture, tools, xbox


def png(color="blue", size=(40, 30)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


class Fn:
    def __init__(self, fn): self.fn = fn
    def __call__(self, *args): return self.fn(*args)


def window(monkeypatch, *, hits=None, surface=True, owner=123, klass="CxbxRender", moved=False, size=(40, 30)):
    calls = {"hits": 0, "geometry": 0, "screen": 0, "print": 0}
    def rect(hwnd, ptr):
        box = ctypes.cast(ptr, ctypes.POINTER(w.RECT)).contents
        box.left, box.top, box.right, box.bottom = 0, 0, *size
        return 1
    def origin(hwnd, ptr):
        calls["geometry"] += 1
        point = ctypes.cast(ptr, ctypes.POINTER(w.POINT)).contents
        point.x = 1 if moved and calls["geometry"] > 1 else 0
        point.y = 0
        return 1
    def pid(hwnd, ptr):
        ctypes.cast(ptr, ctypes.POINTER(w.DWORD)).contents.value = 999 if hwnd == 9 else owner
        return 1
    def name(hwnd, buf, count):
        buf.value = klass
        return len(klass)
    def hit(point):
        n = calls["hits"]; calls["hits"] += 1
        return hits[n % len(hits)] if hits else 1
    user = SimpleNamespace(GetClientRect=Fn(rect), GetWindowRect=Fn(rect), ClientToScreen=Fn(origin),
        GetWindowThreadProcessId=Fn(pid), GetClassNameW=Fn(name), WindowFromPoint=Fn(hit),
        IsChild=Fn(lambda parent, child: child == 2))
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user), raising=False)
    def print_window(*args):
        calls["print"] += 1
        return png() if surface else None
    def grab(*args, **kwargs):
        calls["screen"] += 1
        return Image.new("RGB", (40, 30), "green")
    monkeypatch.setattr(adapters, "_print_window_png", print_window)
    monkeypatch.setattr(ImageGrab, "grab", grab)
    return calls


@pytest.mark.parametrize("hits,expected,count", [
    ([1], "sampled-clear", 0), ([2], "sampled-clear", 0),
    ([9,1,1,1,1,1,1,1,1], "occluded", 1), ([3], "occluded", 9),
    ([0], "unknown", 0), ([0,9], "occluded", 5),
])
def test_printwindow_is_diagnostic_and_coverage_checked_even_when_it_returns_pixels(monkeypatch, hits, expected, count):
    calls = window(monkeypatch, hits=hits)
    data, meta = cxbx_capture.capture_window(1, 123)
    assert Image.open(io.BytesIO(data)).size == (40, 30)
    assert meta == {"pid":123, "hwnd":1, "source":"cxbx-print-window", "covered":count,
                    "occlusion":expected, "sha256":hashlib.sha256(data).hexdigest()}
    assert calls == {"hits":18,"geometry":2,"print":1,"screen":0}
    assert "uncovered" not in meta.values()


@pytest.mark.parametrize("hits", [[9], [0], [1]*9+[9]*9, [1]*9+[0]*9])
def test_compositor_never_returns_known_or_unknown_obscured_pixels(monkeypatch, hits):
    window(monkeypatch, hits=hits, surface=False)
    with pytest.raises(RuntimeError, match="covered|unknown"):
        cxbx_capture.capture_window(1, 123)


def test_compositor_clear_samples_still_are_not_entire_window_proof(monkeypatch):
    calls = window(monkeypatch, surface=False)
    data, meta = cxbx_capture.capture_window(1,123)
    assert meta["source"] == "cxbx-desktop-compositor" and meta["occlusion"] == "sampled-clear"
    assert meta["sha256"] == hashlib.sha256(data).hexdigest() and calls["screen"] == 1


@pytest.mark.parametrize("options,match", [({"owner":999},"identity"), ({"klass":"Cxbx"},"identity"),
    ({"size":(100000,100000)},"capture limit"), ({"size":(0,0)},"minimized"),
    ({"moved":True},"outside|changed")])
def test_changed_or_invalid_window_is_not_captured_as_a_valid_frame(monkeypatch, options, match):
    window(monkeypatch, **options)
    with pytest.raises(RuntimeError, match=match): cxbx_capture.capture_window(1,123)


def test_wrong_printwindow_dimensions_rejected(monkeypatch):
    window(monkeypatch)
    monkeypatch.setattr(adapters,"_print_window_png",lambda *a:png(size=(80,60)))
    with pytest.raises(RuntimeError,match="dimensions"):cxbx_capture.capture_window(1,123)


def adapter(monkeypatch, cfg):
    ad = xbox.XboxAdapter(cfg)
    ad.render_pid, ad.render_window, ad._owned = 123, {"hwnd":1}, {123:10.0}
    ad.proc = SimpleNamespace(pid=123)
    monkeypatch.setattr(ad,"_running",lambda:True)
    monkeypatch.setattr(ad,"_live",lambda:{123})
    return ad


def test_real_cxbx_adapter_metadata_reaches_tool_and_artifact_without_shared_state(monkeypatch,cfg):
    window(monkeypatch,hits=[9])
    ad=adapter(monkeypatch,cfg)
    monkeypatch.setitem(tools.SESSIONS,"cxbx-fixture",(ad,{"game_id":"owned"}))
    monkeypatch.setattr(tools,"HOST_OS","windows")
    monkeypatch.setattr(adapters,"win_grab_state",lambda:pytest.fail("Cxbx must use its own exact capture metadata"))
    artifacts=[]
    result=tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(session_id="cxbx-fixture"),
        SimpleNamespace(artifact=lambda *a,**kw:artifacts.append((a,kw))))).model_dump()
    assert result["capture_source"]=="cxbx-print-window" and result["capture_occlusion"]=="occluded"
    assert result["covered"]==9 and result["mean_luma"]>3 and result["gameplay_verified"] is False
    assert artifacts[0][1]["capture_occlusion"]=="occluded" and artifacts[0][1]["gameplay_verified"] is False
    assert result["sha256"]==ad.frame_capture_state()["sha256"]


@pytest.mark.parametrize("change",["pid","birth","gone","hwnd","capture-fails"])
def test_failed_or_replaced_capture_clears_old_metadata(monkeypatch,cfg,change):
    ad=adapter(monkeypatch,cfg);ad._capture_local.state={"sha256":"old"}
    def capture(*args, **kwargs):
        if change=="pid":ad.render_pid=456
        elif change=="birth":ad._owned[123]=11.0
        elif change=="gone":monkeypatch.setattr(ad,"_live",lambda:set())
        elif change=="hwnd":ad.render_window={"hwnd":2}
        else:raise RuntimeError("capture failed")
        return png(),{"sha256":"new"}
    monkeypatch.setattr(cxbx_capture,"capture_window",capture)
    with pytest.raises(RuntimeError):ad.get_frame()
    assert ad.frame_capture_state()=={}


def test_concurrent_captures_do_not_share_metadata(monkeypatch,cfg):
    import threading
    ad=adapter(monkeypatch,cfg)
    gate=threading.Barrier(2)
    def capture(*args, **kwargs):
        name=threading.current_thread().name
        data=png('red' if name=='capture-one' else 'blue')
        return data,{'pid':123,'sha256':hashlib.sha256(data).hexdigest(),'source':name}
    monkeypatch.setattr(cxbx_capture,'capture_window',capture)
    results=[]
    def run():
        data=ad.get_frame();gate.wait(timeout=5)
        results.append((threading.current_thread().name,data,ad.frame_capture_state()))
    threads=[threading.Thread(target=run,name=n) for n in ('capture-one','capture-two')]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=6)
    assert len(results)==2 and all(not t.is_alive() for t in threads)
    assert all(meta['source']==name and meta['sha256']==hashlib.sha256(data).hexdigest() for name,data,meta in results)
    assert ad.frame_capture_state() is None


def test_native_presenter_subclass_keeps_its_existing_capture_metadata(monkeypatch,cfg):
    from gbox.doa3_native import Doa3NativeAdapter
    ad=Doa3NativeAdapter(cfg,{})
    ad.render_pid,ad.render_window,ad._owned=123,{'hwnd':1},{123:10.0}
    ad.proc=SimpleNamespace(pid=123)
    monkeypatch.setattr(ad,'_running',lambda:True)
    monkeypatch.setattr(ad,'_boot_frame',lambda **kwargs:None)
    data=png()
    monkeypatch.setattr(adapters,'win_grab',lambda pid:data)
    monkeypatch.setattr(adapters,'win_grab_state',lambda:{'pid':123,'sha256':hashlib.sha256(data).hexdigest(),
        'covered':2,'source':'window-surface'})
    monkeypatch.setitem(tools.SESSIONS,'native-fixture',(ad,{'game_id':'owned'}))
    monkeypatch.setattr(tools,'HOST_OS','windows')
    out=tools.get_frame(tools.FrameIn(session_id='native-fixture'),SimpleNamespace(artifact=lambda *a,**k:None))
    assert out['capture_source']=='window-surface' and out['covered']==2
    assert ad.frame_capture_state() is None


def test_missing_capture_state_is_initialized_lazily(monkeypatch,cfg):
    window(monkeypatch)
    ad=adapter(monkeypatch,cfg)
    del ad._capture_local
    assert ad.frame_capture_state() is None
    data=ad.get_frame()
    assert ad.frame_capture_state()['sha256']==hashlib.sha256(data).hexdigest()

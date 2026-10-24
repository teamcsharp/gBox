"""Letterbox measurement for PiP fitting: pure black bars only, dark scenes and black frames are not bars."""
import io
import random

from PIL import Image

from gbox import picture_bounds as P


def jpeg(w, h, box=None, fill=(90, 40, 30), noise=0, bg=(0, 0, 0)):
    im = Image.new("RGB", (w, h), bg)
    if box:
        x, y, bw, bh = box
        rng = random.Random(1)
        panel = Image.new("RGB", (bw, bh), fill)
        if noise:
            px = panel.load()
            for i in range(0, bw, 3):
                for j in range(0, bh, 3):
                    v = rng.randint(0, noise)
                    px[i, j] = (fill[0] + v, fill[1], fill[2])
        im.paste(panel, (x, y))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=90)
    return out.getvalue()


def test_re4_style_letterbox_in_a_4_3_frame_is_measured():
    m = P.measure(jpeg(640, 480, (0, 60, 640, 360)))
    assert (m["w"], m["h"]) == (640, 480)
    c = m["content"]
    assert abs(c["y"] - 60) <= 6 and abs(c["h"] - 360) <= 12 and c["x"] <= 3 and c["w"] >= 634
    assert m["bars"]["top"] > 0.1 and m["bars"]["bottom"] > 0.1 and m["bars"]["left"] == 0


def test_dark_scene_without_pure_black_is_not_a_bar():
    m = P.measure(jpeg(640, 480, (0, 0, 640, 480), fill=(14, 14, 14), noise=10))
    assert m["content"] == {"x": 0, "y": 0, "w": 640, "h": 480}


def test_black_frame_reports_no_content():
    m = P.measure(jpeg(320, 240))
    assert m["content"] is None and m["bars"]["top"] == 1.0


def test_cache_returns_same_measurement_within_ttl_and_survives_bad_bytes():
    f = jpeg(320, 240, (40, 0, 240, 240))
    a = P.cached("s1", f, now=100.0)
    b = P.cached("s1", f, now=101.0)
    assert a == b and a["content"]["x"] >= 36
    bad = P.cached("s2", b"not a jpeg", now=100.0)
    assert bad["content"] is None and bad.get("error")

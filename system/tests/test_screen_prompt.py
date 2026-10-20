"""On-screen action prompts (gbox.screen_prompt): the RE4 A icon is found in its box, nothing else is."""
import numpy as np

from gbox import screen_prompt as P


def frame(button_rgb=None, at=(259, 386), size=(480, 640)):
    img = np.zeros(size + (3,), np.uint8)
    img[:, :] = (90, 80, 60)
    if button_rgb is not None:
        yy, xx = np.ogrid[:size[0], :size[1]]
        img[(yy - at[1]) ** 2 + (xx - at[0]) ** 2 <= 10 ** 2] = button_rgb
    return img


def test_finds_the_a_icon_where_re4_draws_it():
    found = P.detect(frame((40, 134, 104)))
    assert found["button"] == "a" and found["box"][0] in range(245, 255)


def test_scales_with_the_picture():
    assert P.detect(frame((40, 134, 104), at=(388, 579), size=(720, 960)))["button"] == "a"


def test_no_prompt_no_detection():
    assert P.detect(frame()) is None
    assert P.detect(frame((40, 134, 104), at=(560, 450))) is None          # the ammo dial's corner: outside the box
    grass = frame()
    grass[350:420, 190:380] = (60, 140, 90)                                   # a strip of green grass: not a disc
    assert P.detect(grass) is None


def test_watcher_reports_the_latest_button_while_fresh():
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(frame((40, 134, 104))).save(b, "JPEG", quality=95)
    now = [100.0]
    w = P.Watcher(lambda: b.getvalue(), clock=lambda: now[0])
    w.step()
    assert w.visible() == "a"
    now[0] += 2.0
    assert w.visible() is None                                               # stale: no longer on screen

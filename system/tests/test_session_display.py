"""Every Linux session on one 1280x720 display (gbox.session_display): where each emulator's window and picture go, the
letterboxed RE4's taller window, the window fitter every standalone emulator shares, and the pixel code that measured
positions on 4:3 frames. No X display or emulator runs here."""
import base64
import io
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from gbox import adapters, cheats, imitate, screen_prompt, session_display as sd
from gbox.config import Config


def disc(path: Path, serial: bytes) -> str:
    header = serial + bytes(0x8000 - len(serial))
    first = zlib.compress(header)
    path.write_bytes(struct.pack('<IIQQII', 0xB10BC001, 0, len(first), len(header) * 2, len(header), 2)
                     + struct.pack('<QQII', 0, len(first), 0, 0) + first)
    return str(path)


def dolphin(tmp_path, serial: str | None = None, display=(1280, 720)):
    ad = adapters.DolphinAdapter(Config(data_dir=tmp_path / "data"), "gamecube")
    ad.gecko_id = serial
    if display:
        ad.display = SimpleNamespace(name=":95", w=display[0], h=display[1])
    return ad


# --- geometry -------------------------------------------------------------------------------------------------------

def test_every_linux_session_display_is_1280x720():
    assert sd.SESSION_SIZE == (1280, 720)
    assert adapters.Display.__init__.__defaults__ == (1280, 720)          # RetroArch's Linux sessions take the default
    for cls in (adapters.StandaloneAdapter, adapters.DolphinAdapter, adapters.DuckStationAdapter, adapters.MgbaAdapter,
                adapters.MameAdapter, adapters.RPCS3LinuxAdapter, adapters.SwitchLinuxAdapter,
                adapters.CitronLinuxAdapter):
        assert tuple(cls.screen) == (1280, 720), cls.__name__


def test_the_session_stream_keeps_960_wide(tmp_path, monkeypatch):
    """Measured 2026-10-27: a 1280x720 stream cost 12-15 more points of a core than 960x540 on the CPU-starved Spark,
    so the stream stays at 960 wide (session_display.STREAM_MAX_WIDTH) for every Linux session."""
    made = []
    monkeypatch.setattr(adapters, "MjpegStream", lambda display, **kw: made.append((display, kw)) or "stream")
    ad = dolphin(tmp_path, "G4BE08")
    assert ad.stream_session() == "stream"
    ra = adapters.RetroArchAdapter(adapters.EmulatorConfig(core="x"), platform="psx")
    ra.display = SimpleNamespace(name=":96", w=1280, h=720)
    ra.stream_session()
    assert sd.STREAM_MAX_WIDTH == 960
    assert made == [(":95", {"size": (1280, 720), "max_width": 960}), (":96", {"size": (1280, 720), "max_width": 960})]


def test_mame_opens_its_window_at_the_display_size(tmp_path):
    ad = adapters.MameAdapter(Config(data_dir=tmp_path / "data"), "arcade")
    argv = ad._argv(str(tmp_path / "sf2.zip"))
    assert argv[argv.index("-resolution") + 1] == "1280x720"


def test_a_4_3_picture_is_pillarboxed_by_the_emulator():
    assert sd.window_rect((1280, 720)) == (0, 0, 1280, 720)               # the window fills the display
    assert sd.picture_rect((1280, 720)) == (160, 0, 960, 720)             # the emulator keeps 4:3 inside it
    assert sd.picture_rect((1280, 720), sd.WIDE) == (0, 0, 1280, 720)
    assert sd.picture_rect((1280, 720), 3 / 2) == (100, 0, 1080, 720)    # GBA
    assert sd.picture_rect((640, 480)) == (0, 0, 640, 480)                # the old Dolphin display: frame = picture
    assert sd.picture_rect((960, 1280)) == (0, 280, 960, 720)            # a tall display letterboxes instead


RE4 = sd.LETTERBOXED["G4BE08"]


def test_a_letterboxed_title_gets_a_taller_window_whose_band_covers_the_display():
    """RE4 on GameCube (measured 2026-10-27): bars of 60 lines top and bottom of 480, so its picture is the middle
    360/480 of the frame, and Dolphin draws the frame 625:480. A window 1280 wide fills the display's width; 1 % taller
    than the frame, so Dolphin fits the frame to the width and no side bar can appear."""
    assert (RE4.band, RE4.aspect) == (0.75, 625 / 480)
    assert sd.window_rect((1280, 720), RE4.aspect, RE4.band) == (0, -137, 1280, 993)
    x, y, w, h = sd.picture_rect((1280, 720), RE4.aspect, RE4.band)
    assert (x, y, w, h) == (0, -132, 1280, 983)                            # the frame, centred in its window
    band_top, band_bottom = y + h * 60 / 480, y + h * 420 / 480            # the game's picture, in display pixels
    assert -10 < band_top < 0 and 720 < band_bottom < 730                  # covers the display; 8-9 px off each edge
    # an exact 4:3 frame with a 16:9 band and no margin: the band is exactly the display, at 2x
    assert sd.window_rect((1280, 720), sd.STANDARD, 0.75, margin=0) == (0, -120, 1280, 960)
    assert sd.window_rect((1920, 1080), sd.STANDARD, 0.75, margin=0) == (0, -180, 1920, 1440)
    assert sd.window_rect((1280, 720)) == (0, 0, 1280, 720)                # not letterboxed: the whole display


@pytest.mark.parametrize("serial", ["G4BE08", "g4be08"])
def test_resident_evil_4_usa_is_the_letterboxed_fact(serial):
    assert sd.letterbox(serial) is RE4


@pytest.mark.parametrize("serial", ["GMSE01", "GZLE01", "", None, "G4BE", "G4BP08"])
def test_other_discs_are_not_letterboxed(serial):
    assert sd.letterbox(serial) is None                                     # (PAL RE4 has another frame: unmeasured)


def test_frame_picture_finds_the_picture_in_frames_of_any_origin():
    assert sd.frame_picture(640, 480) == (0, 0, 1, 1)                      # an old Spark frame, a 4:3 window
    assert sd.frame_picture(1280, 720) == (0.125, 0, 0.75, 1)              # pillarboxed 4:3
    assert sd.frame_picture(960, 540) == (0.125, 0, 0.75, 1)               # the same display through the stream
    band = sd.frame_picture(1280, 720, RE4.aspect, RE4.band)
    assert band == pytest.approx((0, -132 / 720, 1, 983 / 720))            # RE4: the band fills the grab
    assert sd.frame_picture(960, 540, RE4.aspect, RE4.band) == pytest.approx(band, abs=0.003)
    old = sd.frame_picture(640, 480, RE4.aspect, RE4.band)                 # RE4's old 640x480 grabs: the whole frame,
    assert old == pytest.approx((7.5 / 640, 0, 625 / 640, 1), abs=0.002)   # 8 px side bars as Dolphin drew them


def test_map_box_maps_picture_fractions_into_frame_pixels_and_clamps():
    assert sd.map_box((0.30, 0.72, 0.60, 0.88), (0, 0, 1, 1), 640, 480) == (192, 345, 384, 422)
    assert sd.map_box((0.30, 0.72, 0.60, 0.88), (0.125, 0, 0.75, 1), 1280, 720) == (448, 518, 736, 633)
    assert sd.map_box((0.30, 0.72, 0.60, 0.88), (0, -1 / 6, 1, 4 / 3), 1280, 720) == (384, 571, 768, 720)


# --- adapters -------------------------------------------------------------------------------------------------------

def test_dolphin_sizes_re4s_window_past_the_display_and_keeps_its_own_aspect(tmp_path, monkeypatch):
    re4 = dolphin(tmp_path, "G4BE08")
    assert re4.letterbox() is RE4
    assert re4.window_rect() == (0, -137, 1280, 993)
    assert re4.picture_rect() == (0, -132, 1280, 983)
    sms = dolphin(tmp_path, "GMSE01")
    assert sms.letterbox() is None
    assert sms.window_rect() == (0, 0, 1280, 720)
    assert sms.picture_rect() == (160, 0, 960, 720)
    # no aspect option: Dolphin 2609a ignored every -C aspect setting on the Spark (Stretch, Force 16:9, Custom
    # stretch, Raw, Crop: the same 625:480 picture), so the window takes the frame's drawn shape instead
    monkeypatch.setattr(cheats, "gecko_codes", lambda *args: [])
    ad = adapters.DolphinAdapter(Config(data_dir=tmp_path / "data"), "gamecube")
    argv = ad._argv(disc(tmp_path / "Resident Evil 4 (USA) (Disc 1).gcz", b"G4BE08"))
    assert ad.gecko_id == "G4BE08" and not any("AspectRatio" in a or "Settings.Crop" in a for a in argv)


def fitter(ad, geometry: dict, names=None):
    moves, searches = [], []

    def out(*a):
        if a[0] == "search":
            searches.append(a)
            return "".join(f"{w}\n" for w in geometry)
        return geometry[a[1]]
    ad._xdo_out = out
    ad._xdo = lambda *a: moves.append(a)
    return moves, searches


def geo(x, y, w, h, wid="7"):
    return f"Window {wid}\n  Position: {x},{y} (screen: 0)\n  Geometry: {w}x{h}\n"


def test_the_fitter_moves_re4s_render_window_to_its_letterbox_geometry(tmp_path):
    ad = dolphin(tmp_path, "G4BE08")
    g = {"7": geo(0, 0, 1280, 720)}                                        # Qt's fullscreen: the whole display
    moves, searches = fitter(ad, g)
    assert ad._fit_window_once() == 1
    assert searches == [("search", "--onlyvisible", "--name", "^Dolphin.*[|]")]    # only the render window
    import re                                                              # (xdotool's regex is POSIX extended)
    assert re.search(ad.FIT_NAME, "Dolphin 2609a | JITARM64 SC | Vulkan | HLE | Resident Evil 4 (G4BE08)")
    assert not re.search(ad.FIT_NAME, "Dolphin") and not re.search(ad.FIT_NAME, "Warning")
    assert moves == [("windowmove", "7", "0", "-137"), ("windowsize", "7", "1280", "993")]
    moves.clear()
    g["7"] = geo(0, -137, 1280, 993)
    assert ad._fit_window_once() == 0 and moves == []                      # nothing to do once fitted


def test_the_fitter_fills_the_display_for_other_games_and_emulators(tmp_path):
    ad = dolphin(tmp_path, "GMSE01")
    moves, _ = fitter(ad, {"7": geo(320, 120, 640, 480)})
    assert ad._fit_window_once() == 1
    assert moves == [("windowmove", "7", "0", "0"), ("windowsize", "7", "1280", "720")]
    moves, _ = fitter(ad, {"7": geo(0, 0, 1280, 720)})
    assert ad._fit_window_once() == 0 and moves == []
    duck = adapters.DuckStationAdapter(Config(data_dir=tmp_path / "data"), "psx")
    duck.display = SimpleNamespace(name=":96", w=1280, h=720)
    moves, searches = fitter(duck, {"9": geo(0, 0, 640, 480, "9")})
    assert duck._fit_window_once() == 1 and searches[0][-1] == "."         # any named window: DuckStation's own
    assert moves[-1] == ("windowsize", "9", "1280", "720")
    rpcs3 = adapters.RPCS3LinuxAdapter.__new__(adapters.RPCS3LinuxAdapter)
    assert rpcs3.FIT_NAME == "^FPS[: ]"                                    # RPCS3: its renderer, never a dialog


def test_a_window_already_in_place_is_still_resized_so_its_renderer_fills_it(tmp_path):
    """2026-10-27, live: Dolphin's Qt fullscreen window was 1280x720 from the start, the fitter had nothing to move,
    and Dolphin drew its 640x480 picture in the top-left corner (its renderer keeps the size of the window it started
    in until a resize reaches it). A fitter run resizes such a window off and back, FIT_NUDGES times, then leaves it."""
    ad = dolphin(tmp_path, "GMSE01")
    moves, _ = fitter(ad, {"7": geo(0, 0, 1280, 720)})
    nudged = {}
    assert ad._fit_window_once(nudged) == 1
    assert moves == [("windowsize", "7", "1280", "718"), ("windowmove", "7", "0", "0"),
                     ("windowsize", "7", "1280", "720")]
    assert ad._fit_window_once(nudged) == 1 and ad._fit_window_once(nudged) == 0   # twice per window, then left alone
    assert nudged == {"7": 2}
    moves.clear()
    assert ad._fit_window_once() == 0 and moves == []                      # a bare check never nudges


def thumb(lit: tuple[int, int, int, int] | None, w=160, h=90) -> bytes:
    """A 160x90 grey grab with the box (x0, y0, x1, y1), inclusive, lit."""
    px = bytearray(w * h)
    if lit:
        x0, y0, x1, y1 = lit
        for y in range(y0, y1 + 1):
            px[y * w + x0:y * w + x1 + 1] = bytes([120]) * (x1 - x0 + 1)
    return bytes(px)


@pytest.mark.parametrize("lit, verdict", [
    ((1, 0, 79, 45), True),          # RE4's window at y -120 drawing its old 640x480 picture (live: 8,0 - 649,375)
    ((0, 0, 80, 60), True),          # a 1280x720 window drawing 640x480 in its corner (live: 0,0 - 649,480)
    ((2, 0, 158, 89), False),        # the band filling the display (live: 15,0 - 1265,720)
    ((21, 11, 139, 79), False),      # 4:3 pillarboxed with RE4's own letterbox (live: 171,90 - 1109,631)
    ((32, 14, 132, 63), False),      # RE4's memory card prompt at full size (live: 260,117 - 1057,508)
    (None, None),                    # a black frame: nothing to judge
    ((79, 44, 80, 46), None),        # a speck (the pointer, were it drawn)
])
def test_a_picture_stuck_in_the_top_left_corner_is_told_from_a_full_one(lit, verdict):
    assert sd.corner_only(thumb(lit), 160, 90) is verdict


def test_the_fitter_resizes_again_while_the_picture_is_stuck_and_stops_once_it_is_full(tmp_path):
    import threading
    import time
    ad = dolphin(tmp_path, "G4BE08")
    ad.FIT_WINDOW_EVERY_S, ad.FIT_WINDOW_S, ad.STALE_CHECK_S = 0.01, 0.0, 5.0
    looks = iter([None, True, True, False])                                # black, stuck, stuck, full
    calls, done = [], threading.Event()

    def stale():
        v = next(looks, "over")
        if v == "over":
            done.set()
            return False
        return v
    ad._picture_stale = stale
    ad._fit_window_once = lambda nudged=None: calls.append(dict(nudged) if nudged is not None else None) or 1
    ad._fit_window()
    time.sleep(0.5)
    assert ad.stale_nudges == 2 and calls == [{}, {}]                      # one resize per stuck look, none after
    assert not done.is_set()                                               # settled: no more looks once it was full


def test_a_picture_that_only_looks_stuck_is_resized_a_bounded_number_of_times(tmp_path):
    import time
    ad = dolphin(tmp_path, "GMSE01")
    ad.FIT_WINDOW_EVERY_S, ad.FIT_WINDOW_S, ad.STALE_CHECK_S, ad.STALE_NUDGES_MAX = 0.01, 0.0, 5.0, 3
    looks = []
    ad._picture_stale = lambda: looks.append(1) or True                    # e.g. a menu drawn in the top-left only
    ad._fit_window_once = lambda nudged=None: 1
    ad._fit_window()
    time.sleep(0.5)
    assert ad.stale_nudges == 3 and len(looks) == 3                         # then it stops looking


def test_a_standalone_launch_starts_the_fitter_and_reports_window_and_picture(tmp_path, monkeypatch):
    ad = dolphin(tmp_path, None, display=None)
    started = []
    monkeypatch.setattr(adapters, "Display", lambda w, h: SimpleNamespace(name=":97", w=w, h=h, proc=None,
                                                                          close=lambda: None))
    monkeypatch.setattr(adapters.provision, "ensure_flatpak", lambda *a: None)
    monkeypatch.setattr(adapters.provision, "linux_audio_env", lambda *a: {})
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    monkeypatch.setattr(ad, "_argv", lambda rom: setattr(ad, "gecko_id", "G4BE08") or ["true"])
    monkeypatch.setattr(ad, "_debugger", lambda: None)
    monkeypatch.setattr(ad, "_fit_window", lambda: started.append(ad.window_rect()))
    monkeypatch.setattr(adapters.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=4242, poll=lambda: None))
    d = ad.launch_game(str(tmp_path / "re4.gcz"))
    assert ad.display.w == 1280 and ad.display.h == 720
    assert started == [(0, -137, 1280, 993)]
    assert d["window"] == [0, -137, 1280, 993] and d["picture"] == [0, -132, 1280, 983]


def test_stop_game_ends_the_fitter(tmp_path, monkeypatch):
    import threading
    import time
    ad = dolphin(tmp_path, "G4BE08")
    ad.FIT_WINDOW_EVERY_S = 0.01
    seen = []
    ad._fit_window_once = lambda nudged=None: seen.append(threading.current_thread()) or 0
    ad._fit_window()
    deadline = time.monotonic() + 5
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    thread = seen[0]
    monkeypatch.setattr(adapters, "_kill_tree", lambda proc: None)
    ad.display = SimpleNamespace(name=":95", w=1280, h=720, close=lambda: None)
    ad.stop_game()
    thread.join(5)
    assert not thread.is_alive()


def test_session_picture_is_where_frames_hold_the_game(tmp_path):
    assert sd.session_picture(dolphin(tmp_path, "G4BE08")) == pytest.approx((0, -132 / 720, 1, 983 / 720))
    assert sd.session_picture(dolphin(tmp_path, "GMSE01")) == (0.125, 0, 0.75, 1)
    assert sd.session_picture(dolphin(tmp_path, "GMSE01", display=None)) is None     # a local Windows window
    retroarch = SimpleNamespace(display=SimpleNamespace(w=1280, h=720), platform="gba")
    assert sd.session_picture(retroarch) == pytest.approx((100 / 1280, 0, 1080 / 1280, 1))
    switch = adapters.SwitchLinuxAdapter.__new__(adapters.SwitchLinuxAdapter)
    switch.display = SimpleNamespace(w=1280, h=720)
    assert switch.letterbox() is None and sd.session_picture(switch) == (0, 0, 1, 1)


# --- pixel code measured on 4:3 frames ----------------------------------------------------------------------------

def re4_frame(size=(480, 640), at=(259, 386), shown=True):
    """RE4's 640x480 frame (letterbox included), the A prompt's teal-green disc where the game draws it."""
    img = np.zeros(size + (3,), np.uint8)
    h, w = size
    img[int(h * 60 / 480):int(h * 420 / 480), :] = (90, 80, 60)
    if shown:
        yy, xx = np.ogrid[:h, :w]
        img[(yy - at[1] * h / 480) ** 2 + (xx - at[0] * w / 640) ** 2 <= (10 * w / 640) ** 2] = (40, 134, 104)
    return img


def band(img, size):
    """What a Linux session shows of that frame: Dolphin draws it at RE4's window geometry (picture_rect, 2x wide and
    2.05x tall on 1280x720), and the display (size w, h) shows the middle of it: the band, minus 4 lines each edge."""
    w, h = size
    x, y, pw, ph = sd.picture_rect(size, RE4.aspect, RE4.band)
    big = np.asarray(Image.fromarray(img).resize((pw, ph), Image.NEAREST))
    return np.ascontiguousarray(big[-y:-y + h, -x:-x + w])


def pillarbox(img, size):
    w, h = size
    out = np.zeros((h, w, 3), np.uint8)
    pw = h * 4 // 3
    out[:, (w - pw) // 2:(w - pw) // 2 + pw] = np.asarray(Image.fromarray(img).resize((pw, h), Image.NEAREST))
    return out


@pytest.mark.parametrize("size", [(1280, 720), (960, 540)])
def test_the_re4_prompt_is_found_in_the_band_a_linux_session_shows(size):
    found = screen_prompt.detect(band(re4_frame(), size))
    assert found and found["button"] == "a"
    x0, y0, x1, y1 = found["box"]
    assert size[1] * 0.85 < y0 < y1 < size[1]                               # the icon sits low in the band
    assert screen_prompt.detect(band(re4_frame(shown=False), size)) is None


def test_the_re4_prompt_is_found_with_the_sessions_own_picture(tmp_path):
    picture = sd.session_picture(dolphin(tmp_path, "G4BE08"))
    frame = band(re4_frame(), (1280, 720))
    assert screen_prompt.detect(frame, picture=picture)["button"] == "a"
    w = screen_prompt.Watcher(lambda: jpeg(frame), picture=picture)        # tools.py: ad.get_frame() on the display
    w.step()
    assert w.visible() == "a"


def test_the_re4_prompt_is_still_found_on_old_and_pillarboxed_frames():
    assert screen_prompt.detect(re4_frame())["button"] == "a"                # a 640x480 frame, as measured
    docked = pillarbox(re4_frame(), (1280, 720))                             # a 16:9 docked window on Windows
    assert screen_prompt.detect(docked)["button"] == "a"


def jpeg(img) -> bytes:
    b = io.BytesIO()
    Image.fromarray(img).save(b, "PNG")
    return b.getvalue()


def test_anchor_thumbnails_of_the_picture_match_anchors_taken_on_4_3_frames(tmp_path):
    rng = np.random.default_rng(7)
    scene = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    scene[:60], scene[420:] = 0, 0                                           # RE4's letterbox, as the old frames had it
    old = imitate.thumb(jpeg(scene))
    re4 = dolphin(tmp_path, "G4BE08")
    shown = band(scene, (1280, 720))                                         # the new display: the band only
    assert imitate.distance(imitate.thumb(jpeg(shown), sd.session_picture(re4)), old) < 6
    assert imitate.distance(imitate.thumb(jpeg(shown)), old) > imitate.MATCH  # the whole frame would never match
    plain = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)              # a 4:3 game, pillarboxed now
    sms = dolphin(tmp_path, "GMSE01")
    boxed = pillarbox(plain, (1280, 720))
    assert imitate.distance(imitate.thumb(jpeg(boxed), sd.session_picture(sms)), imitate.thumb(jpeg(plain))) < 6
    assert len(base64.b64decode(imitate.thumb(jpeg(boxed), sd.session_picture(sms)))) == 32 * 24


def test_the_black_frame_check_judges_the_picture_not_the_pillarbox(tmp_path, monkeypatch):
    from gbox import tools
    dim = np.full((480, 640, 3), 7, np.uint8)                                 # a dark scene, not a black screen
    sms = dolphin(tmp_path, "GMSE01")
    sms.stream = None
    sms.get_frame = lambda: jpeg(pillarbox(dim, (1280, 720)))
    assert tools._black(sms) is False                                         # the bars no longer drag the mean down
    whole = base64.b64decode(imitate.thumb(sms.get_frame()))
    assert sum(whole) / len(whole) < tools.BLACK_LUMA                         # (the whole frame would read as black)
    sms.get_frame = lambda: jpeg(np.zeros((720, 1280, 3), np.uint8))
    assert tools._black(sms) is True


def test_psos_talk_box_is_found_inside_the_pillarboxed_picture(monkeypatch):
    from gbox import autoplay
    pic = np.full((480, 640), 40, np.uint8)
    pic[int(480 * .24):int(480 * .36), int(640 * .2):int(640 * .72)] = 250  # the white panel
    d = autoplay.Driver.__new__(autoplay.Driver)
    d.frame = lambda: Image.fromarray(pic)
    assert d.dialog_open()                                                    # an old 4:3 stream frame
    boxed = np.zeros((720, 1280), np.uint8)
    boxed[:, 160:1120] = np.asarray(Image.fromarray(pic).resize((960, 720), Image.NEAREST))
    d.frame = lambda: Image.fromarray(boxed)
    assert d.dialog_open()                                                    # the 1280x720 session's frame
    d.frame = lambda: Image.fromarray(np.full((720, 1280), 40, np.uint8))
    assert not d.dialog_open()


def test_an_agents_click_without_a_window_aspect_is_a_share_of_the_sessions_frame(tmp_path):
    from gbox import tools
    ad = dolphin(tmp_path, "GMSE01")
    agent = tools.PickIn(session_id="s", x=0.5, y=0.5)
    assert tools._click_aspect(agent, ad) == pytest.approx(16 / 9)            # x, y on the 1280x720 frame it saw
    agent.window_aspect = tools._click_aspect(agent, ad)
    assert tools._picture_xy(tools.PickIn(session_id="s", x=0.125, y=0.0, window_aspect=agent.window_aspect)) == (0.0, 0.0)
    client = tools.PickIn(session_id="s", x=0.5, y=0.5, window_aspect=1.25)
    assert tools._click_aspect(client, ad) == 1.25                            # a client's own window wins
    windows = dolphin(tmp_path, "GMSE01", display=None)
    assert tools._click_aspect(tools.PickIn(session_id="s", x=0.5, y=0.5), windows) == pytest.approx(4 / 3)

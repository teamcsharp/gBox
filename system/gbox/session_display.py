"""One picture size for every Linux session, and where each emulator's window and picture sit on it.

Operator 2026-10-27: "re4 should also run at 1280x720, in fact all versions should strive for that similar resolution
for consistency", and the broadcast showed the GameCube's RE4 small in the middle of the 16:9 frame with black bars on
all four sides.

Every Linux emulator session gets its own Xvfb display of SESSION_SIZE, the size RPCS3 and Switch sessions already had.
The emulator's window fills the display and the emulator keeps its own aspect ratio, so a 4:3 console is pillarboxed by
the emulator itself: its picture is about 960x720, centred (picture_rect). There is no window manager on these
displays, so the adapter sizes the window itself (adapters.StandaloneAdapter._fit_window).

Titles that draw their own letterbox inside their frame (LETTERBOXED: Resident Evil 4 on GameCube) get a taller window
instead, sized so the band covers the whole display and the game's black bars fall off-screen (window_rect: RE4 on
1280x720 is 1280x993 at y -137). Nothing downstream crops: the stream, the broadcast, the desktop app and Pine Box all
receive the full 1280x720 display.

Measured live on 2026-10-27 (private Dolphin 2609a on the Spark): RE4's bars are 60 lines at the top and bottom of its
480, so its band is 640x360 at y 60 of the framebuffer. Dolphin draws that frame at its analog TV shape, 625:480 (Auto
aspect, from the game's video-interface timing: 8 px black side bars in a 640x480 window, 15 px in 1280x960). Dolphin
ignores every aspect setting passed on its command line here (-C GFX.Settings.AspectRatio Stretch / Force 16:9 /
Custom stretch / Raw and GFX.Settings.Crop all drew the same 625:480 picture), so the window takes that shape: 1280 wide
fills the display's width with no side bars, and the band, 737 px tall at that scale, loses 8-9 px at the top and the
bottom (about 4 of the game's 360 lines each), where RE4 draws nothing but the edge of the scene.

Pixel code that measured positions on 4:3 frames maps them through the picture rectangle: picture_rect for a session
display, frame_picture for a frame of unknown origin (a stream frame read over HTTP), session_picture for an adapter.
"""
from __future__ import annotations

from dataclasses import dataclass

SESSION_SIZE = (1280, 720)
STANDARD, WIDE = 4 / 3, 16 / 9
# The session stream (adapters.MjpegStream) scales a 1280x720 display to 960x540. Measured 2026-10-27 on the Spark (RE4,
# private Dolphin, x11grab at 60 fps): 1280x720 grabbed and scaled to 960 wide cost 54-60 % of a core, sent at 1280
# wide 69-72 % (+12-15 points per stream; 640x480 before this change: 25-28 %). The Spark runs near 80 % with stalls
# from CPU starvation, so the stream stays at 960 wide; 1280 here makes every Linux session's stream 1280x720.
STREAM_MAX_WIDTH = 960
# A letterboxed title's window is this much taller than its frame: the emulator then fits the frame to the window's
# width, so its own rounding (Dolphin rounds the picture to whole pixels) can never leave a bar at the sides; the extra
# height is off-screen.
WINDOW_MARGIN = 0.01


@dataclass(frozen=True)
class Letterbox:
    title: str
    band: float          # the band's share of the frame's height (RE4: 360 of 480 lines, centred)
    aspect: float        # the frame's shape as the emulator draws it (Dolphin's Auto aspect for this title)


# GameCube disc ids (the six-byte game id) whose picture is a band letterboxed inside the frame. Only measured discs:
# other regions draw other frames (a PAL disc at 50 Hz has 528/576 lines), so each is added once measured.
LETTERBOXED = {
    "G4BE08": Letterbox("Resident Evil 4 (GameCube, USA; both discs)", 360 / 480, 625 / 480),
}

# The picture's aspect ratio per platform when it is not 4:3: the emulator fits it inside the display, centred.
PICTURE_ASPECT = {"gba": 3 / 2, "gb": 10 / 9, "gbc": 10 / 9, "switch": WIDE, "ps3": WIDE, "psp": 480 / 272}


def letterbox(game_id: str | None) -> Letterbox | None:
    """The letterbox fact for this disc id, or None."""
    return LETTERBOXED.get(str(game_id or "").upper())


def window_rect(display: tuple[int, int], frame_aspect: float = STANDARD, band: float | None = None,
                margin: float = WINDOW_MARGIN) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the emulator's window on a display (w, h): the whole display, or for a letterboxed title (band:
    the band's share of the frame's height) a window centred on the display and just large enough that the band of a
    frame_aspect frame drawn at the window's width covers the display; `margin` taller than that frame (WINDOW_MARGIN).
    RE4 on 1280x720: (0, -137, 1280, 993); an exact 4:3 frame with a 16:9 band and no margin: (0, -120, 1280, 960)."""
    dw, dh = (int(v) for v in display)
    if not band:
        return 0, 0, dw, dh
    w = max(dw, round(dh * frame_aspect / band))       # the band spans the frame's width and is band * w / aspect tall
    h = round(w / frame_aspect * (1 + margin))
    return (dw - w) // 2, (dh - h) // 2, w, h


def picture_rect(display: tuple[int, int], aspect: float = STANDARD, band: float | None = None,
                 margin: float = WINDOW_MARGIN) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the game's whole frame (its drawn aspect, bars included) on the display. The emulator fits it
    inside the display and centres it (4:3 on 1280x720: 960x720 at x 160); a letterboxed title's frame fills its
    window's width, centred in it (window_rect), so it reaches past the display's top and bottom edges."""
    if band:
        x, y, w, h = window_rect(display, aspect, band, margin)
        fh = round(w / aspect)
        return x, y + (h - fh) // 2, w, fh
    dw, dh = (int(v) for v in display)
    if dw / dh > aspect:
        w = round(dh * aspect)
        return (dw - w) // 2, 0, w, dh
    h = round(dw / aspect)
    return 0, (dh - h) // 2, dw, h


def fractions(rect: tuple[float, float, float, float], size: tuple[float, float]) -> tuple[float, float, float, float]:
    """A rectangle in pixels of a w x h picture as fractions of it (the same on any scaled copy, e.g. the stream)."""
    x, y, w, h = rect
    sw, sh = size
    return x / sw, y / sh, w / sw, h / sh


def frame_picture(w: int, h: int, aspect: float = STANDARD, band: float | None = None) -> tuple[float, float, float, float]:
    """Where the game's whole frame is in a frame grab of unknown origin, as fractions (x, y, w, h) of the grab, which
    may reach past 0..1. A grab shaped like the frame (an old 640x480 Dolphin grab, a docked 4:3 window) holds the frame
    fitted inside it. For a letterboxed title (band), a grab shaped like the band (aspect / band) is the band filling
    the grab (a Linux session of this title); any other grab holds the frame fitted inside it, centred (a pillarboxed
    4:3 game on a 16:9 display)."""
    shape = w / h
    if band and abs(shape - aspect / band) < abs(shape - aspect):
        return fractions(picture_rect((w, h), aspect, band), (w, h))
    return fractions(picture_rect((w, h), aspect), (w, h))


def map_box(box: tuple[float, float, float, float], picture: tuple[float, float, float, float],
            w: int, h: int) -> tuple[int, int, int, int]:
    """A box (x0, y0, x1, y1) given as fractions of the whole picture -> pixels of a w x h frame whose picture is at
    `picture` (fractions of the frame, frame_picture / session_picture); clamped to the frame."""
    px, py, pw, ph = picture
    x0, y0, x1, y1 = box

    def at(fx, fy):
        return (min(w, max(0, int((px + fx * pw) * w))), min(h, max(0, int((py + fy * ph) * h))))
    (ax, ay), (bx, by) = at(x0, y0), at(x1, y1)
    return ax, ay, bx, by


def corner_only(gray: bytes, w: int, h: int, black: int = 16) -> bool | None:
    """A w x h grey thumbnail of a session display (no pointer drawn): True when everything that is not black sits in
    its top-left corner - a renderer still drawing at the size of the smaller window it started in (Dolphin on a
    1280x720 display drew its 640x480 picture there, 2026-10-27) -, False when the picture reaches past that corner,
    None when there is too little to judge (a black or nearly black frame)."""
    xs = ys = None
    for y in range(h):
        row = gray[y * w:(y + 1) * w]
        lit = [x for x, v in enumerate(row) if v > black]
        if lit:
            xs = (min(lit), max(lit)) if xs is None else (min(xs[0], lit[0]), max(xs[1], lit[-1]))
            ys = (y, y) if ys is None else (ys[0], y)
    if xs is None or xs[1] - xs[0] < w // 20 or ys[1] - ys[0] < h // 15:
        return None
    return xs[1] < w * 0.53 and ys[1] < h * 0.72


def session_picture(ad) -> tuple[float, float, float, float] | None:
    """Where the game's whole frame is in a session's frame grabs (get_frame and the stream show the whole display), as
    fractions of the grab; None for a session without a private display (a local Windows window), whose grabs keep
    whatever shape the window has."""
    display = getattr(ad, "display", None)
    w, h = getattr(display, "w", None), getattr(display, "h", None)
    if not w or not h:
        return None
    rect = getattr(ad, "picture_rect", None)
    if callable(rect):
        return fractions(rect(), (w, h))
    aspect = PICTURE_ASPECT.get(str(getattr(ad, "platform", "") or ""), STANDARD)
    return fractions(picture_rect((w, h), aspect), (w, h))

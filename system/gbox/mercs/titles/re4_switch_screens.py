"""RE4 Switch: which screen is up, read from the capture frame.

The title task's menu state has no measured RAM anchor yet, so the walk from the title to a Mercenaries round reads the
picture. Measured 2026-11-06 on lilspark (Citron d3df71e55) over 114 labelled frames of one boot walk:

- title, THE MERCENARIES, Select Player and Select Stage are fixed pictures: a 64x36 thumbnail is within 2 RMSE of its
  reference (Select Player's pulsing portrait within 9), and at least 14 from every other screen.
- the main menu and EXTRAS pan a village behind a fixed logo: the logo's pixels stay within 10 RMSE across the pan, and
  every other screen is at least 14 away. The row under the cursor is the only red text.
- a live round has its HUD: the clock's digits and the line under them, which no menu draws.

Only what a frame proves is named. Anything else is "unknown", and nothing presses on "unknown": that is what keeps a
stray confirm from loading a story save (11-06: repeated A presses went title -> LOAD -> a save -> the merchant).
"""
from __future__ import annotations

import io
import json
from pathlib import Path

W, H = 960, 540
THUMB = (64, 36)
REFS_PATH = Path(__file__).with_name("re4_switch_screens.json")

# Select Player's highlighted portrait pulses, reaching 8.9 from its reference, and every other screen stays 35 away.
FIXED = {"title": 3.0, "mercs_title": 3.0, "select_player": 12.0, "select_stage": 3.0}
# story_load_list_2 is the same list in another state (a different slot page): the walk sat on it for 255 s while
# it read as unknown, 18.0 from the only reference against a 12.0 threshold, and >= 28.7 from every other screen
# (measured 2026-11-07 from walk_10 of that run).
STORY = ("story_load_list", "story_load_list_2", "story_buy", "story_case")
STORY_MAX, LOGO_MAX = 12.0, 11.5
BLACK_MEAN = 8.0

MENU_BOX = (420, 285, 720, 490)                 # x0, y0, x1, y1: the rows of both menus, at 960x540
MAIN_ROWS = (300, 329, 357, 385, 414, 444, 472)     # NEW GAME, LOAD, LEADERBOARDS, HELP & OPTIONS, ACHIEVEMENTS, EXTRAS, CREDITS
EXTRAS_ROWS = (346, 375, 404, 432, 460)             # SEPARATE WAYS, ASSIGNMENT ADA, THE MERCENARIES, MOVIE BROWSER, ADA'S REPORT
ROW_TOLERANCE, RED_MIN_PIXELS = 5, 12


def _np():
    import numpy
    return numpy


def load_refs(path: Path = REFS_PATH) -> dict:
    """{"refs": {name: 64x36 uint8}, "logo_ref": 64x36 uint8, "logo_mask": 64x36 bool}"""
    np = _np()
    raw = json.loads(path.read_text())
    shape = (raw["size"][1], raw["size"][0])
    grid = lambda text, kind=np.uint8: np.frombuffer(bytes.fromhex(text), dtype=kind).reshape(shape)
    return {"refs": {k: grid(v).astype(np.float32) for k, v in raw["refs"].items()},
            "logo_ref": grid(raw["logo_ref"]).astype(np.float32),
            "logo_mask": grid(raw["logo_mask"]).astype(bool)}


_REFS = None


def refs() -> dict:
    global _REFS
    if _REFS is None:
        _REFS = load_refs()
    return _REFS


def decode(png: bytes):
    """A frame at the canonical 960x540 (the session display is 1280x720, the API's frame.jpg 960x540)."""
    from PIL import Image
    np = _np()
    with Image.open(io.BytesIO(png)) as im:
        return np.asarray(im.convert("RGB").resize((W, H), Image.BILINEAR), dtype=np.int16)


def thumbnail(rgb):
    from PIL import Image
    np = _np()
    small = Image.fromarray(rgb.astype(np.uint8), "RGB").convert("L").resize(THUMB, Image.BILINEAR)
    return np.asarray(small, dtype=np.float32)


def rmse(a, b, mask=None) -> float:
    np = _np()
    d = (a - b) if mask is None else (a - b)[mask]
    return float(np.sqrt((d ** 2).mean()))


def has_hud(gray) -> bool:
    """The clock's digits and the line under them: 0.58-0.62 and 0.067-0.078 in a Village round; no menu shows both."""
    line = gray[int(.10 * H):int(.125 * H), 0:int(.45 * W)].max(axis=0)
    digits = gray[int(.015 * H):int(.095 * H), int(.04 * W):int(.24 * W)]
    return float((line > 170).mean()) > 0.4 and float((digits > 200).mean()) > 0.05


def clock_patch(rgb):
    """The HUD clock's pixels: they change from one sample to the next only while the round runs."""
    return rgb[int(.015 * H):int(.095 * H), int(.04 * W):int(.24 * W)].mean(axis=2)


def red_row(rgb) -> float | None:
    """The cursor's row: the median y of the red text in the menu box (it pulses, so the threshold sits low)."""
    np = _np()
    x0, y0, x1, y1 = MENU_BOX
    box = rgb[y0:y1, x0:x1]
    red = (box[..., 0] > 90) & (box[..., 0] - box[..., 1] > 30) & (box[..., 0] - box[..., 2] > 30)
    if int(red.sum()) < RED_MIN_PIXELS:
        return None
    return float(np.median(np.nonzero(red)[0])) + y0


def menu_cursor(y: float | None) -> tuple[str, int] | None:
    """(menu, row) for a red text height, None when it sits on no row of either menu."""
    if y is None:
        return None
    best = min([("main_menu", i, abs(y - r)) for i, r in enumerate(MAIN_ROWS)]
               + [("extras_menu", i, abs(y - r)) for i, r in enumerate(EXTRAS_ROWS)], key=lambda t: t[2])
    return (best[0], best[1]) if best[2] <= ROW_TOLERANCE else None


# "You Are Dead - Continue Yes / No" (measured 2026-11-10 on lilspark, artifact 0c0a88732908d1a8..., kept out of git): an almost
# black frame (mean 6.5, so it read as "loading") with the prompt's rule - rows 391-394, every pixel of x 415..958
# above 40 - grey "Continue Yes / No" text above it and the red "You Are Dead" over the darkened scene.
DEAD_MEAN_MAX = 25.0
DEAD_RULE_ROWS, DEAD_RULE_X = (385, 401), (415, 958)
DEAD_TEXT_BOX = (480, 352, 900, 386)            # x0, y0, x1, y1
DEAD_RED_BOX = (100, 150, 860, 470)


def is_dead_continue(rgb, gray) -> bool:
    if float(gray.mean()) > DEAD_MEAN_MAX:
        return False
    x0, x1 = DEAD_RULE_X
    rule = max(float((gray[y, x0:x1] > 40).mean()) for y in range(*DEAD_RULE_ROWS))
    tx0, ty0, tx1, ty1 = DEAD_TEXT_BOX
    text = float((gray[ty0:ty1, tx0:tx1] > 90).mean())
    rx0, ry0, rx1, ry1 = DEAD_RED_BOX
    box = rgb[ry0:ry1, rx0:rx1]
    red = float(((box[..., 0] - box[..., 1] > 15) & (box[..., 0] > 30)).mean())
    return rule >= 0.9 and text >= 0.05 and red >= 0.03


# The story save list's two prompts (measured 2026-11-10 on lilspark, 960x540, the share of pixels over 150):
# "Cancel loading? Yes / No" stacks its options mid-left over an empty panel (title 0.030, Yes 0.022, No 0.024,
# the cursor 0.19 beside the row it is on, the one-line options row 0.000); "Load data? Yes > No" puts them on one
# line lower down (title 0.029, options 0.041, the stacked rows 0.000). B on the first is No, which drops back to the
# list - whose B opens it again: a loop the walk sat in for 10 minutes. Its way out is Yes (up, then A).
PROMPT_BOXES = {"cancel_title": (375, 200, 590, 235), "cancel_yes": (410, 280, 470, 310),
                "cancel_no": (410, 315, 470, 348), "cur_yes": (385, 283, 408, 307), "cur_no": (385, 318, 408, 343),
                "load_title": (405, 330, 560, 365), "load_opts": (445, 405, 590, 440)}
PROMPT_TEXT = 150.0


def prompt_kind(gray) -> dict | None:
    """{"prompt": "cancel", "cursor": "yes" | "no" | None} for Cancel loading?, {"prompt": "load"} for Load
    data?, else None (gray: the frame's luma at 960x540)."""
    f = {k: float((gray[y0:y1, x0:x1] > PROMPT_TEXT).mean()) for k, (x0, y0, x1, y1) in PROMPT_BOXES.items()}
    if f["cancel_title"] > 0.015 and f["cancel_yes"] > 0.01 and f["cancel_no"] > 0.01 and f["load_opts"] < 0.01:
        cur = "yes" if f["cur_yes"] > 0.1 else "no" if f["cur_no"] > 0.1 else None
        return {"prompt": "cancel", "cursor": cur}
    if f["load_title"] > 0.015 and f["load_opts"] > 0.02 and f["cancel_yes"] < 0.005:
        return {"prompt": "load"}
    return None


def classify(png: bytes) -> dict:
    """One frame, no memory: {"where": title | main_menu | extras_menu | mercs_title | select_player | select_stage |
    dead_continue | loading | playing | story | menu | unknown, "cursor": row on a menu}."""
    rgb = decode(png)
    gray = rgb.mean(axis=2)
    if has_hud(gray):
        return {"where": "playing"}
    if is_dead_continue(rgb, gray):
        return {"where": "dead_continue"}
    r, thumb = refs(), thumbnail(rgb)
    for name, limit in FIXED.items():
        if rmse(thumb, r["refs"][name]) <= limit:
            return {"where": name}
    if rmse(thumb, r["logo_ref"], r["logo_mask"]) <= LOGO_MAX:
        at = menu_cursor(red_row(rgb))
        return {"where": at[0], "cursor": at[1]} if at else {"where": "menu"}
    # the save list's prompts only once no reference screen matched (live 2026-11-10 21:42: Select Player's plate
    # and portraits light the Load data? boxes; read first, the walk cancelled out of the character select)
    kind = prompt_kind(gray)
    if kind is not None:
        return {"where": "story_prompt", **kind}
    for name in STORY:
        if name in r["refs"] and rmse(thumb, r["refs"][name]) <= STORY_MAX:
            return {"where": "story", "story": name}
    if float(gray.mean()) < BLACK_MEAN:
        return {"where": "loading"}
    return {"where": "unknown"}


class Reader:
    """classify() plus what one frame can't know: that a stage is loading because THIS walk picked it, so the dark scene
    after that black is the round's intro. Its banners type out letter by letter over a moving camera, so no picture
    names them, and A is what pages them. Harmless past the last page (3, 6 and 10 presses all measured the same).

    The same trick covers the story save list's confirm dialog. Measured 2026-11-07: the walk strayed onto LOAD, the
    "Load data? Yes / No" overlay matched no reference (it is drawn over the list), so it read as `unknown` and a press
    meant for an unnamed screen loaded a story save (the merchant's TUNE UP came up). After a story screen, an unnamed
    frame is that dialog, and it is cancelled - never confirmed.
    """
    INTRO_MAX_PRESSES = 12
    # Select Player / Select Stage steering (MercMode's DJ pick, re4_switch.request): the references are the default
    # cursor (Leon, the Village), so once the walk has moved the cursor the picture matches no reference and reads as
    # unknown. While a steer is open, that unknown is the same select screen with `moved` presses in; it closes on the
    # confirm, on another named screen, or after STEER_MAX_MOVES (a picture that never comes back is not a select).
    STEER_SCREENS = ("select_player", "select_stage")
    STEER_KEYS = ("dleft", "dright", "dup", "ddown")
    STEER_MAX_MOVES = 6

    def __init__(self):
        self.stage_picked = self.armed = False
        self.intro_presses = 0
        self.last_menu: tuple[str, int] | None = None
        self.story_armed = False
        self.steer: str | None = None
        self.steer_moves = 0

    def press_went_in(self, where: str, key: str) -> None:
        if where == "round_intro" and key == "a":
            self.intro_presses += 1
        if where == "dead_continue" and key == "a":
            self.stage_picked, self.intro_presses = True, 0     # Continue: the same stage loads again, intro and all
        if where in self.STEER_SCREENS:
            if key in self.STEER_KEYS:
                if self.steer != where:
                    self.steer, self.steer_moves = where, 0
                self.steer_moves += 1
            elif key == "a":
                self.steer, self.steer_moves = None, 0          # confirmed: the next screen is read afresh

    def _steered(self, scr: dict) -> dict:
        """A select screen with its cursor moved by this walk (see STEER_SCREENS), else scr unchanged."""
        where = scr["where"]
        if self.steer is None:
            return scr
        if where not in ("unknown", self.steer) or self.steer_moves > self.STEER_MAX_MOVES:
            self.steer, self.steer_moves = None, 0              # another screen came up: the steer is over
            return scr
        return {"where": self.steer, "moved": self.steer_moves, "steering": True}

    def read(self, png: bytes) -> dict:
        scr = self._steered(classify(png))
        where = scr["where"]
        if where == "select_stage":
            self.stage_picked = True
        elif where == "loading" and self.stage_picked:
            self.armed = True
        elif where == "playing":
            self.stage_picked = self.armed = False
            self.intro_presses = 0
        elif where in ("main_menu", "extras_menu"):
            self.last_menu = (where, scr["cursor"])
        elif where == "menu" and self.last_menu:             # the red text pulses dark for a moment: the same row
            scr = {"where": self.last_menu[0], "cursor": self.last_menu[1], "held": True}
        elif where == "unknown" and self.armed and self.intro_presses < self.INTRO_MAX_PRESSES:
            scr = {"where": "round_intro"}
        # the story save list, and the unnamed confirm drawn over it: both are cancelled, never confirmed
        if where == "story":
            self.story_armed = True
        elif where == "story_prompt" and scr.get("prompt") == "load" and not self.story_armed:
            scr = {"where": "unknown"}           # Load data? only ever follows the list: anything else is not it
        elif where in ("story_prompt",) or (where == "unknown" and self.story_armed):
            scr = scr if where == "story_prompt" else {"where": "story_prompt"}   # a named prompt keeps its kind
        elif where not in ("unknown", "menu"):
            self.story_armed = False
        if scr["where"] == "menu":                           # no row read yet this run: nothing to act on
            scr = {"where": "unknown"}
        return scr

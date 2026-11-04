"""Universal quick-time-event (QTE) handling for every Mercenaries title (one module, all titles).

A QTE is an on-screen button prompt the player must answer inside a short window or take damage / die / fail:
a single timed press, a rapid MASH (the grab escape / struggle-free - the common one), a stick shake/rotate, or a
dual-button chord. The operator saw a Switch "press B" grab-escape prompt (B + a down arrow = mash B to break free)
and the bot "did not even try, just ate the grab". A lost grab-QTE can kill the bot, so this is both a stream
embarrassment and a death cause.

Solve it once, cover every title. Each title driver hooks this module with its own button maps + RAM offsets; the
detection and the response live here. Two detection paths, memory first (operator 2026-10-20: "Vision analysis to me
should be the last level that we have to fall back to"):

  1. MEMORY (robust)  per title a RAM reader that returns the shown prompt (which button(s), its kind, the mash /
     struggle meter). We reuse the readers already measured live:
        re5 switch  gbox.mercs.titles.re5_switch_prompt.selected_prompt  (the sActionButton system, 64-bit build)
        re6 switch  gbox.mercs.titles.re6_switch.prompts                 (the sActionButton singleton, port layout)
        re5 ps3     gbox.mercs.titles.re5_ps3.selected_prompt            (the PS3 QTE_INPUT_TABLE)
        re4 gc      gbox.re4_ram_prompts.source                          (the action manager's button kind)
        re4 switch  pending live RAM measurement (scaffolded; vision answers it until then)

  2. VISION (fallback)  template / glyph match of the button-prompt overlay on the capture frame, so EVERY title has
     at least a working QTE response immediately, even one with no RAM map yet or on a frame where a RAM read tore.
     Built on gbox.screen_prompt (its RE4 GC profile is live-calibrated); Switch profiles are scaffolded here and
     answer nothing until calibrated from live frames (CALIBRATED), so vision never presses a false button on stream.

RESPONSE (respond()):
  - MASH (grab escape / struggle, stick wiggle/rotate): hammer the indicated input, press/release alternating every
    tick (~10-15 presses/sec through the engine's mash cadence) until the QTE clears.
  - SINGLE timed press: press once, with a small reaction delay so it reads natural, not frame-perfect-robotic.
  QTE handling PREEMPTS the normal fire loop while active, then hands back (the engine drops the held keys before it
  presses a prompt; the Switch tick's hold path does the same).

This module is pure bot logic under gbox.mercs, so it hot-reloads in place (gbox.hot_reload): a fix deploys by
bot-reload, no gbox.service restart, no emulator / stream / warm game closed. It touches no adapter, thread-owner or
store. Parity rule (gbox-mods-parity-across-editions): QTE handling must work on Switch / 3DS / VR as well, so the
response vocabulary and the registry are keyed by the title's map id, never hard-coded to one console.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

# --- kinds ----------------------------------------------------------------------------------------------------------
MASH = "mash"                 # a grab escape / struggle / finisher: hammer the button until it clears
SINGLE = "single"             # one timed press inside the window (a cinematic dodge, a ledge jump)
STICK_WIGGLE = "stick_wiggle"  # the left stick shaken (Break free's icon)
STICK_ROTATE = "stick_rotate"  # the left stick rotated (a knife ring)
STICK_AXIS = "stick_axis"     # the stick pushed on one axis
STICK_KINDS = frozenset({STICK_WIGGLE, STICK_ROTATE, STICK_AXIS})

# The response sequences, mirrored from the proven per-title handlers (re5_switch WIGGLE/ROTATE/MASH, re6_switch
# WIGGLE). A mash alternates press / release tick by tick (a fresh press each time); a stick prompt steps its sequence.
WIGGLE = (("lleft",), ("lright",))
ROTATE = (("lup",), ("lup", "lleft"), ("lleft",), ("lleft", "ldown"), ("ldown",), ("ldown", "lright"),
          ("lright",), ("lright", "lup"))
AXIS_Y = (("lup",), ("ldown",))
AXIS_X = (("lleft",), ("lright",))

MASH_HZ = 12.0                # 10-15 presses/sec (the engine's own MASH_DOWN_S cadence is used on its path)
SINGLE_REACTION_S = (0.10, 0.22)   # a single timed press waits this long (random) so it is not frame-perfect-robotic

# A token says what the game asks for, the vocabulary the per-title RAM readers already speak:
#   "press:y"  "release:b"  "mash:a"  "mash:a+b"  "mash:wiggle"  "stick:rotate"  "stick:y"  "stick:x"
_KIND_BY_VERB = {"press": SINGLE, "release": SINGLE, "mash": MASH}


def parse_token(token: str) -> tuple[str, tuple]:
    """A reader's token -> (kind, keys). "mash:wiggle"/"stick:rotate"/"stick:y" map to the stick kinds (no keys)."""
    token = str(token or "")
    verb, _, rest = token.partition(":")
    if verb == "stick" or rest in ("wiggle",) or token == "wiggle":
        if rest in ("rotate",):
            return STICK_ROTATE, ()
        if rest in ("y",):
            return STICK_AXIS, ()
        if rest in ("x",):
            return STICK_AXIS, ()
        return STICK_WIGGLE, ()
    if verb == "mash" and rest == "wiggle":
        return STICK_WIGGLE, ()
    keys = tuple(k for k in rest.split("+") if k) if rest else ()
    return _KIND_BY_VERB.get(verb, SINGLE if keys else MASH), keys


@dataclass
class Qte:
    """One QTE the game is asking for, normalised across titles. `keys` is the button chord to press (empty for a
    pure-stick prompt); `kind` drives respond(); `source` is "ram" or "vision"."""
    token: str
    kind: str
    keys: tuple = ()
    button: str | None = None
    source: str = ""
    label: int | None = None
    owner: int | None = None
    target: int | None = None
    progress: float | None = None
    target_count: float | None = None
    raw: dict | None = None

    @property
    def is_mash(self) -> bool:
        return self.kind in (MASH, STICK_WIGGLE, STICK_ROTATE, STICK_AXIS)

    @property
    def is_stick(self) -> bool:
        return self.kind in STICK_KINDS

    @property
    def axis(self) -> str:
        """For STICK_AXIS: "y" or "x" (from the token)."""
        return "y" if self.token.endswith("y") else "x"


def from_token(token: str, *, keys=None, source: str = "", **extra) -> Qte:
    kind, parsed = parse_token(token)
    chord = tuple(keys) if keys else parsed
    btn = extra.pop("button", None) or (chord[0] if chord else None)
    return Qte(token=token, kind=kind, keys=chord, button=btn, source=source,
               **{k: v for k, v in extra.items()
                  if k in ("label", "owner", "target", "progress", "target_count", "raw")})


# --- response -------------------------------------------------------------------------------------------------------
def respond(qte: Qte, phase: int) -> dict:
    """The pad action for this QTE on tick `phase` (0, 1, 2, ...): {"hold": keys}. A mash alternates press / release;
    a stick prompt steps its sequence; a single press holds the keys on phase 0 then lets go. Empty dict = nothing."""
    if qte.kind == STICK_WIGGLE:
        return {"hold": WIGGLE[phase % len(WIGGLE)]}
    if qte.kind == STICK_ROTATE:
        return {"hold": ROTATE[phase % len(ROTATE)]}
    if qte.kind == STICK_AXIS:
        seq = AXIS_Y if qte.axis == "y" else AXIS_X
        return {"hold": seq[phase % len(seq)]}
    keys = tuple(qte.keys)
    if not keys:
        return {}
    if qte.kind == MASH:
        return {"hold": keys if phase % 2 == 0 else ()}   # down, up, down, ...: a fresh press each tick
    return {"hold": keys if phase == 0 else ()}           # SINGLE: one press, then released


def reaction_delay(rng: random.Random | None = None) -> float:
    """A small human-like delay before a single timed press (never frame-perfect)."""
    lo, hi = SINGLE_REACTION_S
    return (rng or random).uniform(lo, hi)


# --- engine (reactions.PromptPresser) bridge ------------------------------------------------------------------------
# The engine's reactions.PromptPresser already presses a prompt from a `source` (RAM) or a `vision` callback, with the
# mash / burst / rest rule. It recognises "mash:<chord>" tokens (fast, no rest) and plain button names (bursted). So a
# title's prompt_vision() hook returns a callable that yields one of those tokens, and prompt_keys() decodes them.
def vision_token(qte: Qte | None) -> str | None:
    """A Qte -> the token reactions.PromptPresser wants from a vision callback: "mash:b" for a mash/grab (hammered),
    the bare button for a single press, "wiggle"/"rotate" for a stick prompt (reactions.MASH presses those every
    step). None when there is nothing to press."""
    if qte is None:
        return None
    if qte.kind == STICK_WIGGLE:
        return "wiggle"
    if qte.kind == STICK_ROTATE:
        return "rotate"
    if qte.kind == STICK_AXIS:
        return "stick:" + qte.axis
    if not qte.keys:
        return None
    chord = "+".join(qte.keys)
    return ("mash:" + chord) if qte.kind == MASH else chord


def decode_keys(button, *, wiggle=WIGGLE, rotate=ROTATE) -> list:
    """prompt_keys() helper: a token (or bare button) -> the chords to press. "mash:a+b" -> [("a","b")];
    "wiggle"/"rotate"/"stick:y" are stick tokens the engine steps itself, so they decode to the stick keys. A bare
    "a" -> [("a",)]. Keeps the ":" guard reactions needs (no ":" inside a returned key)."""
    s = str(button)
    if s in ("wiggle", "mash:wiggle"):
        return [wiggle[0]]
    if s in ("rotate", "stick:rotate"):
        return [rotate[0]]
    if s.startswith("stick:"):
        axis = s.split(":", 1)[1]
        return [AXIS_Y[0] if axis == "y" else AXIS_X[0]]
    if s.startswith("mash:"):
        s = s.split(":", 1)[1]
    parts = [p for p in s.split("+") if p and ":" not in p]
    return [tuple(parts)] if parts else [(s,)]


# --- vision ---------------------------------------------------------------------------------------------------------
@dataclass
class VisionProfile:
    """How a title draws its QTE button overlay, for the vision fallback. Two ways to detect it:
      - screen_prompt_profile: reuse a gbox.screen_prompt PROFILES entry (a coloured button disc, live-calibrated), or
      - glyph_box: the game draws its action-button prompt as a bright, near-white letter disc + arrow + label text
        (RE5/RE6 Switch: "(A) Resuscitate", "(L) Break free") in a fixed centre-bottom box - measured live and counted
        here (a torn-read grab is answered by a vigorous struggle, not by reading which letter it is).
    CALIBRATED stays False for a scaffolded title, so the detector returns nothing (vision never fires on stream until
    the title's overlay is measured from live frames)."""
    map_id: str
    screen_prompt_profile: str | None = None   # a key in gbox.screen_prompt.PROFILES to delegate to
    glyph_box: tuple | None = None             # (x0, y0, x1, y1) as frame fractions: where the prompt glyph/label sits
    glyph_min_px: int = 400                    # near-white neutral pixels in the box that count as a prompt present
    glyph_white: int = 180                     # a pixel's channels all above this (a light glyph on a dark HUD)
    glyph_neutral: int = 40                    # and its channel spread below this (white, not the orange timer / HELP)
    calibrated: bool = False
    mash_default: bool = False                 # a detected overlay is a mash (hammer it), not a single press
    note: str = ""


def _glyph_px(frame_rgb, profile: VisionProfile) -> int:
    """Near-white neutral pixels in the profile's glyph box (the prompt overlay's letter/label), or 0. Never raises."""
    try:
        import numpy as np
        a = np.asarray(frame_rgb)
        if a.ndim != 3 or a.shape[2] < 3:
            return 0
        h, w = a.shape[:2]
        x0, y0, x1, y1 = profile.glyph_box
        reg = a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w), :3].astype("int16")
        r, g, b = reg[..., 0], reg[..., 1], reg[..., 2]
        spread = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
        white = (r > profile.glyph_white) & (g > profile.glyph_white) & (b > profile.glyph_white) \
            & (spread < profile.glyph_neutral)
        return int(white.sum())
    except Exception:                                  # noqa: BLE001 - a torn frame
        return 0


def detect_vision(frame_rgb, profile: VisionProfile, picture=None) -> Qte | None:
    """The QTE visible in the capture frame (H x W x 3 RGB array). None when there is no prompt, no calibrated
    profile, or the detector is unsure. Never raises (a torn frame -> None). A glyph_box profile cannot read which
    button it is, so it reports a generic struggle (a torn-read grab -> mash the stick); a screen_prompt profile
    names the button."""
    if frame_rgb is None or profile is None or not profile.calibrated:
        return None
    if profile.glyph_box is not None:
        if _glyph_px(frame_rgb, profile) < profile.glyph_min_px:
            return None
        return from_token("mash:wiggle", source="vision", raw={"glyph": True})
    if not profile.screen_prompt_profile:
        return None
    try:
        from .. import screen_prompt
        found = screen_prompt.detect(frame_rgb, profile.screen_prompt_profile, picture)
    except Exception:                                  # noqa: BLE001 - vision is a best-effort fallback
        return None
    if not found:
        return None
    btn = found["button"]
    # Vision cannot read the mash meter; a grab overlay is hammered (mash_default), everything else is one press.
    token = ("mash:" + btn) if profile.mash_default else ("press:" + btn)
    return from_token(token, keys=(btn,), source="vision", raw=found)


class VisionWatcher:
    """A background thread that grabs capture frames and keeps the latest QTE it sees, so the bot tick reads it
    cheaply (visible()) without ever blocking on a frame grab. Wraps gbox.screen_prompt.Watcher with detect_vision.

    `grab` is a callable returning frame bytes (JPEG/PNG) or an RGB array; e.g. an adapter's get_frame, or a
    gbox.screen_prompt.MjpegFrames(url, headers).grab for the session's /api/sessions/{sid}/mjpeg stream."""

    def __init__(self, grab, profile: VisionProfile, hz: float = 10.0, picture=None, clock=time.time):
        self.profile = profile
        self._grab = grab
        self._last: Qte | None = None
        self._at = 0.0
        self._clock = clock
        self._picture = picture
        self._w = None
        if grab is not None and profile is not None and profile.calibrated:
            try:
                from .. import screen_prompt
                self._w = screen_prompt.Watcher(grab, profile.screen_prompt_profile, hz=hz, clock=clock,
                                                 picture=picture)
            except Exception:                           # noqa: BLE001
                self._w = None

    def start(self) -> "VisionWatcher":
        if self._w is not None:
            self._w.start()
        return self

    def visible(self, max_age: float = 0.5) -> Qte | None:
        """The QTE on screen now (its button fresh within max_age), or None."""
        if self._w is None:
            return None
        btn = self._w.visible(max_age)
        if not btn:
            return None
        token = ("mash:" + btn) if self.profile.mash_default else ("press:" + btn)
        return from_token(token, keys=(btn,), source="vision")

    def stop(self) -> None:
        if self._w is not None:
            try:
                self._w.stop.set()
            except Exception:                           # noqa: BLE001
                pass


# --- the per-title registry -----------------------------------------------------------------------------------------
@dataclass
class QteContext:
    """What a detector needs: the memory reader `m`, the title's module base and the player's pointer / index (Switch
    RAM readers), and - for vision - a decoded RGB `frame` or a `watcher` already running on the session's frames."""
    m: object = None
    base: int | None = None
    player_ptr: int | None = None
    index: int = 0
    frame: object = None
    picture: object = None
    watcher: "VisionWatcher | None" = None


@dataclass
class TitleQte:
    """A title's QTE hook: its RAM reader (ctx -> Qte | None, may raise reactions.Unknown / LookupError when RAM can't
    tell) and its vision profile. `ram` None = no RAM map yet (vision only)."""
    map_id: str
    ram: object = None                 # callable(QteContext) -> Qte | None
    vision: VisionProfile | None = None
    note: str = ""


# RAM adapters: wrap each title's existing, live-measured reader into the normalised Qte. Lazy imports keep this
# module light (the big title modules are already loaded in the worker) and keep hot-reload dependency-clean.
def _ram_re5_switch(ctx: QteContext) -> Qte | None:
    from .titles import re5_switch_prompt
    if ctx.m is None or ctx.base is None or ctx.player_ptr is None:
        return None
    pr = re5_switch_prompt.selected_prompt(ctx.m, ctx.base, ctx.player_ptr, ctx.index or 0)
    if not pr:
        return None
    return from_token(pr["token"], keys=tuple(pr.get("keys") or ()), source="ram", button=None,
                      label=pr.get("label"), owner=pr.get("owner"), target=pr.get("target"),
                      progress=pr.get("progress"), target_count=pr.get("target_count"), raw=pr)


def _ram_re6_switch(ctx: QteContext) -> Qte | None:
    from .titles import re6_switch
    if ctx.m is None or ctx.base is None:
        return None
    shown = re6_switch.prompts(ctx.m, ctx.base, ctx.index or 0)
    if not shown:
        return None
    # The re6 reader lists the shown prompts (it has no mash meter / mode). Prefer a real button over a bare stick;
    # a held/grab break shows B + the stick (re6_switch WIGGLE), so a stick-bearing prompt is hammered (mash).
    real = next((q for q in shown if q.get("key") and q["key"] not in ("r", "stick")), None)
    stick = any(q.get("key") == "stick" for q in shown)
    if real is not None:
        token = ("mash:" + real["key"]) if stick else ("press:" + real["key"])
        return from_token(token, keys=(real["key"],), source="ram", button=real["key"],
                          label=real.get("type"), raw=real)
    if stick:
        return from_token("mash:wiggle", source="ram", raw={"key": "stick"})
    return None


def _ram_re5_ps3(ctx: QteContext) -> Qte | None:
    from .titles import re5_ps3
    if ctx.m is None:
        return None
    pr = re5_ps3.selected_prompt(ctx.m)
    if not pr:
        return None
    token = pr.get("token")
    if not token:
        # re5_ps3's request dict carries mode + keys; synthesize a token if it lacks one.
        mode = pr.get("mode")
        keys = tuple(pr.get("keys") or ())
        verb = "mash" if mode in (3, 4, 5) else ("stick:wiggle" if mode == 6 else "press")
        token = "mash:wiggle" if mode == 6 else (verb + ":" + "+".join(keys) if keys else verb)
    return from_token(token, keys=tuple(pr.get("keys") or ()), source="ram",
                      label=pr.get("label"), raw=pr)


REGISTRY: dict[str, TitleQte] = {
    # RE5 Switch (title 010018100CD46000, game_id 52d15709be0fda1a): the sActionButton reader is live-verified
    # (re5_switch_prompt); Break free is mode 6 -> mash:wiggle, Resuscitate is mash:a. The glyph box is CALIBRATED
    # from the live lilspark stream 2026-11-04 (full-display 1280x720, the picture filling the frame): the game draws
    # its action-button prompt as a bright near-white letter disc + down-arrow + label text in the centre-bottom -
    # "(L) Break free" measured 1300 near-white-neutral px there, "(A) Resuscitate" 1780, ordinary play 0-70, a
    # "You Are Dead" screen 350. 500 fires on a real prompt and clears everything else.
    "010018100CD46000": TitleQte("010018100CD46000", ram=_ram_re5_switch,
                                 vision=VisionProfile("010018100CD46000", calibrated=True, mash_default=True,
                                                      glyph_box=(0.33, 0.52, 0.67, 0.80), glyph_min_px=500,
                                                      note="Switch prompt glyph box, live-calibrated 2026-11-04"),
                                 note="RAM: re5_switch_prompt.selected_prompt (verified)"),
    # RE6 Switch (title 01002A000CD48000, game_id 115f9cdbba115432): the sActionButton reader lists shown prompts.
    # The glyph box is pre-filled (RE6 draws prompts the same bright way) but stays uncalibrated until measured on a
    # live RE6 grab frame, so vision never fires on RE6 on guesswork.
    "01002A000CD48000": TitleQte("01002A000CD48000", ram=_ram_re6_switch,
                                 vision=VisionProfile("01002A000CD48000", calibrated=False, mash_default=True,
                                                      glyph_box=(0.33, 0.52, 0.67, 0.80), glyph_min_px=500,
                                                      note="Switch glyph box pending calibration from a live RE6 frame"),
                                 note="RAM: re6_switch.prompts (verified)"),
    # RE5 PS3 (BLUS30491): the PS3 QTE_INPUT_TABLE reader.
    "re5_ps3": TitleQte("re5_ps3", ram=_ram_re5_ps3, note="RAM: re5_ps3.selected_prompt"),
    # RE4 GameCube (G4BE08): RAM via gbox.re4_ram_prompts (wired in the driver); vision via the live-calibrated
    # screen_prompt G4BE08 profile (the teal A disc / red B disc).
    "G4BE08": TitleQte("G4BE08", ram=None,
                       vision=VisionProfile("G4BE08", screen_prompt_profile="G4BE08", calibrated=True,
                                            mash_default=False, note="screen_prompt G4BE08 (teal A / red B disc)")),
    # RE4 Switch (title 010099A00BC1E000): RAM map pending live measurement on the Spark; vision answers until then.
    "010099A00BC1E000": TitleQte("010099A00BC1E000", ram=None,
                                 vision=VisionProfile("010099A00BC1E000", calibrated=False, mash_default=True,
                                                      note="RE4 Switch: RAM map + Switch glyph profile both pending")),
}


def entry_for(map_id: str) -> TitleQte | None:
    return REGISTRY.get(str(map_id))


def detect(entry: TitleQte | None, ctx: QteContext, *, unknown=()) -> Qte | None:
    """The QTE the game asks for now: MEMORY first (entry.ram), then VISION (entry.vision, from ctx.frame or
    ctx.watcher). None when there is no prompt. Never raises (a reader's Unknown / torn read falls through to vision,
    then to None)."""
    if entry is None:
        return None
    if entry.ram is not None and ctx.m is not None:
        try:
            q = entry.ram(ctx)
            if q is not None:
                return q
        except unknown:
            pass
        except Exception:                               # noqa: BLE001 - a torn RAM read: try vision, then give up
            pass
    if entry.vision is not None:
        if ctx.watcher is not None:
            q = ctx.watcher.visible()
            if q is not None:
                return q
        if ctx.frame is not None:
            return detect_vision(ctx.frame, entry.vision, ctx.picture)
    return None


def snapshot_qte(map_id: str, ctx: QteContext, *, unknown=()) -> dict | None:
    """Convenience for a title's snapshot: the shown QTE as a plain dict ({token, kind, keys, button, source, ...}),
    or None. A driver that reads prompts in its own tick can fall back to this (the vision path) when its own RAM
    read came back empty, so a missed read still gets a QTE response. Pass a running VisionWatcher on ctx.watcher."""
    q = detect(entry_for(map_id), ctx, unknown=unknown)
    if q is None:
        return None
    return {"token": q.token, "kind": q.kind, "keys": q.keys, "button": q.button, "source": q.source,
            "label": q.label, "owner": q.owner, "target": q.target, "progress": q.progress,
            "target_count": q.target_count, "is_mash": q.is_mash, "is_stick": q.is_stick}


# --- the in-tick grab fallback (the single hook a Switch driver's snapshot calls) -----------------------------------
# The player's grabbed / held motion states (read from the player struct, independent of the sActionButton prompt
# manager): the gate that keeps the vision fallback off during ordinary play. RE5 Switch: re5_switch.MOTION_HELD.
GRAB_MOTIONS: dict[str, frozenset] = {
    "010018100CD46000": frozenset({100, 106, 107, 113, 114}),   # RE5 Switch grabbed / held
}
# The synthesized prompt a missed grab gets, in the title's own snapshot["prompt"] shape so the existing tick response
# (re5_switch._prompt: mode 6 -> WIGGLE, the stick shaken) mashes it out. A stick struggle is always safe while held
# and fills the Break-free meter; it never needs to read which letter the glyph was.
_GRAB_PROMPT = {"token": "mash:wiggle", "keys": (), "mode": 6, "kind": 0, "label": "qte_vision",
                "button": "qte_vision", "owner": None, "target": None, "progress": 0.0, "target_count": 0.0,
                "source": "vision", "qte_vision": True}


class _GrabWatcher:
    """A background thread that only grabs frames while recently poked (a held tick), so it costs nothing during
    ordinary play and bursts only during a grab. visible() is what the tick reads - never blocking on a frame grab."""

    def __init__(self, grab, profile: VisionProfile, hz: float = 8.0, clock=time.time):
        self._grab, self._profile, self._clock = grab, profile, clock
        self._period = 1.0 / max(1.0, hz)
        self._poked = 0.0
        self._seen_at = 0.0
        self._stop = False
        import threading
        self._t = threading.Thread(target=self._run, daemon=True, name="qte-grab-vision")
        self._t.start()

    def _run(self):
        import io
        while not self._stop:
            if self._clock() - self._poked > 1.0:        # not held recently: idle, no frame grab
                time.sleep(0.2)
                continue
            try:
                raw = self._grab()
                if raw:
                    if isinstance(raw, (bytes, bytearray)):
                        from PIL import Image
                        import numpy as np
                        img = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
                    else:
                        img = raw
                    if _glyph_px(img, self._profile) >= self._profile.glyph_min_px:
                        self._seen_at = self._clock()
            except Exception:                            # noqa: BLE001 - a torn frame / a stopped session
                pass
            time.sleep(self._period)

    def poke(self):
        self._poked = self._clock()

    def visible(self, max_age: float = 0.6) -> bool:
        return self._seen_at > 0 and (self._clock() - self._seen_at) <= max_age

    def stop(self):
        self._stop = True


_GRAB_WATCHERS: dict[str, _GrabWatcher] = {}
RELOAD_KEEP = ("_GRAB_WATCHERS",)          # the grab-vision threads survive a bot hot-reload (gbox.hot_reload)


def grab_fallback(map_id: str, m, snap: dict, *, clock=time.time) -> dict | None:
    """THE single hook a Switch driver's snapshot calls when its own RAM prompt read came back empty:
        snap["prompt"] = <ram prompt> or qte.grab_fallback(MAP_ID, m, snap)
    Returns a synthesized prompt (the title's shape, a stick struggle) ONLY when the player is actually in a grabbed /
    held motion AND the prompt overlay is visible on the capture frame - i.e. a grab the RAM reader missed (a torn
    read). None otherwise. Costs nothing during ordinary play: the gate short-circuits before any frame is grabbed,
    and in normal operation the RAM read is truthy so this is never even called. Never raises."""
    try:
        entry = entry_for(map_id)
        if entry is None or entry.vision is None or not entry.vision.calibrated:
            return None
        player = snap.get("player") or {}
        if player.get("motion") not in GRAB_MOTIONS.get(map_id, frozenset()):
            return None                                  # not grabbed: never synthesize, never grab a frame
        grab = getattr(getattr(m, "adapter", None), "get_frame", None)
        if not callable(grab):
            return None
        w = _GRAB_WATCHERS.get(map_id)
        if w is None:
            w = _GRAB_WATCHERS[map_id] = _GrabWatcher(grab, entry.vision, clock=clock)
        w.poke()
        return dict(_GRAB_PROMPT) if w.visible() else None
    except Exception:                                    # noqa: BLE001 - a fallback must never break the snapshot
        return None

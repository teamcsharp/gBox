"""Universal QTE handling (gbox.mercs.qte): the shared detect() (memory first, vision fallback) + respond() that
every title hooks. Tokens, the response vocabulary, the engine bridge, the RE5 Switch RAM adapter end to end, and the
vision fallback (a torn RAM read still answers a grab)."""
import io
import struct

import numpy as np
import pytest
from PIL import Image

from gbox.mercs import qte
from gbox.mercs import reactions
from gbox.mercs.titles import re5_switch_prompt as P


# --- tokens -> (kind, keys) -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("token, kind, keys", [
    ("press:y", qte.SINGLE, ("y",)),
    ("release:b", qte.SINGLE, ("b",)),
    ("mash:a", qte.MASH, ("a",)),
    ("mash:a+b", qte.MASH, ("a", "b")),
    ("mash:wiggle", qte.STICK_WIGGLE, ()),
    ("stick:rotate", qte.STICK_ROTATE, ()),
    ("stick:y", qte.STICK_AXIS, ()),
    ("wiggle", qte.STICK_WIGGLE, ()),
])
def test_parse_token(token, kind, keys):
    assert qte.parse_token(token) == (kind, keys)


def test_from_token_sets_button_and_kind():
    q = qte.from_token("mash:b", source="ram", label=28)
    assert q.kind == qte.MASH and q.keys == ("b",) and q.button == "b" and q.is_mash and q.label == 28


# --- respond(): mash hammers, single presses once, sticks step ------------------------------------------------------
def test_mash_alternates_press_and_release():
    q = qte.from_token("mash:b")
    assert qte.respond(q, 0) == {"hold": ("b",)}       # down
    assert qte.respond(q, 1) == {"hold": ()}           # up: a fresh press next tick
    assert qte.respond(q, 2) == {"hold": ("b",)}


def test_single_presses_once_then_releases():
    q = qte.from_token("press:y")
    assert qte.respond(q, 0) == {"hold": ("y",)}
    assert qte.respond(q, 1) == {"hold": ()}


def test_stick_wiggle_shakes_the_left_stick():
    q = qte.from_token("mash:wiggle")
    assert qte.respond(q, 0) == {"hold": ("lleft",)}
    assert qte.respond(q, 1) == {"hold": ("lright",)}


def test_stick_rotate_and_axis():
    assert qte.respond(qte.from_token("stick:rotate"), 0) == {"hold": ("lup",)}
    assert qte.respond(qte.from_token("stick:y"), 1) == {"hold": ("ldown",)}


# --- the engine (reactions.PromptPresser) bridge --------------------------------------------------------------------
def test_vision_token_maps_to_reactions_vocabulary():
    assert qte.vision_token(qte.from_token("mash:b")) == "mash:b"   # hammered
    assert qte.vision_token(qte.from_token("press:b")) == "b"       # bursted single
    assert qte.vision_token(qte.from_token("mash:wiggle")) == "wiggle"
    assert qte.vision_token(None) is None


def test_decode_keys_rejects_colon_in_keys():
    # reactions.PromptPresser refuses chords whose keys contain ":"; decode_keys must never emit one.
    for token in ("mash:b", "mash:a+b", "b", "wiggle", "rotate", "stick:y"):
        chords = qte.decode_keys(token)
        assert chords and all(":" not in k for chord in chords for k in chord)
    assert qte.decode_keys("mash:a+b") == [("a", "b")]


def test_vision_token_feeds_the_prompt_presser_as_a_mash():
    # A vision callback yielding "mash:b" drives PromptPresser's fast mash path, decoded by decode_keys.
    pp = reactions.PromptPresser(None, vision=lambda: "mash:b", keys=qte.decode_keys, stats={})
    chords = pp.step(now=100.0)
    assert chords == [("b",)] and pp.mashing is True


# --- the RE5 Switch RAM adapter, end to end (reusing the live-verified reader) --------------------------------------
BASE = 0x3CA7C04000
AB, MGR_BTN, PLAYER = 0x5D10000000, 0x5D20000000, 0x5D30000000


class Guest:
    def __init__(self):
        self.mem = {}

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def q(self, a, v):
        self.put(a, struct.pack("<Q", v))

    def rd(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))


def _guest(mode=1, key=1, label=112, hp=1000):
    g = Guest()
    g.put(BASE + P.KEY_TABLE, struct.pack("<32I", *P.MASKS))
    g.q(BASE + P.S_ACTION, AB)
    g.q(AB, BASE + P.AB_VT)
    g.put(AB + P.AB_ENABLED, b"\x01")
    mgr = AB + P.AB_MGR
    g.put(mgr + P.MGR_ENABLED, b"\x01")
    g.put(mgr + P.MGR_INDEX, struct.pack("<i", 0))
    unit = mgr + P.MGR_UNITS[0]
    g.put(unit + P.UNIT_SHOWN, b"\x01")
    g.q(unit + P.UNIT_BTN, MGR_BTN)
    g.put(unit + P.UNIT_MODE, struct.pack("<I", mode))
    g.q(MGR_BTN, BASE + P.BTN_VT)
    g.q(MGR_BTN + P.BTN_OWNER, 0x5D40000000)
    g.put(MGR_BTN + P.BTN_PLAYER, struct.pack("<6I", 4, 1, mode, 33, key, label))
    g.put(PLAYER + 0x1EB8, struct.pack("<h", hp))
    return g


RE5_SWITCH = "010018100CD46000"


def test_re5_switch_break_free_detects_as_a_stick_wiggle_mash():
    # Break free (a Majini's grab) is mode 6: the left stick shaken. The shared detect() must return a mash.
    g = _guest(mode=6, label=28)
    ctx = qte.QteContext(m=g, base=BASE, player_ptr=PLAYER, index=0)
    q = qte.detect(qte.entry_for(RE5_SWITCH), ctx)
    assert q is not None and q.kind == qte.STICK_WIGGLE and q.is_mash and q.source == "ram"
    assert qte.respond(q, 0) == {"hold": ("lleft",)}


def test_re5_switch_press_y_detects_as_single():
    g = _guest(mode=1, key=1, label=112)             # the hourglass: press Y
    ctx = qte.QteContext(m=g, base=BASE, player_ptr=PLAYER, index=0)
    q = qte.detect(qte.entry_for(RE5_SWITCH), ctx)
    assert q is not None and q.kind == qte.SINGLE and q.keys == ("y",) and q.source == "ram"


def test_no_prompt_no_detection():
    g = _guest(mode=1)
    g.put((AB := 0x5D10000000) + P.AB_ENABLED, b"\x00")   # the manager off: nothing shown
    ctx = qte.QteContext(m=g, base=BASE, player_ptr=PLAYER)
    assert qte.detect(qte.entry_for(RE5_SWITCH), ctx) is None


# --- vision fallback: a torn RAM read still answers -----------------------------------------------------------------
def _re4_frame(button_rgb=(40, 134, 104), at=(259, 386), size=(480, 640)):
    img = np.zeros(size + (3,), np.uint8)
    img[:, :] = (90, 80, 60)
    yy, xx = np.ogrid[:size[0], :size[1]]
    img[(yy - at[1]) ** 2 + (xx - at[0]) ** 2 <= 10 ** 2] = button_rgb
    return img


def test_vision_answers_re4_gc_when_ram_has_no_map():
    # RE4 GC has no RAM adapter in the registry (ram=None): the vision profile (screen_prompt G4BE08) must answer.
    ctx = qte.QteContext(frame=_re4_frame())
    q = qte.detect(qte.entry_for("G4BE08"), ctx)
    assert q is not None and q.button == "a" and q.source == "vision" and q.kind == qte.SINGLE


def test_vision_falls_back_when_the_ram_read_tears():
    # A RAM reader that raises (a torn read) must not stop a vision answer: detect() swallows it and uses vision.
    def torn(_ctx):
        raise reactions.Unknown("torn read")
    entry = qte.TitleQte("G4BE08", ram=torn, vision=qte.entry_for("G4BE08").vision)
    ctx = qte.QteContext(m=object(), frame=_re4_frame())
    q = qte.detect(entry, ctx, unknown=(reactions.Unknown,))
    assert q is not None and q.source == "vision" and q.button == "a"


def test_uncalibrated_switch_vision_never_false_presses():
    # The Switch glyph profiles are scaffolded (calibrated=False) until measured from live frames: vision returns
    # nothing rather than guessing a button on stream.
    ctx = qte.QteContext(frame=_re4_frame())
    assert qte.detect_vision(_re4_frame(), qte.entry_for(RE5_SWITCH).vision) is None
    assert qte.detect(qte.entry_for(RE5_SWITCH), ctx) is None        # no RAM (no m), no calibrated vision


# --- the non-blocking watcher the tick reads -----------------------------------------------------------------------
def test_vision_watcher_reports_the_button_on_a_real_frame_source():
    buf = io.BytesIO()
    Image.fromarray(_re4_frame()).save(buf, "JPEG", quality=95)
    now = [100.0]
    vw = qte.VisionWatcher(lambda: buf.getvalue(), qte.entry_for("G4BE08").vision, clock=lambda: now[0])
    vw._w.step()                                        # white-box: one grab+detect without spinning the thread
    q = vw.visible()
    assert q is not None and q.button == "a" and q.source == "vision"
    now[0] += 2.0
    assert vw.visible() is None                         # stale: the prompt is off screen now


# --- snapshot convenience -------------------------------------------------------------------------------------------
def test_snapshot_qte_shape():
    g = _guest(mode=6, label=28)
    ctx = qte.QteContext(m=g, base=BASE, player_ptr=PLAYER)
    row = qte.snapshot_qte(RE5_SWITCH, ctx)
    assert row["kind"] == qte.STICK_WIGGLE and row["is_mash"] is True and row["source"] == "ram"

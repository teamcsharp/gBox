"""re4_editions: GC->edition relocation by masked code-signature scan (request #3350).

The GC main.dol is pinned by SHA256; when present, self_check() is the identity proof. The
synthetic tests below prove relocation and rejection without the disc: a fake target whose
immediates are rewritten to a shifted layout must relocate to the shifted addresses, and any
corrupted or duplicated signature must be rejected (None), never a wrong table.
"""
import struct
from pathlib import Path

import pytest

from gbox import re4_editions as ed

DOL = Path("/home/ehm_eckx/gBox_alt/scratch/re4-ram/main.dol")


def _sig_words(name):
    return list(ed.CODE_SIGS[name][1])


def _make_target(delta=0x40000, dup_emmgr=False):
    """A minimal synthetic target: GC sig windows with immediates shifted by delta."""
    out = bytearray(0x1000)
    def put(off, words):
        struct.pack_into(">%dI" % len(words), out, off, *words)
    # EMMGR at 0x100, GAME_PAD at 0x300, MERC at 0x500
    for name, off in (("EMMGR", 0x100), ("GAME_PAD", 0x300), ("MERC", 0x500)):
        ws = _sig_words(name)
        gc = ed.CODE_SIGS[name][0]
        new = gc + delta
        hi = ((new + 0x8000) & 0xFFFF0000) >> 16   # lis hi rounds so addi's s16 lo fits
        lo = new - (hi << 16)
        ws[2] = (ws[2] & 0xFFFF0000) | (hi & 0xFFFF)
        ws[3] = (ws[3] & 0xFFFF0000) | (lo & 0xFFFF)
        put(off, ws)
    if dup_emmgr:
        put(0x800, _sig_words("EMMGR"))
    return bytes(out)


def test_catalog_mapping():
    assert ed.edition("79c3a3eccb34fe62") == "wii"
    assert ed.edition("G4BE08") == "gc"
    assert ed.edition("nope") is None
    assert ed.offsets("79c3a3eccb34fe62") == ed.GC_OFFSETS
    assert ed.offsets("nope") is None


def test_gc_offsets_match_bot_constants():
    # P_PLAYER_PTR and P_GLOBAL derive from r13 exactly like re4_merc_bot/re_games.
    assert ed.GC_OFFSETS["P_PLAYER_PTR"] == 0x802B3044
    assert ed.GC_OFFSETS["P_GLOBAL"] == 0x802B2280
    assert ed.GC_OFFSETS["EMMGR"] == 0x8027DF20


def test_relocate_synthetic_shift():
    delta = 0x40000
    table = ed.locate(_make_target(delta=delta))
    assert table is not None
    for name in ed.CODE_SIGS:
        assert table[name] == ed.CODE_SIGS[name][0] + delta
    # single common delta -> delta-only anchors resolve too
    assert table["MERC_TIMER"] == ed.GC_OFFSETS["MERC_TIMER"] + delta
    assert table["AIM_PITCH"] == ed.GC_OFFSETS["AIM_PITCH"] + delta
    # r13-relative anchors stay unresolved until the target's r13 is known
    assert table["P_PLAYER_PTR"] is None
    assert table["P_GLOBAL"] is None


def test_relocate_with_target_r13():
    delta = 0x40000
    target_r13 = ed.R13 + delta
    table = ed.locate(_make_target(delta=delta), r13=target_r13)
    assert table is not None
    assert table["P_PLAYER_PTR"] == 0x802B3044 + delta
    assert table["P_GLOBAL"] == 0x802B2280 + delta


def test_duplicate_signature_rejected():
    assert ed.locate(_make_target(dup_emmgr=True)) is None


def test_corrupted_signature_rejected():
    hay = bytearray(_make_target())
    hay[0x300] ^= 0xFF  # corrupt GAME_PAD window
    assert ed.locate(bytes(hay)) is None


def test_empty_haystack_rejected():
    assert ed.locate(b"") is None
    assert ed.locate(b"\x00" * 8) is None


def test_gc_dol_identity_self_check():
    if not DOL.exists():
        pytest.skip("G4BE08 main.dol not on this machine")
    assert ed.self_check(str(DOL))

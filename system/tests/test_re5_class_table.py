"""The RE5 grenade class table (uWp06/07/08) and its derivation from the game's own initialiser.

The pinned DTIs are checked against a synthetic registration block built in the same shape as the game's (adrp/add
into x0, the name into x1, the parent into x2, the size into w3, the id into w4, then the constructor call), so the
derivation itself is tested without a 30 MB image.
"""
import struct

import pytest

from gbox.mercs.native.re5_ebffdb22 import classes as C


def test_the_pinned_table_is_the_three_grenade_classes():
    assert [(k, C.CLASSES[k].name, C.CLASSES[k].dti, C.CLASSES[k].item)
            for k in ("hand", "incendiary", "flash")] == [
        ("hand", "uWp06", 0x1D714C8, 0x106),
        ("incendiary", "uWp07", 0x1D71500, 0x107),
        ("flash", "uWp08", 0x1D71538, 0x108)]
    assert C.CLASSES["flash"].dti == 0x1D71538           # the DTI the live-verified flash already uses
    assert all(c.size for c in C.CLASSES.values())
    with pytest.raises(KeyError):
        C.class_for("nuke")


# ---- a synthetic MtDTI registration block, encoded by hand ---------------------------------------------------------------

SHIFT = 0x100


def _adrp(rd, target, pc):
    page = target & ~0xFFF
    immlo = ((page - (pc & ~0xFFF)) >> 12) & 3
    immhi = (((page - (pc & ~0xFFF)) >> 12) >> 2) & 0x7FFFF
    return 0x90000000 | (immlo << 29) | (immhi << 5) | rd


def _add(rd, rn, imm):
    return 0x91000000 | ((imm & 0xFFF) << 10) | (rn << 5) | rd


def _movz(rd, imm):
    return 0xD2800000 | (imm << 5) | rd


def _movk(rd, imm, shift):
    return 0xF2800000 | ((shift // 16) << 21) | (imm << 5) | rd


def _bl(pc, target):
    return 0x94000000 | (((target - pc) // 4) & 0x3FFFFFF)


def registration(object_, name_at, parent, size, class_id, at, image, names):
    """Write one registration at `at`: the bytes to the image and the name string to its table; returns the next pc."""
    words = []
    pc = at
    for reg, value in ((0, object_), (1, name_at), (2, parent)):
        words.append(_adrp(reg, value, pc)); pc += 4
        words.append(_add(reg, reg, value & 0xFFF)); pc += 4
    words.append(_movz(3, size & 0xFFFF)); pc += 4
    if size >> 16:
        words.append(_movk(3, size >> 16, 16)); pc += 4
    words.append(_movz(4, class_id & 0xFFFF)); pc += 4
    if class_id >> 16:
        words.append(_movk(4, class_id >> 16, 16)); pc += 4
    words.append(_bl(pc, C.CTOR)); pc += 4
    struct.pack_into(f"<{len(words)}I", image, at + SHIFT, *words)
    return pc


def synthetic_image(overrides=None):
    """A main image with a registration block at 0x84800 and three class names in its 'rodata'."""
    size = 0x90000
    image = bytearray(size)
    names = {0x80000: "uWp06", 0x80040: "uWp07", 0x80080: "uWp08"}
    for at, text in names.items():
        image[at + SHIFT:at + SHIFT + len(text)] = text.encode() + b"\0"
    rows = [(C.CLASSES["hand"], 0x80000), (C.CLASSES["incendiary"], 0x80040), (C.CLASSES["flash"], 0x80080)]
    pc = C.BLOCK[0]
    for spec, name_at in rows:
        object_ = (overrides or {}).get(spec.kind, spec.dti)
        pc = registration(object_, name_at, 0x1D71180, spec.size, 0x07010000 + ((spec.item & 0xFF) << 8), pc, image, names)
    return bytes(image)


def test_the_derivation_reads_a_registration_block_like_the_game_s():
    derived = C.derive(synthetic_image())
    assert set(derived) == {"uWp06", "uWp07", "uWp08"}
    assert derived["uWp06"]["dti"] == 0x1D714C8 and derived["uWp06"]["item"] == 0x106
    assert derived["uWp07"]["dti"] == 0x1D71500 and derived["uWp07"]["size"] == 0x28D0
    assert derived["uWp08"]["dti"] == 0x1D71538 and derived["uWp08"]["parent"] == 0x1D71180
    assert C.verify(synthetic_image())["ok"] is True


def test_a_moved_dti_is_reported_instead_of_trusted():
    moved = synthetic_image({"incendiary": 0x1D71600})
    report = C.verify(moved)
    assert report["ok"] is False
    assert {"kind": "incendiary", "why": "dti", "pinned": "0x1d71500", "image": "0x1d71600"} in report["mismatches"]


def test_the_flash_cross_check_is_enforced():
    # uWp08 is the one class whose DTI was already verified live; if it moves, the whole block is suspect even when
    # the pinned table would otherwise match.
    image = bytearray(synthetic_image())
    for spec, name_at in ((C.CLASSES["flash"], 0x80080),):
        registration(0x1D71540, name_at, 0x1D71180, spec.size, 0x07010000 + ((spec.item & 0xFF) << 8), C.BLOCK[0] + 0x60,
                     image, {})
    report = C.verify(bytes(image))
    assert report["ok"] is False
    assert any(m["why"] == "the documented flash DTI does not match uWp08" for m in report["mismatches"])

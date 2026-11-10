"""The RE6 native build verifier: the pinned offsets against a decompressed `main` image.

`verify_build` is what tells an operator (or this lane) whether the RE6 installation in front of them is the build
the ring's spawn/detonate pair was checked against, and whether its three code caves are still padding. The images
here are synthetic (zeros plus the signature); the real receipt is in docs/ds-grenade-ring-lane-2026-11-10.md.
"""
import pytest

from gbox.mercs.titles import re6_switch_native as N

SIG_AT = 0x100 + N.R.SIG_OFF
IMAGE = SIG_AT + len(N.R.SIGNATURE) + 0x1000                  # covers the signature and every cave


def image(fill: bytes = b"") -> bytearray:
    out = bytearray(IMAGE)
    if fill:
        out[:] = (fill * (IMAGE // len(fill) + 1))[:IMAGE]
    at = SIG_AT
    out[at:at + len(N.R.SIGNATURE)] = N.R.SIGNATURE
    return out


def test_the_pinned_build_with_pristine_caves_is_accepted():
    report = N.verify_build(bytes(image()))
    assert report["ok"] is True and report["build_signature"] is True and report["reason"] == ""
    assert set(report["caves"]) == {"call", "spawn", "detonate"}
    assert all(c["pristine_padding"] and c["installable"] for c in report["caves"].values())


def test_a_different_build_is_refused_by_its_signature():
    img = image()
    img[SIG_AT] ^= 0xFF
    report = N.verify_build(bytes(img))
    assert report["ok"] is False and report["build_signature"] is False
    assert "not the pinned RE6 build" in report["reason"]


def test_a_cave_that_is_no_longer_padding_is_refused():
    img = image()
    off, name, size, _digest = N.CODE[1]
    img[0x100 + off:0x100 + off + size] = b"\xAA" * size
    report = N.verify_build(bytes(img))
    assert report["ok"] is False
    assert report["caves"][name]["pristine_padding"] is False
    assert report["caves"][name]["installable"] is False
    assert "code cave" in report["reason"]


def test_an_image_that_is_too_short_is_reported_not_trusted():
    report = N.verify_build(b"NSO0" + bytes(64))
    assert report["ok"] is False and "shorter" in report["reason"]
    assert report["caves"] == {}
    not_bytes = N.verify_build("not bytes")             # a wrong type is a report, never an exception
    assert not_bytes["ok"] is False and "shorter" in not_bytes["reason"]

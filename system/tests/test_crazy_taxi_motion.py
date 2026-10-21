"""Motion-bank acceptance for the owned Crazy Taxi (USA) GameCube build (request #2513).

The shape bank (polDC0.all) carries the driver parts; this checks the other half of
the rig: motDC.bin, the motion bank main.dol walks to pose those bones. Four focused
checks against the owned disc: the motion container hash, the header walk (17 groups
per motion, contiguous records), the frame count of the first motion, and that every
group exposes three channels.

Scope note: the motion -> bone mapping is NOT asserted here. main.dol's rig table
still has to prove which group belongs to which bone before a pose can be rebuilt;
this file only pins the container layout that mapping work will read. The header
walk currently stops at 1_525_560 B, so the tail of the container is still
unclassified - the counts below are the observed walk, not a claim of completeness.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import gbox.crazy_taxi as ct

EXPECTED_MOTION_SIZE = 2_854_048
EXPECTED_MOTIONS = 278
EXPECTED_GROUPS = ct.MOTION_GROUPS
EXPECTED_END = 1_525_560
FIRST_FRAMES = 91


def _owned_iso() -> Path:
    """The owned disc: GBOX_CT_ISO overrides, then the two known cache roots (the
    worker's gBox_alt cache and the prime Spark's gbox-cache)."""
    env = os.environ.get("GBOX_CT_ISO")
    for candidate in (Path(env) if env else None,
                      Path("/home/ehm_eckx/gBox_alt/gbox-cache/modbase/bc02bb68790ce2e7/"
                           "Crazy Taxi (USA).iso"),
                      Path("/home/ehm_eckx/gbox-cache/modbase/bc02bb68790ce2e7/"
                           "Crazy Taxi (USA).iso")):
        if candidate is not None and candidate.is_file():
            return candidate
    return Path("/nonexistent/Crazy Taxi (USA).iso")


ISO_PATH = _owned_iso()
requires_iso = pytest.mark.skipif(not ISO_PATH.is_file(), reason=f"owned ISO absent: {ISO_PATH}")


def _motion_bytes() -> bytes:
    from gbox.gcdisc import GCDisc

    return GCDisc(ISO_PATH).read(ct.MOTION)


@requires_iso
def test_motion_container_identity():
    """motDC.bin from the owned disc is byte-identical to the module constant."""
    motion = _motion_bytes()
    assert len(motion) == EXPECTED_MOTION_SIZE
    assert hashlib.sha256(motion).hexdigest() == ct.MOTION_SHA256


@requires_iso
def test_motion_header_walk():
    """The header walk finds 278 contiguous motion records ending at 1_525_560."""
    motion = _motion_bytes()
    bank = ct.motion_bank(motion)
    motions = bank["motions"]
    assert len(motions) == EXPECTED_MOTIONS
    assert bank["end"] == EXPECTED_END
    for previous, following in zip(motions, motions[1:]):
        assert previous.offset + previous.size == following.offset


@requires_iso
def test_motion_group_shape():
    """Every motion carries 17 groups of 3 channels; the first motion has 91 frames."""
    motion = _motion_bytes()
    motions = ct.motion_bank(motion)["motions"]
    for entry in motions:
        assert len(entry.groups) == EXPECTED_GROUPS
        assert all(len(channel) == 3 for channel in entry.groups)
    assert motions[0].offset == 0
    assert motions[0].frames == FIRST_FRAMES

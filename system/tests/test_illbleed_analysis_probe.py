"""Pinned checks for gbox.illbleed_analysis_probe: the shared Ninja reader decodes Illbleed's .NJ
character models, C04's identity is pinned from texture names, and the probe's synthetic-header
helpers behave.  The full-disc probe is pinned to the owned Illbleed (USA) GD-ROM cache when present
(GBOX_ILLBLEED_GDI, default ~/gbox-cache/dc/81a90290abc15a37/disc.gdi)."""
import os
import struct
from pathlib import Path

import pytest

from gbox import illbleed_analysis_probe as ap
from gbox.illbleed_inventory import njtl


def synth_njtl(names: list[str], payload: bytes) -> bytes:
    """A minimal NJTL file with one NJCM-style payload chunk."""
    head = b"NJTL" + struct.pack("<III", 0, 8, len(names))
    base = 8
    entries, blob = b"", b""
    for n in names:
        # name position (header + full entry table + blob so far), relative to base
        off = (len(head) + 12 * len(names) + len(blob) - base)
        entries += struct.pack("<III", off, 0, 0)
        blob += n.encode() + b"\0"
    body = b"NJCM" + struct.pack("<I", len(payload)) + payload
    return head + entries + blob + body


def test_njtl_header_matches_inventory_reader():
    d = synth_njtl(["vkev001z", "jorg001z"], b"\x00" * 16)
    head = njtl(d)
    assert head["names"] == ["vkev001z", "jorg001z"]


def test_c04_identity_pins_jorge():
    rep = {"C04": {"textures": ["Vyor000z", "jorg001z", "jorg002z", "jorg003z"]}}
    assert ap.c04_identity(rep) == "jorge (jorg/yor texture prefix on C04.NJ; the fifth playable model)"


def test_c04_identity_rejects_unmatched_prefix():
    rep = {"C04": {"textures": ["vkev001z", "vkev002z"]}}
    with pytest.raises(ValueError):
        ap.c04_identity(rep)


def test_playable_and_enemy_sample_lists():
    assert ap.PLAYABLE == ("C00", "C01A", "C02A", "C03", "C04")
    assert ap.ENEMY_SAMPLE == ("AMAZON/E00.NJ", "AMAZON/E01.NJ")
    assert ap.CHD_SHA.startswith("cc63a6ba")


@pytest.fixture(scope="module")
def disc_gdi():
    p = Path(os.environ.get("GBOX_ILLBLEED_GDI", "~/gbox-cache/dc/81a90290abc15a37/disc.gdi")).expanduser()
    if not p.exists():
        pytest.skip("Illbleed disc cache not present")
    return str(p)


def test_full_disc_probe(disc_gdi):
    rep = ap.decode_report(disc_gdi)
    for stem in ap.PLAYABLE:
        m = rep[stem]
        assert 60 <= m["bones"] <= 120, f"{stem} bones {m['bones']} outside a playable-range"
        assert m["vertex_count"] >= 1000, f"{stem} vertices {m['vertex_count']} too small"
        assert m["textures"], f"{stem} lost its texture names"
        assert set(m["vertex_attrs"]) >= {"pos", "nrm", "joints"}, m["vertex_attrs"]
    # C04 pinned
    assert ap.c04_identity(rep).startswith("jorge")
    # enemies decode through the same reader
    for stem in ap.ENEMY_SAMPLE:
        assert rep[stem]["bones"] >= 2, f"{stem} did not decode"

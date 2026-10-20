"""Pinned checks for gbox.illbleed_analysis_probe: the shared Ninja reader decodes Illbleed's .NJ
character models, C04's identity is pinned from texture names, and the probe's synthetic-header
helpers behave.  The full-disc probe is pinned to the owned Illbleed (USA) GD-ROM cache when present
(GBOX_ILLBLEED_GDI, default ~/gBox_alt/gbox-cache/dc/81a90290abc15a37/disc.gdi)."""
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
    p = Path(os.environ.get("GBOX_ILLBLEED_GDI", "~/gBox_alt/gbox-cache/dc/81a90290abc15a37/disc.gdi")).expanduser()
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


# ---- CMCK deep-dive ----

def test_cmck_decode_all_playables(disc_gdi):
    """All 5 playables have CMCK 141496 B, count=5, stride=0x18, 5 GBIX markers
    (first at +0x18), a 4-entry table at +0x08 whose entries equal GBIX
    positions, and slot 0 at 0x18 as the one GBIX the table omits."""
    cmck = ap.cmck_decode(disc_gdi)
    assert set(cmck) == set(ap.PLAYABLE)
    for stem, c in cmck.items():
        assert c["cmck_size"] == 141496, f"{stem}: CMCK size {c['cmck_size']} != 141496"
        assert c["count"] == 5, f"{stem}: count {c['count']} != 5"
        assert c["stride"] == 0x18, f"{stem}: stride {c['stride']:#x} != 0x18"
        assert len(c["offsets"]) == 4, f"{stem}: table should hold count-1 = 4 entries"
        assert len(c["gbix_positions"]) == 5, f"{stem}: expected 5 GBIX"
        assert c["gbix_positions"][0] == 0x18, f"{stem}: first GBIX not at +0x18"
        assert c["offsets_match_gbix"], f"{stem}: table entries are not GBIX positions"
        assert c["unmatched_gbix"] == [0x18], f"{stem}: only slot 0 should be off-table"


def test_cmck_texture_slots_exact_vq_fit(disc_gdi):
    """Each slot's PVRT payload_size exactly fills the slot: texture data ends
    at the next GBIX (or CMCK end) and every payload follows the VQ law
    payload_size - 8 == w*h//4 + 0x800 (256-entry codebook + 2bpp indices).
    CMCK therefore holds only the 5 textures -- no inter-GBIX motion data."""
    cmck = ap.cmck_decode(disc_gdi)
    for stem, c in cmck.items():
        assert all(f is not None for f in c["fmt"]), f"{stem}: missing PVRT meta"
        assert all(c["vq_exact_fit"]), f"{stem}: VQ size law violated"
        ends = [tb["end"] for tb in c["tex_bounds"]]
        starts = [tb["start"] for tb in c["tex_bounds"]]
        assert ends[:-1] == c["gbix_positions"][1:], (
            f"{stem}: slot texture end != next GBIX ({[hex(e) for e in ends]})")
        assert ends[-1] == c["cmck_size"], f"{stem}: last slot does not fill CMCK"
        for k, (gp, s) in enumerate(zip(c["gbix_positions"], starts)):
            assert s == gp + 0x20, f"{stem} slot {k}: texture start {s:#x} != GBIX+0x20"


def test_cmck_blob_sizes_and_pvr_dims(disc_gdi):
    """All 5 GBIX per playable carry the fixed GBIX blob_size 0x8, a PVRT
    header and positive power-of-two dimensions."""
    cmck = ap.cmck_decode(disc_gdi)
    for stem, c in cmck.items():
        assert len(c["blob_sizes"]) == 5, f"{stem}: expected 5 blob sizes"
        assert all(b == 8 for b in c["blob_sizes"]), f"{stem}: unexpected blob size"
        assert len(c["pvr_dims"]) == 5, f"{stem}: expected 5 PVR dims"
        for i, d in enumerate(c["pvr_dims"]):
            assert d is not None, f"{stem}: GBIX {i} missing PVRT dims"
            assert d["w"] > 0 and d["h"] > 0, f"{stem}: GBIX {i} has non-positive dims {d}"
            assert d["w"] & (d["w"] - 1) == 0 and d["h"] & (d["h"] - 1) == 0, (
                f"{stem}: GBIX {i} dims {d} not power-of-two")


def test_cmck_cross_character_layout(disc_gdi):
    """Cross-character layout check: C00/C01A (small texture variant) has
    offsets [0x4838, 0x9058, 0xd878, 0x1e098] and C02A/C03/C04 (large texture
    variant) has [0x10838, 0x15058, 0x19878, 0x1e098]."""
    cmck = ap.cmck_decode(disc_gdi)
    small = [0x4838, 0x9058, 0xd878, 0x1e098]
    large = [0x10838, 0x15058, 0x19878, 0x1e098]
    for stem, expected in [("C00", small), ("C01A", small), ("C02A", large),
                           ("C03", large), ("C04", large)]:
        assert cmck[stem]["offsets"] == expected, (
            f"{stem}: offsets {[hex(o) for o in cmck[stem]['offsets']]} "
            f"expected {[hex(o) for o in expected]}"
        )

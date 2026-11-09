"""RE6 Switch TEX reader tests (skip when the extracted RomFS is absent)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from gbox import mt_arc, re6_switch_tex as X

ROMFS = Path(os.environ.get("GBOX_RE6_SWITCH_ROMFS", r"C:\_tools\gBox\.tmp\re6sw_romfs"))
ARC = ROMFS / "nativeNXx64" / "arc" / "NX" / "uPlTex0000_0.arc"
needs_arc = pytest.mark.skipif(not ARC.is_file(), reason="the extracted RE6 Switch RomFS is not present")


@needs_arc
def test_describe_lists_the_measured_formats():
    rows = X.describe_arc(mt_arc.parse(ARC.read_bytes()))
    assert len(rows) >= 20
    formats = {row["format"] for row in rows}
    assert {0x19, 0x1F, 0x2B} <= formats
    normal = next(row for row in rows if row["name"].endswith("_NM"))
    assert normal["format"] == 0x1F and normal["block_bytes"] == 16
    albedo = next(row for row in rows if row["name"].endswith("_BM"))
    assert albedo["format"] == 0x2B and albedo["decodable"] is False


@needs_arc
def test_a_normal_map_decodes_to_a_normal_map():
    arc = mt_arc.parse(ARC.read_bytes())
    entry = next(e for e in arc.entries if e.name.endswith("_NM"))
    surface = X.from_arc_entry(entry)
    assert surface.format == 0x1F
    image = surface.decode()
    assert image.size == (surface.width, surface.height)
    colours = {image.getpixel((x, y))[:3] for x in range(0, image.width, 16) for y in range(0, image.height, 16)}
    assert len(colours) > 3


@needs_arc
def test_the_unresolved_albedo_layout_is_refused():
    arc = mt_arc.parse(ARC.read_bytes())
    entry = next(e for e in arc.entries if e.name.endswith("_BM"))
    with pytest.raises(X.TexError):
        X.from_arc_entry(entry).decode()

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
    assert albedo["format"] == 0x2B and albedo["decodable"] is True


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
def test_the_albedo_encoder_round_trips_through_a_real_tex():
    import numpy as np
    from PIL import Image

    arc = mt_arc.parse(ARC.read_bytes())
    entry = next(e for e in arc.entries if e.name.endswith("eye_BM"))
    template = X.from_arc_entry(entry)
    width, height = template.width, template.height
    yy, xx = np.mgrid[0:height, 0:width]
    canvas = np.zeros((height, width, 3), np.uint8)
    canvas[..., 0] = (yy * 255 // max(1, height - 1)).astype(np.uint8)
    canvas[..., 1] = 100
    canvas[..., 2] = (xx * 255 // max(1, width - 1)).astype(np.uint8)
    canvas[(yy - height // 2) ** 2 + (xx - width // 2) ** 2 < (min(width, height) // 5) ** 2] = (240, 200, 40)
    written = X.replace_albedo(template.data, canvas)
    surface = X.parse(written)
    assert (surface.width, surface.height, surface.mip_count) == (template.width, template.height, template.mip_count)
    assert surface.format == 0x2B
    decoded = np.asarray(surface.decode().convert("L"), float)
    source = np.asarray(Image.fromarray(
        (0.299 * canvas[..., 0] + 0.587 * canvas[..., 1] + 0.114 * canvas[..., 2]).astype(np.uint8)).convert("L"), float)
    mse = ((decoded - source) ** 2).mean()
    assert 10 * np.log10(255 * 255 / mse) > 25.0


@needs_arc
def test_the_albedo_decodes_its_detail_layer():
    """0x2B blocks are BC4 detail (bytes 0-7) + a BC1 half (bytes 8-15); the detail layer must be a real image."""
    arc = mt_arc.parse(ARC.read_bytes())
    entry = next(e for e in arc.entries if e.name.endswith("_BM"))
    surface = X.from_arc_entry(entry)
    assert surface.format == 0x2B
    image = surface.decode()
    assert image.size == (surface.width, surface.height)
    grey = image.convert("L")
    values = [grey.getpixel((x, y)) for x in range(0, grey.width, 32) for y in range(0, grey.height, 32)]
    assert max(values) - min(values) > 32                  # a detail map, not a flat fill
    detail, tint = surface._albedo_layers()
    assert detail.shape == (surface.height, surface.width)
    assert tint.shape == (surface.height, surface.width, 3)

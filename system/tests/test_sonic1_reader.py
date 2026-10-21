"""Reader tests for the Sonic 1 (Mega Drive) player in "Shadow In Sonic 1"
(gbox.sonic1_reader): the indexed-PNG encoder, the frame assembler, and the
owned-ROM export (130 frames, animation map, import-ready pieces/DPLC, Nemesis
art), plus the characters.DEDICATED registration.

The owned-ROM test pins what the reader finds in the operator's build (cached at
~/gBox_alt/gbox-cache/1fff93531f10c256/source.zip, identified by the ROM's SHA-256) and
skips when the dump is not on this machine.
"""
from __future__ import annotations

import io
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import sonic1_analysis as A
from gbox import sonic1_inventory as I
from gbox import sonic1_reader as R
from gbox.formats import sega_md as M

CACHE = Path(os.environ.get("GBOX_ROM_CACHE", Path.home() / "gBox_alt/gbox-cache"))
OWNED_ROM_SHA256 = "a22564d49d28bfab70e2046b1c08d7a6a19f6bf4183491e0280ef916fb4863ce"


def _owned_rom() -> bytes:
    p = CACHE / "1fff93531f10c256" / "source.zip"
    if not p.is_file():
        pytest.skip(f"owned ROM not cached at {p}")
    d, info = I.read_rom(p)
    if info["rom_sha256"] != OWNED_ROM_SHA256:
        pytest.skip(f"{p} is not the owned Shadow In Sonic 1 build")
    return d


# ----------------------------------------------------------------- indexed PNG

def test_indexed_png_structure_and_transparency():
    pal = [(0, 0, 0)] + [(c * 17, c * 17, c * 17) for c in range(1, 16)]
    idx = bytes([0, 1, 2, 3])
    png = R.indexed_png(2, 2, idx, pal)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    assert im.mode == "P" and im.size == (2, 2)
    assert len(im.getpalette()) == 16 * 3                       # 16-colour palette
    tr = im.info.get("transparency")
    assert tr == 0                                              # only index 0 transparent
    back = np.array(im)
    assert list(back.ravel()) == [0, 1, 2, 3]                   # indices survive the round trip


def test_assemble_flip_priority_and_transparency():
    # two 1x1 pieces overlap exactly: piece 0 (colour 2) on top of piece 1 (colour 3)
    pieces = [
        {"x": 0, "y": 0, "w": 1, "h": 1, "tile": 0, "hflip": False, "vflip": False},
        {"x": 0, "y": 0, "w": 1, "h": 1, "tile": 1, "hflip": False, "vflip": False},
    ]
    raw = b"\x22" * 32 + b"\x33" * 32                       # 4bpp: colour 2 and colour 3 tiles
    idx, x0, y0, w, h = R.assemble(raw, pieces, [(0, 2)])
    assert (x0, y0, w, h) == (0, 0, 8, 8)
    arr = np.frombuffer(idx, np.uint8).reshape(8, 8)
    assert set(arr.ravel().tolist()) == {2}                 # piece 0 drawn on top
    # an hflipped tile mirrors its pixels: the old left pixels A,B,C,D land on the right
    tile = bytes([0xAB, 0xCD] + [0] * 30)                   # row 0: pixels A,B,C,D then transparent
    flipped = [{"x": 0, "y": 0, "w": 1, "h": 1, "tile": 0, "hflip": True, "vflip": False}]
    idx, *_ = R.assemble(tile, flipped, [(0, 1)])
    arr = np.frombuffer(idx, np.uint8).reshape(8, 8)
    assert [int(arr[0, k]) for k in range(8)] == [0, 0, 0, 0, 0xD, 0xC, 0xB, 0xA]


# ---------------------------------------------------------------- owned ROM

def test_owned_export(tmp_path):
    d = _owned_rom()
    man = R.export(CACHE / "1fff93531f10c256" / "source.zip", tmp_path)
    assert man["name"] == "Shadow" and man["slot"] == "sonic"
    assert man["frame_count"] == 130
    assert man["max_frame_tiles"] == 27
    assert man["palette"]["line"] == 0 and len(man["palette"]["rgb"]) == 16
    loc = I.locate(d)
    assert man["tables"]["mappings"] == f"0x{loc['mappings']:06x}"
    assert man["tables"]["dplc"] == f"0x{loc['dplc']:06x}"
    assert man["tables"]["art"] == f"0x{loc['art']:06x}"
    assert man["tables"]["palette_index"] == 3
    # animation map: 33 scripts, walk +[0,6,12,18], run +[0,8,16,24]
    an = man["animations"]
    assert an["count"] == 33 and man["tables"]["animations"] == f"0x{loc['animations']:06x}"
    assert an["walk"]["angle_offsets"] == [0, 6, 12, 18]
    assert an["run"]["angle_offsets"] == [0, 8, 16, 24]
    assert an["reachable_frames"] == 119
    assert an["unreachable_frames"] == [30, 31, 32, 33, 34, 41, 42, 43, 44, 45, 74]
    # frame 0 is the empty frame (no PNG), every other frame exports an indexed PNG
    assert man["frames"][0]["pieces"] == [] and man["frames"][0]["png"] is None
    written = [f for f in (tmp_path / "frames").iterdir() if f.name.endswith(".png")]
    assert len(written) == 129
    assert (tmp_path / "frames" / "frame_001.png").is_file()
    # the manifest's pieces + DPLC re-encode byte-identically (import-ready)
    maps, cues = I.mapping_frames(d, loc["mappings"]), I.dplc_frames(d, loc["dplc"])
    for i, fr in enumerate(man["frames"]):
        assert fr["pieces"] == maps[i] and fr["dplc"] == cues[i]
        assert A.encode_frame_map(fr["pieces"]) == A.encode_frame_map(maps[i])
        assert A.encode_frame_dplc(fr["dplc"]) == A.encode_frame_dplc(cues[i])
    # the assembled PNG bytes survive a decode -> re-encode of the table (no-op round trip)
    rt = A.roundtrip(d, loc)
    assert rt["rom_identical"] and rt["art"]["identical"]


def test_owned_nemesis_art():
    _owned_rom()
    art = R.nemesis_art(CACHE / "1fff93531f10c256" / "source.zip")
    by_role = {a["role"]: a for a in art}
    assert len(art) == 7
    assert by_role["Nem_Lives (HUD lives icon)"]["tiles"] == 12
    assert by_role["Nem_SignPost (end-of-act signpost face)"]["tiles"] == 58
    assert by_role["Nem_MiniSonic (special-stage results)"]["tiles"] == 30
    assert by_role["Nem_EndSonic (ending sequence Sonic)"]["tiles"] == 273
    assert by_role["Nem_EndStH (ending SONIC THE HEDGEHOG logo)"]["tiles"] == 48
    assert by_role["Nem_TitleSonic (title screen Sonic)"]["tiles"] == 569
    assert by_role["Nem_ContSonic (continue screen Sonic)"]["tiles"] == 73
    for a in art:
        assert a["decoded_bytes"] == a["tiles"] * 32           # Nemesis decoded to the claimed tile count


def test_owned_extract_run(tmp_path, monkeypatch):
    """characters.extract_dedicated with the sonic1_shadow reader: a valid sprites entry."""
    _owned_rom()
    from types import SimpleNamespace
    from gbox import characters as C, tools
    gid = "1fff93531f10c256"
    monkeypatch.setattr(tools, "rom_path", lambda entry, cfg: CACHE / gid / "source.zip")
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path / "cache"), progress=lambda p, m: None)
    game = {"game_id": gid, "title": "Shadow In Sonic 1", "platform": "genesis",
            "source_paths": ["source.zip"], "format": "zip", "profile_id": "genesis"}
    root = tmp_path / "characters"
    res = C.extract_dedicated(ctx, game, "sonic1_shadow", root)
    assert res["status"] == "extracted" and res["extractor"] == "sonic1_shadow"
    meta = C.get(root, "sonic1_shadow")
    assert meta["kind"] == "sprites" and meta["model"] == "overview.png" and meta["picture"] == "2d"
    assert meta["name"] == "Shadow (Shadow In Sonic 1)"
    assert C.verify_entry(root, meta)["ok"]
    assert (root / "sonic1_shadow" / "frames" / "frame_001.png").is_file()
    assert meta["sonic1_reader"]["game"] == "sonic1" and meta["sonic1_reader"]["character"] == "shadow"


# ------------------------------------------------------------- registration

def test_dedicated_registration():
    from gbox import characters as C
    names = {n for n, *_ in C.DEDICATED}
    assert "sonic1_shadow" in names
    row = next(r for r in C.DEDICATED if r[0] == "sonic1_shadow")
    assert row[1]("shadow in sonic 1", "genesis")
    assert row[1]("shadow the hedgehog in sonic the hedgehog", "genesis")
    assert not row[1]("sonic the hedgehog", "genesis")        # stock Sonic 1 is the sonic2d reader
    assert not row[1]("shadow the hedgehog", "gamecube")      # the standalone Shadow game
    roster = row[2]()
    assert [r["slug"] for r in roster] == ["sonic1_shadow"]
    assert roster[0]["slot"] == "sonic" and roster[0]["key"] == "shadow"


@pytest.mark.parametrize('w,h,idx', [(0,1,b''),(1,0,b''),(1,1,bytes([16]))])
def test_invalid_indexed_png_is_rejected(w,h,idx):
    with pytest.raises(R.ReaderError): R.indexed_png(w,h,idx,[(0,0,0)]*16)


@pytest.mark.parametrize('cues', [[(-1,1)],[(0,2)],[(0,0)]])
def test_invalid_dplc_cues_are_rejected(cues):
    with pytest.raises(R.ReaderError): R._stream_tiles(bytes(32),cues)


def test_missing_streamed_tile_is_not_silently_blank():
    piece = {'x':0,'y':0,'w':1,'h':1,'tile':1,'hflip':False,'vflip':False}
    with pytest.raises(R.ReaderError, match='unstreamed'):
        R.assemble(bytes(32),[piece],[(0,1)])


def test_reader_version_is_registered():
    from gbox import characters as C
    assert C.reader_version('sonic1_shadow') == R.READER_VERSION
    assert not C.reader_status({'sonic1_shadow_reader':R.READER_VERSION}, 'sonic1_shadow')['stale']

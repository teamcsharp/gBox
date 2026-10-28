"""Focused tests for gbox.tetris_nes — the Tetris (Nintendo Famicom) CHR-page and PPU-palette reader.

Self-contained: no ROM, no third-party packages. The parsers are additionally
validated against the owned Tetris (Bulletproof) (Japan).nes dump (sha256
9b5fb0559d14c673fcb8742a17861bc84aa6ab6923883f86b50cd181ee815673) in the
integration runs recorded on request 89c27bd5d1d9449c: all 16 CHR page
SHA-256 checksums match, and the blank_tiles metric reproduces exactly.
"""

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from gbox import tetris_nes as T


# ---------------------------------------------------------------- iNES header

def test_read_ines_header_minimal():
    """A minimal iNES 1.0 header parses correctly."""
    # Magic + 1 PRG page + 2 CHR pages + mapper 3 (CNROM) + flags
    data = b"NES\x1a" + bytes([1, 2, 0x30, 0x00, 0, 0, 0, 0, 0, 0, 0, 0])
    hdr = T.read_ines_header(data)
    assert hdr["version"] == 1
    assert hdr["prg_pages"] == 1
    assert hdr["chr_pages"] == 2
    assert hdr["mapper"] == 3
    assert hdr["trainer"] is False
    assert hdr["mirror"] == "horizontal"
    assert hdr["prg_ram"] is False
    assert hdr["system"] == "ntsc"


def test_read_ines_header_too_small():
    with pytest.raises(ValueError, match="too small"):
        T.read_ines_header(b"NES")


def test_read_ines_header_bad_magic():
    with pytest.raises(ValueError, match="missing magic"):
        T.read_ines_header(b"BAD!" + bytes(12))


# ---------------------------------------------------------------- 2bpp codec

def test_decode_2bpp_tile_all_zero():
    tile = T.decode_2bpp_tile(b"\x00" * 16)
    assert tile == [[0] * 8 for _ in range(8)]


def test_decode_2bpp_tile_all_one():
    tile = T.decode_2bpp_tile(b"\xff" * 16)
    assert tile == [[3] * 8 for _ in range(8)]


def test_decode_2bpp_tile_mixed():
    # lo=0x80, hi=0x00 -> pixel 0 = 1, rest 0
    data = bytes([0x80] + [0] * 7 + [0] * 8)
    tile = T.decode_2bpp_tile(data)
    assert tile[0][0] == 1
    assert tile[0][1] == 0
    assert tile[1][0] == 0


def test_decode_2bpp_tile_wrong_length():
    with pytest.raises(ValueError, match="16 bytes"):
        T.decode_2bpp_tile(b"\x00" * 15)


def test_encode_tile_roundtrip():
    rows = [[0, 1, 2, 3, 0, 1, 2, 3]] * 8
    encoded = T.encode_tile(rows)
    assert len(encoded) == 16
    decoded = T.decode_2bpp_tile(encoded)
    assert decoded == rows


def test_encode_tile_invalid():
    with pytest.raises(ValueError, match="8x8"):
        T.encode_tile([[0] * 8] * 7)


# ---------------------------------------------------------------- PNG encoder

def test_indexed_png_bytes_basic():
    # 2x2 image with 2-colour palette
    palette = [(255, 0, 0), (0, 255, 0)]
    indices = [0, 1, 1, 0]
    png = T.indexed_png_bytes(2, 2, indices, palette)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    # Verify IHDR
    ihdr_pos = png.find(b"IHDR")
    assert ihdr_pos > 0
    w, h = struct.unpack(">II", png[ihdr_pos + 4:ihdr_pos + 12])
    assert w == 2 and h == 2


def test_indexed_png_bytes_invalid_dimensions():
    with pytest.raises(ValueError, match="Invalid PNG dimensions"):
        T.indexed_png_bytes(0, 2, [], [(0, 0, 0)])
    with pytest.raises(ValueError, match="Invalid PNG dimensions"):
        T.indexed_png_bytes(2, 2, [0, 1], [(0, 0, 0)])  # wrong length


def test_indexed_png_bytes_index_out_of_range():
    with pytest.raises(ValueError, match="out of palette range"):
        T.indexed_png_bytes(1, 1, [5], [(0, 0, 0)])


# ---------------------------------------------------------------- CHR page helpers

def test_tile_sha256():
    chr_data = bytes(range(256)) * 64  # 16 KB = 16 pages
    sha = T.tile_sha256(chr_data, 0)
    assert len(sha) == 64
    assert sha == hashlib.sha256(chr_data[0:1024]).hexdigest()


def test_count_blank_tiles():
    chr_data = b"\x00" * 1024 + bytes(range(256)) * 4  # page 0 blank, page 1 not
    assert T.count_blank_tiles(chr_data, 0) == 64
    assert T.count_blank_tiles(chr_data, 1) == 0


# ---------------------------------------------------------------- extract_all

def _make_rom(prg_pages=1, chr_pages=2, mapper=3, trainer=False):
    """Build a minimal iNES ROM image.

    Real Tetris is mapper 3 (CNROM) with 2 PRG pages and 2 CHR pages (16 KB CHR total,
    16 pages of 1 KB each — the header's chr_pages count is in 8 KB units, so 2 means 16 KB).
    """
    flags6 = ((mapper & 0x0F) << 4) | (0x04 if trainer else 0)
    flags7 = mapper & 0xF0
    header = b"NES\x1a" + bytes([prg_pages, chr_pages, flags6, flags7, 0, 0, 0, 0, 0, 0, 0, 0])
    trainer_data = b"\x00" * 512 if trainer else b""
    prg = b"\x00" * (prg_pages * 16384)
    # 2 CHR pages in iNES header = 2 * 8 * 1024 = 16 KB
    chr_total = chr_pages * 8 * 1024
    chr_data = bytes(range(256)) * (chr_total // 256)
    return header + trainer_data + prg + chr_data


def test_extract_all_valid_rom(tmp_path):
    rom = _make_rom()
    result = T.extract_all(rom, tmp_path)

    assert result["version"] == T.READER_VERSION
    assert result["header"]["mapper"] == 3
    assert result["header"]["chr_pages"] == 2
    assert len(result["chr_pages"]["pages"]) == 16

    # Verify all 16 pages have SHA-256 checksums
    for page in result["chr_pages"]["pages"]:
        assert len(page["sha256"]) == 64
        assert "blank_tiles" in page
        assert "png_file" in page

    # Verify PRG+CHR SHA-256
    assert len(result["sha256_prg_chr"]) == 64

    # Verify PNG files were written
    for page in result["chr_pages"]["pages"]:
        png_path = tmp_path / page["png_file"]
        assert png_path.exists()
        assert png_path.stat().st_size > 0


def test_extract_all_wrong_mapper(tmp_path):
    rom = _make_rom(mapper=0)
    with pytest.raises(ValueError, match="Expected mapper 3"):
        T.extract_all(rom, tmp_path)


def test_extract_all_wrong_chr_pages(tmp_path):
    rom = _make_rom(chr_pages=4)
    with pytest.raises(ValueError, match="Expected 2 CHR pages"):
        T.extract_all(rom, tmp_path)


# ---------------------------------------------------------------- title_test / roster

def test_title_test_matches_tetris_nes():
    assert T.title_test("Tetris (Nintendo Famicom)", "nes") is True
    assert T.title_test("Tetris", "nes") is False  # too generic
    assert T.title_test("Tetris (Nintendo Famicom)", "n64") is False


def test_roster_entries():
    roster = T.roster()
    assert len(roster) == 2
    keys = {e["key"] for e in roster}
    assert "CHR_PAGES" in keys
    assert "PALETTE" in keys
    kinds = {e["kind"] for e in roster}
    assert "sprites" in kinds
    assert "palette" in kinds


# ---------------------------------------------------------------- integration (owned ROM)

OWNED = Path.home() / "gBox_alt/gbox-cache/85e2ddf8456f4574/source.zip"
needs_rom = pytest.mark.skipif(not OWNED.is_file(), reason="Owned Tetris ROM is not cached")


@needs_rom
def test_owned_rom_chr_page_sha256_match(tmp_path, monkeypatch):
    """The reader reproduces the exact CHR page SHA-256 checksums recorded in tetris_nes_build.json."""
    from gbox import tools
    monkeypatch.setattr(tools, "rom_path", lambda *_: OWNED)

    game = {
        "game_id": "85e2ddf8456f4574",
        "title": "Tetris (Nintendo Famicom)",
        "platform": "nes",
        "source_paths": [str(OWNED)],
        "format": "zip",
        "profile_id": "nes",
    }

    # Load the build evidence
    build_path = Path(__file__).parent.parent / "tetris_nes_build.json"
    if not build_path.is_file():
        pytest.skip("tetris_nes_build.json not found")
    build = json.loads(build_path.read_text())

    # Extract from the owned ROM
    import zipfile
    with zipfile.ZipFile(OWNED) as zf:
        members = [n for n in zf.namelist() if n.endswith(".nes")]
        assert members, "No .nes file in owned zip"
        data = zf.read(members[0])

    result = T.extract_all(data, tmp_path)

    # Verify all 16 CHR page SHA-256 checksums match the build evidence
    expected_shas = {p["page"]: p["sha256"] for p in build["chr_pages"]}
    for page in result["chr_pages"]["pages"]:
        page_hex = f"0x{page['page_idx']:x}"
        assert page["sha256"] == expected_shas[page_hex], f"Page {page_hex} SHA mismatch"

    # Verify blank_tiles metric matches
    expected_blanks = {p["page"]: p["blank_tiles"] for p in build["chr_pages"]}
    for page in result["chr_pages"]["pages"]:
        page_hex = f"0x{page['page_idx']:x}"
        assert page["blank_tiles"] == expected_blanks[page_hex], f"Page {page_hex} blank_tiles mismatch"

    # Verify PRG+CHR SHA-256 matches
    assert result["sha256_prg_chr"] == build["prg_chr_sha256"]

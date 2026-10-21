import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from gbox import smb3_sprites as S, smb3_inventory as I, characters as C, tools


def test_known_bitplanes_and_invalid_edit_indices():
    rows = [[0,1,2,3,0,1,2,3]]*8
    assert S.encode_tile(rows) == bytes([0x55]*8+[0x33]*8)
    assert I.tile(S.encode_tile(rows), 0) == rows
    for bad in ([[4]*8]*8, [[-1]*8]*8, [[0]*7]*8, [[0]*8]*7):
        with pytest.raises(ValueError): S.encode_tile(bad)


def test_indexed_png_preserves_indices_and_selected_transparency():
    data = S.indexed_png_bytes(2, 2, bytes([0,1,2,3]), S.ATLAS_PALETTE, transparent=2)
    image = Image.open(io.BytesIO(data))
    assert list(image.getdata()) == [0,1,2,3]
    assert [p[3] for p in image.convert('RGBA').getdata()] == [255,255,0,255]
    for w,h,idx in ((0,1,b''),(2,2,b'123'),(1,1,bytes([4]))):
        with pytest.raises(ValueError): S.indexed_png_bytes(w,h,idx,S.ATLAS_PALETTE)


def test_owned_collection_paths_and_native_tile_identity(tmp_path, monkeypatch):
    source = Path.home()/'gBox_alt/gbox-cache/213e4208929ec3e9/source.zip'
    if not source.is_file(): pytest.skip('Owned SMB3 ROM is not cached')
    monkeypatch.setattr(tools, 'rom_path', lambda *_: source)
    game = {'game_id':'213e4208929ec3e9','title':'Super Mario Bros. 3 (USA)','platform':'nes',
            'source_paths':[str(source)],'format':'zip','profile_id':'nes'}
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path/'cache'),progress=lambda *_:None)
    root = tmp_path/'characters'
    result = C.extract_dedicated(ctx, game, 'smb3_mario', root)
    assert result['status'] == 'extracted' and result['extractor'] == 'smb3'
    meta = C.get(root,'smb3_mario')
    assert C.verify_entry(root,meta)['ok'] and meta['kind'] == 'sprites'
    assert meta['smb3']['frame_map'] == 'frames.json'
    frame_map = json.loads((root/'smb3_mario'/meta['smb3']['frame_map']).read_text())
    assert frame_map['roundtrip']['byte_identical'] and frame_map['roundtrip']['checked'] > 0
    assert frame_map['sheet']['frames'] == 81 and len(frame_map['suits']) == 7
    for suit in frame_map['suits'].values():
        image = Image.open(root/'smb3_mario'/suit['sheet'])
        assert image.mode == 'P' and image.size == (216,288)
    assert C.reader_version('smb3') == S.READER_VERSION
    assert not C.reader_status(meta, 'smb3')['stale']


def test_every_chr_page_sheet_is_tile_exact():
    """#2799: the every-sprite-and-tile entry lays out all CHR pages; each 8x8 cell is the page's tile verbatim."""
    ex = object.__new__(S.SMB3Sprites)
    chr_ = bytearray(I.CHR_PAGE * 18)                 # 18 pages: two sheet rows
    for page in range(18):
        for t in range(64):
            rows = [[(page + t + x + y) % 4 for x in range(8)] for y in range(8)]
            chr_[(page * 64 + t) * 16:(page * 64 + t) * 16 + 16] = S.encode_tile(rows)
    ex.chr = bytes(chr_)
    assert ex.page_count() == 18
    image = Image.open(io.BytesIO(ex.all_pages_png()))
    assert image.size == (S.ALL_COLS * 64, 2 * 64) and image.mode == 'P'
    px = image.load()
    for page, t in ((0, 0), (5, 63), (17, 9)):
        ox, oy = (page % S.ALL_COLS) * 64 + (t % 8) * 8, (page // S.ALL_COLS) * 64 + (t // 8) * 8
        assert [[px[ox + x, oy + y] for x in range(8)] for y in range(8)] == I.tile(ex.chr, page * 64 + t)


def test_roster_offers_every_sprite_and_tile():
    keys = {e['key']: e for e in S.roster()}
    assert keys['MARIO']['slug'] == 'smb3_mario'
    assert keys['ALL']['slug'] == 'smb3_all_tiles' and keys['ALL']['kind'] == 'sprites'

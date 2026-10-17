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
    source = Path.home()/'gbox-cache/213e4208929ec3e9/source.zip'
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

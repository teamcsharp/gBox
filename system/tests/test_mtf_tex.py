"""TEX storage, native BC7 encoding, and real-fixture checks without game writes."""
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from gbox import mt_arc, mtf_tex as T


def fixture(fmt=0x30):
    # Measured 32x32 BC7 Switch storage: 1024 bytes for mip0, then one
    # 512-byte GOB each for16x16,8x8,4x4,2x2,1x1. Nonzero padding sentinel.
    offsets = (0, 1024, 1536, 2048, 2560, 3072)
    header = b'TEX\0\xa1\x80\0\x20' + struct.pack('<3I', 6 | 32<<6 | 32<<19,
        0x10001 | fmt<<8, 3584) + struct.pack('<6I', *offsets)
    return header + bytes((n*37+13)%256 for n in range(3584))


def test_known_tegra_gob_offsets_and_mip_layout():
    tex = T.parse(fixture())
    assert [(m.width, m.height, m.offset, m.size, m.block_height) for m in tex.mips] == [
        (32,32,44,1024,1), (16,16,1068,512,1), (8,8,1580,512,1),
        (4,4,2092,512,1), (2,2,2604,512,1), (1,1,3116,512,1)]
    # Known hardware sector order, including a second GOB column and row.
    addresses = T._addresses(T.Mip(512,512,0,262144,16),16).reshape(128,128,16)
    assert addresses[0,:5,0].tolist() == [0,32,256,288,8192]
    assert addresses[:9,0,0].tolist() == [0,16,64,80,128,144,192,208,512]
    assert addresses[64,4,0] == 12288


def test_replacing_one_mip_preserves_header_other_mips_and_every_padding_byte():
    original = fixture()
    tex = T.parse(original)
    for i, mip in enumerate(tex.mips):
        linear = T.linear_blocks(original,i)
        assert T.replace_blocks(original,linear,i) == original
        changed = T.replace_blocks(original,bytes(b^255 for b in linear),i)
        addresses = set((T._addresses(mip,16)+mip.offset).flat)
        assert {n for n,(a,b) in enumerate(zip(original,changed)) if a != b} == addresses
        assert len(changed) == len(original)
        assert T.parse(changed) == tex


@pytest.mark.parametrize('offset,value', [(4,0), (12,6), (13,0xFF), (14,2), (8,0), (20,8), (24,512)])
def test_unmeasured_or_damaged_layout_is_rejected(offset,value):
    data = bytearray(fixture())
    if offset in (20,24):
        struct.pack_into('<I',data,offset,value)
    else:
        data[offset] = value
    with pytest.raises(ValueError):
        T.parse(bytes(data))


def test_bad_lengths_indices_and_dimensions_are_rejected():
    original = fixture()
    for data in (original[:-1], original+b'\0', original[:30]):
        with pytest.raises(ValueError):
            T.parse(data)
    for mip in (-1,6):
        with pytest.raises(ValueError):
            T.decode(original,mip)
    with pytest.raises(ValueError,match='byte count'):
        T.replace_blocks(original,b'bad')
    with pytest.raises(ValueError,match='dimensions'):
        T.replace_image(original,Image.new('RGBA',(16,16)))


@pytest.mark.parametrize('fmt',[0x30,0x31])
def test_bc7_cpu_encode_all_mips_preserves_alpha_header_and_padding(fmt):
    pytest.importorskip('ispc_texcomp')
    original = fixture(fmt)
    # Flat RGBA exercises all levels including sub-block mips. Alpha must
    # survive the encoder profile; edge padding must not blacken tiny levels.
    image = Image.new('RGBA',(32,32),(23,114,231,73))
    replaced = T.replace_image(original,image)
    tex = T.parse(replaced)
    assert len(replaced) == len(original)
    assert replaced[:tex.data_offset] == original[:tex.data_offset]
    covered = set()
    for i,mip in enumerate(tex.mips):
        pixels = np.asarray(T.decode(replaced,i)).astype(int)
        assert pixels.shape == (mip.height,mip.width,4)
        assert np.abs(pixels - (23,114,231,73)).max() <= 3
        covered.update((T._addresses(mip,16)+mip.offset).flat)
    assert all(a == b for i,(a,b) in enumerate(zip(original,replaced)) if i not in covered)


def test_bc7_image_quadrants_keep_orientation_and_channel_order():
    pytest.importorskip('ispc_texcomp')
    pixels = np.zeros((32,32,4),dtype=np.uint8)
    colors = [(255,0,0,255), (0,255,0,192), (0,0,255,128), (190,130,80,64)]
    for (x,y),color in zip(((0,0),(16,0),(0,16),(16,16)),colors):
        pixels[y:y+16,x:x+16] = color
    decoded = np.asarray(T.decode(T.replace_image(fixture(),Image.fromarray(pixels))))
    assert np.abs(decoded.astype(int)-pixels).max() <= 3


def test_encoder_dependency_error_is_actionable(monkeypatch):
    monkeypatch.setitem(sys.modules,'ispc_texcomp',None)
    with pytest.raises(RuntimeError,match=r'gbox\[textures\]'):
        T.replace_image(fixture(),Image.new('RGBA',(32,32)))


def test_real_uem10_all_texture_mips_roundtrip_when_local_asset_exists():
    source = Path(__file__).resolve().parents[2] / '.scratch-merc-recovery/assets/uEm10.arc'
    if not source.is_file():
        pytest.skip('optional local owned-game fixture is absent')
    count = 0
    for entry in mt_arc.parse(source.read_bytes()).entries:
        try:
            data = zlib.decompress(entry.data)
        except zlib.error:
            continue
        if not data.startswith(b'TEX\0'):
            continue
        tex = T.parse(data)
        for i in range(len(tex.mips)):
            assert T.replace_blocks(data,T.linear_blocks(data,i),i) == data, entry.name
        count += 1
    assert count == 196

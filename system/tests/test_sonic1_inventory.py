import hashlib
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import sonic1_inventory as s1

REAL = Path.home() / 'gBox_alt/gbox-cache/1fff93531f10c256/source.zip'


def _synthetic_rom() -> bytes:
    d = bytearray(0x10000)
    d[0x100:0x110] = b'SEGA MEGA DRIVE '
    d[0x150:0x180] = b'SHADOW THE HEDGEHOG IN SONIC THE HEDGEHOG'.ljust(48)
    d[0x180:0x18e] = b'GM 00001009-00'
    d[0x1a0:0x1a8] = struct.pack('>II', 0, len(d) - 1)
    MAP, DPLC, ART, ANI, PALT, PAL = 0x8000, 0x8400, 0x9000, 0x8800, 0x8a00, 0x8b00
    # LoadSonicDynPLC (DMA-queue variant)
    d[0x1000:0x1000 + 30] = (b'\x45\xf9' + struct.pack('>I', DPLC) + b'\xd0\x40\xd4\xf2\x00\x00'
                             b'\x7a\x00\x1a\x1a\x53\x45\x6b\x36\x38\x3c\xf0\x00\x2c\x3c'
                             + struct.pack('>I', ART))
    # Sonic_Main: move.l #Map_Sonic,obMap(a0) ; move.w #$780,obGfx(a0)
    d[0x1100:0x110e] = b'\x21\x7c' + struct.pack('>I', MAP) + b'\x00\x04\x31\x7c\x07\x80\x00\x02'
    d[0x1200:0x120c] = b'\x43\xf9' + struct.pack('>I', ANI) + b'\x70\x00\x10\x28\x00\x1c'
    d[0x1300:0x1310] = b'\x43\xf9' + struct.pack('>I', PALT) + b'\xe7\x48\xd2\xc0\x24\x59\x36\x59\x3e\x19'
    d[PALT:PALT + 16] = struct.pack('>IHHIHH', 0x8c00, 0xFB00, 0x1F, PAL, 0xFB00, 7)
    d[PAL:PAL + 32] = struct.pack('>16H', *[(i & 7) << 1 for i in range(16)])
    # 2 frames: null, then one 2x2 piece using 4 tiles loaded from art tiles 3..6
    d[MAP:MAP + 4] = struct.pack('>HH', 4, 5)        # byte-packed: odd offset
    d[MAP + 4] = 0
    d[MAP + 5:MAP + 11] = bytes([1, 0xF0, 0x05, 0x00, 0x00, 0xF8])
    d[DPLC:DPLC + 4] = struct.pack('>HH', 4, 5)
    d[DPLC + 4] = 0
    d[DPLC + 5:DPLC + 8] = bytes([1]) + struct.pack('>H', (3 << 12) | 3)
    for t in range(7):
        d[ART + 32 * t:ART + 32 * t + 32] = bytes([(t + 1) * 0x11]) * 32
    d[ANI:ANI + 2] = struct.pack('>H', 2)
    d[ANI + 2:ANI + 6] = bytes([5, 1, 1, 0xFF])
    n = (len(d) - 0x200) // 2
    d[0x18e:0x190] = struct.pack('>H', sum(struct.unpack(f'>{n}H', d[0x200:])) & 0xFFFF)
    return bytes(d)


def test_synthetic_layout_found_through_code(tmp_path):
    rom = tmp_path / 'hack.bin'
    rom.write_bytes(_synthetic_rom())
    man = s1.inventory(rom, str(tmp_path / 'sheet.png'))
    p = man['player']
    assert man['header']['checksum_ok']
    assert (p['mappings'], p['dplc'], p['art']) == ('0x008000', '0x008400', '0x009000')
    assert p['frames'] == 2 and p['art_tiles'] == 7 and p['max_frame_tiles'] == 4
    assert p['palette'] == '0x008b00' and p['palette_index'] == 1
    assert p['animation_count'] == 1 and man['animations'][0]['frames'] == [1, 1]
    assert p['name'] == 'Shadow' and man['roster'][0]['slot'] == 'sonic'
    sheet = (tmp_path / 'sheet.png').read_bytes()
    assert sheet[:8] == b'\x89PNG\r\n\x1a\n'
    assert man['sheet']['sha256'] == hashlib.sha256(sheet).hexdigest()


def test_render_uses_dplc_order_and_column_major_tiles():
    rom = _synthetic_rom()
    maps = s1.mapping_frames(rom, 0x8000)
    cues = s1.dplc_frames(rom, 0x8400)
    assert cues[1] == [(3, 4)]
    pal = [(i, i, i) for i in range(16)]
    x0, y0, w, h, px = s1.render_frame(rom[0x9000:0x9000 + 7 * 32], maps[1], cues[1], pal)
    assert (x0, y0, w, h) == (-8, -16, 16, 16)
    pix = lambda x, y: px[(y * w + x) * 4]
    # buffer tile 0 = art tile 3 (colour 4) top-left, tile 1 = art 4 below it
    assert (pix(0, 0), pix(0, 8), pix(8, 0), pix(8, 8)) == (4, 5, 6, 7)


def test_zip_and_smd_containers(tmp_path):
    raw = _synthetic_rom()
    z = tmp_path / 'g.zip'
    with zipfile.ZipFile(z, 'w') as f:
        f.writestr('Game.bin', raw)
    d, info = s1.read_rom(z)
    assert d == raw and info['member'] == 'Game.bin'
    body = bytearray()
    for b in range(0, len(raw), 16384):
        blk = raw[b:b + 16384]
        body += blk[1::2] + blk[0::2]
    smd = tmp_path / 'g.smd'
    smd.write_bytes(b'\0' * 512 + bytes(body))
    d2, info2 = s1.read_rom(smd)
    assert d2 == raw and info2['interleaved']


def test_missing_loader_is_an_error(tmp_path):
    rom = bytearray(_synthetic_rom())
    rom[0x1000:0x1002] = b'\0\0'
    (tmp_path / 'x.bin').write_bytes(bytes(rom))
    with pytest.raises(s1.InventoryError):
        s1.inventory(tmp_path / 'x.bin')


@pytest.mark.skipif(not REAL.exists(), reason='owned ROM not cached')
def test_owned_shadow_in_sonic1_build():
    man = s1.inventory(REAL)
    assert man['source']['rom_sha256'] == 'a22564d49d28bfab70e2046b1c08d7a6a19f6bf4183491e0280ef916fb4863ce'
    p = man['player']
    assert (p['mappings'], p['dplc'], p['art']) == ('0x0226da', '0x0232f2', '0x0238b2')
    assert (p['frames'], p['art_tiles'], p['animation_count']) == (130, 2465, 33)
    assert p['art_sha256'] == 'a564a06f2cda880b0d302cf3aafa0dbe5582bf49bd0794f015b9f8d5203306ce'

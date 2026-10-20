"""Tests for gbox.sonic1_analysis: Sonic 1 player writer constraints and the
byte-identical Map/DPLC/Art re-encoder (Shadow In Sonic 1, #1327)."""
import os
import struct
from pathlib import Path

import pytest

from gbox import sonic1_analysis as A
from gbox import sonic1_inventory as I

ROM = Path(os.environ.get('GBOX_SHADOW_SONIC1_SRC', Path.home() / 'gBox_alt/gbox-cache/1fff93531f10c256/source.zip'))
ROM_SHA = 'a22564d49d28bfab70e2046b1c08d7a6a19f6bf4183491e0280ef916fb4863ce'


def _piece(**kw):
    p = {'x': -8, 'y': -16, 'w': 2, 'h': 3, 'tile': 0, 'hflip': False, 'vflip': False,
         'pal': 0, 'pri': False}
    p.update(kw)
    return p


def test_mapping_table_roundtrip_keeps_odd_offsets_and_shared_frames():
    maps = [[], [_piece()], [_piece(tile=6, hflip=True, vflip=True, pal=1, pri=True,
                                    x=5, y=-3, w=1, h=4)], [_piece()]]
    share = {3: 1}
    tbl = A.encode_table([A.encode_frame_map(f) for f in maps], share)
    offs = struct.unpack('>4H', tbl[:8])
    assert offs == (8, 9, 15, 9)            # empty frame 0 is 1 byte: frame 1 is odd
    rom = b'\x00' * 16 + tbl + b'\x00' * 16
    assert I.mapping_frames(rom, 16) == maps
    addrs, end, sh = A.table_span(rom, 16, 5)
    assert (end, sh) == (16 + len(tbl), share)
    again = A.encode_table([A.encode_frame_map(f) for f in I.mapping_frames(rom, 16)], sh)
    assert again == tbl
    with pytest.raises(A.AnalysisError):
        A.encode_frame_map([_piece(w=5)])


def test_dplc_entries_obey_the_dma_loader_limits():
    cues = [[(0, 16), (0x10, 3)], [(0xFFF, 1)]]
    tbl = A.encode_table([A.encode_frame_dplc(c) for c in cues])
    assert I.dplc_frames(tbl + b'\x00', 0) == cues
    for bad in ([(0, 17)], [(0x1000, 1)], [(0, 0)]):
        with pytest.raises(A.AnalysisError):
            A.encode_frame_dplc(bad)


def test_tiles_unpack_and_pack_roundtrip():
    art = bytes(range(256)) * 2
    px = A.unpack_tiles(art)
    assert len(px) == 16 and px[0][:4] == bytes([0, 0, 0, 1])
    assert A.pack_tiles(px) == art
    with pytest.raises(A.AnalysisError):
        A.pack_tiles([bytes([16]) * 64])


def test_checksum_follows_the_boot_loop_and_fix_writes_header():
    rom = bytearray(0x400)
    rom[0x1A4:0x1A8] = struct.pack('>I', 0x3FF)
    rom[0x200:0x204] = b'\x12\x34\x00\x01'
    rom[0x3FE:0x400] = b'\xff\xff'
    assert A.checksum(rom) == (0x1234 + 1 + 0xFFFF) & 0xFFFF
    c = A.fix_checksum(rom)
    assert rom[0x18E:0x190] == struct.pack('>H', c) and A.checksum(rom) == c


def test_angle_offsets_are_simulated_from_the_animate_code():
    walk = bytes.fromhex('1200e209d001d000600000021600')   # S1 walk path + bra.w
    run = bytes.fromhex('d000d0001600')                     # this hack's run path
    assert A._sim_offsets(walk, 0) == [0, 6, 12, 18]
    assert A._sim_offsets(run, 0) == [0, 8, 16, 24]
    with pytest.raises(A.AnalysisError):
        A._sim_offsets(bytes.fromhex('4e751600'), 0)


@pytest.mark.skipif(not ROM.exists(), reason='owned Shadow In Sonic 1 ROM is not cached')
def test_owned_rom_writer_constraints_and_noop_roundtrip():
    r = A.analyze(ROM)
    assert r['rom_sha256'] == ROM_SHA
    rt = r['roundtrip']
    assert all(rt[k]['identical'] for k in ('mappings', 'dplc', 'art'))
    assert rt['rom_identical'] and rt['rom_sha256'] == ROM_SHA and r['checksum_ok']
    assert (rt['mappings']['end'], rt['dplc']['end'], rt['art']['end']) == (
        '0x0232f1', '0x0238b2', '0x036cd2')
    f = r['functions']
    assert (f['QueueDMATransfer'], f['Sonic_Animate'], f['LoadSonicDynPLC'], f['NemDec']) == (
        '0x001398', '0x0141c4', '0x01447c', '0x001428')
    assert '0x01c44c' in f['LoadSonicDynPLC_callers']       # special-stage Sonic, jsr d16(pc)
    dq = r['dma_queue']
    assert (dq['buffer'], dq['entry_bytes'], dq['capacity']) == ('0xffc800', 14, 18)
    assert dq['tiles_per_entry_max'] == 16 and dq['entries_crossing_128k'] == []
    # The hack's own effect object (obGfx $7A0, move.w #$F400,$3C(a0) at 0x12e9c)
    # streams an S2-format DPLC into $F400: the level buffer is 32 tiles, not 50.
    (o,) = dq['other_users']
    assert (o['site'], o['dplc'], o['art'], o['count_bytes'], o['max_tiles']) == (
        '0x01303a', '0x013128', '0x08b6f6', 2, 16)
    assert (o['vram_field'], o['vram_candidates']) == (0x3C, ['f400'])
    v = r['vram']
    assert (v['sprite_table'], v['hard_limit_tiles'], v['special_stage_limit_tiles']) == (
        'f800', 64, 23)
    assert (v['level_limit_vram'], v['level_limit_tiles']) == ('f400', 32)
    assert v['max_frame_tiles_now'] == 27 <= v['level_limit_tiles']
    assert v['frames_over_level_limit'] == []
    an = r['animation']
    assert an['max_frame_id'] == 0xEF and an['out_of_range'] == []
    assert an['walk']['angle_offsets'] == [0, 6, 12, 18]
    assert an['run']['angle_offsets'] == [0, 8, 16, 24]
    ss = [m for m in an['mapping_refs'] if m['site'] == '0x01c1e2'][0]
    assert ss['init_anim'] == 2 and ss['max_tiles'] <= v['special_stage_limit_tiles']
    pal = r['palette']
    assert pal['player_piece_lines'] == [0]
    assert {e['name'] for e in pal['line0_writers'] if e['line0_equals_pal_sonic']} == {
        'Sonic', 'Special', 'Ending'}
    assert [len(r['pointer_sites'][k]) for k in ('mappings', 'dplc', 'art')] == [6, 1, 1]
    roles = {u['role'].split()[0] for u in r['sonic_art_users']}
    assert {'Nem_TitleSonic', 'Nem_ContSonic', 'Nem_MiniSonic', 'Nem_SignPost', 'Nem_Lives',
            'Nem_EndSonic'} <= roles
    assert r['free_space']['start'] == '0x08d036'
    d = I.read_rom(ROM)[0]
    same = A.sonic_art_users(d, A.plc_lists(d)[1], A.nemesis_loads(d)[1], stock=d)
    assert same and all(u['stock_prefix_match'] for u in same)

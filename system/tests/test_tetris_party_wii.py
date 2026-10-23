"""Focused tests for the Tetris Party Deluxe (USA) Wii unlock research module."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import game_unlocks
from gbox import tetris_party_wii as tpd


def _dol_header(segments, bss_addr=0x804C6000, bss_size=0xF42CC, entry=0x80006310) -> bytes:
    """A minimal ELFDOL header for the given segments."""
    head = bytearray(0xE4)
    text = [s for s in segments if s[0] == 'text']
    data = [s for s in segments if s[0] == 'data']
    for i, s in enumerate(text):
        struct.pack_into('>I', head, 0x00 + 4 * i, s[2])
    for i, s in enumerate(data):
        struct.pack_into('>I', head, 0x1C + 4 * i, s[2])
    for i, s in enumerate(text):
        struct.pack_into('>I', head, 0x48 + 4 * i, s[3])
    for i, s in enumerate(data):
        struct.pack_into('>I', head, 0x64 + 4 * i, s[3])
    for i, s in enumerate(text):
        struct.pack_into('>I', head, 0x90 + 4 * i, s[4])
    for i, s in enumerate(data):
        struct.pack_into('>I', head, 0xAC + 4 * i, s[4])
    struct.pack_into('>I', head, 0xD8, bss_addr)
    struct.pack_into('>I', head, 0xDC, bss_size)
    struct.pack_into('>I', head, 0xE0, entry)
    return bytes(head)


def test_pinned_revision_is_complete():
    for digest in (tpd.WBFS_SHA256, tpd.MAIN_DOL_SHA256):
        assert len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
    assert tpd.WBFS_SIZE == 60817408
    assert tpd.MAIN_DOL_SIZE == 5010592
    assert tpd.DISC_GAMECODE == 'STEE'
    assert tpd.TITLE_ID == '4fb00410ea31f649'
    assert tpd.GAME_ID == '6ad5e998536407a3'
    assert tpd.PLATFORM == 'wii'


def test_pinned_segments_are_inside_the_executable():
    for kind, index, file_offset, vaddr, size in tpd.DOL_SEGMENTS:
        assert size > 0
        assert file_offset + size <= tpd.MAIN_DOL_SIZE, (kind, index)
        assert 0x80000000 <= vaddr < 0x81000000, (kind, index)


def test_dol_header_round_trip():
    parsed = tpd.parse_dol_header(_dol_header(tpd.DOL_SEGMENTS))
    assert parsed['entry'] == tpd.DOL_ENTRY
    assert parsed['bss_addr'] == tpd.DOL_BSS_ADDR
    assert parsed['bss_size'] == tpd.DOL_BSS_SIZE
    assert len(parsed['segments']) == len(tpd.DOL_SEGMENTS)
    assert [(x['kind'], x['index'], x['file_offset'], x['vaddr'], x['size'])
            for x in parsed['segments']] == [tuple(s) for s in tpd.DOL_SEGMENTS]


def test_vaddr_and_file_mapping_agree():
    for kind, index, file_offset, vaddr, size in tpd.DOL_SEGMENTS:
        assert tpd.vaddr_to_file(vaddr) == file_offset
        assert tpd.file_to_vaddr(file_offset) == vaddr
        inside = vaddr + size - 4
        assert tpd.vaddr_to_file(inside) == file_offset + size - 4
    # the pinned save-name string address maps into a loaded section
    assert tpd.vaddr_to_file(tpd.SAVE_NAME_VADDR) is not None
    # an address that is not loaded has no file offset
    assert tpd.vaddr_to_file(0x7F000000) is None
    assert tpd.file_to_vaddr(tpd.MAIN_DOL_SIZE) is None


def test_find_ascii_reports_offsets_and_addresses():
    blob = bytearray(b'\x00' * 64)
    blob[16:16 + len(tpd.SAVE_FILE_NAME)] = tpd.SAVE_FILE_NAME.encode()
    hits = tpd.find_ascii(bytes(blob), tpd.SAVE_FILE_NAME.encode())
    assert hits and hits[0]['offset'] == 16
    assert hits[0]['vaddr'] is None or isinstance(hits[0]['vaddr'], int)


def test_save_template_records_decode():
    body = bytearray(b'\x00' * tpd.SAVE_TEMPLATE_HEADER_SIZE)
    body += bytes([0x81, 0x74, 0x81, 0x74])
    body += bytes([0x81, 0x95, 0x81, 0x95])
    body += bytes([0x00, 0x00, 0x00, 0x00])
    records = tpd.save_tpl_records(bytes(body))
    assert len(records) == 3
    assert records[0]['offset'] == tpd.SAVE_TEMPLATE_HEADER_SIZE
    assert records[0]['high_bit_set'] is True
    assert records[0]['b1'] == 0x74
    assert records[1]['b1'] == 0x95
    assert records[2]['high_bit_set'] is False
    summary = tpd.record_summary(records)
    assert summary['records'] == 3
    assert summary['populated'] == 2
    assert summary['distinct_second_bytes'] == [0x00, 0x74, 0x95]


def test_save_template_too_short_is_refused():
    try:
        tpd.save_tpl_records(b'\x00' * 16)
    except ValueError:
        return
    raise AssertionError('a truncated save template must be refused')


def test_gate_is_honest_and_complete():
    gate = tpd.profile_gate()
    assert gate['verified'] is False
    assert gate['blockers'] and gate['next']
    assert set(tpd.CATEGORIES) <= set(gate['categories'])
    assert gate['evidence']['save_file'] == tpd.SAVE_FILE_NAME
    plan = tpd.save_file_plan()
    assert plan['save_file'] == tpd.SAVE_FILE_NAME
    assert plan['record_size'] == tpd.SAVE_RECORD_SIZE


def test_play_path_reports_research_pending_and_writes_nothing():
    game = {'game_id': tpd.GAME_ID, 'platform': tpd.PLATFORM, 'title': tpd.GAME_TITLE}
    profile = game_unlocks.profile_for(game)
    assert profile['verified'] is False
    assert profile['status'] == 'pending_research'
    hook = getattr(game_unlocks, 'pre_launch', None)
    if hook is not None:
        try:
            result = hook(game, None)
        except TypeError:
            result = hook(game)
        assert not result.get('applied')
        assert 'research' in str(result).lower() or result.get('status') == 'pending_research'

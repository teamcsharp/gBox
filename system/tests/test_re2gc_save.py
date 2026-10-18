import json
import os
from pathlib import Path
import struct

import pytest

from gbox import re2gc_save as save
from gbox.re2gc_state import Build, sha


def gci(*, character=0, flags=0, awards=0, family=' ', slot=0):
    """Synthetic envelope only; never a claimed playable save fixture."""
    data = bytearray(0x2040)
    data[:6] = b'GHAE08'
    name = f'RESIDENTEVIL2{family}-{slot:02d}'.encode('ascii')
    data[8:8 + len(name)] = name
    struct.pack_into('>H', data, 0x38, 1)
    # Known vector: the 0x1ffc bytes are zero except explicitly set fields.
    data[0x40 + 0x180a] = character
    struct.pack_into('>I', data, 0x40 + 0x1814, flags)
    struct.pack_into('>I', data, 0x40 + 0x1b88, awards)
    data[0x40 + 0x1cde] = 3
    refresh(data)
    return data


def refresh(data):
    checksum = 0
    for value in data[0x40:0x203c]:
        checksum += value
    struct.pack_into('>I', data, 0x203c, checksum)


@pytest.mark.parametrize('character,flags,route', [
    (0, 0, 'ordinary'), (1, 0x40000000, 'ordinary'),
    (0x0c, 0, 'hunk'), (0x0d, 0, 'tofu'), (0x10, 0x4000, 'extreme_battle'),
    (0x0c, 0x4000, 'hunk'), (0x0d, 0x4000, 'tofu'),
])
def test_native_dispatch_priority_is_only_a_route_not_playability(character, flags, route):
    data = gci(character=character, flags=flags)
    before = bytes(data)
    report = save._inspect_gci(memoryview(data))
    assert report['native_load_route'] == route
    assert report['saved_character'] == character
    assert report['saved_system_flags'] == f'{flags:08x}'
    assert report['progression_counter'] == 3
    assert not report['gameplay_verified'] and not report['complete_unlocks_verified']
    assert not report['save_writer_available']
    assert bytes(data) == before


def test_award_records_do_not_masquerade_as_playable_modes():
    report = save._inspect_gci(gci(awards=0x1c00))
    assert report['award_records'] == {'hunk': True, 'tofu': True, 'extreme_battle': True}
    assert report['native_load_route'] == 'ordinary'
    assert report['clear_flag_words'] == ['00001c00', '00000000']
    assert not report['complete_unlocks_verified']
    assert any('suppress' in text for text in report['limits'])


@pytest.mark.parametrize('word,expected', [(0x1000, 'hunk'), (0x800, 'tofu'), (0x400, 'extreme_battle')])
def test_native_msb_first_award_bits(word, expected):
    report = save._inspect_gci(gci(awards=word))
    assert [name for name, value in report['award_records'].items() if value] == [expected]


@pytest.mark.parametrize('offset', [0x40, 0x40 + 0x1600, 0x40 + 0x180a, 0x203b, 0x203f])
def test_corruption_anywhere_in_checked_card_file_rejected(offset):
    data = gci(); data[offset] ^= 1
    with pytest.raises(ValueError, match='checksum mismatch'):
        save._inspect_gci(data)


def test_checksum_is_big_endian_byte_sum_excluding_gci_header_and_stored_word():
    data = gci(); data[0x40:0x203c] = bytes([255]) * 8188
    struct.pack_into('>I', data, 0x203c, 2087940)
    report = save._inspect_gci(data)
    assert report['native_checksum']['calculated'] == 2087940
    # Non-identity directory metadata is outside the native checksum.
    data[0x28:0x2c] = b'ABCD'
    assert save._inspect_gci(data)['native_checksum']['stored'] == 2087940
    struct.pack_into('<I', data, 0x203c, 2087940)
    with pytest.raises(ValueError, match='checksum mismatch'):
        save._inspect_gci(data)


@pytest.mark.parametrize('size', [0, 0x2000, 0x203f, 0x2041, 0x4040])
def test_only_exact_one_block_gci_is_supported(size):
    with pytest.raises(ValueError, match='size'):
        save._inspect_gci(bytes(size))


@pytest.mark.parametrize('field,value,error', [
    (0, b'GHAJ', 'identity'), (4, b'01', 'identity'),
    (0x38, b'\0\0', 'one card block'), (0x38, b'\0\2', 'one card block'),
    (8, b'NOTRE2', 'filename'), (8, b'RESIDENTEVIL2 -15', 'slot'),
    (8, b'RESIDENTEVIL2 -AA', 'filename'),
])
def test_identity_and_directory_size_rejections(field, value, error):
    data = gci(); data[field:field + len(value)] = value
    with pytest.raises(ValueError, match=error):
        save._inspect_gci(data)


@pytest.mark.parametrize('family', [' ', 'A'])
@pytest.mark.parametrize('slot', [0, 14])
def test_exact_native_filename_families_and_slots(family, slot):
    data = gci(family=family, slot=slot)
    # Native/Dolphin filename comparison stops at NUL; padding need not be zero.
    data[35:40] = b'abcde'
    assert save._inspect_gci(data)['slot'] == slot


@pytest.fixture(scope='module')
def owned():
    root = Path(os.environ.get('GBOX_RE2GC_EVIDENCE',
        '/home/ehm_eckx/gbox-pr-audit-20261017/re-export-evidence'))
    if not (root / 'leon.rel').is_file():
        pytest.skip('exact owned GHAE08 DOL/REL evidence unavailable')
    return root


@pytest.mark.parametrize('scenario', ['leon', 'claire'])
def test_owned_source_and_checksum_code_identity(owned, scenario):
    dol, rel = (owned / 're2gc-main.dol').read_bytes(), (owned / f'{scenario}.rel').read_bytes()
    before = (sha(dol), sha(rel))
    build = Build(dol, rel)
    report = save.inspect_gci(build, gci(character=0x0c))
    assert report['layout_source']['scenario'] == scenario
    at = save.CHECKSUM_CODE[scenario]
    assert sha(rel[at:at + 80]) == save.CHECKSUM_CODE_SHA256
    assert (sha(dol), sha(rel)) == before
    build.rel = bytes(len(rel))
    with pytest.raises(ValueError, match='REL SHA'):
        save.inspect_gci(build, gci())


def test_public_inspection_requires_verified_source():
    with pytest.raises(ValueError, match='Build'):
        save.inspect_gci(None, gci())


def test_cli_reports_only_and_preserves_every_input(owned, tmp_path, capsys):
    path = tmp_path / 'copied.gci'; data = bytes(gci(character=0x0d)); path.write_bytes(data)
    args = ['--dol', str(owned / 're2gc-main.dol'), '--rel', str(owned / 'claire.rel'), str(path)]
    save.main(args)
    report = json.loads(capsys.readouterr().out)
    assert report['read_only'] and report['saves'][0]['native_load_route'] == 'tofu'
    assert not report['complete_unlocks_verified']
    assert path.read_bytes() == data and list(tmp_path.iterdir()) == [path]
    path.write_bytes(data + b'x')
    with pytest.raises(SystemExit) as exc:
        save.main(args)
    assert exc.value.code == 2
    assert path.read_bytes() == data + b'x'


def test_cli_reads_only_fixed_size_plus_sentinel(owned, tmp_path, monkeypatch):
    path = tmp_path / 'growing.gci'; path.write_bytes(bytes(gci()))
    original = Path.open
    sizes = []
    class Growing:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, count):
            sizes.append(count)
            return b'x' * count
    def opened(self, *args, **kwargs):
        return Growing() if self == path else original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opened)
    with pytest.raises(SystemExit):
        save.main(['--dol', str(owned / 're2gc-main.dol'), '--rel', str(owned / 'leon.rel'), str(path)])
    assert sizes == [0x2041]

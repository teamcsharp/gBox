from pathlib import Path
from types import SimpleNamespace
import struct

import pytest

from gbox import memory_card_emulators as M


@pytest.mark.parametrize('platform,size,blocks', [('dreamcast', 131072, 200), ('gamecube', 2097152, 251)])
def test_new_cards_are_formatted_and_empty(platform, size, blocks):
    data = M.blank(platform)
    assert len(data) == size
    assert M.describe(data, platform) == {'formatted': True, 'free_blocks': blocks,
                                        'total_blocks': blocks, 'files': []}
    with pytest.raises(ValueError):
        M.describe(data[:-1], platform)
    assert not M.describe(bytes(size), platform)['formatted']


def test_gc_serial_persists_in_card_bytes_and_bad_bat_copies_are_detected():
    a, b = M.blank('gamecube'), M.blank('gamecube')
    assert a[:12] != b[:12]
    card = bytearray(a)
    card[3 * M.GC_BLOCK + 10] ^= 1
    assert M.describe(card, 'gamecube')['formatted']  # one redundant metadata copy survives
    card[4 * M.GC_BLOCK + 10] ^= 1
    assert not M.describe(card, 'gamecube')['formatted']
    card = bytearray(a)
    card[0] ^= 1
    assert not M.describe(card, 'gamecube')['formatted']


def _vmu_save(name='PSO_SYSTEM', blocks=3):
    data = bytearray(M.blank('dreamcast'))
    off = 253 * 512
    data[off] = 0x33
    data[off + 4:off + 16] = name.encode().ljust(12, b'\0')
    struct.pack_into('<HH', data, off + 24, blocks, 0)
    for i in range(blocks):
        struct.pack_into('<H', data, 254 * 512 + i * 2, i + 1 if i < blocks - 1 else 0xfffa)
    return data


def test_vmu_inventory_follows_fat_and_rejects_cycles():
    data = _vmu_save()
    row = M.describe(data, 'dreamcast')
    assert row['formatted'] and row['free_blocks'] == 197
    assert row['files'] == [{'name': 'PSO_SYSTEM', 'blocks': 3, 'copy_protected': False}]
    struct.pack_into('<H', data, 254 * 512 + 2, 0)
    assert not M.describe(data, 'dreamcast')['formatted']


def test_selected_vmu_saves_copy_with_payload_and_no_input_mutation():
    source = _vmu_save()
    source[:1536] = b'P' * 1536
    before = bytes(source)
    destination = M.blank('dreamcast')
    result = M.copy_saves(source, destination, ['PSO_SYSTEM'])
    assert bytes(source) == before
    assert result[:1536] == b'P' * 1536
    assert M.describe(result, 'dreamcast')['free_blocks'] == 197
    assert M.describe(destination, 'dreamcast')['files'] == []
    with pytest.raises(ValueError, match='already has'):
        M.copy_saves(source, result, ['PSO_SYSTEM'])
    with pytest.raises(ValueError, match='not on'):
        M.copy_saves(source, destination, ['missing'])
    full = _vmu_save('OTHER', 200)
    with pytest.raises(ValueError, match='do not fit'):
        M.copy_saves(source, full, ['PSO_SYSTEM'])


def test_gc_inventory_uses_valid_newest_directory_and_checks_chains():
    card = bytearray(M.blank('gamecube'))
    directory = bytearray(card[M.GC_BLOCK:2 * M.GC_BLOCK])
    directory[:64] = b'\xff' * 64
    directory[:6] = b'GPOE8P'
    directory[8:40] = b'PSO_SYSTEM'.ljust(32, b'\0')
    struct.pack_into('>HH', directory, 0x36, 5, 1)
    struct.pack_into('>h', directory, 0x1ffa, 1)
    directory[0x1ffc:] = M._checksum(directory[:0x1ffc])
    card[2 * M.GC_BLOCK:3 * M.GC_BLOCK] = directory
    bat = bytearray(card[3 * M.GC_BLOCK:4 * M.GC_BLOCK])
    struct.pack_into('>HHHH', bat, 4, 1, 250, 5, 0xffff)
    bat[:4] = M._checksum(bat[4:])
    card[4 * M.GC_BLOCK:5 * M.GC_BLOCK] = bat
    info = M.describe(card, 'gamecube')
    assert info['formatted'] and info['free_blocks'] == 250
    assert info['files'] == [{'name': 'PSO_SYSTEM', 'blocks': 1, 'game_code': 'GPOE8P'}]
    struct.pack_into('>H', directory, 0x38, 2)
    directory[0x1ffc:] = M._checksum(directory[:0x1ffc])
    card[2 * M.GC_BLOCK:3 * M.GC_BLOCK] = directory
    assert not M.describe(card, 'gamecube')['formatted']


def test_retroarch_isolates_vmus_bios_and_options_without_touching_original(tmp_path):
    source = tmp_path / 'system' / 'dc'
    source.mkdir(parents=True)
    (source / 'dc_boot.bin').write_bytes(b'firmware')
    old = source / 'vmu_save_A1.bin'
    original = bytes(_vmu_save())
    old.write_bytes(original)
    co = tmp_path / 'global.cfg'
    co.write_text('reicast_per_content_vmus = "All VMUs"\nunrelated = "keep"\n')
    leased = tmp_path / 'leased.bin'
    leased.write_bytes(M.blank('dreamcast'))
    context = {'platform': 'dreamcast', 'work_dir': str(tmp_path / 'private'),
               'slots': {'A1': {'path': str(leased)}}}
    adapter = SimpleNamespace(memory_card_context=context)
    opts = {'system_directory': tmp_path / 'system'}
    M.retroarch_options(adapter, opts, co)
    working = Path(context['slots']['A1']['path'])
    assert working != leased and working.is_file()
    assert working.read_bytes() == leased.read_bytes()
    assert (working.parent / 'dc_boot.bin').read_bytes() == b'firmware'
    assert old.read_bytes() == original
    assert M._cfg(co)['reicast_per_content_vmus'] == 'All VMUs'
    selected = M._cfg(opts['core_options_path'])
    assert selected['unrelated'] == 'keep'
    assert selected['reicast_per_content_vmus'] == 'disabled'
    assert selected['reicast_device_port1_slot1'] == 'VMU'
    assert selected['reicast_device_port1_slot2'] == 'None'
    assert M.discover(adapter) == [{'slot': 'A1', 'path': str(working), 'platform': 'dreamcast'}]


def test_dolphin_paths_are_explicit_and_missing_slot_disabled(tmp_path):
    path = tmp_path / 'pso.raw'
    path.write_bytes(M.blank('gamecube'))
    ad = SimpleNamespace(_disc_id=lambda rom:'GPOE8P',memory_card_context={'platform': 'gamecube','work_dir':str(tmp_path/'session'), 'slots': {'A': {'path': str(path)}}})
    expected = tmp_path/'session'/'dolphin'/'A.USA.raw'
    assert M.dolphin_options(ad,'game.iso') == {'Dolphin.Core.MemoryCardSize':'-1','Dolphin.Core.SlotA': '1', 'Dolphin.Core.MemcardAPath': str(expected),
                                      'Dolphin.Core.SlotB': '255'}
    assert ad.memory_card_context['slots']['A']['path']==str(expected)
    assert expected.read_bytes()==path.read_bytes()
    expected.write_bytes(bytes(2097152))
    with pytest.raises(ValueError, match='valid formatted'):
        M.dolphin_options(ad)


@pytest.mark.parametrize('serial,region',[('GPOJ8P','JAP'),('GPOD8P','EUR'),('GPOE8P','USA')])
def test_dolphin_actual_region_path_and_unknown_formats_fail_before_launch(tmp_path,serial,region):
    path=tmp_path/'A.raw';path.write_bytes(M.blank('gamecube'))
    ad=SimpleNamespace(_disc_id=lambda rom:serial,memory_card_context={'platform':'gamecube','work_dir':str(tmp_path/'session'),'slots':{'A':{'path':str(path)}}})
    out=M.dolphin_options(ad,'game.iso')
    assert out['Dolphin.Core.MemcardAPath'].endswith('A.'+region+'.raw')
    ad._disc_id=lambda rom:None
    with pytest.raises(ValueError,match='recognized disc ID'):M.dolphin_options(ad,'unknown.rvz')


def test_discovery_does_not_guess_per_game_vmu_as_inserted(tmp_path):
    (tmp_path / 'system' / 'dc').mkdir(parents=True)
    card = tmp_path / 'system' / 'dc' / 'vmu_save_A1.bin'
    card.write_bytes(M.blank('dreamcast'))
    (tmp_path / 'retroarch').mkdir()
    co = tmp_path / 'retroarch' / 'core-options.cfg'
    co.write_text('reicast_per_content_vmus = "disabled"\n')
    ad = SimpleNamespace(platform='dreamcast', config=SimpleNamespace(runtime=tmp_path))
    assert M.discover(ad)[0]['path'] == str(card)
    co.write_text('reicast_per_content_vmus = "VMU A1"\n')
    assert M.discover(ad) == []


def test_discovery_does_not_enable_old_files_in_disabled_expansion_slots(tmp_path):
    dc = tmp_path / 'system' / 'dc';dc.mkdir(parents=True)
    for slot in ('A1', 'A2', 'B1'):
        (dc / f'vmu_save_{slot}.bin').write_bytes(M.blank('dreamcast'))
    co = tmp_path / 'retroarch' / 'core-options.cfg';co.parent.mkdir()
    co.write_text('reicast_device_port2_slot1 = "None"\n')
    ad = SimpleNamespace(platform='dreamcast', config=SimpleNamespace(runtime=tmp_path))
    assert [r['slot'] for r in M.discover(ad)] == ['A1']


def test_gc_discovery_uses_region_native_dolphin_will_open(tmp_path):
    root=tmp_path/'dolphin-user'/'GC';root.mkdir(parents=True)
    for region in ('USA','EUR'):(root/f'MemoryCardA.{region}.raw').write_bytes(M.blank('gamecube'))
    ad=SimpleNamespace(platform='gamecube',config=SimpleNamespace(runtime=tmp_path),memory_card_rom='game.iso',_disc_id=lambda rom:'GPOD8P')
    rows=M.discover(ad)
    assert len(rows)==1 and rows[0]['path'].endswith('MemoryCardA.EUR.raw')

import json
import os
import struct
from pathlib import Path

import pytest

from gbox import re2gc_state as state


@pytest.fixture(params=['leon', 'claire'])
def build(request):
    root = os.environ.get('GBOX_RE2GC_EVIDENCE')
    if not root:
        pytest.skip('set GBOX_RE2GC_EVIDENCE to the exact owned DOL/REL directory')
    root = Path(root)
    return state.Build((root / 're2gc-main.dol').read_bytes(),
                       (root / (request.param + '.rel')).read_bytes())


def snapshot(build, *, bss=0x80800000):
    """Synthetic memory image, not gameplay evidence. Header follows owned OSLink."""
    ram = bytearray(state.RAM_SIZE)
    ram[:6] = b'GHAE08'

    def put(address, data):
        ram[address - state.RAM_BASE:address - state.RAM_BASE + len(data)] = data

    def word(address, value):
        put(address, struct.pack('>I', value))

    for off, address, size in zip(*[struct.unpack_from('>18I', build.dol, at) for at in (0, 0x48, 0x90)]):
        if size:
            put(address, build.dol[off:off + size])
    base = 0x80400000
    put(base, build.linked_rel(base, bss))
    word(state.MODULE_POINTER, base)
    word(0x800030c8, base)
    word(0x800030cc, base)
    word(base + 0x10, base + build.table_offset)
    for i, (off, size) in enumerate(build.sections):
        address = base + off if off else bss if size else 0
        word(base + build.table_offset + i * 8, address)
    put(state.CAPACITY, b'\x08')
    put(state.INVENTORY, bytes([2, 18, 0, 0xaa, 1, 1, 0, 0xbb]))
    put(state.INVENTORY + 40, bytes([0x2f, 1, 0, 0xcc]))
    put(state.ITEM_BOX, bytes([0x11, 255, 3, 0xdd]))
    put(bss + state.EQUIPPED_SLOT, b'\0')
    put(bss + state.EQUIPPED_ITEM, b'\x02')
    put(0x801688ec, b'\x02\x00')
    put(0x80163f36, b'\xf0\x02')
    word(bss + state.END_RESULT_FLAGS, 0x2000)
    return bytes(ram)


def test_rejects_unknown_revision_without_analysis():
    with pytest.raises(ValueError, match='DOL SHA'):
        state.Build(b'not this game', b'not a REL')


def test_owned_analysis_image_maps_bss_without_overlaps(build):
    data = build.analysis_elf()
    assert data[:7] == b'\x7fELF\x01\x02\x01'
    phoff = struct.unpack_from('>I', data, 28)[0]
    count = struct.unpack_from('>H', data, 44)[0]
    segments = [struct.unpack_from('>8I', data, phoff + i * 32) for i in range(count)]
    ranges = sorted((p[2], p[2] + p[5]) for p in segments)
    assert all(a >= previous_end for (_, previous_end), (a, _) in zip(ranges, ranges[1:]))
    assert any(p[2] <= state.INVENTORY < p[2] + p[5] and p[4] == 0 for p in segments)
    assert all(p[1] == 0 for p in segments if p[4] == 0)
    assert all(p[1] + p[4] <= len(data) for p in segments)
    # Existing linker is an independent cross-check at its default contiguous BSS layout.
    from gbox.gcdisc import rel_link
    bss = (0x80400000 + len(build.rel) + 31) & ~31
    assert build.linked_rel(0x80400000, bss) == rel_link(build.rel, 0x80400000)
    with pytest.raises(ValueError, match='overlaps'):
        build.analysis_elf(base=0x80100000)


def test_owned_snapshot_resolves_two_different_dynamic_bss_allocations(build):
    for bss in (0x80800000, 0x80b00000):
        data = snapshot(build, bss=bss)
        digest = state.sha(data)
        report = build.read_snapshot(data)
        assert state.sha(data) == digest
        assert report['bss_base'] == bss
        assert report['capacity'] == 8
        assert len(report['inventory']) == 10 and len(report['item_box']) == 64
        assert report['reserved_item']['item_id'] == 0x2f
        assert report['inventory'][0]['raw_hex'] == '021200aa'
        assert report['item_box'][0]['raw_hex'] == '11ff03dd'
        assert report['equipped'] == {'slot': 0, 'item_id': 2, 'coherent': True, 'loaded_weapon_word': 0xf002}
        assert report['saved_equipment'] == {'item_id': 2, 'slot': 0}
        assert report['ending_result_flags'] == 0x2000
        assert report['source_code_verified']
        assert not report['gameplay_verified']
        assert not report['unlock_profile_verified'] and not report['live_writes_enabled']


def test_owned_snapshot_rejects_wrong_identity_and_relocated_memory(build):
    original = snapshot(build)
    cases = [
        (0, b'GHAP08', 'GHAE08'),
        (state.MODULE_POINTER - state.RAM_BASE, struct.pack('>I', 0x80400001), 'unaligned'),
        (0x400000, struct.pack('>I', 99), 'header'),
        (0x30c8, struct.pack('>I', 0), 'active linked'),
        (0x400004, struct.pack('>I', 0x80400000), 'module list'),
        (0x400010, struct.pack('>I', 0x80400050), 'section-table'),
        (0x400048 + 6 * 8, struct.pack('>I', 0x80160000), 'overlaps main'),
        (0x400048 + 6 * 8, struct.pack('>I', 0x80410000), 'overlaps module'),
        (0x400048 + 8 + 4, struct.pack('>I', 1), 'size'),
        (0x4000d0, b'\0\0\0\0', 'REL executable'),
        (0x46d98, b'\0\0\0\0', 'DOL executable'),
        (state.CAPACITY - state.RAM_BASE, b'\xff', 'capacity'),
        (state.INVENTORY - state.RAM_BASE, b'\xff', 'record'),
    ]
    for offset, value, message in cases:
        mutated = bytearray(original)
        mutated[offset:offset + len(value)] = value
        with pytest.raises(ValueError, match=message):
            build.read_snapshot(mutated)
    with pytest.raises(ValueError, match='complete'):
        build.read_snapshot(original[:-1])


def test_owned_snapshot_only_accepts_documented_audio_code_changes(build):
    data = bytearray(snapshot(build))
    rel_offset = 0x1903fc if build.scenario == 'leon' else 0x190294
    instruction = struct.unpack_from('>I', data, 0x400000 + rel_offset)[0]
    # Independent check: the documented original branch resolves to main's memset.
    displacement = instruction & 0x3fffffc
    if displacement & 0x2000000:
        displacement -= 0x4000000
    assert instruction >> 26 == 18 and (instruction & 3) == 1
    assert 0x80400000 + rel_offset + displacement == 0x80003100
    for offset in (0x339e4, 0x400000 + rel_offset):
        data[offset:offset + 4] = b'\x60\x00\x00\x00'
    report = build.read_snapshot(data)
    assert len(report['allowed_audio_patches']) == 2
    data[0x400000 + rel_offset + 4] ^= 1
    with pytest.raises(ValueError, match='REL executable'):
        build.read_snapshot(data)


def test_owned_equipped_state_reports_incoherence_without_guessing(build):
    data = bytearray(snapshot(build))
    data[0x800000 + state.EQUIPPED_ITEM] = 0x11
    report = build.read_snapshot(data)
    assert not report['equipped']['coherent']
    assert report['equipped']['item_id'] == 0x11
    data[0x800000 + state.EQUIPPED_SLOT] = 0x80
    data[0x800000 + state.EQUIPPED_ITEM] = 0
    assert build.read_snapshot(data)['equipped']['coherent']


def test_owned_cli_exclusive_output(build, tmp_path, monkeypatch, capsys):
    dol, rel = tmp_path / 'main.dol', tmp_path / 'scenario.rel'
    dol.write_bytes(build.dol)
    rel.write_bytes(build.rel)
    output = tmp_path / 'analysis.elf'
    monkeypatch.setattr('sys.argv', ['re2gc_state', '--dol', str(dol), '--rel', str(rel), '--analysis-elf', str(output)])
    state.main()
    receipt = json.loads(capsys.readouterr().out)
    assert not receipt['executable_artifact']
    assert receipt['sha256'] == state.sha(output.read_bytes())
    with pytest.raises(FileExistsError):
        state.main()

"""Tests for the 007 unlock analysis built from the owned disc's Bond.elf.

The disc ships a debug ELF, so the addresses below are read off its own
symbol table rather than assumed.  The test re-derives them from the ELF when
the ELF is present, and always checks the committed evidence artifact so a
reviewer can see the same numbers without the disc.
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / 'docs' / 'auf-unlock-analysis.json'

ELF_CANDIDATES = [
    os.environ.get('AUF_BOND_ELF', ''),
    '/home/ehm_eckx/gBox_alt/gbox-cache/65b7187589166b26/Bond.elf',
    '/home/ehm_eckx/.hermes/cache/scratch/auf_extract/Bond.elf',
]

# Addresses read from the disc's own symbol table.
EXPECTED = {
    'medal_flags_reader': ('UI_CurrentMissionGetMedalFlags', 0x8001ac60),
    'gold_medal_reader': ('UI_CurrentMissionHasGoldMedal', 0x8001ac44),
    'game_medal_flags': ('G_GetMedalFlags__Fv', 0x8011f704),
    'game_gold_medal': ('G_GoldMedalForMission__Fv', 0x8011f6d4),
    'medal_levels_table': ('gSC_MedalLevels', 0x80407c88),
    'medal_earned': ('pMedalEarned', 0x8023e028),
    'current_unlocked': ('pCurrentUnlocked', 0x804e366c),
    'set_gold_medal_level': ('SetGoldMedalLevel__12ScriptThreadFP5Event', 0x800fb0b4),
    'set_silver_medal_level': ('SetSilverMedalLevel__12ScriptThreadFP5Event', 0x800fb130),
    'save_game_variables': ('G_SaveGameVariables__FP18ScriptVariableList', 0x8009275c),
    'restore_game_variables': ('G_RestoreGameVariables__FP18ScriptVariableList', 0x800926c4),
    'save_to_slot': ('SaveToSaveFileSlot', 0x801abf04),
    'load_from_slot': ('LoadFromSaveFileSlot', 0x801abf90),
}


def _elf_path():
    for candidate in ELF_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _artifact():
    assert ARTIFACT.exists(), f'missing evidence artifact: {ARTIFACT}'
    return json.loads(ARTIFACT.read_text(encoding='utf-8'))


def test_artifact_pins_the_owned_executable():
    data = _artifact()
    assert data['elf']['sha256'] == '1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f'
    assert data['elf']['size'] == 4729888
    assert data['elf']['symbols'] > 14000


def test_artifact_keeps_the_progression_symbols():
    data = _artifact()
    for role, (name, address) in EXPECTED.items():
        entry = data['symbols'].get(role)
        assert entry is not None, f'role missing from the artifact: {role}'
        assert entry['name'] == name
        assert int(entry['address'], 16) == address


def test_medal_flag_table_is_decoded_from_the_reader():
    """The table address is decoded from the reader's own instruction words."""
    data = _artifact()
    table = data['medal_flags_table']
    assert table['address'] == '0x8023dfc0'
    assert table['entries'] == 13 and table['entry_size'] == 4
    # The pair that forms it: lis r4,0x8024 / addi r5,r4,0xdfc0.
    pair = table['pairs'][0]
    assert pair['high'] == '0x80240000'
    assert pair['low'] == '0xdfc0'
    assert (int(pair['high'], 16) + (int(pair['low'], 16) - 0x10000)) & 0xFFFFFFFF \
        == int(pair['address'], 16)


def test_medal_levels_table_is_written_by_the_medal_setters():
    """gSC_MedalLevels is the table the medal setters write."""
    data = _artifact()
    refs = data['xref_targets']['gSC_MedalLevels']['refs']
    writers = {r['function'] for r in refs if r['access'] == 'write'}
    assert 'SetGoldMedalLevel__12ScriptThreadFP5Event' in writers
    assert 'SetSilverMedalLevel__12ScriptThreadFP5Event' in writers


def test_medal_earned_is_saved_and_restored():
    """pMedalEarned is read when the game collects what to save and written back."""
    data = _artifact()
    refs = data['xref_targets']['pMedalEarned']['refs']
    functions = {r['function'] for r in refs}
    assert 'UI_CollectInfoToBeSaved' in functions
    assert 'UI_RestoreSavedInfo' in functions
    assert 'SaveBeforeRaceMission' in functions


def test_symbols_match_the_disc_elf_when_available():
    elf_path = _elf_path()
    if not elf_path:
        pytest.skip('Bond.elf not present on this machine; the committed artifact is checked instead')
    from gbox.auf_disasm import Elf
    elf = Elf(elf_path)
    for role, (name, address) in EXPECTED.items():
        assert elf.symbols.get(name) == address, f'{role} moved: {name}'


def test_reader_indexes_the_table_with_thirteen_missions():
    """UI_CurrentMissionGetMedalFlags loops 13 times over the table."""
    elf_path = _elf_path()
    if not elf_path:
        pytest.skip('Bond.elf not present on this machine')
    from gbox.auf_disasm import Elf
    elf = Elf(elf_path)
    reader = elf.symbols['UI_CurrentMissionGetMedalFlags']
    raw = elf.bytes_at(reader, 0x50)
    words = [struct.unpack('>I', raw[i:i + 4])[0] for i in range(0, len(raw) - 3, 4)]
    # li r0, 13 -> addi r0,r0,13  (opcode 14, rd=0, ra=0, imm=13)
    assert any((w >> 26) & 0x3F == 14 and ((w >> 21) & 0x1F) == 0
               and ((w >> 16) & 0x1F) == 0 and (w & 0xFFFF) == 13 for w in words)
    # the loop increments the table pointer by 4 (addi r5,r5,4)
    assert any((w >> 26) & 0x3F == 14 and ((w >> 21) & 0x1F) == 5
               and ((w >> 16) & 0x1F) == 5 and (w & 0xFFFF) == 4 for w in words)


def test_template_and_artifact_agree_on_the_medal_table_address():
    """Regression: the table address was mis-decoded once as 0x801ddfc0.

    ``lis r4,0x8024`` gives 0x80240000 and the paired ``addi`` immediate is
    -0x2040, so the table is 0x8023dfc0 (UI_Level_Unlocked_Gold).  The
    template and the evidence artifact must not disagree.
    """
    tpl = json.loads((ROOT / 'profiles' / 'gamedata' / '65b7187589166b26-unlock.json').read_text())
    art = json.loads(ARTIFACT.read_text())
    assert tpl['progression']['medal_flags_table']['address'] == art['medal_flags_table']['address']
    assert art['medal_flags_table']['address'] == '0x8023dfc0'


def test_medal_table_is_data_not_code():
    """0x8023dfc0 is UI_Level_Unlocked_Gold; 0x801ddfc0 would be code."""
    elf_path = _elf_path()
    if not elf_path:
        pytest.skip('Bond.elf not present on this machine')
    from gbox.auf_disasm import Elf
    elf = Elf(elf_path)
    assert elf.symbol_for(0x8023dfc0) == 'UI_Level_Unlocked_Gold'
    assert elf.symbol_for(0x8023df90) == 'UI_Level_Unlocked'


def test_player_model_availability_is_decoded_from_the_gate_function():
    """The on-load model gate is read out of the instruction words."""
    data = _artifact()
    avail = data['model_availability']
    assert avail['function'].startswith('_IsPlayerModelAvailable')
    assert avail['jump_table'] == '0x8028790c'
    models = {m['model']: m for m in avail['models']}
    assert sorted(models) == list(range(3, 16))
    assert models[3]['table_symbol'] == 'UI_Level_Unlocked'
    assert models[3]['word'] == 4
    assert models[10]['table_symbol'] == 'UI_Level_Unlocked'
    assert models[12]['table_symbol'] == 'UI_Level_Unlocked'


def test_template_records_the_model_gate():
    tpl = json.loads((ROOT / 'profiles' / 'gamedata' / '65b7187589166b26-unlock.json').read_text())
    gate = tpl['progression']['player_model_gate']
    assert gate['function'].startswith('_IsPlayerModelAvailable')
    assert gate['jump_table'] == '0x8028790c'
    assert sorted(int(k) for k in gate['gates']) == list(range(3, 16))

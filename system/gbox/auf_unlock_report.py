"""Build the verified AUF unlock-analysis artifact from the owned disc's Bond.elf.

The disc's debug ELF keeps ``.symtab`` (17,636 symbols) and RAM-linked
addresses, so the progression machinery can be located exactly instead of
guessed.  This module collects that evidence into one JSON artifact:

* the key progression symbols with their addresses;
* the cross-references of the progression data (who reads and who writes it);
* the medal-flag table address, decoded directly from the instruction words
  of ``UI_CurrentMissionGetMedalFlags``;
* the disc-side content inventory (multiplayer bodies, mission levels) when
  the swap module can be imported.

Read-only: nothing is written except the JSON report the caller names.

    python -m gbox.auf_unlock_report <Bond.elf> --json docs/auf-unlock-analysis.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from .auf_disasm import Elf

# Progression symbols read off the disc's own symbol table.
KEY_SYMBOLS = {
    'medal_flags_reader': 'UI_CurrentMissionGetMedalFlags',
    'gold_medal_reader': 'UI_CurrentMissionHasGoldMedal',
    'game_medal_flags': 'G_GetMedalFlags__Fv',
    'game_gold_medal': 'G_GoldMedalForMission__Fv',
    'medal_levels_table': 'gSC_MedalLevels',
    'medal_earned': 'pMedalEarned',
    'current_unlocked': 'pCurrentUnlocked',
    'set_gold_medal_level': 'SetGoldMedalLevel__12ScriptThreadFP5Event',
    'set_silver_medal_level': 'SetSilverMedalLevel__12ScriptThreadFP5Event',
    'set_bronze_medal_level': 'SetBronzeMedalLevel__12ScriptThreadFP5Event',
    'enable_bonus_items': 'G_EnableBonusItems__Fi',
    'ui_level_unlocked': 'UI_Level_Unlocked',
    'is_player_model_available': '_IsPlayerModelAvailable',
    'ui_level_unlocked_gold': 'UI_Level_Unlocked_Gold',
    'ui_unlock_strings': 'UI_Unlock_Strings',
    'ui_unlock_target_score': 'UI_Unlock_Target_Score',
    'save_game_variables': 'G_SaveGameVariables__FP18ScriptVariableList',
    'restore_game_variables': 'G_RestoreGameVariables__FP18ScriptVariableList',
    'save_to_slot': 'SaveToSaveFileSlot',
    'load_from_slot': 'LoadFromSaveFileSlot',
    'mp_save_to_slot': 'MPM_SaveToSaveFileSlot',
    'mpp_save_to_slot': 'MPP_SaveToSaveFileSlot',
    'save_file_global': 'SaveFile',
    'current_save_file': 'gCurrentSaveFile',
    'static_save_file': 'gStaticSaveFile',
    'sp_statistics_class': 'clSPStatistics',
}

# Cross-reference targets: the progression data whose readers and writers
# decide what an on-load unlock has to touch.
XREF_TARGETS = ['gSC_MedalLevels', 'pMedalEarned', 'pCurrentUnlocked',
                'gCurrentSaveFile', 'SaveFile', 'gStaticSaveFile',
                'UI_Level_Unlocked', 'UI_Unlock_Target_Score']


def _sx16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def decode_address_pairs(elf: Elf, addr: int, count: int = 24) -> list[dict]:
    """Decode the ``lis``/``addi`` address pairs of a function.

    The pair is exact: the high half is the sign-extended immediate of the
    ``lis`` shifted left 16, the low half is the sign-extended immediate of
    the ``addi``.
    """
    raw = elf.bytes_at(addr, count * 4)
    out: list[dict] = []
    high = None
    high_reg = None
    for index in range(0, len(raw) - 3, 4):
        word = struct.unpack('>I', raw[index:index + 4])[0]
        opcode = (word >> 26) & 0x3F
        rd = (word >> 21) & 0x1F
        ra = (word >> 16) & 0x1F
        imm = word & 0xFFFF
        site = addr + index
        if opcode == 15 and ra == 0:
            high = (_sx16(imm) << 16) & 0xFFFFFFFF
            high_reg = rd
        elif opcode == 14 and ra == high_reg and high is not None:
            value = (high + _sx16(imm)) & 0xFFFFFFFF
            out.append({'site': f'0x{site:08x}', 'address': f'0x{value:08x}',
                        'high': f'0x{high:08x}', 'low': f'0x{imm:04x}',
                        'register': f'r{rd}'})
            high, high_reg = None, None
    return out


def _words(elf: Elf, addr: int, count: int) -> list[int]:
    raw = elf.bytes_at(addr, count * 4)
    return [struct.unpack('>I', raw[i:i + 4])[0] for i in range(0, len(raw) - 3, 4)]


def model_availability(elf: Elf) -> dict:
    """Decode which table word gates each selectable player model.

    ``_IsPlayerModelAvailable`` dispatches on the model id through a
    13-entry jump table (models 3..15).  Every case loads exactly one word
    of a global table, so the model -> gate mapping is read out of the
    instruction words rather than guessed.
    """
    from .auf_xref import functions
    func = elf.symbols.get('_IsPlayerModelAvailable')
    if func is None:
        return {}
    size = 0
    for start, end, name in functions(elf):
        if name == '_IsPlayerModelAvailable' and start == func:
            size = end - start
            break
    if not size:
        return {}
    ws = _words(elf, func, size // 4)
    end_addr = func + size
    candidates = []
    for i, word in enumerate(ws):
        opcode = (word >> 26) & 0x3F
        rd = (word >> 21) & 0x1F
        ra = (word >> 16) & 0x1F
        if opcode == 15 and ra == 0:
            high = (_sx16(word & 0xFFFF) << 16) & 0xFFFFFFFF
            for j in range(i + 1, min(i + 4, len(ws))):
                w2 = ws[j]
                if ((w2 >> 26) & 0x3F) == 14 and ((w2 >> 16) & 0x1F) == rd:
                    candidates.append((func + i * 4, high, w2 & 0xFFFF,
                                       (high + _sx16(w2 & 0xFFFF)) & 0xFFFFFFFF))
                    break
    table = None
    for site, high, low, value in candidates:
        raw = elf.bytes_at(value, 13 * 4)
        if len(raw) < 13 * 4:
            continue
        entries = [struct.unpack('>I', raw[i:i + 4])[0] for i in range(0, len(raw), 4)]
        if all(func <= entry < end_addr for entry in entries):
            table = (site, high, low, value, entries)
            break
    if table is None:
        return {}
    site, high, low, value, entries = table
    models = []
    for index, entry in enumerate(entries):
        cw = _words(elf, entry, 16)
        base = None
        breg = None
        for i, word in enumerate(cw):
            opcode = (word >> 26) & 0x3F
            rd = (word >> 21) & 0x1F
            ra = (word >> 16) & 0x1F
            if opcode == 15 and ra == 0:
                h = (_sx16(word & 0xFFFF) << 16) & 0xFFFFFFFF
                for j in range(i + 1, min(i + 3, len(cw))):
                    w2 = cw[j]
                    if ((w2 >> 26) & 0x3F) == 14 and ((w2 >> 16) & 0x1F) == rd:
                        base = (h + _sx16(w2 & 0xFFFF)) & 0xFFFFFFFF
                        breg = (w2 >> 21) & 0x1F
                        break
            if base is not None:
                break
        word_index = None
        for word in cw:
            if ((word >> 26) & 0x3F) == 32 and ((word >> 16) & 0x1F) == breg:
                word_index = (word & 0xFFFF) // 4
                break
        models.append({'model': index + 3, 'case': f'0x{entry:08x}',
                       'table': f'0x{base:08x}' if base else None,
                       'table_symbol': elf.symbol_for(base) if base else None,
                       'word': word_index})
    return {'function': f'_IsPlayerModelAvailable @ 0x{func:08x}',
            'jump_table': f'0x{value:08x}', 'jump_table_site': f'0x{site:08x}',
            'models': models,
            'note': 'model id 3..15; a model is available when the listed word of the table is non-zero'}


def build(elf_path: str) -> dict:
    elf = Elf(elf_path)
    raw = Path(elf_path).read_bytes()
    report: dict = {
        'elf': {
            'path': elf_path,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'size': len(raw),
            'symbols': len(elf.symbols),
            'source': 'owned 007: Agent Under Fire (USA) GameCube disc, /base.elf/Bond.elf',
        },
        'symbols': {},
        'xref_targets': {},
        'medal_flags_table': None,
        'content_inventory': {},
        'model_availability': {},
    }
    report['model_availability'] = model_availability(elf)
    for role, name in KEY_SYMBOLS.items():
        addr = elf.symbols.get(name)
        report['symbols'][role] = {
            'name': name,
            'address': f'0x{addr:08x}' if addr is not None else None,
        }

    # The medal-flag table: decoded from the instruction words of the reader
    # that indexes it (13 dwords, one per mission, packed into a bitmask).
    reader = elf.symbols.get('UI_CurrentMissionGetMedalFlags')
    if reader is not None:
        pairs = decode_address_pairs(elf, reader)
        report['medal_flags_table'] = {
            'reader': f'UI_CurrentMissionGetMedalFlags @ 0x{reader:08x}',
            'address': pairs[0]['address'] if pairs else None,
            'pairs': pairs,
            'entry_size': 4,
            'entries': 13,
            'note': 'one u32 per mission; a non-zero entry sets bit i of the medal bitmask',
        }

    from .auf_xref import scan
    targets = []
    for name in XREF_TARGETS:
        addr = elf.symbols.get(name)
        if addr is not None:
            targets.append(addr)
    if targets:
        found = scan(elf, targets)
        for name in XREF_TARGETS:
            addr = elf.symbols.get(name)
            if addr is None:
                continue
            report['xref_targets'][name] = {
                'address': f'0x{addr:08x}',
                'refs': found.get(addr, []),
            }
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('elf')
    ap.add_argument('--json', required=True)
    args = ap.parse_args(argv)
    report = build(args.elf)
    Path(args.json).write_text(json.dumps(report, indent=1, sort_keys=True), encoding='utf-8')
    print(f'wrote {args.json}')
    print('medal flags table:', (report.get('medal_flags_table') or {}).get('address'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

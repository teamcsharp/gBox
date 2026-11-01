"""Read-only picker metadata from the current RE5 executable and inventory.

Rank by the same upgrade-table firepower used by bullet_damage, at level zero
for every weapon. It includes active multipliers, not guessed DPS or critical
hit damage. Special weapons without that table entry retain an unknown value.
"""
from __future__ import annotations

import math
import struct

from . import re5_switch as R, re5_switch_mods as M, re5_weapons

# The upgrade entries for explosives/melee are multipliers (normally 1), not
# damage. Never display those placeholders as one point of damage. Reference
# base damage from Christopher Lane's firsthand Weapon/Combat Guide, sections
# 2 and 8; these remain explicitly separate from live firepower in the UI.
REFERENCE = 'https://gamefaqs.gamespot.com/ps3/929198-resident-evil-5/faqs/58576'
BASE_DAMAGE = {0x01: 50, 0x0E: 50, 0x22: 666, 0x06: 1500, 0x07: 500,
               0x0A: 1500, 0x0D: 30000}
FIREPOWER_FAMILIES = re5_weapons.DIRECT | {'bow', 'flame'}


def choices(ctl):
    player, generation = ctl.ready()
    inventory = R.inventory(ctl, player)
    if not inventory:
        raise RuntimeError('current player inventory is unavailable')
    # One guest-memory read, rather than a syscall per weapon on every claim.
    table = ctl.rd(ctl.base + M.UPG_TABLE, M.UPG_STRIDE * M.N_WEAPONS)
    rows = []
    for item, spec in re5_weapons.WEAPONS.items():
        damage, basis = BASE_DAMAGE.get(item), 'reference_base_damage'
        if item < M.N_WEAPONS and spec.family in FIREPOWER_FAMILIES:
            value = struct.unpack_from('<f', table, M.UPG_STRIDE * item + M.UPG_GROUP0)[0]
            if math.isfinite(value) and 0 <= value <= 1e9:
                damage, basis = round(value, 2), 'live_level0_firepower'
        if damage is None:
            basis = 'unmeasured'
        slots = [s for s in inventory if s['type'] == 1 and s['item'] == item]
        rows.append({'item': item, 'weapon': spec.name, 'family': spec.family,
                     'damage': damage, 'damage_basis': basis,
                     **({'damage_source': REFERENCE} if basis == 'reference_base_damage' else {}),
                     'in_inventory': bool(slots), 'equipped': any(s['hand'] for s in slots),
                     'inventory_slots': sorted(s['grid'] for s in slots)})
    if ctl.ready() != (player, generation):
        raise RuntimeError('player changed while reading the weapon catalogue')
    return sorted(rows, key=lambda r: (r['damage'] is None, -(r['damage'] or 0), r['weapon'].casefold()))

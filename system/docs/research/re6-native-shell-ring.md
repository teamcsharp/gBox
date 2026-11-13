# RE6 native launcher ring research, 2026-11-13

Build: Switch main `061D2A06`, ELF SHA-256
`441516ee1a4f26720e92956ecdb6cedcf253022cad7cbae239ad7e8ba002dd78`.
Addresses below are main-relative. Ghidra exports add `0x100000`.

The former shell branch called the thrown-grenade initializer with a shell DTI,
relocated the returned object, and counted it as a detonated, verified grenade.
That initializer writes bomb fields and requests bomb throw action 7. It does not
implement the shell launch or impact path. The controller now refuses this path
before attaching or allocating, including `allow_unverified` probes and direct
`_ring_one` calls. `allow_unverified` only bypasses missing live evidence for an
implemented operation. It cannot turn an allocation into a blast receipt.

Validation: 54 ring, scatter and class-image tests passed. This includes three
regressions that prevent native calls or writes for the unsupported shell kinds.
A stale hand-spawn test now checks the absolute DTI pointer required by the
parameterized wrapper, matching the previously shipped address correction.

## Native launch and impact evidence

- `F72760`, the grenade launcher's firing method, resolves the chosen ammo class,
  allocates it through the item factory with mode **14**, calls `F6B500` to set up
  muzzle position, orientation and previous position, detaches it through its
  vtable `+0x98`, clears flags `0x2800` at `+0x14`, assigns player ownership at
  `+0x1300` and launcher identity at `+0x38E0`, and registers the projectile through
  `1ED840`. The bomb initializer uses mode 13 and a different action lifecycle.
- `F6B500` writes position `+0x60`, prior position `+0x3890`, the initialized-history
  byte `+0x38A0`, rotation `+0x70` and origin `+0x38D0`. It requires a real launcher's
  bone data; calling it on a player or fabricated launcher is not a valid shortcut.
- `F59F30` advances launcher shells from local velocity `+0x3870`, world velocity
  `+0x3880`, rotation and the frame delta. It applies delayed gravity using
  `+0x3960/+0x3964`. These fields are not the bomb initializer's velocity fields.
- `F45AB0` performs shell movement and collision. `F45340` dispatches its native
  impact to action 17, 18 or 19 according to collision flags. The shell-explode
  action's vtable is `288C6C8`; its allocator is `11320C0`, start `1132190`, and
  tick `1132210`. A shell action transition must not be reported as an enemy hit.
- Constructors `F5A3D0/F5A110/F59C80` allocate **0x3970 bytes** for
  `uWp1302/uWp1303/uWp1304`. Their final vtables are
  `283AD18/283A880/283A3E8`. The DTI metadata value `0xE5C` is not the byte allocation
  size. There is no established out-of-bounds write merely from the old wrapper's
  offsets being above `0xE5C`; the defect is incompatible field/action semantics.
- `B2BC70` maps grenade launcher item `0x112`, inventory mode 0/1/2, to shell items
  `0x133/0x134/0x135`. It maps rocket launcher `0x11B` to `0x136` (`uWp1305`), **not**
  to `uWp1304`. The older `LAUNCHER_ROUNDS` rocket entry needs that correction.

Targeted exports are retained on Spark under
`gBox_alt/analysis/merc-full/re6-shell-research-20261113/`. The project requires
Ghidra 12.2; `/tmp/gbox-re6-shell-phase2.py` through `phase5.py` record the targeted
decompiler calls. Nothing in this investigation modified a running game.

## Payload evidence and remaining verification

The extracted `Msg_eng.arc` contains the native labels “40mm Explosive Rounds”,
“40mm Acid Rounds” and “40mm Nitrogen Rounds”. The three `uWp1302/1303/1304.arc`
archives each contain distinct hit resources and distinct sound/effect resources.
The `0x6E45FABB` hit resource's `attack_em` entry has these serialized values:

| Class | Damage | Attribute0 | Attribute1 |
| --- | ---: | ---: | ---: |
| uWp1302 | 1000 | 0x1142 | 1 |
| uWp1303 | 250 | 0x08000022 | 4 |
| uWp1304 | 300 | 0x00020022 | 4 |

The executable registers `cEm1000ActDmgIce`, `cEm3000ActDmgIce`,
`cEm3100ActDmgIce`, `cEm3200ActDmgIce`, `cEm5000ActDmgIce`,
`cEm5700ActDmgIce`, `cEm8100ActDmgIce`, and `cPlAction_pl_act_damage_ice`.
The nitrogen candidate therefore has its own damage payload; it must never be
replaced by flash or inferred successful because an object was allocated. An
implemented shell-only probe still needs a native explosion/effect receipt and
observed ice-state evidence on a susceptible enemy before the user control is
advertised as working. Boss susceptibility must be measured separately.

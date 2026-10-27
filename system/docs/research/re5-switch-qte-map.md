# RE5 Switch: QTE and live-weapon mapping (what Ghidra must find)

Request #4481 (7f80f9201d4b411e). The PS3 parity work has 20 of 22 ops on Switch
(`gbox/mercs/titles/re5_switch_mods.py`). Two ops remain "not yet on Switch":

- `instant_qte` — the QTE progress fields are not mapped on Switch yet
- `live_weapon` — the native pickup that builds a weapon mid-round is not found on Switch yet

Both need Switch-specific addresses that only Ghidra analysis of the RE5 Switch main
NSO (build EBFFDB223149A725A93CD9B60979F6AA) can provide. This document records the
working reference (RE6 Switch), the PS3 target behavior, and the exact queries the
next Ghidra session must run.

## The working reference: RE6 Switch `auto_qte`

RE6 Switch (`gbox/mercs/titles/re6_switch_mods.py`) has two QTE ops:

1. **`auto_qte`** — the game's own automatic action button. Writes
   `cSystemInfo mTempData.mExOptAutoActBtn` (+0x46B0, copy B +0x5510) to 1 in both
   copies. Every QTE site tests this field nonzero. Simple, one field, read back.

2. **`auto_qte_ram`** — while a zombie holds him (action 8 / 9 / 25), writes the
   grab's action-button progress to free him. More complex; reads the hold's units,
   writes progress up to the target.

The RE5 Switch `instant_qte` op should follow the same pattern: first try the
game's own auto-QTE option (one field), then the RAM progress manipulation if the
game does not have that option.

## The PS3 target: RE5 PS3 `instant_qte`

`gbox/mercs/titles/re5_qte.py` on PS3 (BLUS30491 01.01) does scoped QTE accumulator
assistance:

- Modes 4 and 6 compare the selected display unit's +0x2C float (progress) with its
  +0x30 target.
- The evaluator's true return reaches 0x8CD694, which invokes the real event callback.
- Only the progress float is changed; setting button success bytes would bypass the
  callback and is deliberately not implemented.
- Code signatures validate the build before any write.

PS3 addresses (not portable to Switch):
- `QTE_UNITS = (0x298, 0x2DC)` — offsets into the action-button manager
- `QTE_INPUT_TABLE = 0x0139E2C0` — the input mask table
- `QTE_BUTTON_VT = 0x016332A8` — the button vtable
- Code signatures at `0x000AC414`, `0x000ACA88`, `0x000ACBA8`, `0x000B7EF4`,
  `0x000B7FD4`, `0x000B8048`, `0x008CD6E4`

## What RE5 Switch Ghidra must find

### For `instant_qte` (the game's own auto-QTE option — preferred)

RE5 on PS3 does not expose an auto-QTE option in its menu. RE6 does. RE5 Switch may
or may not have the field. The Ghidra query:

1. **Find `cSystemInfo`**: search for the string `cSystemInfo` or `mTempData` in
   main's strings. Find its DTI (MtDTI pattern: `adrp x0 / add x0 / ret` or through
   GOT). The singleton instance pointer sits beside the DTI.
2. **Find `mExOptAutoActBtn`**: search for the string `mExOptAutoActBtn`. Its
   referencing code registers it as a property in `cSystemInfo::createProperty`.
   The registration gives the field offset.
3. **Find the copy pattern**: RE6 has two 0x5510-byte copies of cSystemInfo data
   (+0x8 and +0x5518). Check if RE5 Switch has the same double-copy layout.
4. **Find QTE readers**: search for code that tests the auto-QTE field nonzero.
   On RE6, every QTE site branches on it.

If RE5 Switch has this field, the op is a simple two-copy write (like RE6).
If not, fall back to the RAM progress approach.

### For `instant_qte` (RAM progress fallback)

If RE5 Switch lacks the auto-QTE option:

1. **Find the action-button manager**: on PS3 it is `sActionButton` with units at
   +0x298 and +0x2DC. On Switch, find the equivalent singleton (search for
   `sActionButton` or `ActionButton` strings, or find the QTE prompt code by
   searching for `Break free` / `Resuscitate` strings and tracing back to the
   manager).
2. **Find the QTE unit layout**: PS3 units are 0x44 bytes with progress at +0x2C
   and target at +0x30. Switch is 64-bit; the layout may differ.
3. **Find the button vtable**: PS3 uses `0x016332A8`. Switch will have its own.
4. **Code signatures**: find the equivalent Switch code sites that validate the
   build before any write.

### For `live_weapon`

PS3 path: `0x1AEE90 -> 0x9D417C / 0x9D693C -> 0x9D6520 -> 0x151540` constructs the
item and `uWp0f` mid-round. Switch needs:

1. **Find the item-construction path**: search for the string `uWp0f` or the item
   construction code. The PS3 path starts at `0x1AEE90`; Switch will have its own.
2. **Find the pickup serialization**: the PS3 op changes an ownerless ammo pickup's
   serialized source. Find the Switch equivalent.
3. **Verify no owner, weapon pointer, model, or owner is edited** — the PS3 op's
   safety invariant.

## Implementation plan (once addresses are known)

1. Add `AUTO_QTE = (offset, offset + copy_size)` to `re5_switch_mods.py`.
2. Implement `instant_qte(g, on)` following `re6_switch_mods.auto_qte`:
   - Read both copies, write 1 (or 0 for off), read back.
   - Store in `g.state["instant_qte"]`.
   - Return `{"instant_qte": bool(on), "verified": ..., ...}`.
3. Add `instant_qte` to `AVAILABLE` with the note.
4. Add `instant_qte` to `tool_run` and `run` routing.
5. Add tests in `tests/test_re5_switch_parity.py`:
   - `test_instant_qte_sets_the_auto_qte_field_in_both_copies` — mock guest with
     the cSystemInfo address, verify both copies read 1 after on, 0 after off.
   - `test_instant_qte_is_not_yet_on_switch_without_the_field` — if the field is
     not found, the op answers `verified: False` with the reason.
6. For `live_weapon`, follow the PS3 `re5_live_weapon.py` pattern with Switch
   addresses.

## Acceptance criteria

- [ ] `instant_qte` op writes the auto-QTE field (or progress) and reads it back
- [ ] `instant_qte` off restores the original value
- [ ] `live_weapon` op constructs a weapon mid-round through the native path
- [ ] Both ops report `verified: True` with live read-back
- [ ] Tests pass in `tests/test_re5_switch_parity.py`
- [ ] The panel's `capabilities()` shows both ops available

## Current blocker

Ghidra MCP is not running (connection refused on 127.0.0.1:8080). The RE5 Switch
main NSO has not been loaded into Ghidra. The addresses above must be found by
Ghidra analysis before implementation can proceed.

## Evidence

- RE6 Switch `auto_qte`: `gbox/mercs/titles/re6_switch_mods.py` lines 564-569
- RE6 Switch `auto_qte_ram`: `gbox/mercs/titles/re6_switch_mods.py` lines 739-743
- RE5 PS3 `instant_qte`: `gbox/mercs/titles/re5_qte.py` (entire file)
- RE5 PS3 `live_weapon`: `gbox/mercs/titles/re5_live_weapon.py` (entire file)
- RE5 Switch RAM map: `docs/research/re5-switch-ram.md`
- RE6 Switch RAM map (with Ghidra methodology): `docs/research/re6-switch-ram.md`

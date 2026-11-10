# Switch titles: RAM breakdown and Ghidra hooking, one index (request a67362b6c38444de, 2026-11-10)

Consolidated from the measured docs; every figure is cited from its source, nothing here is new measurement.
Offsets are module (main) offsets unless stated; Ghidra address = module offset + 0x100000 (ELF image base).

## 1. Method (same for all three titles)
1. Under NCE a guest address is the host address, so `/proc/<pid>/mem` reads it. ASLR moves main each boot: find it by
   scanning read-only rows for 64 unique bytes of main (RE5: +0x1191000, about 0.1 s, under 100 MB).
2. Statics: dump the NSO (`dump_nso`), convert with `scratch/agent/re6sw/tools/nso2elf.py`, open in Ghidra
   (`ghidra_bridge op=open`; RE5 main = 20,835 functions, about 40 min, held by the bridge process, so follow-up
   queries must run on the same worker). Anchors: `MtDTI::MtDTI` calls give each class DTI (+0 vtable, +8 name,
   +0x30 size>>2, +0x34 id); a singleton's instance pointer is the hottest 64-bit global beside its DTI.
3. Prove a field live (value tracks HUD/timer), not by static reading alone. RE4 lesson: a "clock" found by scan
   (copies 0x30 apart) was matrix floats in `mtxPalette`; always cross-check against the game's own state.
4. Hooks = native code written into verified zero padding through the HostMemory backing file with the owned emulator
   briefly stopped (RE5 `gbox/mercs/native/re5_ebffdb22`). Ghidra itself is static; it is not a ptrace hook.

## 2. RAM maps
| title | singletons / state | round fields | source |
|---|---|---|---|
| RE5 `010018100CD46000` (build EBFFDB22...) | sMain +0x26A1BA8, sPlayer +0x1CF1C98, sEnemy +0x1CF04B8, sUnit +0x26A3270; cGameSys = [sBioMain+0x584E0] | phase +0x944, time +0x948 f32, kills +0x96C, combo +0x974, score +0x990; player pos +0x60, quat +0x70, hp s16 +0x1EB8 (max +0x1EBA) | docs/research/re5-switch-ram.md |
| RE6 `01002A000CD48000` v131072 | sGameMan +0x28E9B10, sPlayer +0x28EAC10, sEnemy +0x28E9AA8, sInfoMan +0x28E9BE0 | phase +0x3DEC, time +0x3DF0 (per-frame copy: writes overwritten), kills +0x408C, combo +0x4094, score +0x40B0; unlock flag cSystemInfo+0xB8 bit 0; grenades: player inventory 24 cItem x0x28 at +0x5070 | docs/research/re6-switch-ram.md |
| RE4 `010099A00BC1E000` | pG = *(0xB1AE08) = 0x1274338; ITEM_MGR 0x124D918; MercSysWk 0x124F690 | System_flg pG+0x78, frame step +0xA4, Stop_flg +0x1A8, Status_flg +0x5090, life +0x5028; intro run +0xD4, round run MercSysWk+0xD9 | re4-switch-game-state.md, re4-weapons-ram.md |

## 3. Flashbang / grenade hooks (umbrella 5972)
- RE5: native flash construction `main+0x1C21C0` (sItem 0x1CF1408, DTI 0x1D71538); detonation `60D6D0(unit,1,0,0x108,1)`,
  callback `820E50`, base update `806B80`. Accepted when allocation, owner, generation and exploded flag all match
  afterward. Measured: 20 requests -> 20 confirmed explosions in 2325 ms (Sheva Cos1); cold first click 1848.8 ms, 442.5 ms
  after PR1598. Receipts: re5-production-flash-1793342443371018469 / ...949121516917 / ...975883739932 (Spark).
  The "20 grenades in two seconds" goal is NOT proven as a guarantee (2325-2505 ms measured).
- RE6: grenade/flash types 0x113 hand, 0x114 incendiary, 0x115 flash, 0x116 remote bomb; throw records 0x13-0x15.
- RE4: flash x3 only in Krauser/Wesker loadouts (0x295070); no native-throw hook exists yet.

## 4. Open items (not done here)
- A live RE4/RE6 native flash hook equivalent to RE5's has not been built.
- This index changes docs only; no live session was run, so there is no runtime acceptance for this request.

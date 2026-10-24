# Splinter Cell Pandora Tomorrow (GC, d11d44eeacdd5e31) unlock research - static milestone

Status: in progress. Evidence is read-only from the owned gcz via gbox.gcdisc.GCDisc.

- game code GT7E41; source gcz sha256 84478e9c30c4bf9d9f01c6556de7ef8a2806d5c74652240b0ab0ece4506ef42b
- main.dol 4180640 bytes sha256 c3a4c6e5c99f8541ec9dd2b6a3fb37381e08b4b0b1fe8f61300a7061c1cc28f2 entry 0x803f7a40
- DOL strings: UnlockLadder, UCheatManager, bCheat, LoadProfile, UpdateProfile, SL_UpdateProfile, GetSavedGameVariables, PutSavedGameVariables, UGCNSaveGameDevice
- Unlock logic is UnrealScript in dataGCN UE2 packages; profile lives on memory card. Not yet traced.
- Prior-run claim verified only partly: spt_gc_inventory.py exists in sibling workspace 7389576ca1a74fdc (not this one); no GCEE41 Gecko mechanism found for this game.
- Inventory of characters/modes/levels/costumes/items: unknown (not yet derived).

Next: parse .u packages for UnlockLadder/profile vars, Ghidra main.dol, revision-guarded save overlay or Gecko, runtime test on idle i9-NUC/Spark.

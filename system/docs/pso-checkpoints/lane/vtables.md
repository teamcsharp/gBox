# Lane-log text of `ds-pso-vtables-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `e2d5191e`.

----

## Round 53 (2026-11-10, later session) — A7: the travel primitives have no gate; the pad's handler is the next hunt

Working locally; no lilspark, no live session.

P2b item 7 asked what the city teleporter checks before it opens. Decompiled on the existing Ghidra project:

* **The primitive is unguarded.** `SET_TARGET` (`0x80228540`) is a plain store into the travel target at `0x80515BA0`;
  `BEGIN_TRAVEL` (`0x8000F998`) sets the load-request flag; `WARP` (`0x801BAB1C`) runs the party transition. Every
  caller decides for itself — which is why `pso_fence.warp_to_floor` works live regardless of quest state.
* **The callers found:** `FUN_80136C94` is the game-start load (fixed target, after `s_Game_start__d_8043efd4`);
  `FUN_8019C988` is a party-warp helper (destination id from `this+4`, compared with the current area); `FUN_8019C05C`
  and `FUN_8019CA24` are the lobby/party transition helpers (`this+0xbc`, with a `WARP` after the travel). The rest of
  the 13 callers are listed in the note for the next pass.
* **Where it stopped:** the city pad is an object (`TObjCityAreaWarp` class `0x5d`, `TObjCityMainWarp` `0x5c`) whose
  interaction handler is the thing to read, and that needs its vtable. The class registry (`0x805D3138`) holds only
  name pointers, and there is **no `lis/ori` reference into it** because PSO reaches globals through **`r13`**, the
  GameCube small-data base (the decompiler shows `unaff_r13 - 0x5260` throughout). So the next step is to pin `r13`
  (consistent with a base in `0x805D7Dxx`–`0x805DDxxx`) and then find the loader that indexes the registry by `kind`;
  from there the class constructor, its update and the pad's interaction — and the condition, if there is one.

Written up in `docs/research/pso-travel-and-gate.md`. No code change: the actionable output is that the dev warp is
legitimately gate-free (so editor/survey evidence may use it, labelled "reached by warp"), and P1's quest route stays a
live problem until the pad handler is read.

## Round 56 (2026-11-10, later session) — the class vtables are found, and the city pad is not a class object

Working locally; no lilspark, no live session.

A7's hunt reached the vtable convention: a class's vtable starts with a pointer to its **registry slot**
(`0x805D3138 + id*4`), then `0x00010000`, two zeros, the method pointers and two data pointers
(`0x804B4280` = slot 6, `0x804B4308` = slot 8). Scanning the whole DOL for such headers finds vtables for **38 of the
registry's 148 classes** (in `0x804B4200`-`0x804B9000`).

**The decisive negative:** no vtable header anywhere points at the `TObjCityMainWarp` (`0x5c`) or `TObjCityAreaWarp`
(`0x5d`) slots - nor at `0x02`/`0x10`/`0x46` for comparison. The city pad is therefore not an object of those classes in
this build; the city's warp triggers are most likely event-set driven (`map_city00*.evt`), with the `TObjCity*Warp` names
left over from another version. That is also the simplest explanation for "the teleporter does not answer" however it is
approached.

**Next:** read the city event set and the `TObjMapWarp`/`TObjAreaWarp` family (which *is* in the 38-class census) for
the trigger, the destination and any quest condition. Written up in `docs/research/pso-travel-and-gate.md`.

# PSO's travel primitives, and where the city teleporter's gate is *not*

Measured 2026-11-10, later session, on `PsoV3.dol` (owned `GPOE8P` disc, i9-NUC) with the existing Ghidra project
(`D:\gBox\ghidra-pso\PSO`). Work for the lane's P2b item 7 ("the Ragol teleporter / quest gate in code"): this note
records what the primitive looks like and narrows where the gate can be, so the next pass starts from evidence.

## The three primitives

| address | name in `pso_fence.py` | what the disassembly shows |
|---|---|---|
| `0x80228540` | `SET_TARGET` | stores the travel destination into the global target at **`0x80515BA0`** - arguments `(target_ptr?, id, flags)` |
| `0x8000F998` | `BEGIN_TRAVEL` | sets the area-load request flag |
| `0x801BAB1C` | `WARP` | executes the party area transition |

**The primitive is unguarded.** `SET_TARGET` is a plain store; `BEGIN_TRAVEL` sets a flag. Every caller we found does
its own decision first, so a quest check - if one exists at all - is in the *caller*, never in the primitive. That is
also why `gbox.pso_fence.warp_to_floor` works live regardless of quest state: it calls exactly these three, verified
on 11-03/04.

## The callers we found (decompiled, i9-NUC)

* `FUN_80136C94` - the **game-start load**: `SET_TARGET(0x80515BA0, 0, 0)` then `BEGIN_TRAVEL`, right after
  `s_Game_start__d_8043efd4` and the player/party reset. This is the entry warp into the city, not a selectable one.
* `FUN_8019C988` - reads a destination id from `this+4` (`lha r0,0x4(r31)`), compares it with the current area
  (`bl 0x800196EC`), and if they differ calls `SET_TARGET(0x80515BA0, id, 0)` + `BEGIN_TRAVEL`, then
  `FUN_8024AEAC` and a party pass. A **party-warp helper** ("take this object's target area id").
* `FUN_8019C05C` and `FUN_8019CA24` - the same shape with the id coming from `this+0xbc` (lobby/party state) and,
  for `FUN_8019CA24`, a `WARP` call after the travel and a second `FUN_8019DCD0` target fix-up. These are the
  **lobby/party transition helpers**.
* `FUN_801A1260` and the `0x801B30BC/3274/31D8`, `0x802348B4`, `0x8026D18C`, `0x8034E7A0/E708`, `0x801ED468`,
  `0x8019C05C..` family - the remaining callers, in the same lobby/menu families (listed for the next pass).

So the city's teleporter pad is *not* one of these: it is an object (`TObjCityAreaWarp`, class `0x5d`; `TObjCityMainWarp`,
`0x5c`) whose interaction handler decides whether to call a helper like `FUN_8019C988`.

## Where the search stopped, and the exact next step

Finding the pad's handler needs its class's **vtable**, and the class registry at `0x805D3138` gives only names. The
class *name* pointer is not stored in the vtable (the only pointer to it is the registry slot), and there is **no
`lis/ori` reference into the registry window** in `.text` - PSO reaches its globals through **`r13` (the GameCube small
data area)**, as the decompiler's `unaff_r13 - 0x5260` shows everywhere.

**The next step is therefore mechanical:** pin `r13` (the SDA base - the last two data sections are
`0x805D2600+0x23A0` and `0x805D7D00+0x9500`, and the decompiled offsets (`-0x5260`, `-0x5070`, `-0x45A0`, `-0x36F0`)
are consistent with a base in `0x805D7Dxx`-`0x805DDxxx`), then look for the loader that does
`r13 + (0x805D3138 - r13) + kind*4`. From there: the class's constructor/vtable, its update, and the pad's interaction -
where the quest/party condition will be visible.

Until then, the honest statement for P1 is: the *primitive* has no gate, the live-verified dev path bypasses every
condition by design, and the city pad's condition (quest state, party state, or nothing at all) is still unlocated. That
is why the lane's live work should keep using the dev warp for editor and survey evidence, and keep the quest route as
P1's own acceptance problem.

## The class vtables, and the pad that does not have one

The lane found the class-name registry (`0x805D3138`, A3) but no way to reach a class's code. This pass found the
convention and the answer for the city pad.

**Convention.** A class's vtable carries its identity in its first word: a pointer at the **registry slot** of the class
(`0x805D3138 + id*4`), followed by flags (`0x00010000`), two zero words, then the method pointers, then two data
pointers. Two examples, read out of `.data`:

```
0x804b4280: 0x805d3150   -> name slot 6, then 0x00010000 0x00000000 0x00000000, 22 code pointers, 0x80442a38 ...
0x804b4308: 0x805d3158   -> name slot 8, the same shape with its own methods
```

**Census.** Scanning the whole DOL for a word equal to a registry-slot address finds vtables for only **38 classes**
(slots 6, 8, 10, 12, 14, 26, 28, 29, 30, 34, 46, 47, 86-90, 98-100, 104-107, 116, 118, 119, 128, 130, 140-142, 152,
166, 192, 194, 196, 197), across `0x804B4200`-`0x804B9000`. The registry names **148** classes. So the executable
instantiates fewer than a third of them as C++ objects - the rest are names only.

**The city pad is not among them.** A direct search for a vtable header pointing at the `TObjCityMainWarp` (slot `0x5c`)
or `TObjCityAreaWarp` (`0x5d`) name slots finds **nothing**, and neither do the ordinary object classes probed alongside
them (`0x02` TOSensor, `0x10` TOSwitchAttack, `0x46` TObjCityDoor_Shop). The pad therefore is not an object of those
classes in this build: the likely truth is that the city's warp triggers are **event-set** driven (`map_city00*.evt`),
with the `TObjCity*Warp` names left over from another version, which is also the simplest explanation for "the
teleporter does not answer" however it is approached.

**Next step.** Read the city's event set and the `TObjMapWarp`/`TObjAreaWarp` family (whose entries *are* in the
38-class vtable census) instead of the pad classes: the trigger, the destination and any quest condition should be in
the event/`AreaWarp` path, not in a `TObjCity*Warp` update.

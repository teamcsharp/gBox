# Lane-log text of `ds-pso-sda-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `28def085`.

----

## Round 54 (2026-11-10, later session) — the small-data bases, and the tool that maps the globals

Working locally; no lilspark, no live session.

The A7 hunt stalled on "the class registry has no code reference". The reason is now measured: PSO keeps its static
state in the **small data areas**, and the CRT sets the bases in the init section at `0x8000C180`:

* `r2 = 0x805CFD00` (`_SDA2_BASE_`, the float pool - the `unaff_r2 - 0x36f0` in decompiled code);
* `r13 = 0x805CA600` (`_SDA_BASE_`, the small data area - the `unaff_r13 - 0x5260` everywhere).

Everything within `r13 ± 32 KiB` (i.e. `0x805C2600`..`0x805D25FF`) is addressed by displacement, and **anything above
`0x805D25FF` cannot be**: the class-name table at `0x805D3138`, and `pso_ram.FLOOR` at `0x805D5FC0`, both sit outside
it. So a `lis`/`ori` search over the DOL was never going to find their readers - they are reached through pointer
variables or `addis`, which is the line the next pass should follow.

**New tool `gbox/pso_sda.py`:** `SDA_BASE`/`SDA2_BASE` pinned to the measured values, `sda_address()` (strict about the
±32 KiB window), and `globals_used(dol)` - decodes every D-form load/store through `r13` and returns
`{address: [pcs]}`, **4,803 distinct globals** on the owned disc, plus `candidates(dol, known={...})` to name the ones
already known. Tests (`test_pso_sda.py`, 5): the base values, the window, a synthetic DOL with three r13 accesses (and
one non-r13 that must be ignored), the name mapping, and the real disc (>1,000 globals, all in the window, `FLOOR` not
among them - the point of the module).

This is the groundwork for the next A7 step: with the globals enumerated, the class-name pointer variable and the pad's
handler are searchable by *what they touch* rather than by address.

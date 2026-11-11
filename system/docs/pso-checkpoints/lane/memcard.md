# Lane-log text of `ds-pso-memcard-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `1438cf10`.

----

## Round 55 (2026-11-10, later session) — A10 first pass: the lane's memory card has three PSO saves and none has data

Working locally; no lilspark, no live session.

The lane's notes said the Dolphin card holds a PSO directory entry but "no character". Measured precisely with a new
reader (`gbox/pso_memcard.py`, tests in `test_pso_memcard.py`) against
`D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw`:

* **three** PSO entries, at `0x20C0` (`PSO_SYSTEM`), `0x2100` (`PSO_CHARACTER`) and `0x2140` (`PSO_GUILDCARD`), game
  `GPOE`, company `8P`, plus the same three in the spare directory at `0x40C0`/`0x4100`/`0x4140`;
* **every one of them has first block `0xFFFF` and block count 0** — an entry with no data blocks at all. The BAT has
  no chain to follow. So there is no PSO save payload on this card: nothing for a save-layout study, and it is exactly
  why SELECT CHARACTER shows four `NO DATA` slots.

This is a negative result with a clear consequence: **A10 cannot start from this card**, and P1's character screen
cannot be satisfied from it either. The two ways forward are the operator's (a save that already holds a character, or
the in-game creation screens) — the same decision the lane already asked for, now with the card itself as evidence
rather than an inference.

The reader is in the repo so the check is reproducible: `entries()` (directory + spare, real entries only), `chain()`
(BAT walk, stops on a loop), `saves(game=...)`, `read()` (16 MiB validation). Tests: entry fields, an entry with no
blocks, a three-block chain, a looping chain, junk entries ignored, and the real card asserting the three PSO saves
exist with no data.

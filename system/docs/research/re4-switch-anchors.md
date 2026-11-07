# RE4 Switch anchors: the live scan, and where it stands (2026-11-07)

The two anchors `RE4_REASON` names (`S_PLAYER`, `S_EMMGR`) came one step closer: the module base is confirmed live and
the health search runs. What is not yet done is the last narrowing step, and this note records exactly why.

## What worked

**The base is confirmed, not assumed.** Reading 32 bytes at `0x3CA7C04000 + 0x100000` through
`GET /api/sessions/{sid}/ram/hex` returns the driver's own measured signature:

```
0x3CA7D04000 -> fd7b07a9fdc30191355100b0b5c646f9a90240f928514439f30300aa88080035
```

`module_base = 0x3CA7C04000` for that boot, so `base + vaddr` addressing is real for this title.

**The health search runs over `.bss` and narrows.**

```
POST /api/sessions/{sid}/ram/search {"type":"u16","base":0x3CA8730738,"size":7602176,"tolerance":0}
  -> 3,801,088 candidates (dense, little-endian)
POST /api/sessions/{sid}/ram/search/sample {"op":"equals","value":100}
  -> 400 candidates
```

## What blocked the last step

1. **`.bss` is not fully mapped.** The ELF describes `.bss` as `0xb2c738` + `0x11938c8` (18,430,152 bytes), but reading
   past `0x3CA8E70738` fails with *"Switch address … is not mapped guest memory"*. The usable window is 7,602,176 bytes of
   the 18.4 MB, so a whole-`.bss` scan is not available through the reader as it stands.
2. **A `100` is not health.** 400 addresses hold `u16 == 100`; the top-scoring ones form a **64-byte array whose element
   index counts 0,1,2,3,…** at `+4` - a table, not a unit. Scoring a candidate by "has 100 nearby" does not separate them.
3. **The decisive filter was consumed.** `decreased` after an 18-second walk returned **0**, so the candidate set became
   empty and the second pass started from nothing (`candidates: 0`). The filter itself is the right one - nothing had
   dropped, and once emptied a search cannot be re-filtered without a new snapshot.

## The procedure to run next, in order

```
1. POST /ram/search {type:"u16", base: base+0xb2c738, size: 7602176}    (inside the mapped window)
2. POST /ram/search/sample {op:"equals", value:100}                     -> ~400
3. confirm Leon is actually being damaged (a hit, not just walking): watch the frame for the red flash
4. POST /ram/search/sample {op:"decreased"}                             -> health only
5. unit = survivor - 0x3C2;  S_PLAYER = a pointer to that unit found in the module's data
6. S_EMMGR: stride/scan around that unit for neighbours that also read as units
```

Steps 1-2 are verified; step 3 is where the last attempt failed, by walking without confirming a hit. The fix is
behavioural rather than technical: engage until damage is visible, then sample.

## Cost note

Each of these rounds boots the Switch title and stops RE5, because one emulator runs at a time. The measured cost is about
five minutes per boot plus the walk, and RE5 has to be restarted afterwards (stop → confirm no `eden` → start once). That
is why this work is done in bounded passes rather than a long loop.

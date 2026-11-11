# CP07.1 the model-walk crash at `0x8028f508` — done

Session identity: DeepSeek    Branch: ds-pso-cp07-model-walk-20261110    Commits: this branch
Goal: 1 (and through it CP12's rigged swap)

## The address is an instruction, not a function

`0x8028f508` lies at **+0x268 inside `FUN_8028f2a0`** (1,024 bytes, body `[8028f2a0, 8028f69f]`) in the Ghidra project
`D:\gBox\ghidra-pso\PSO` (program `/pso_v3.elf`). What round 35 saw was the faulting *instruction*:

```
8028f508  lfs f0,0x8(r4)     ; the first float of a vec3 reached through [[entry+0x18]] + 4
```

with the surrounding block a per-frame **pose composer** over a 5-entry table: each entry is `{flags, ptr}`; `ptr[+4]` is a
structure whose `+8 / +0xc / +0x10` (one vec3) is read from three sources and written back as a weighted sum
(`_DAT_8051d274 * srcC + _DAT_8051d26c * srcB + _DAT_8051d270 * srcA`). The decompile excerpt and the disassembly are in
`docs/research/pso-gc-executable.md` **section 9** (new), with the field described as: *the X component of a model/pose
vector at +0x8, Y at +0xc, Z at +0x10*.

## The check the accept asked for, from the file

`gbox/pso_swapfit.py` now reads that field out of the NJCM payload, not from a model's opinion:

* `model_centres(nj)` walks the body and returns each node model's four floats at `model+8` (centre X/Y/Z, radius) — the
  same vec3 the runtime walk composes;
* `signature_nj` adds **`models`** (nodes with a model — the list length the 5-entry walk indexes) and **`centre_ok`**
  (all those vectors finite);
* `compare()` refuses when either side's `centre_ok` is false (reason names `0x8028f508`) or when the model-list lengths
  differ. This is what the editor page's swap-fit gate and `body_swap` use.

**Measured on the owned disc:** bones are 64 on every class (so they never discriminate); the model lists are
**HUmar 18, HUnewearl 20, HUcast 18**, and all centres are finite. That reproduces round 35's two outcomes from the files
alone: A<-B (20 vs 18, and 8 buckets vs 5) is the crash case; A<-C (18 vs 18, 311 vs 269 vertices) is the deform case.

Tests: `tests/test_pso_swapfit.py` **11 passed** (7 pre-existing + 4 new: the +0x8 refusal with a NaN centre, the
model-list mismatch with chained nodes and child/sibling as byte offsets, the synthetic signature, and the three real
bodies' measured counts).

## What is still open in CP7

- item 2, the object loader (what turns a placement `kind` into a constructor call) — coverage above 84.4 % is the accept;
- item 3, the scene loader (`n.rel`/`r.rel` and its transform) — CP8/CP14 need it, and CP3 already exported the functions
  that reference those strings (`801fb798` `r.rel`, `802066bc`/`80206db8` `n.rel`), so it is the next target.

Tests: no other suites changed. CP0 baseline unchanged (45 failed / 1,329 passed / 132 skipped).

Next: CP7.3, the scene loader, from the CP3-exported `n.rel`/`r.rel` functions.

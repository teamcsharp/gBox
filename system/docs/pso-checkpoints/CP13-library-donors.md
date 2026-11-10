# CP13 (P7b): library donors, per boot and then hot

Session identity: DeepSeek    Branch: ds-pso-cp13-library-donors-20261110    Commits: this branch
Goal: 3

## Round 84: the per-boot donor list runs through CP12's path - one clean, one donor-specific defect

CP13's first step is "a donor from gBox's character library, retargeted to PSO's 64-bone skeleton by CP12's path, built, and
shown at character select". The build half of that now runs offline for **every** library donor, because CP12's path is
proven end to end (`build_swap` -> `pso_swapfit` gate -> body export -> headless Blender render on the 3090). Two donors were
run through it:

| donor | model | source -> baked triangles | scale | gate | body | render |
|---|---|---|---|---|---|---|
| **Daisy** (`daisy_ssbu`) | 10.2 MB | 23,635 -> **788** | 1.3466 | **SAFE**, subset buckets (518 vertices against the host's 311) | 44,424 B, 582 vertices, 673 triangles in the render, bounds x -8.81..8.80 / y -12.01..7.14 / z 0.03..25.51 | **coherent figure in a full dress** (`D:\\gBox\\pso-ds\\renders\\cp13-daisy.png`) |
| **Cloud** (`cloud_ssbu`) | 16.4 MB | build completed | - | **not reached** | 50,608 B, **unparsable** | - |

**Cloud's defect, isolated:** the build writes the body, but `ninja.NJ(body, be=True)` desynchronises while walking two nodes'
polygon lists - node **0** and node **39** - running off the 50,460-byte payload (node 0's walk reaches offset 0x20960, node
39's 0xfaca, against a payload of 0xc51c). The other 62 nodes' lists walk cleanly, so this is data-dependent, not a general
writer break: the two nodes whose lists overrun are exactly the kind that carry the host's kept vertex chunks
(`keep_vlist`) plus new geometry, and their chunk stream stops looking like chunks (bogus types 52/20/46 and 32/48 at the
last positions). The diagnosis script is kept as `docs/research/pso-cp13-cloud-body-walk.py`; the next step is a
node-by-node byte comparison against Daisy's clean body, which keeps the same shape but smaller chunks.

**The render for Daisy** was produced with the same headless path as CP12: Cycles, 64 samples, 900x900, **RTX 3090 only**
(`devices_enabled: ["NVIDIA GeForce RTX 3090"]`), importing the OBJ exported from the *game* body (per-corner snapshots), so
the image shows what the game will draw, not the donor source.

## What CP13 still needs

1. **the fix for Cloud-style donors** (nodes with both kept host vertex chunks and new geometry);
2. **the "per boot" half in game**: pick a donor from the library in the character menu and see it at character select - needs
   the CP4 window;
3. **the "then hot" half**: swap the donor without returning to the menu - the same window, after the per-boot case works.

Tests: no new unit tests this round (both donors are end-to-end artifacts); the CP12 snapshot test (`1 passed`) guards the
export that produced the Daisy render.

## Round 85: the Cloud diagnosis above is wrong, and here is why (correction)

The round-84 claim that "Cloud's nodes 0 and 39 overrun their polygon lists" does **not** survive a byte-level look. The
model struct is `{u32 vlist, u32 plist, float centre x3, float radius}`, and for both bodies node 0's model at `0xd00` reads

```
vlist 0x0   plist 0xd18   centre (6.14.., 0.00.., ...) radius ...
0xd18:  ff 00 | 00 00 00 00 0d 34 | 40 c4 ac 73 ...     <- 0xFF is an EMPTY polygon list, then the floats
```

i.e. `plist` addresses an **empty list** (a lone end chunk) and everything after it is the model's centre/radius floats. My
round-84 walker started at `plist`, read the end chunk, then kept walking into those floats and pinned the "overrun" on
arbitrary float bytes - which is exactly what it also did on **Daisy** (it reported `unknown 0x3c` / `unknown 0x78` /
`unknown 0xc` for Daisy's nodes 0, 26 and 39). So the comparison was measuring my own walker, not the bodies.

**What is actually known about Cloud:** `ninja.NJ(cloud_body, be=True)` raises in `_polys` with an offset beyond the payload,
and the body is 50,608 bytes with 64 nodes, **18 non-empty polygon lists**, and every model pointer in range. The failure is
therefore inside one of those 18 lists, and the next step is to instrument `NJ._polys` itself (record the node and offset
when the walk overruns) rather than reimplementing it - a walker outside the class cannot know where a list legitimately
ends.

That correction is the round's real result: it stops the next session from chasing a defect that the evidence never showed,
and it narrows Cloud to "one of 18 lists, found by instrumenting the parser".

## Round 86: Cloud narrowed to two lists, with the parser itself as the measuring instrument

The round-85 correction named the next step ("instrument `NJ._polys` itself"). That is now done
(`docs/research/pso-cp13-cloud-per-node.py`), and the result is unambiguous:

| body | node 0 (`plist 0xd18`) | node 39 | the other 16 non-empty lists |
|---|---|---|---|
| **Daisy** (clean) | **ok**, 0 texture buckets | ok | ok |
| **Cloud** | **FAILS**: `unpack_from ... 133472 (buffer 50460)` | **FAILS**: `... 64202` | **ok** - 16 lists parse (nodes 2, 4, 5, 8, 13, 14, 17, 25, 26, 28, 29, 34, 41, 42, 47, 56) |

So Cloud's defect is confined to **the root's list and one other node's list**, and in both cases the walk leaves the payload
after these chunk reads:

```
node 0:  0xd18 0xFF00 (null)  -> 0xd1c 0x0000 (null) -> 0xd1e 0x0d34 (0x34) -> 0xd22 0x1314 (type 0x14, size 0x4022)
         ... jump to 0x8d6a (type 0x2e) ... then out of the 0xc51c payload at 0x20960
node 39: 0x7b06/0x7b08 (nulls) -> 0x7b0a 0x20 -> 0x7b0e 0x30 ... out of the payload at 0xfaca
```

**What is *not* yet established - and deliberately not guessed this round:** whether the root's `plist` is genuinely a polygon
list in Cloud's body or points into the model/pointer region. Two facts argue for the latter: the same offset in Daisy walks
to an end chunk without trouble, and the values at `0xd22` (Cloud `0x1314`, Daisy `0x243c`) are exactly the *next node's
polygon-list pointer* - i.e. this region looks like a pointer/model table, not a chunk stream. The round-85 lesson applies
again: a walker that starts where a pointer happens to point proves nothing until it is shown that the pointer addresses a
list. The next step is to compare the **model structs** of node 0 in both bodies word by word (vlist/plist/centre/radius) and
to dump the bytes at each node's model, rather than at its `plist` target.

The instrument is committed and reusable for any donor: `python pso-cp13-cloud-per-node.py <body.nj>`.

**Unchanged this round:** Daisy remains a clean end-to-end donor (gate SAFE, 788 triangles, coherent render); Cloud remains the
one donor whose body does not parse, now localised to two lists.

## Round 87: the Cloud defect found and fixed - the empty polygon list was written little-endian

The round-86 probe localised the failure to node 0's and node 39's lists. Reading `write_tree`'s model layout showed what
those lists should be, and the bytes showed what they were:

```
model struct = {u32 vlist, u32 plist, f32 centre x3, f32 radius}        (write_tree, 24 bytes)
node 0: vlist 0x0, plist 0xd18      ->  the node has NO geometry, so plist is the empty list
at 0xd18 in BOTH bodies:  ff 00        <- 0x00 0xFF in LITTLE-endian
```

`build_swap` built that empty list as

```python
empty_pl = struct.pack("<HH", 0xFF, 0)      # hard-coded little-endian
```

so in a big-endian GameCube body the end-of-list marker `0x00 0xFF` was read as the **null chunk `0xFF00`** and the parser
walked past the end of the list into the model's centre/radius floats. Whether that then crashed depended on those floats'
low bytes: **Daisy's 0x3C is not a chunk type, so its list stopped gracefully (which is why Daisy appeared clean);
Cloud's 0x14 is a material chunk, so the parser read a bogus size (0x4022) and ran off the payload.** The bug was present in
every built GC body and Daisy had simply been lucky.

**The fix** is one line - `struct.pack(e + "HH", 0xFF, 0)` - and with it:

| donor | triangles | scale | gate | body | parse |
|---|---|---|---|---|---|
| Daisy | 788 | 1.3466 | SAFE, subset | 44,424 B, 582 vertices | ok |
| **Cloud** | **857** | 1.1249 | **SAFE, subset** | 50,608 B, 792 vertices | **ok** |

Cloud's body now renders (`D:\gBox\pso-ds\renders\cp13-cloud.png`, Cycles 64 samples 900x900, 3090 only): a coherent
armoured figure with its great sword, bounds x -3.89..4.46 / y -18.04..3.56 / z -0.10..23.75.

**Branch note:** this branch was **rebased onto `ds-pso-cp12-rigged-swap-20261110`**, because the swap path needs CP12's
endianness fixes (readers, writers, BML and the gate); CP13's commits only add evidence, a script and the donor builds, so the
rebase was clean. The branch therefore stacks on CP12 and must be reviewed after it.

## Round 88: the same endianness bug in a second place - and a third donor at 708 triangles

A third donor (**Bayonetta**, 13.9 MB) was run to test whether the round-87 fix generalised. It did not - and the failure was
the *same class of bug* in a second place:

```
node 13's vertex list, chunk trace: 0x29 (size 0x2b) -> 0x2c (0x40) -> 0x2c (0x2b) -> word 0xFF000000
```

`0xFF000000` is `struct.pack("<I", 0xFF)` read big-endian: a **null chunk with size 0xFF00**, so the vertex walk skips ~260 KB
and leaves the body. The writer had it in `build_swap`'s kept-vertex-list branch:

```python
models[j] = (keep + struct.pack("<I", 0xFF) if keep else b"", empty_pl, ...)     # hard-coded little-endian
```

so **the vertex-list terminator** (not just the polygon-list one from round 87) was written little-endian. Fixed to
`struct.pack(e + "I", 0xFF)`.

**All three donors now build, gate and parse:**

| donor | source -> baked | scale | gate | body | render |
|---|---|---|---|---|---|
| Daisy | 23,635 -> 788 | 1.3466 | SAFE, subset | 44,424 B, 582 v | coherent figure in a dress |
| Cloud | 19,926 -> 857 | 1.1249 | SAFE, subset | 50,608 B, 792 v | armoured figure with a great sword |
| **Bayonetta** | **30,634 -> 708** | **0.7535** | **SAFE, subset** | **49,196 B, 496 v** | **winged figure** (bounds x -18.65..18.64 / y -3.19..10.50 / z -0.17..27.83) |

**The two bugs together explain the donor-dependent behaviour** of rounds 84-87: both end markers were little-endian, so any
body whose node handed the parser a "plausible" chunk header after a mis-terminated list would either walk off the payload
(Cloud, Bayonetta) or stop by luck (Daisy). Every built GC body carried both bugs; only some donors exposed them.

**New tests:** `tests/test_pso_body_endian.py` **3 passed** - a synthetic two-node body with an empty polygon list parses in
**both** endiannesses, and a test that pins the exact round-87 byte fact (`struct.pack("<HH", 0xFF, 0)` read big-endian is
`0xFF00`, a null chunk, not an end marker).

**CP13's remaining work is unchanged and live-only:** the per-boot donor pick at character select and the hot swap, both in a
CP4 window. The offline half now covers three donors end to end.

## Round 88 addendum: the endianness sweep finished - the head stand-in was little-endian as well

With the two end-marker bugs fixed, a sweep of `pso_player.py` for remaining hard-coded little-endian writes found one more
real one: **`speck_nj`**, the one-node placeholder written over the class **head / hair / cap** parts, built its node tree,
its `trs` and its container with the default little-endian. A GameCube swap therefore carried little-endian head stand-ins
that the game would read as garbage (an invisible or exploded head, and possibly the crash dialog).

Fixed: `speck_nj(e="<")`, with the `trs` pack and the `write_tree` call following `e`, and **both** call sites inside
`build_swap` passing the container endianness. The other two little-endian writes that remain are platform-invariant by
design: the `NJCM` container size and the `POF0` header length are little-endian on both Dreamcast and GameCube (`ninja`
documents this explicitly).

Suites: `test_pso_body_endian.py` + `test_pso_gc_swap.py` + `test_pso_swapfit.py` = **22 passed**.

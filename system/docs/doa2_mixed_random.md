# DOA2: Sonic Adventure 2 vs Super Mario 64 DS, a random donor on every selection

Inbox request #1652 asked for "a build of Dead or Alive 2 on Dreamcast where half the cast is Sonic characters from
Sonic Adventure 2 and half the cast is Super Mario 64 DS characters where it randomly assigns the character to the
person each time a character is selected". A later message added: "I need those characters battling in the same
game." The game is the JP Limited Edition (`1de2e7634f3161ff`, `1ST_READ.BIN` sha256 `27a014ae...c97e1`).

The mod is `doa2_sonic_vs_mario_random`, built by `gbox/doa2_mixed.py` with the select patch
`gbox/doa2_random_select.py`.

## Design

**Approach (a): per-fighter costume pools, plus a randomised costume on selection.** DOA2 loads a fighter as a
(render slot, costume) pair. Every costume has its own CHR/BIN/SUP/APV/ACS files, render script and file-table row.
So:

1. **Every costume of every selectable fighter gets its own donor.** That is 75 costumes over 14 fighters, written
   by the existing per-costume writer (`doa2_swap.prepare`): retarget onto the costume's verified rig, native skin
   fit with at most two influences, SUP seam plan within the 14-descriptor limit, CHR/SUP budgets, and the APV and
   ACS supplements disabled as in every roster build. A donor whose textures overflow the native pages is retried
   with explicit downscaling (Bowser).
2. **Half and half.** 7 fighters are headlined by an SA2 character and 7 by an SM64DS character (their first
   costume). Every pool alternates the two franchises, so a pick of any fighter can come up Sonic or Mario. Tengu,
   which has only two costumes, holds one of each. Two players can meet as Sonic vs Mario in the same fight.
3. **Random on every selection.** When a human confirms a fighter, the select-screen patch draws that player's
   costume uniformly from the fighter's pool before the selection is committed. The game's selection tables, the
   loader (file table `0x8c17f5f4`), the render script (`0x8c1c85f4`) and the actor therefore all use the same
   index, and picking the same fighter again can bring a different donor. CPU opponents keep the game's own random
   costume routine.

Approach (b), a runtime hook that remaps the model load, was not needed. Hooking the loader alone would leave the
render script, the accessory table and the actor on the costume the player chose, and they would disagree with the
geometry.

### The select patch

These are static findings; they are also listed in `docs/doa2_re_findings.md`.

| Address | What |
|---|---|
| `0x8c0262e0..0x8c02631e` | Human confirm handler. `r14` = cursor record (select base `r12` + player << 7), `+1` render slot, `+2` costume. It calls the commit routine through the pool word `0x8c02638c`. |
| `0x8c02a1ca` | Commit: cursor `+1`/`+2` into the selection tables `0x8c239d50` / `0x8c239d64` (and mirrors), for every mode. |
| `0x8c120cf0` | `rand()`: LCG, seed `0x8c1e64e0`, 15-bit result. The CPU's random pick (`0x8c02ac04`) uses it. |
| `0x8c010080..0x8c011000` | Zero-filled boot-header gap. Nothing points into it. |

The patch writes a 0x80-byte SH-4 routine at `0x8c010100`, a 25 x 16-byte pool table at `0x8c010200` (count +
render costume indices per render slot) and the tag `GBOXRND1`. It then changes the one pool word `0x8c02638c` from
`0x8c02a1ca` to `0x8c010100`. No other byte of the executable changes. The routine:

```
cursor = base + (player << 7); slot = cursor[1]
if slot < 25 and TABLE[slot].count:
    r = (rand() ^ TMU0.TCNT) & 0x7fff          # the game's LCG mixed with the free-running timer
    cursor[2] = TABLE[slot].costume[(r * count) >> 15]
jmp 0x8c02a1ca                                 # r4, r5, r8, pr, macl as the caller left them
```

`doa2_random_select.simulate` interprets the built executable's own bytes (the hook, the game's `rand()` and the jump
into the commit routine). The tests and the verification use it to show that every pool index comes up, picks are
uniform, registers are preserved, and a slot without a pool keeps the player's costume. One bug was caught this way
before the build: an early version kept 14 bits of the 15-bit `rand()`, so a two-costume pool could never pick its
second entry.

## Fighter pools (seed "", `doa2_mixed.plan_pools`)

| Fighter | Render slot | Headline | Pool (costume: donor; DS = Super Mario 64 DS, otherwise Sonic Adventure 2) |
|---|---|---|---|
| Ayane (AYA) | 13 | SA2 | 00: amy rose, 01: DS mario, 02: super shadow, 03: DS peach, 04: super sonic, 05: DS yoshi, 06: dr eggman |
| Leifang (LEI) | 12 | SA2 | 00: rouge, 01: DS luigi, 02: chaos 0, 03: DS wario, 04: tikal, 05: DS ukiki |
| Helena (HIK) | 7 | SA2 | 00: tikal, 01: DS bowser, 02: rouge, 03: DS koopa troopa, 04: tails, 05: DS mario, 06: shadow |
| Ryu Hayabusa (RYU) | 4 | SA2 | 00: shadow, 01: DS peach, 02: knuckles, 03: DS yoshi, 04: amy rose |
| Jann Lee (JAN) | 2 | SA2 | 00: sonic, 01: DS luigi, 02: metal sonic, 03: DS wario, 04: super shadow |
| Gen Fu (GEN) | 6 | SA2 | 00: tails, 01: DS ukiki, 02: super sonic, 03: DS bowser, 04: dr eggman, 05: DS koopa troopa |
| Tengu (TNG) | 17 | SA2 | 00: dr eggman, 01: DS mario |
| Kasumi (KAS) | 5 | SM64DS | 00: DS peach, 01: chaos 0, 02: DS yoshi, 03: tikal, 04: DS luigi, 05: rouge, 06: DS wario, 07: tails, 09: DS ukiki |
| Tina (TIN) | 1 | SM64DS | 00: DS yoshi, 01: shadow, 02: DS peach, 03: knuckles, 04: DS koopa troopa, 05: amy rose, 06: DS mario |
| Bass (BAS) | 9 | SM64DS | 00: DS bowser, 01: metal sonic, 02: DS peach, 03: sonic |
| Zack (ZAC) | 0 | SM64DS | 00: DS wario, 01: super shadow, 02: DS yoshi, 03: super sonic, 04: DS luigi |
| Bayman (BAY) | 8 | SM64DS | 00: DS luigi, 01: dr eggman, 03: DS wario, 04: chaos 0 |
| Ein (KTE) | 3 | SM64DS | 00: DS mario, 01: tikal, 02: DS ukiki, 03: rouge, 04: DS peach |
| Leon (SAM) | 24 | SM64DS | 00: DS koopa troopa, 01: tails, 02: DS mario |

The plan has 7 SA2 headlines, 7 SM64DS headlines and 75 costumes. 20 donors are used: 12 SA2 and 8 SM64DS (Mario,
Luigi, Wario, Yoshi, Peach, Bowser, Koopa Troopa, Ukiki). Two costumes could not hold their planned donor, so the
build substituted the next donor of the same franchise and recorded it in the marker (`substitutions`): TIN02 DS bowser -> DS peach (weighted topology requires13 seam model slots but only12 are spare); KTE04 DS bowser -> DS peach (weighted topology requires13 seam model slots but only10 are spare).
Bowser's textures are downscaled where he fits (`downscaled`: HIK01, GEN03, BAS00).

## Verification (offline)

`verification.json` and the marker's `verification` hold the read-back of the written image:

- All 375 changed files are byte-identical when read back.
- All 75 costumes' CHR files decode. The largest is 48%
  of its sector budget.
- Every SUP decodes with at most 14 seam descriptors (the native limit is
  14).
- At most two influences per vertex after the writer's influence reduction.
- The select patch is installed: pool word `0x8c010100`, tag `GBOXRND1`,
  routine sha256 `e9ad988cb1450013...`. Its 14 pools equal the plan.

The evidence (`scripts/doa2_mixed_evidence.py`) is one picture per fighter. Each shows the stock costume, the donors
as collected, and every pool costume read back from the built disc and assembled through DOA2's own costume path. A
further picture shows the patched call path, the disassembled hook, and the costumes 240 interpreted confirmations
per fighter picked. Every pool index came up for every fighter.

**Not verified:** gameplay. No emulator session was started for this build. The select patch is checked statically
and by interpreting the executable's own bytes, not on a running game. The build is `built_unverified`, like every
DOA2 roster build. Things to check in game:

- Confirming a fighter twice gives different donors.
- Both players in Versus can be Sonic vs Mario.
- Story, Tag and Team modes go through the same confirm handler. This is expected from the code, but untested.
- Each donor's fit holds up in motion.

## Rebuilding

```
python -m gbox.doa2_mixed DISC.gdi LIBRARY OUT_DIR        # LIBRARY holds the sa2_* / sonic / sm64ds_* entries
python scripts/doa2_mixed_evidence.py DISC.gdi OUT_DIR LIBRARY EVIDENCE_DIR
```

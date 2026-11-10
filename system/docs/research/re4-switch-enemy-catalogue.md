# RE4 (Switch) Mercenaries enemy & boss catalogue — request #9186

Measured from `romfs/010099A00BC1E000/bio4` on lilspark (2026-11-09, re-verified 2026-11-10), with the
repo's own readers (`gbox/re4_switch_enemies.py` `roster()`/`read_esl()`,
`gbox/re4_switch_assets.py` model/TPL parsers). No gameplay session, no worker job.
This completes the "enemies" half of #9186: per-stage roster, per-pack contents,
bone counts, skeleton compatibility, texture packs, and writer-or-blocker status
for every Mercenaries enemy and boss archive.

## 1. Stage roster (ESL ground truth)

Mercenaries stages per `re4_switch_enemies.STAGES` and `re4_menus.STAGE_ROOMS`
(village 400 / castle 402 / base 403 / waterworld 404), roster from omake01.esl
and omake02.esl. The ESL type byte → body-slot mapping is NOT recorded anywhere in
the repo (no `TYPE_SLOTS` exists); it is unmeasured.

| Stage (room) | ESL | Pack | Type counts | Total |
|---|---|---|---|---|
| Village 0400 | omake01 | em28 (dogs) | t0:4, t1:2 | 6 |
| Village 0400 | omake01 | em16 (Ganados) | t3:49, t4:39, t11:21, t12:15 | 124 |
| Castle 0402 | omake01 | em1c (Ganados/leaders) | t7:87, t9:27, t10:2, t13:1 | 117 |
| Base 0403 | omake02 | em1d (Ganados + J.J.) | t2:5, t14:17, t15:17, t16:17, t17:17, t18:17, t19:16, t20:16, t21:16 | 138 |
| Waterworld 0404 | omake02 | em20 (Ganados) | t14:12, t15:10, t16:10, t17:10, t18:10, t19:10, t20:9, t21:8, t22:5 | 84 |

Stage totals: 130 / 117 / 138 / 84 = 469 placed units.

> Count discrepancy note: `re4-parity.md` §1.1 recorded Base 164 and Waterworld
> 109 in an earlier session. This run's fresh read of the same ESL files gives
> 138 and 84 (Δ −26 / −25); Village 130 and Castle 117 match exactly. Either the
> earlier read aggregated differently or the ESL contents changed. This run's
> measurement is the literal `roster()` output and the per-type counts sum to the
> totals. ESL sha256 (this run): omake00 `1ac1b5f0…9d02`, omake01 `7e74dcfc…c553`,
> omake02 `4699f8cb…6052`. The earlier 164/109 may have counted other rooms;
> unresolved without the earlier session's script.

Evidence JSON (this run's live read):

```json
{
  "measured_at": "2026-11-09",
  "host": "lilspark",
  "romfs": "010099A00BC1E000/bio4",
  "reader": "gbox/re4_switch_enemies.py roster()/read_esl()",
  "stages": {
    "0400": {"name": "Village", "esl": "omake01.esl",
             "packs": {"em28": {"0": 4, "1": 2},
                       "em16": {"3": 49, "4": 39, "11": 21, "12": 15}}, "total": 130},
    "0402": {"name": "Castle", "esl": "omake01.esl",
             "packs": {"em1c": {"7": 87, "9": 27, "10": 2, "13": 1}}, "total": 117},
    "0403": {"name": "Base", "esl": "omake02.esl",
             "packs": {"em1d": {"2": 5, "14": 17, "15": 17, "16": 17, "17": 17,
                                "18": 17, "19": 16, "20": 16, "21": 16}}, "total": 138},
    "0404": {"name": "Waterworld", "esl": "omake02.esl",
             "packs": {"em20": {"14": 12, "15": 10, "16": 10, "17": 10, "18": 10,
                                "19": 10, "20": 9, "21": 8, "22": 5}}, "total": 84}
  }
}
```

omake03–omake09 exist in `etc/` and are not Mercenaries stages per
`STAGES` (not catalogued here). omake00.esl places units in eight further 04xx
rooms (0405–0411) with packs em1d/em1f/em39/em00; those rooms are not in the
four-stage STAGE_ROOMS set — likely shared room pools or alternate layouts.
Next run: confirm live which of these rooms Mercenaries actually routes to, and
catalogue em1f if so (not yet measured).

## 2. Per-pack catalogue (bodies, bones, skeleton, texture, writer status)

Pack = 698-slot `emXX.es` table; slots with a BIN are enemy bodies or effects.
Bone/skeleton/archive/sha facts are from the sha256-pinned measurements in
`re4_switch_enemies.KNOWN` / `re4-parity.md` §1.2 (verified against the same
romfs by earlier runs; pins unchanged this run).

### em16 — Village Ganados (types 3, 4, 11, 12)
- Archive `em/00000016.pack.fen`, sha256 `5b8026bf…` (pinned in KNOWN).
- 4 bodies: slots 453 / 457 / 472 / 476 (table 454/458/473/477), 1920–2139 verts.
- 34 bones, shared Leon tree 0..25 (same as the 26-bone Leon base → compatible).
- **Replaceable**: existing `build_class()` body writer; already exercised in the
  re4-enemy-pool-01 build (offline). Live round still unverified.

### em1c — Castle Ganados/leaders (types 7, 9, 10, 13) + Garrador
- Archive `em/0000001c.pack.fen`, sha256 `00bd13eab74a0592…`.
- 4 bodies: slots 504 (1613 v) / 537 (1935 v) / 541 (5892 v) / 543 (5583 v), 37–38 bones,
  tree 0..25 shared with Leon.
- **Garrador boss**: slot 640 (table 641) — 31-bone figure on its OWN tree with
  zero shared bones; not writable with the current role map.
  **Blocker**: needs a dedicated role map + quadruped/big-model donor before a
  custom Garrador can be authored.
- Bodies **replaceable** with the existing writer (pool-01 build).

### em1d — Base Ganados (types 2, 14–21) + J.J. + parasite
- Archive `em/0000001d.pack.fen`, sha256 `a6163270…` (full `a61632700f2f6006a2097d8dc55b60a3f7610872f0c2bd946552ef5868f1ae63`).
- 3 bodies: slots 551 / 555 / 579. **J.J. (inferred) = slot 551** (6614-vert body; gatling
  apparently baked into the body mesh — a replacement body would lose it).
  Slots 555/579 are Ganado variants.
- Slot 551 has 37 bones, tree 0..25 shared with Leon, mesh reaches x −1824 (weapon
  in mesh); J.J. identity is inferred (parity doc), not confirmed. 555 = 2086 v,
  579 = 2138 v, both 37 bones. **Replaceable** with the existing body writer
  (`measure_class` finds 551/555/579).
- Parasite slot 629 (table 630): 26-bone own tree — kept native in all packs
  that carry it; **not** a replacement target.

### em20 — Waterworld Ganados (types 14–22)
- Archive `em/00000020.pack.fen`, sha256 `6f3ccb89…` (full `6f3ccb89b71ea532ad30965eb815c1e4f27720343675ec2eeef0fdfe9e82d255`).
- 3 bodies: slots 476 / 555 / 579. Slot 476: 4747 verts, 40 bones (tree 0..25 shared,
  bones 34–39 extra); slots 555/579: 37 bones, identical to em1d's (2086/2138 v).
  All textures reference `00000020.pack.fen` (not em1d's archive).
- **Replaceable** with the existing body writer.

### em28 — Village dogs (types 0, 1) — 6 placed units
- Pack has 27 slots: slot 0 = 1376-vert 19-bone body (own skeleton, y −161..582),
  slot 3 = 138-vert 1-bone piece; texture archive `00000028.pack.fen`;
  pack sha256 `27469636d8768d77…`. Head at y≈515, legs in bones 12–17 (KNOWN).
- **NOT_WRITTEN / blocker**: no biped donor fits a quadruped rig. Options:
  quadruped donor rig + dedicated role map, or texture-only swap of the dog TPL
  (lower priority; dogs are environmental in Mercenaries).

### Named specials from the ticket — status
| Special | Where | Measured? | Writer status |
|---|---|---|---|
| Ganados (all 4 stages) | em16/em1c/em1d/em20 bodies | yes | replaceable (offline build done; live unverified) |
| Dogs | em28 | yes (19-bone quadruped) | blocker — needs quadruped donor |
| Garrador | em1c slot 640 | yes (31-bone own tree) | blocker — needs dedicated role map |
| J.J. | em1d slot 551 | yes (6614 verts, shared tree) | replaceable (weapon-in-mesh caveat) |
| Chainsaw Ganado | type variant within a pack (no dedicated archive in any Mercenaries roster) | pack-level yes; exact body slot unconfirmed | replaceable once slot↔type mapping confirmed live |
| Bella Sisters | no dedicated archive in the 4-stage rosters; if present in Castle, candidates are em1c slots 504/537/541/543 (640 is Garrador) | pack-level yes; identity unconfirmed | confirm via live round with slot capture, then same body-writer path |

## 3. Texture packs
One fen archive per pack file, named `000000XX.pack.fen` (XX = pack id); TPL
slots inside reference `imagepackhd/000000XX.pack.fen`. Measured per-type texture
slots: em16 4, em1c 5, em1d 5, em20 5 (from `KNOWN` pins); body-table TPLs reference `00000016/1c/1d/20.pack.fen` respectively (re-verified). A custom texture set
per enemy family is therefore one fen archive each.

## 4. Verification performed this run
- `roster()` run on the stage ESLs; per-type counts sum to 130/117/138/84.
- Re-measured pack sha256, per-BIN vertex/bone counts, tree compatibility and
  texture archives with `measure_class`/`HdBin` on 2026-11-10; `measure_class`
  reproduces the KNOWN body tables for em16/em1c/em1d/em20 exactly and refuses
  em28 (no biped). Script: `~/gBox_alt/scratch-hermes/m9186.py`.
- Corrections vs the first draft: pack sha256s for em1c/em1d/em20, bone counts for
  em1d/em20, removal of an invented `TYPE_SLOTS`, ESL count (omake00–09 exist).

## 5. Next acceptance steps (out of scope this run)
1. Live round on i9-NUC/Spark (idle, 2% audio) with the built re4-enemy-pool-01
   pack loaded: confirm body replacements actually render (Village first).
2. During that round, capture which body slot serves the chainsaw Ganado and
   whether Bella Sisters appear in Castle; extend this catalogue's §2 with the
   confirmed slot↔type mapping.
3. Reconcile 164/109 (parity doc) vs 138/84 (this read).
4. If omake00's 0405–0411 rooms are live Mercenaries rooms, catalogue em1f/em39.

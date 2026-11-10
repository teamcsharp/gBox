# RE4 Switch Mercenaries enemy aim heights (request #9361)

Units cm above the feet. Source: `~/gBox_alt/switch/romfs/010099A00BC1E000/bio4/em/{em16,em1c,em1d,em20,em28}.udas`, parsed with `gbox.re4_switch_assets.pack_slots` and `HdBin` (`bone_world()` bind pose, `positions()`); raw units are mm, divided by 10. Pack-to-enemy mapping from `re4-switch-mercs-spawns.md` and `re4-parity.md` 1.2. Nothing under `system/gbox` was changed; no game files copied.

## How each column was obtained
* **head** = bone 4 y; **chest** = bone 2 (spine) y, neck base bone 3 = 156.0; **shoulder** = mean y of bones 6/12; **knee** = mean y of bones 19/23; **radius** = half of the shoulder bone x distance (34.4 -> 17.2), hip bone distance 18.4; **height** = range of max y over the pack's head-piece BINs (lower values are partial head pieces; which head goes with which body is not determined). Same conventions as the RE5 rows in `mercs-enemy-aim-heights.md`.
* The ids 0..25 are Leon's tree in every Ganado body (re4-parity.md 1.2); all 15 body BINs of em16/em1c/em1d/em20 were checked and give identical head/chest/shoulder/knee/width values (165.0/136.0/150.8/57.5/34.4), so the Ganado-family rows differ only in mesh and pack.

## Table

| enemy | pack | head | chest | shoulder | knee | radius | height | posture |
|---|---|---|---|---|---|---|---|---|
| Ganado | em16.udas | 165.0 | 136.0 | 150.8 | 57.5 | 17.2 | 161.6-187.1 | upright |
| Salvador / Bella | em16.udas | 165.0 | 136.0 | 150.8 | 57.5 | 17.2 | 161.6-187.1 | upright |
| Zealot / Ganado (em1c) | em1c.udas | 165.0 | 136.0 | 150.8 | 57.5 | 17.2 | 161.6-185.3 | upright |
| J.J. | em1d.udas | 165.0 | 136.0 | 150.8 | 57.5 | 17.2 | 164.1-185.3 | upright |
| Ganado soldier / Super Salvador (em20) | em20.udas | 165.0 | 136.0 | 150.8 | 57.5 | 17.2 | 164.1-185.3 | upright |
| Garrador | em1c.udas | 151.5 | 116.9 | not determined | not determined | not determined | 185.4 | upright |
| Colmillos (dog) | em28.udas | 67.6 | 48.9 | 51.1 | 21.1 | 7.5 | 74.3 | four-legged |

## Per-pack body BINs (measured)

| pack | sha256 | body slot: vertices / mesh top / x extent |
|---|---|---|
| em16 | `5b8026bf…` | 453: 1920 / 160.7 / -70.8..70.8; 457: 1955 / 160.7 / -70.8..70.8; 472: 1940 / 161.1 / -72.3..72.5; 476: 2139 / 160.4 / -70.8..70.8 ; head tops 161.6-187.1 |
| em1c | `00bd13ea…` | 504: 1613 / 161.9 / -71.7..71.7; 537: 1935 / 161.8 / -71.3..71.3; 541: 5892 / 187.6 / -167.7..167.7; 543: 5583 / 187.9 / -167.6..167.6 ; head tops 161.6-185.3 |
| em1d | `a6163270…` | 551: 6614 / 184.4 / -182.4..84.4; 555: 2086 / 164.8 / -71.4..71.7; 579: 2138 / 163.9 / -71.4..71.7 ; head tops 164.1-185.3 |
| em20 | `6f3ccb89…` | 476: 4747 / 187.1 / -84.2..84.4; 555: 2086 / 164.8 / -71.4..71.7; 579: 2138 / 163.9 / -71.4..71.7 ; head tops 164.1-185.3 |

## Not determined (and what would settle it)

* **Which body BIN each enemy type uses** (Salvador, Bella, Super Salvador, Zealot leader, militia): the type byte's meaning is code in `main`; read the spawn code or the in-game model id. It does not change the aim row inside a pack (one skeleton).
* **Runtime scale** of giants (Super Salvador, Garrador, El Gigante): the bind pose is Ganado-sized (about 185 cm); a scale in ESL/code would multiply every column.
* **Garrador** (em1c 640, own tree): head and chest are bone readings; shoulder has two candidate chains, knee/radius cannot be read (no leg chain). Idle animation frame 0 would settle it.
* **Colmillos** (em28): the mesh bottom is y=-16.1, so the table adds 16.1 to every raw y; the ground origin is not read. Radius is half the shoulder width only.
* **Posture in play**: bind pose is a T-pose; crouch/hunch/idle need the animation slots. Plaga (slot 629) is not an aim target of its own. El Gigante, Novistadores, Regenerador etc. are not in these packs' Mercenaries spawns, so no row.

Colmillos detail: head bone 4 raw y 51.5, chest bone 3 32.8, shoulder bones 5/8 35.0, knee bones 13/16 5.0; all + 16.1.

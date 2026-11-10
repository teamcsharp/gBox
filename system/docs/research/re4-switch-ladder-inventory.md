# RE4 Switch Mercs - ladder (AEV) inventory per stage (request #9534)

Evidence derived from the committed nav data `gbox/data/re4_switch_nav/{r400,r402,r403,r404}.json`
(fields `ladders`, `crossings`). All ladder crossings are `verified: false` (static ESL/AEV extraction; no live traversal test).

| Stage | File | Ladders | Ladder crossings (up+down) | Other crossings |
|---|---|---|---|---|
| Village | r400 | 1 (AEV[9], 9 rungs, top y=9000) | 2 | 174 vault, all unverified |
| Castle | r402 | 0 | 0 | 0 (no nav crossings recorded) |
| Base | r403 | 10 (AEV 0-8,10; 3-5 rungs) | 18 (9 up + 9 down) | 0 |
| Waterworld | r404 | 8 (AEV 1-7,11; 3-12 rungs) | 16 (8 up + 8 down) | 0 |

Observations
- Base has 10 ladders but only 9 up/9 down crossings: one ladder (AEV[10] at 73290.8,12359.5,28100.6) yields no crossing pair.
- Castle has no ladder or crossing data; ladder-dependent routes there are unmodelled.
- Waterworld AEV[1] is the tallest (12 rungs, 12000 mm). Facing values are quantised to multiples of pi/2 except Base AEV[6],[7],[8],[10] and Village AEV[9].
- Next acceptance step: live-verify at least one ladder crossing per stage on i9-NUC/Spark (not the play PC) and flip `verified`.

# Universal QTE handling — grab break, live on stream (RE5 Switch)

Captured from the live lilspark RE5 Switch MercMode stream, 2026-11-04 (read-only `get_frame`
on the running session; the bot kept playing).

The operator's report: a Switch grab-escape prompt showed and the bot "did not even try."
RE5/RE6 Switch already break grabs from RAM (`re5_switch_prompt`); the gap was that a torn /
empty RAM read had **no fallback**, so a missed grab was eaten. `gbox.mercs.qte` adds the
vision safety net.

| frame | what it shows |
| --- | --- |
| `1-grabbed.png` | Wesker grabbed from behind; the game draws **(L) Break free** centre-screen |
| `2-broke-free.png` | ~1.3 s later: prompt gone, upright and mobile, combo `003` kept — **the grab was broken** (the existing RAM path) |
| `3-vision-detects.png` | the new vision fallback's box over the same grab frame: `glyph_px=1300 ≥ 500 → FIRES mash:wiggle` |
| `4-no-false-fire.png` | the same detector on the free frame: `glyph_px=15 < 500 → None` (no false fire) |

## Calibration (near-white neutral pixels in the centre-bottom glyph box)

| on-screen | glyph_px | detector |
| --- | --- | --- |
| (L) Break free (grab) | 1300 | FIRES |
| (A) Resuscitate (dying) | 1773 / 1792 | FIRES |
| ordinary play | 0–204 | None |
| "You Are Dead" screen | 350 | None (also gated out by motion) |

The RE5 Switch `VisionProfile` is calibrated with box `(0.33, 0.52, 0.67, 0.80)` and a 500-px
floor. The tick hook (`re5_switch.snapshot`) only consults vision when the RAM read is empty
**and** the player is in a grabbed/held motion, so it costs nothing in ordinary play and can
never fight the combat loop.

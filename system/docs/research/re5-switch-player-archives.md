# RE5 (Switch) player archives — research deliverable

Request 41d19e16668f4377 (#9076) — Switch player-archive inventory and Mercenaries roster mapping.

## Method and sources

- ROMFS `010018100CD46000` (RE5 Switch), read-only.
- Listing: `gbox.re5_char_swap.catalogue(romfs)` — **41 character archives** (`uPl*.arc`), 139 enemy archives (`uE*.arc`).
- Entry tables: `gbox.mt_arc.parse`; geometry: `gbox.mt_model.parse_mod` (entry payloads are zlib-compressed; decompressed before parse); textures: `gbox.re6_switch_tex.from_arc_entry`.
- Body MOD = `pl0000` entry (`pawn\pl\plNN\model\pl0000`) that parses as a MOD container.

## Verification results

- `catalogue(romfs)` returns 41 character / 139 enemy archives.
- Chris BSAA record matches ticket standard: `uPl00ChrisNormal.arc`, body MOD entry **index 97** (`pawn\pl\pl00\model\pl0000`, i.e. pl0000) with bone count **130**, mesh records **162** (header 162), material count **123**, option-group ids (distinct mesh group_index): [0, 1, 2, 3, 4, 5] (6 groups), vertex count 28091, face count 48300, texture entries **84**.

## Per-archive inventory

| archive | bytes | sha256(16) | char | costume | body idx | bones | mesh recs | materials | option groups | textures |
|---|---|---|---|---|---|---|---|---|---|---|
| uPl00ChrisArmorA.arc | 42191749 | 8a72b6021849b045 | ChrisArmorA | None | 94 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 82 |
| uPl00ChrisArmorB.arc | 42191749 | aa0efdce6a209793 | ChrisArmorB | None | 94 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 82 |
| uPl00ChrisArmorF.arc | 42191749 | b11af6a0109683f4 | ChrisArmorF | None | 94 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 82 |
| uPl00ChrisCos1.arc | 51701933 | fa3f0a85ca2c8c99 | ChrisCos | 1 | 134 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 120 |
| uPl00ChrisCos2.arc | 52678658 | 4df4a987b59761cb | ChrisCos | 2 | 134 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 120 |
| uPl00ChrisCos3.arc | 50536390 | 96d74a35058f8d19 | ChrisCos | 3 | 131 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 117 |
| uPl00ChrisCos4.arc | 50258715 | 79883b7afbe03b68 | ChrisCos | 4 | 135 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 121 |
| uPl00ChrisEp1.arc | 50662098 | c4b8cf5147c63edb | ChrisEp | 1 | 128 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 115 |
| uPl00ChrisNormal.arc | 43337492 | 8ab0dc181d1f6ec1 | ChrisNormal | None | 97 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 84 |
| uPl00ChrisPlain.arc | 50934540 | 9ba7809835249a00 | ChrisPlain | None | 125 | 130 | 162 | 123 | [0, 1, 2, 3, 4, 5] | 112 |
| uPl00Eff.arc | 6013074 | b810b0b4134f0c6e | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 23 |
| uPl01Eff.arc | 5768260 | 2f481bd3c629cf42 | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 20 |
| uPl01ShebaArmorA.arc | 45236671 | 96a5c36c5b575526 | ShebaArmorA | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 67 |
| uPl01ShebaArmorB.arc | 45236671 | 6dc21f3ad151616f | ShebaArmorB | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 67 |
| uPl01ShebaArmorF.arc | 45236671 | 0c711a8aab0db6a4 | ShebaArmorF | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 67 |
| uPl01ShebaCos1.arc | 54790744 | d550005ea851af8d | ShebaCos | 1 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 104 |
| uPl01ShebaCos2.arc | 55398091 | f63256a6e61a5b09 | ShebaCos | 2 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 101 |
| uPl01ShebaCos3.arc | 54711602 | bf60cfd03eb8179e | ShebaCos | 3 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 118 |
| uPl01ShebaCos4.arc | 54081295 | a236928f3729f036 | ShebaCos | 4 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 97 |
| uPl01ShebaNormal.arc | 47783794 | 77e9ede6a6bf84d7 | ShebaNormal | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 73 |
| uPl01ShebaPlain.arc | 53996897 | 877a03121862ab00 | ShebaPlain | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 101 |
| uPl02Eff.arc | 5745450 | bea5a46312f29650 | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 20 |
| uPl02JillCos1.arc | 14990525 | cb0f8371dd07e201 | JillCos | 1 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 51 |
| uPl02JillCos2.arc | 24161016 | b52533fc3026cc83 | JillCos | 2 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 83 |
| uPl02JillCos3.arc | 23791548 | 804991d120df1859 | JillCos | 3 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 83 |
| uPl02JillCos4.arc | 15157257 | 5cac065d5c36d26d | JillCos | 4 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 51 |
| uPl03Eff.arc | 5856014 | 66febd312fbe103d | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 24 |
| uPl03WeskerCos1.arc | 21036882 | dd1f09202affed7f | WeskerCos | 1 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 98 |
| uPl03WeskerCos2.arc | 21207860 | 9cbeb48d611d41ab | WeskerCos | 2 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 96 |
| uPl04Eff.arc | 5743330 | bccc6156c85306b0 | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 20 |
| uPl04Josh.arc | 10549393 | d6440509a3a554e3 | Josh | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 32 |
| uPl04JoshCos1.arc | 23626695 | f7ac23d11cb64bbc | JoshCos | 1 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 95 |
| uPl04JoshCos2.arc | 23801889 | a85585ae821d342b | JoshCos | 2 | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 95 |
| uPl05Eff.arc | 15211848 | 6bba03d260faba51 | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 26 |
| uPl05ExcellaNormal.arc | 26992449 | 9c22ab0e0892f224 | ExcellaNormal | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 113 |
| uPl06BarryNormal.arc | 22824032 | 352e8d8c75376025 | BarryNormal | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 65 |
| uPl06Eff.arc | 5758492 | 71069f844414e9b5 | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 20 |
| uPl07Eff.arc | 5760281 | 72e70a08cd18c6fd | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 20 |
| uPl07RebeccaNormal.arc | 17843735 | 94316c133f9bd7bf | RebeccaNormal | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 65 |
| uPl18Eff.arc | 5762482 | 9e593a119992d697 | Eff | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 20 |
| uPl86Irving.arc | 15821308 | 4ee9cba711e9d735 | Irving | None | not determined (no zlib/raw MOD parse succeeded among ) | — | — | — | — | 21 |

Full per-entry detail (texture index/name/format/dims, per-mesh group/material indices) is in `re5-switch-player-archives.json`.

## Six Mercenaries roster slots (static evidence)

| slot | character | pl id | evidence | confidence |
|---|---|---|---|---|
| 1 | Chris | pl00 | base body `uPl00ChrisNormal.arc` + ArmorA/B/F, Cos1-4, Ep1, Plain | high (static) |
| 2 | Sheva | pl01 | base body `uPl01ShebaNormal.arc` (archive spelling "Sheba") + ArmorA/B/F, Cos1-4, Plain | high (static) |
| 3 | Josh | pl04 | base body `uPl04Josh.arc` + Cos1, Cos2 | medium |
| 4 | Excella | pl05 | base body `uPl05ExcellaNormal.arc` | high (static) |
| 5 | Barry | pl06 | base body `uPl06BarryNormal.arc` | high (static) |
| 6 | Rebecca | pl07 | base body `uPl07RebeccaNormal.arc` | high (static) |

Jill (pl02) and Wesker (pl03) have only Cos (costume) archives, no base body; Irving (pl86) is story-only; the 9 `uPlXXEff.arc` are effect/texture support archives. Slot order is by pl id, not confirmed menu order. **Live verification (Mercenaries roster menu, idle i9-NUC/Spark session at 2% audio) is pending** — medium confidence until then.

## Not determined

- Mercenaries menu slot order / exact roster (needs one idle live session).
- `uPlXXEff.arc` have no `pl0000` body MOD (effect support archives).

## Checkpoint

- Files: `system/docs/research/re5-switch-player-archives.json` (41 records), `re5-switch-player-archives.md` (this file), phase-1 `re5-switch-player-archives-catalogue.json`.
- No files under system/gbox or tests changed; no binaries/textures/images added. Pending remote jobs: none (local-only extraction).
- Next acceptance step: live Mercenaries roster check on an idle i9-NUC/Spark session, then close request (keep in_progress until then).
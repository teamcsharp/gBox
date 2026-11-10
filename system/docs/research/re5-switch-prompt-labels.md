# RE5 Switch: on-screen prompt label ids -> moves, per character

Request #9187 (ddbb5df57cc14f05). Deliverable: map every on-screen prompt
label id in RE5 Switch Mercenaries to its move name, per character.
This revision records the measured ground truth collected in run
2026-11-09; the MSG2 string-bank decode is the remaining acceptance step.

## Status by table column

| column        | state      | basis |
|---------------|------------|-------|
| label_id      | MEASURED   | live MercMode emulator (2026-10-27) + module constants |
| on_screen_text| UNMEASURED | MSG2 bank is charset-encoded; decode pending (next step) |
| frequency     | MEASURED   | rounds.sqlite prompts_seen_* counters, 1,720 rounds |
| character     | MEASURED   | rounds.sqlite `character` column (12 distinct values) |

## Measured label constants

Source: `system/gbox/mercs/titles/re5_switch_prompt.py` (live, 2026-10-27).
The on-screen prompt is a `cActionButton` unit; the label id is the u32 at
`cActionButton+0x2C`. Mode 6 = QTE; `sActionButton` keeps the label at the
same offset. `selected_prompt()` returns the selected unit and its label.

| label id | move / situation            | evidence |
|----------|-----------------------------|----------|
| 1        | Pick up ("Y Pick up")       | LABEL_PICKUP; herb pickups; 71,132 prompts_seen_pickup |
| 7,8,9,14,58 | Traverse at fixed stage spots (ledges/walls/roofs/fences) | TRAVERSE_LABELS; bot's own actions at stage locations; 11,126 prompts_seen_traverse; traverse_spots logged for all 10 named characters |
| 28       | Break free (Majini grab)    | LABEL_BREAK_FREE, mode 6, shake-left-stick prompt |
| 55       | Resuscitate (dying, mash A) | LABEL_RESUSCITATE; 44,055 prompts_seen_dying |
| 100      | Place (bomb placement, ZL)  | LABEL_PLACE |
| 112      | Time bonus (hourglass statue uOm0100, press Y) | LABEL_TIME_BONUS; 1,098 prompts_seen_bonus |

Per-character finisher prompts (Chris/Jill/Sheva/Wesker specials) are
expected among the remaining label ids; the bot's `specials_labels_text` and
`finishers` counters in rounds.data are the cross-reference once the string
bank decodes.

## String resources (where the on-screen text lives)

Measured 2026-11-09 from the operator's disc RomFS
(`/home/ehm_eckx/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/`):

- `ImgNX/Archive/Msg2Resource_{e,s,g,chS,chT,i,f,j}.arc` — MT `.arc` archives
  (readable with `gbox/mt_arc.py`), 9 entries each:
  `etc\message\mes_{system,item,file,event,stage1..stage7}_<lang>`.
- `ImgNX/Archive/GuiTextResource.arc` — 3 entries (`id\gui_text\...`), GUI
  strings only, not the prompt bank.
- Each mes_ entry is zlib-compressed (magic 0x789c) and decompresses to an
  MT "MSG2" bank. Measured header of `mes_system_e` (275,168 bytes decoded):
  `4D 53 47 32 40` ("MSG2@"), u32 total size 0x432e0 @0x08, then 0x80000
  @0x0c, 0x5000900 @0x10, 0x240012 @0x14, 0 @0x18, and 68,802 (0x10cc2)
  @0x1c.
- STRUCTURE (measured 2026-11-10, full-bank walk of `mes_system_e`): from
  0x40 to EOF the bank is one contiguous u32 record stream with no
  separate string block (last record 0x432dc, bank ends 0x432e0). Record
  types by high 16 bits:
    * 0x0080xxxx — character value (62,005); low 16 bits are code-page
      codes; whole-bank observed range 0x0..0x107a, 103 distinct codes in mes_system_e
    * 0x04010000 — message separator (3,266) → 3,266 message groups
    * 0x0419xxxx — 1,472 records (per-message structural, purpose TBD)
    * 0x042exxxx — 650, 0x0403xxxx — 532, 0x041fxxxx — 488
  Each message is therefore a run of character values between separators.
  Character values are NOT ASCII (e.g. 0x48='H' is followed by 0x86/0x96,
  non-ASCII codes) — a per-language 0x100 byte→char charset table is
  required to read any group.
- CHARSET LOCATION (measured 2026-11-10): the operator disc RomFS at
  `~/gBox_alt/switch/romfs/010018100CD46000/` contains ONLY `nativeNXx64/`
  (etc, ImgNX, movie, sa, sound, system) — no ExeFS, no .nso/.nsp/.nca
  anywhere under that tree, and no charset file in `etc/` (textures/.vib
  only) or in `sa/NX_64/*.arc` candidates. The charset must come from the
  main NSO (ExeFS) or be derived; it is the single remaining dependency
  for the on_screen_text column.

## Frequency + character coverage (measured, rounds.sqlite)

DB: `/home/ehm_eckx/gBox/system/gbox-data/mercs/curriculum/010018100CD46000/rounds.sqlite`
(1,720 rounds; columns id, ts, stage, mode, character, outcome, data, vector —
prompt counters are inside the `data` JSON).

- characters: Chris (STARS/BSAA/Safari), Jill (BSAA/Battle Suit),
  Sheva (BSAA/Clubbin/Tribal), Wesker (Midnight/STARS), `unknown`.
- prompt counters (sum over all rounds):
  prompts_seen_pickup 71,132 | dying 44,055 | other 19,334 | traverse 11,126 |
  enemy 6,198 | bonus 1,098; prompts_taken 65,508; prompt_presses 452,740.
- `traverse_spots` non-empty for all 10 named characters (incl. 'unknown').
- Useful per-round fields: `finishers`, `specials_labels_text`,
  `specials_motions_text`, `specials_character`, `qte_presses`,
  `resuscitate_presses`, `dying`.

## Next acceptance step (bounded)

1. Recover the MT MSG2 per-language charset table (RE5/RE6 Switch; a 0x100
   byte->char map per language). Candidates: the main NSO (ExeFS, outside
   this RomFS) or `nativeNXx64/sa/NX_64/*.arc`. Decoding `mes_system_e` /
   `mes_item_e` / `mes_event_e` into an id->text table is the acceptance
   gate for the on_screen_text column.
2. Join label ids (7, 8, 9, 14, 28, 55, 58, 100, 112 + all ids observed in
   `rounds.data.specials_labels_text`) to their strings; assign the
   per-character finisher prompts.
3. Fill the on_screen_text column and per-character finisher table above.

## Per-character finisher label ids (measured 2026-11-10, rounds.sqlite)

Source: the 54 rounds whose `data` JSON carries `specials_character`
(Chris 15, Sheva 30, Jill 6, Wesker 2, Barry 1) in the same DB. Action
label ids parsed from `data.specials_labels_text` (format
`"prefix: <id>x<count> ..."`); motion ids from `data.specials_motions_text`
(same format, different namespace — motion-table ids, not action labels).
MEASURED from the round database; no game-file decode involved.

| character | finisher label ids (total presses) | motion ids seen |
|-----------|------------------------------------|-----------------|
| Chris     | 21 (3x), 256 (1x)                  | 6, 12, 15, 45 |
| Jill      | 21 (1x)                            | 0, 30 |
| Sheva     | 5 (2x), 6 (2x), 10 (2x), 21 (5x), 191 (1x), 256 (1x) | 6, 11, 12, 15, 21, 45, 85, 100, 111, 112, 150 |
| Wesker    | not determined (2 rounds, no label pairs in specials_labels_text) | not determined |
| Barry     | not determined (1 round, no label pairs) | not determined |

Id->move bindings measured via the bot's own `specials_summary` text in the
same rows (e.g. Sheva: "Sheva Throat Slit ... | Sheva melee (label 5) ... |
Sheva melee (label 6) ..."): the label->move name binding for Sheva labels
5 and 6 is MEASURED from bot telemetry, not the string bank. Label 21
appears for every character that produced pairs (Chris, Jill, Sheva) —
inference: a shared non-finisher prompt (candidate interrupt/rear), not a
per-character finisher. Labels 191 (Sheva, 1x) and 256 (Chris 1x, Sheva
1x) are not determined as moves; the charset decode settles them.

## Next acceptance step (bounded)

1. Recover the MT MSG2 per-language charset table (a 0x100 byte->char map).
   The disc RomFS has no ExeFS/NSO and no charset file (measured), so the
   candidates are: the main NSO of the full NSP (ExeFS — not on this
   machine), or derivation by anchoring known EN strings (Mercs prompt
   texts "Pick up", "Jump over", "Climb up", "Break free", "Resuscitate",
   "Place", "Time bonus" and the bot-measured finisher names "Throat
   Slit" etc.) against the per-message character runs of 3,266 groups,
   using the EN/JP/G/CHS/CHT/I/F/J banks' differing code sequences as a
   second constraint.
2. Decode `mes_system_e` / `mes_item_e` / `mes_event_e` into id->text and
   join the still-unbound label ids (21, 191, 256, plus all ids observed
   in `rounds.data.specials_labels_text`) to their strings; fill the
   on_screen_text column and the per-character finisher table above.
3. Note: `specials_labels_text`/`specials_summary` only exist in the 54
   rounds with specials keys; older rounds carry none of these fields.

Run 2026-11-10 (lilspark2, this run): reused worktree at commit c2a3e63b.
Added the per-character finisher label-id table measured from
rounds.sqlite (54 rounds, `specials_labels_text`/`specials_motions_text`/
`specials_summary`); verified the doc is the only changed file. No pending
jobs; no remote work; read-only. Next acceptance step stands: the
per-language charset table for on_screen_text.

Run 2026-11-10 (lilspark2, this run): full-bank structure walk of
`mes_system_e` (275,168 decoded bytes): record stream confirmed — 62,005
character values (0x0080xxxx, codes 0x0..0x107a, 103 distinct), 3,266 message separators
(0x04010000) → 3,266 message groups, plus 3,142 structural records
(0x0419/0x042e/0x0403/0x041f); no separate string block (records run to
EOF). Character values verified language-specific (EN vs JP table bytes
differ), confirming they are code-page character codes, not pointers. Exact per-message
  record interleaving (which 0x0419/0x042e/0x0403/0x041f records precede or follow each
  character run) is the remaining parse detail before full id->text decoding.
Confirmed the disc RomFS is nativeNXx64-only (no ExeFS/NSO/charset file)
— the charset table is the sole remaining dependency. Read-only; no
pending jobs.

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
  `4D 53 47 32 40` ("MSG2@"), then u32 entry-count-like fields
  (0x432e0, 0x80000, 0x5000900, 0x240012) and an offset table of 0x800000-
  ranged pointers starting at 0x48. Text is NOT plain ASCII/UTF-16 — the MT
  charset table (per-language) is required; no readable runs of 4+ chars
  exist until decoded.

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

1. Recover the MT MSG2 per-language charset table (RE5/RE6 Switch; likely in
   main NSO data or `sa/NX_64/*.arc`) and decode `mes_system_e` /
   `mes_item_e` / `mes_event_e` into an id->text table.
2. Join label ids (7, 8, 9, 14, 28, 55, 58, 100, 112 + all ids observed in
   `rounds.data.specials_labels_text`) to their strings; assign the
   per-character finisher prompts.
3. Fill the on_screen_text column and per-character finisher table above.

No pending jobs this run; no remote work started. No gameplay changes; read-only.

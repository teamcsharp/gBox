# RE6 Switch stage map (request #9185)

Offline measurement over the local RomFS `01002A000CD48000/nativeNXx64/arc/NX`; no game session or worker job was used. Labels: **measured** = read from an archive by code; **inferred** = reasoned from measured names; **not determined** = no evidence found.

## 1. Archive pairing (measured)

Geometry arc `s12NN.arc` (NN=00..09) pairs with spawn/logic arc `s12(NN+10)Soft.arc`, as already listed in `re6-parity.md` section 3.1 (column check below). The Soft arc holds the enemy layouts (`sNNNN_emXX`), `Attack_Control`, `Em_BossPop`, `RankUp`, `SecretEnemy_Pop` entries; the geometry arcs contain **no** nav-named entries (measured, 0 of 10), so NAV lives in the Soft sets / learned stage books, not in `s120x.arc`.

## 2. Stage name -> archive -> evidence

| Stage name | Geometry arc | Soft arc | Name evidence | Label |
|---|---|---|---|---|
| not determined | `s1200.arc` (602 entries) | `s1210Soft.arc` | scr names `a00komono`, `a00GL`; no readable name | not determined |
| not determined | `s1201.arc` (731 entries) | `s1211Soft.arc` | scr `alfaeda/alfaki/alfakusa_NUKI`, `efl_spark*` | not determined |
| not determined (city street, inferred) | `s1202.arc` (775 entries) | `s1212Soft.arc` | scr `hasi`(bridge) `kanban`(sign) `koukoku`(ad) `eiga`(film): urban set | inferred (descriptor only) |
| not determined (ice/snow area, inferred) | `s1203.arc` (564 entries) | `s1213Soft.arc` | scr `area0x_ice` | inferred (descriptor only) |
| not determined (aircraft carrier, inferred) | `s1204.arc` (725 entries) | `s1214Soft.arc` | scr `aircarrier_body`, `01_propera1` | inferred (descriptor only) |
| not determined | `s1205.arc` (440 entries) | `s1215Soft.arc` | numeric scr names only | not determined |
| not determined (heli/bridge, inferred) | `s1206.arc` (650 entries) | `s1216Soft.arc` | scr `heli_NUKI`, `lp_Heli_fly`, `lp_base_Bridge_l/r` | inferred (descriptor only) |
| not determined | `s1207.arc` (653 entries) | `s1217Soft.arc` | numeric scr names only | not determined |
| Mining the Depths (inferred) | `s1208.arc` (372 entries) | `s1218Soft.arc` | s1218Soft nav matches documented Mining-the-Depths nav (prior run, learned book); +10 pairing gives s1208; scr `kaityuu`(undersea) `kaimennaka`, `lp_base_Labo` | inferred |
| not determined (lava hall, inferred) | `s1209.arc` (525 entries) | `s1219Soft.arc` | scr `lp_base_LavaHall_l/r`, `ami_tuuro` | inferred (descriptor only) |

No stage-name string was recovered: `Merce_eng`/`MerceUI_eng`/`Collection_eng` text entries (`extra360`, `merce`) are glyph-index encoded (no ASCII/UTF-16 text), so names cannot be read without the font glyph table. That is the exact check that would settle the 9 open names: decode the `merce` text arc with the glyph map and match the stage-select order in `STAGES` (`gbox/mercs/titles/re6_switch.py`).

## 3. Enemy census per Soft set (measured, `gbox.re6_switch_enemies.stage_census`)

Counts are placed instances by enemy class archive (`uEm*`). Mercenaries and No Mercy use the same Soft set per stage in this measurement; a per-mode split was not separately derivable (not determined).

| Soft arc | Enemy classes (count) | Layouts |
|---|---|---|
| `s1200Soft` | uEm1000 322, uEm4300 1 | 18 |
| `s1201Soft` | uEm1200 153, uEm1000 130, uEm4800 2, uEm3300 1 | 16 |
| `s1202Soft` | uEm5200 50, uEm5191 23, uEm5210 20, uEm5700 20, uEm5181 19, uEm5050 17, uEm5600 3, uEm3200 1 | 17 |
| `s1203Soft` | uEm5000 77, uEm5060 27, uEm5700 26, uEm5191 19, uEm5500 4, uEm3000 1 | 12 |
| `s1204Soft` | uEm1000 302, uEm3300 1 | 16 |
| `s1205Soft` | uEm5400 148, uEm5600 2, uEm4100 2, uEm3000 1 | 20 |
| `s1206Soft` | uEm1200 145, uEm1000 140, uEm3200 7, uEm3300 1 | 16 |
| `s1207Soft` | uEm5200 57, uEm5050 24, uEm5000 23, uEm5191 22, uEm5700 18, uEm5600 7, uEm4300 3, uEm3200 1 | 20 |
| `s1208Soft` | uEm1000 160, uEm1400 148, uEm3200 8, uEm4300 1 | 19 |
| `s1209Soft` | uEm1000 150, uEm1400 147, uEm1370 3, uEm3100 3, uEm4700 2, uEm3200 1 | 19 |
| `s1210Soft` | uEm1000 506, uEm3200 6, uEm4300 2 | 20 |
| `s1211Soft` | uEm1200 298, uEm1000 130, uEm5210 6, uEm4800 3, uEm3300 1 | 18 |
| `s1212Soft` | uEm5200 100, uEm5181 68, uEm5191 46, uEm5210 44, uEm5700 40, uEm5050 34, uEm5600 11, uEm3200 3 | 20 |
| `s1213Soft` | uEm5000 159, uEm5060 54, uEm5700 52, uEm5191 38, uEm5500 7, uEm3000 3 | 14 |
| `s1214Soft` | uEm1000 461, uEm3200 4, uEm3300 1 | 18 |
| `s1215Soft` | uEm5400 307, uEm5600 4, uEm4100 3, uEm3000 2 | 21 |
| `s1216Soft` | uEm1200 286, uEm1000 140, uEm3200 20, uEm3300 1 | 17 |
| `s1217Soft` | uEm5200 112, uEm5050 72, uEm5000 46, uEm5191 46, uEm5700 18, uEm5600 14, uEm3200 6, uEm4300 5 | 22 |
| `s1218Soft` | uEm1400 284, uEm1000 160, uEm5210 19, uEm3200 5, uEm4300 1 | 20 |
| `s1219Soft` | uEm1400 321, uEm1000 160, uEm3100 6, uEm3200 4, uEm1370 3, uEm4700 3 | 22 |

## 4. s1211Soft discrepancy (resolved)

Local census of `s1211Soft`: uEm1200 298, uEm1000 130, uEm5210 6, uEm4800 3, uEm3300 1. `re6-parity.md` row `s1201 -> s1211` lists `uEm1200 298, uEm1000 130, uEm5210 6, uEm4800 3, uEm3300 1`: identical. The previous run's "uEm1000=194 uEm3200=182" came from unrelated grep hits (`mercmode.py:194`, `182.2 cm`), not a census row. No doc change needed.

# RE6 Switch stage map (request #9185)

Offline measurement over the local RomFS `01002A000CD48000/nativeNXx64/arc/NX`; no game session or worker job was used. Labels: **measured** = read from an archive by code; **inferred** = reasoned from measured names; **not determined** = no evidence found.

## 1. Archive pairing (measured)

Geometry arc `s12NN.arc` (NN=00..09) has two per-mode sets: `s12NNSoft.arc` = THE MERCENARIES and `s12(NN+10)Soft.arc` = NO MERCY (measured: `Attack_Control_*` entries top out at 150 kills in `s1200/1204/1208Soft`, at 300 in `s1210/1214/1218Soft`). The tables below list the No Mercy set; section 3 gives both. The Soft arc holds the enemy layouts (`sNNNN_emXX`), `Attack_Control`, `Em_BossPop`, `RankUp`, `SecretEnemy_Pop` entries; the geometry arcs contain **no** nav-named entries (measured, 0 of 10), so NAV lives in the Soft sets / learned stage books, not in `s120x.arc`.

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

No stage-name string was recovered (measured). `Merce_eng` and `MerceUI_eng` hold no text entries, only baked textures (`names_BM_NOMIP` = the ten character names Leon..Agent; `merce_BM_NOMIP` = MISSION START/END, COMBO TIME, Sec., Score; `common02*`, `costumes`, `extra`, `merce_title02`). None contains a stage name, so the earlier "glyph-index encoded text" explanation is **withdrawn**: the names are not in these arcs at all. The remaining candidate is the glyph-encoded message arc (`Msg_eng`-class), which needs the game's font glyph table. The cheaper check that settles all 9 open names: one boot of each stage logging `snapshot()['navmesh'].name` beside the select-index pick (`STAGES`, `gbox/mercs/titles/re6_switch.py:87`); section 5 gives the nav fingerprint to match. Not done here (no game sessions allowed).

## 3. Enemy census per Soft set (measured, `gbox.re6_switch_enemies.stage_census`)

Counts are placed instances by enemy class archive (`uEm*`). **Mode split (measured):** rows `s1200Soft`..`s1209Soft` are THE MERCENARIES (<=150 kills), rows `s1210Soft`..`s1219Soft` are NO MERCY (<=300). Pair rows by `s120N`/`s121N`;

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

Local census of `s1211Soft`: uEm1200 298, uEm1000 130, uEm5210 6, uEm4800 3, uEm3300 1. `re6-parity.md` row `s1201 -> s1211` lists `uEm1200 298, uEm1000 130, uEm5210 6, uEm4800 3, uEm3300 1`: identical. The previous run's "uEm1000=194 uEm3200=182" came from unrelated grep hits (`mercmode.py:194`, `182.2 cm`), not a census row.
Re-run, one stated command (repo root):

```
python3 -c "import sys; sys.path.insert(0,'.'); from gbox import re6_switch_enemies as r; print(r.stage_census(open('<romfs>/01002A000CD48000/nativeNXx64/arc/NX/s1211Soft.arc','rb').read()))"
```

Output: `{'classes': {'uEm1200': 298, 'uEm1000': 130, 'uEm5210': 6, 'uEm4800': 3, 'uEm3300': 1}, 'layouts': ['s1211_em00', 's1211_em01', 's1211_em02', 's1211_em04', 's1211_em05', 's1211_em06', 's1211_em07', 's1211_em08', 's1211_em09', 's1211_em10', 's1211_em11', 's1211_em12', 's1211_em13', 's1211_em15', 's1211_em16', 's1211_em17', 's1211_em20', 's1211_em21']}` - the exact classes of the `re6-parity.md:120` row (`| s1201 | 58.0 | s0302 x65, s0300 | s1211 | uEm1200 298, uEm1000 130, uEm5210 6, uEm4800 3, uEm3300 1 |`), reproducible from one command. (The 194/182 hits are measured as `mercmode.py:194` and `182.2 cm` in `re6-parity.md`; the earlier run's own source of the numbers is not reproduced here, so that attribution is partly inferred.)

## 5. NAV per stage (measured; the earlier per-arc comparison failed)

Cause of the earlier failure: geometry arcs `s120N.arc` contain no NAV entry (section 1), and the `NAV` resource is the entry `...s12XX\\s12XX` of the *Soft* arc, zlib-compressed, so searching geometry arcs or raw bytes finds nothing. After decompression the header is `NAV\0`, `u32 0x22`, then at byte offset 0x23 (unaligned) `u32 vertices, u32 triangles`.

| stage code | Mercenaries Soft | No Mercy Soft | vertices | triangles | NAV bytes | Mercenaries == No Mercy |
|---|---|---|---|---|---|---|
| s1200 | s1200Soft | s1210Soft | 2015 | 3274 | 566278 | yes |
| s1201 | s1201Soft | s1211Soft | 1823 | 2799 | 482101 | yes |
| s1202 | s1202Soft | s1212Soft | 1887 | 2829 | 493071 | yes |
| s1203 | s1203Soft | s1213Soft | 1052 | 1710 | 325717 | yes |
| s1204 | s1204Soft | s1214Soft | 4225 | 7120 | 1156590 | yes |
| s1205 | s1205Soft | s1215Soft | 1237 | 1888 | 334738 | yes |
| s1206 | s1206Soft | s1216Soft | 2213 | 3611 | 581939 | yes |
| s1207 | s1207Soft | s1217Soft | 1547 | 2587 | 458685 | yes |
| s1208 | s1208Soft | s1218Soft | 2005 | 3434 | 619456 | yes |
| s1209 | s1209Soft | s1219Soft | 1824 | 3030 | 515705 | yes |

Cross-check against the live game: only `s1218` (2005 / 3434, `re6_switch.py:669`, MercMode 17:20) has an independent live number in the repo, and it equals the s1218Soft/s1208Soft row, so that is the one measured name (Mining the Depths = s1208 code, select index 2). The other nine were re-verified this run against the learned stage books, which DO exist at `~/gBox/system/gbox-data/mercs/learned/01002A000CD48000/stages/s1210.json`...`s1219.json` (one per real play session, visits 89-151; each records `nav: {name: soft\\stage\\s12NN\\s12NN, vertices, triangles}`). All ten books match the Soft-arc NAV counts in the table above exactly: s1210 2015/3274, s1211 1823/2799, s1212 1887/2829, s1213 1052/1710, s1214 4225/7120, s1215 1237/1888, s1216 2213/3611, s1217 1547/2587, s1218 2005/3434, s1219 1824/3030 - so the NAV table is no longer a hypothesis (the earlier 'not found under ~/gBox_alt' was a search-scope miss; the books live under `~/gBox/system/gbox-data`). Names for the nine remain **not determined**; the (vertex, triangle) pair per row is the fingerprint to match once a boot logs `navmesh.name` per pick.

Reproduce (repo root): the script below prints the table rows.

```python
import sys,zlib,struct; sys.path.insert(0,'.')
from gbox import mt_arc
d='<romfs>/01002A000CD48000/nativeNXx64/arc/NX/'
def nav(n):
    for e in mt_arc.parse(open(d+f's{n}Soft.arc','rb').read()).entries:
        if e.name.endswith(f's{n}\\s{n}'):
            b=zlib.decompress(e.data)
            if b[:3]==b'NAV': return struct.unpack_from('<II',b,0x23)+(len(b),)
for k in range(10): print(k, nav(1200+k), nav(1210+k))
```

# PSO GC maps and sets — per-area measurement

Status: COMPLETE - c.rel collision tables, per-area enemy/object set tables and map-bin record provenance. n.rel geometry and e.bin/f.bin spawn record layouts are not determined and are documented as such.

Disc: Phantasy Star Online Episode I & II Plus (USA), GCZ image at `/home/ehm_eckx/gBox_alt/gbox-cache/436e0bb84d5337d1/Phantasy Star Online Episode I & II Plus (USA).gcz`.

Method: collision tables parsed with `gbox/psomap.collision(data, be=True)` (GC big-endian c.rel;
face stride 36 bytes, flag = u16 at face base + 0x20). Mesh table walked from u32 at (len−0x10),
0x18-byte entries, until u32 at (len−0x20). Walkable grid via `psomap.walkable_cells(size=10, step=6, body=18)`.
Sets from `pso_gc.gsl_files` over the extracted `*.gsl` archives; enemy model packs `bm_ene_*`,
object packs `fe_*`/`obj*`. Map bin set per area: e (enemy data), f (objects), g (geometry refs),
j (jump tables), s (sections/wave data).

## Collision tables (c.rel)

| Area | c.rel file | bytes | meshes | triangles | verts total | verts unique | flags (histogram) | bounds mm (x/y/z) | walkable / blocked cells |
|---|---|---|---|---|---|---|---|---|---|
| Forest 1 | Scene/map_forest01c.rel | 72096 | 69 | 1455 | 1372 | 1070 | 257:591, 2336:540, 32768:164, 272:94, 260:39, 320:21, 273:6 | -683–685/-23–215/-654–660 | 6463 / 2599 |
| Cave 1 | Scene/map_cave01_00c.rel | 363776 | 85 | 7934 | 6181 | 4926 | 288:3555, 257:2725, 32768:1008, 8192:584, 320:62 | -441–3166/-10–159/-2141–438 | 17877 / 7458 |
| Mine 1 | Scene/map_machine01_00c.rel | 280736 | 110 | 5821 | 5502 | 4078 | 288:2484, 32768:1664, 257:1321, 8192:248, 320:104 | -59–3319/-10–100/-729–1809 | 13235 / 4429 |
| Ruins 1 | Scene/map_ruins01_00c.rel | 421152 | 150 | 8798 | 8119 | 6812 | 288:4349, 32768:2496, 1:1612, 320:134, 2048:108, 4:64, 32:16, 16:11, 2049:8 | -1349–975/-120–160/-1340–940 | 12795 / 5270 |
| Jungle 1 (designated Ep II area per task plan) | Scene/map_jungle01_00c.rel | 46624 | 61 | 899 | 948 | 576 | 288:316, 257:244, 32768:220, 8192:102, 320:17 | -2610–264/-150–200/-610–1010 | 5830 / 1357 |

## n.rel (nav) and set inventories

| Area | n.rel file | bytes | n.rel parse | gsl entries | enemy packs | object packs | map bins (e/f/g/j/s) |
|---|---|---|---|---|---|---|---|
| Forest 1 | Scene/map_forest01n.rel | 728768 | not determined | not determined | not determined | not determined | not determined |
| Cave 1 | Scene/map_cave01_00n.rel | 490304 | not determined | not determined | not determined | not determined | not determined |
| Mine 1 | Scene/map_machine01_00n.rel | 988160 | not determined | not determined | not determined | not determined | not determined |
| Ruins 1 | Scene/map_ruins01_00n.rel | 732992 | not determined | not determined | not determined | not determined | not determined |
| Jungle 1 (designated Ep II area per task plan) | Scene/map_jungle01_00n.rel | 1193952 | not determined | not determined | not determined | not determined | not determined |

## Column provenance

| Column | Source |
|---|---|
| c.rel / n.rel file | GCDisc file-table key (disc TOC scan; 649 `.rel` entries total) |
| bytes | `len(GCDisc.read(key))` |
| meshes | mesh-table walk: u32 root at offset len−0x10 (big-endian), 0x18-byte entries, until u32 at len−0x20 — `gbox/psomap.rel_root` |
| triangles, flags | `gbox/psomap.collision(data, be=True)`: face entries at 36-byte stride, flag = u16 at face base + 0x20 |
| verts total | sum of u32 `nv` at mesh header offset 0 per mesh |
| verts unique | deduplicated (x, y, z) tuples across all triangles |
| bounds mm | min/max of triangle vertex coordinates |
| walkable/blocked cells | `gbox/psomap.walkable_cells(tris, size=10.0, step=6.0, body=18.0)` |
| gsl entries / enemy / object | `pso_gc.gsl_files` over extracted `*.gsl`; name prefixes `bm_ene_*` (enemy), `fe_*`/`obj*` (objects) |
| map bins e/f/g/j/s | area manifest (gsl_files entry table); sizes per entry |
| spawn/wave records | **not determined** — record stride unverified; only header/rel_root probes performed |

Cross-check: forest01 measured 69 meshes / 1455 triangles in this run, matching the earlier
checkpoint reading of `map_forest01c.rel`.
#### Per-area enemy/object type table (from .gsl archive entry tables)

**Forest 1 (Episode I)** — `gsl_forest01.gsl`: 51 entries, 6 enemy packs, 40 object packs

| type | pack entry | byte offset | size | count | source |
|---|---|---|---|---|---|
| enemy | `bm_ene_common_all.bml` | 790528 | 13184 | 1 | gsl_forest01.gsl entry table |
| enemy | `bm_ene_re8_b_beast.bml` | 804864 | 196864 | 1 | gsl_forest01.gsl entry table |
| enemy | `bm_ene_lappy.bml` | 1003520 | 133568 | 1 | gsl_forest01.gsl entry table |
| enemy | `bm_ene_bm3_fly.bml` | 1173504 | 122688 | 1 | gsl_forest01.gsl entry table |
| enemy | `bm_ene_bm5_wolf.bml` | 1296384 | 200928 | 1 | gsl_forest01.gsl entry table |
| enemy | `bm_ene_npc_chao.bml` | 1499136 | 14656 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_doa_kanban.bml` | 43008 | 10272 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_door.gvm` | 55296 | 53504 | 1 | gsl_forest01.gsl entry table |
| object | `bm_fe_obj_komo.bml` | 110592 | 3936 | 1 | gsl_forest01.gsl entry table |
| object | `bm_o_abe_butterfly.bml` | 114688 | 3552 | 1 | gsl_forest01.gsl entry table |
| object | `abeno_fs_obj001_fosuno.bml` | 118784 | 4032 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_switch.gvm` | 122880 | 30016 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_baiku.bml` | 153600 | 9632 | 1 | gsl_forest01.gsl entry table |
| object | `obj_motorcycle.GVM` | 163840 | 196800 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_hako01_hahen02.bml` | 362496 | 3776 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_hako01_n.gvm` | 366592 | 8432 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_con_hahen1.bml` | 376832 | 4416 | 1 | gsl_forest01.gsl entry table |
| object | `obj_abecon.gvm` | 382976 | 27424 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_lazer2_4m.bml` | 411648 | 13664 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_lazer2.gvm` | 425984 | 6480 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_switch_laz.bml` | 434176 | 6336 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_switch_laz.gvm` | 442368 | 22992 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_tank.bml` | 466944 | 4448 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_tank.GVM` | 473088 | 27600 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_tanmatu02.bml` | 501760 | 4320 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_computer.gvm` | 507904 | 14576 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_hako_i_rail.bml` | 524288 | 4192 | 1 | gsl_forest01.gsl entry table |
| object | `obj_containerido.GVM` | 530432 | 19744 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_warp.bml` | 550912 | 15072 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_warp.gvm` | 567296 | 9728 | 1 | gsl_forest01.gsl entry table |
| object | `bm_fe_obj_o_capsule01.bml` | 577536 | 7200 | 1 | gsl_forest01.gsl entry table |
| object | `bm_fs_obj_lazerguard.bml` | 585728 | 8160 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_laz_guard_r.gvm` | 593920 | 608 | 1 | gsl_forest01.gsl entry table |
| object | `fe_obj_hashi.bml` | 595968 | 22880 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_hanyousu_body1.bml` | 620544 | 6720 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_hanyousu_light.bml` | 628736 | 5056 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_hanyousu_light_ao.GVM` | 634880 | 608 | 1 | gsl_forest01.gsl entry table |
| object | `bm_o_mine.bml` | 636928 | 17696 | 1 | gsl_forest01.gsl entry table |
| object | `bm_fs_obj_sensor.bml` | 655360 | 17280 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_sensor_r.gvm` | 673792 | 13216 | 1 | gsl_forest01.gsl entry table |
| object | `bm_fe_obj_kaifuku_moto.bml` | 688128 | 30688 | 1 | gsl_forest01.gsl entry table |
| object | `symbolchatcolli.prs` | 718848 | 717 | 1 | gsl_forest01.gsl entry table |
| object | `bm_fs_obj_ki_doa_panel.bml` | 720896 | 28960 | 1 | gsl_forest01.gsl entry table |
| object | `fs_obj_ki_doa_panel_r.gvm` | 751616 | 34960 | 1 | gsl_forest01.gsl entry table |
| object | `ChatSensor.prs` | 788480 | 61 | 1 | gsl_forest01.gsl entry table |
| object | `re3_b_lappy_base_ao.gvm` | 1138688 | 33040 | 1 | gsl_forest01.gsl entry table |

**Cave 1 (Episode I)** — `gsl_cave01.gsl`: 46 entries, 6 enemy packs, 35 object packs

| type | pack entry | byte offset | size | count | source |
|---|---|---|---|---|---|
| enemy | `bm_ene_common_all.bml` | 731136 | 13184 | 1 | gsl_cave01.gsl entry table |
| enemy | `bm_ene_grass.bml` | 745472 | 128704 | 1 | gsl_cave01.gsl entry table |
| enemy | `bm_ene_cgrass.bml` | 874496 | 4864 | 1 | gsl_cave01.gsl entry table |
| enemy | `bm_ene_re2_flower.bml` | 880640 | 97472 | 1 | gsl_cave01.gsl entry table |
| enemy | `bm_ene_nanodrago.bml` | 978944 | 174048 | 1 | gsl_cave01.gsl entry table |
| enemy | `bm_ene_bm1_shark.bml` | 1153024 | 279136 | 1 | gsl_cave01.gsl entry table |
| object | `fs_obj_warp.bml` | 53248 | 15072 | 1 | gsl_cave01.gsl entry table |
| object | `fs_obj_warp.gvm` | 69632 | 9728 | 1 | gsl_cave01.gsl entry table |
| object | `bm_fe_obj_o_capsule01.bml` | 79872 | 7200 | 1 | gsl_cave01.gsl entry table |
| object | `bm_o_mine.bml` | 88064 | 17696 | 1 | gsl_cave01.gsl entry table |
| object | `abeno_fs_obj001_fosuno.bml` | 106496 | 4032 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_switch.gvm` | 110592 | 30016 | 1 | gsl_cave01.gsl entry table |
| object | `bm_fs_obj_do_doa_panel.bml` | 141312 | 7840 | 1 | gsl_cave01.gsl entry table |
| object | `fs_obj_do_doa_panelr.gvm` | 149504 | 6336 | 1 | gsl_cave01.gsl entry table |
| object | `bm_fs_obj_do_doa01.bml` | 157696 | 35104 | 1 | gsl_cave01.gsl entry table |
| object | `fs_obj_do_doa01r.gvm` | 194560 | 35520 | 1 | gsl_cave01.gsl entry table |
| object | `bm_fs_obj_do_doa02.bml` | 231424 | 35104 | 1 | gsl_cave01.gsl entry table |
| object | `fs_obj_do_doa02r.gvm` | 268288 | 35520 | 1 | gsl_cave01.gsl entry table |
| object | `bm_fs_obj_do_doa03.bml` | 305152 | 33088 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_turiten_moto.bml` | 339968 | 51968 | 1 | gsl_cave01.gsl entry table |
| object | `fs_obj_turiten_singo.gvm` | 393216 | 2144 | 1 | gsl_cave01.gsl entry table |
| object | `fs_obj_turiten_singo_r.gvm` | 397312 | 2144 | 1 | gsl_cave01.gsl entry table |
| object | `bm_o_rock_cave01.bml` | 401408 | 33088 | 1 | gsl_cave01.gsl entry table |
| object | `bm_fe_obj_rb_liwa.bml` | 436224 | 57024 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_lazer2_4m.bml` | 493568 | 13664 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_lazer2.gvm` | 507904 | 6480 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_switch_laz.bml` | 516096 | 6336 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_switch_laz.gvm` | 524288 | 22992 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_hako01_hahen02.bml` | 548864 | 3776 | 1 | gsl_cave01.gsl entry table |
| object | `fs_obj_hako01_n.gvm` | 552960 | 8432 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_con_hahen1.bml` | 563200 | 4416 | 1 | gsl_cave01.gsl entry table |
| object | `obj_abecon.gvm` | 569344 | 27424 | 1 | gsl_cave01.gsl entry table |
| object | `bm_fe_obj_kaifuku_moto.bml` | 598016 | 30688 | 1 | gsl_cave01.gsl entry table |
| object | `bm_o_bind.bml` | 628736 | 48064 | 1 | gsl_cave01.gsl entry table |
| object | `symbolchatcolli.prs` | 677888 | 717 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_hako_i_rail.bml` | 679936 | 4192 | 1 | gsl_cave01.gsl entry table |
| object | `obj_containerido.GVM` | 686080 | 19744 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_tanmatu02.bml` | 706560 | 4320 | 1 | gsl_cave01.gsl entry table |
| object | `fe_obj_computer.gvm` | 712704 | 14576 | 1 | gsl_cave01.gsl entry table |
| object | `ChatSensor.prs` | 729088 | 61 | 1 | gsl_cave01.gsl entry table |
| object | `bm7_s_paa_body.bml` | 1433600 | 472416 | 1 | gsl_cave01.gsl entry table |

**Mine 1 (Episode I)** — `gsl_machine01.gsl`: 52 entries, 5 enemy packs, 42 object packs

| type | pack entry | byte offset | size | count | source |
|---|---|---|---|---|---|
| enemy | `bm_ene_common_all.bml` | 903168 | 13184 | 1 | gsl_machine01.gsl entry table |
| enemy | `bm_ene_dubchik.bml` | 917504 | 206048 | 1 | gsl_machine01.gsl entry table |
| enemy | `bm_ene_gyaranzo.bml` | 1191936 | 155200 | 1 | gsl_machine01.gsl entry table |
| enemy | `bm_ene_me3_shinowa.bml` | 1347584 | 202752 | 1 | gsl_machine01.gsl entry table |
| enemy | `bm_ene_me1_mb.bml` | 1550336 | 63968 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_hanyousu_body1.bml` | 40960 | 6720 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_hanyousu_light.bml` | 49152 | 5056 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_hanyousu_light_ao.GVM` | 55296 | 608 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_warp.bml` | 57344 | 15072 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_warp.gvm` | 73728 | 9728 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fe_obj_o_capsule01.bml` | 83968 | 7200 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_lazerguard.bml` | 92160 | 8160 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_laz_guard_r.gvm` | 100352 | 608 | 1 | gsl_machine01.gsl entry table |
| object | `bm_o_mine.bml` | 102400 | 17696 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_sensor.bml` | 120832 | 17280 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_sensor_r.gvm` | 139264 | 13216 | 1 | gsl_machine01.gsl entry table |
| object | `fe_obj_hako01_hahen02.bml` | 153600 | 3776 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_hako01_n.gvm` | 157696 | 8432 | 1 | gsl_machine01.gsl entry table |
| object | `fe_obj_con_hahen1.bml` | 167936 | 4416 | 1 | gsl_machine01.gsl entry table |
| object | `obj_abecon.gvm` | 174080 | 27424 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fe_obj_kaifuku_moto.bml` | 202752 | 30688 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_ki_doa.bml` | 233472 | 33184 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_ki_doa_r.gvm` | 268288 | 35520 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_ki_doa2.bml` | 305152 | 34208 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_ki_doa2_r.gvm` | 339968 | 35520 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_ki_doa_panel.bml` | 376832 | 28960 | 1 | gsl_machine01.gsl entry table |
| object | `fs_obj_ki_doa_panel_r.gvm` | 407552 | 34960 | 1 | gsl_machine01.gsl entry table |
| object | `bm_o_bind.bml` | 444416 | 48064 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_cap_moto.bml` | 493568 | 58816 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_kenkyu_com.bml` | 552960 | 51968 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_monitor.bml` | 606208 | 32160 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_mekatombo.bml` | 638976 | 12416 | 1 | gsl_machine01.gsl entry table |
| object | `bm_o_light_machine01.bml` | 653312 | 10272 | 1 | gsl_machine01.gsl entry table |
| object | `bm_o_explosive_machine.bml` | 665600 | 82880 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fe_obj_tank_hikari.bml` | 749568 | 37376 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_hanger_moto.bml` | 788480 | 19136 | 1 | gsl_machine01.gsl entry table |
| object | `fe_obj_lazer2_4m.bml` | 808960 | 13664 | 1 | gsl_machine01.gsl entry table |
| object | `fe_obj_lazer2.gvm` | 823296 | 6480 | 1 | gsl_machine01.gsl entry table |
| object | `fe_obj_switch_laz.bml` | 831488 | 6336 | 1 | gsl_machine01.gsl entry table |
| object | `fe_obj_switch_laz.gvm` | 839680 | 22992 | 1 | gsl_machine01.gsl entry table |
| object | `symbolchatcolli.prs` | 864256 | 717 | 1 | gsl_machine01.gsl entry table |
| object | `fe_obj_tanmatu02.bml` | 866304 | 4320 | 1 | gsl_machine01.gsl entry table |
| object | `fe_obj_computer.gvm` | 872448 | 14576 | 1 | gsl_machine01.gsl entry table |
| object | `ChatSensor.prs` | 888832 | 61 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_o_torabasami.bml` | 890880 | 11104 | 1 | gsl_machine01.gsl entry table |
| object | `me2_y_me2_z.gvm` | 1124352 | 65680 | 1 | gsl_machine01.gsl entry table |
| object | `bm_fs_obj_zombie_con.bml` | 1615872 | 37184 | 1 | gsl_machine01.gsl entry table |

**Jungle 1 (Episode II)** — `gsl_jungle01.gsl`: 60 entries, 9 enemy packs, 41 object packs

| type | pack entry | byte offset | size | count | source |
|---|---|---|---|---|---|
| enemy | `bm_ene_common_all.bml` | 847872 | 13184 | 1 | gsl_jungle01.gsl entry table |
| enemy | `bm_ene_me3_stelthshinowa.bml` | 862208 | 236512 | 1 | gsl_jungle01.gsl entry table |
| enemy | `bm_ene_re8_merill_lia.bml` | 1099776 | 180736 | 1 | gsl_jungle01.gsl entry table |
| enemy | `bm_ene_bm9_s_mericarol.bml` | 1282048 | 286464 | 1 | gsl_jungle01.gsl entry table |
| enemy | `bm_ene_bm5_gibon_u.bml` | 1568768 | 214816 | 1 | gsl_jungle01.gsl entry table |
| enemy | `bm_ene_gibbles.bml` | 1783808 | 149984 | 1 | gsl_jungle01.gsl entry table |
| enemy | `bm_ene_me1_gee.bml` | 1935360 | 51968 | 1 | gsl_jungle01.gsl entry table |
| enemy | `bm_ene_gi_gue.bml` | 1988608 | 114336 | 1 | gsl_jungle01.gsl entry table |
| enemy | `bm_ene_lappy.bml` | 2103296 | 133568 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_hako01.bml` | 217088 | 11104 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_warp_jung.bml` | 229376 | 24384 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_beamdoa.bml` | 253952 | 17664 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_fe_obj_komo.bml` | 272384 | 3936 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_o_mine.bml` | 276480 | 17696 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_tanmatu02.bml` | 294912 | 8256 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_tanmatu02.gvm` | 305152 | 20896 | 1 | gsl_jungle01.gsl entry table |
| object | `fe_obj_lazer2_2.bml` | 327680 | 30368 | 1 | gsl_jungle01.gsl entry table |
| object | `fe_obj_lazer2_2.gvm` | 358400 | 11088 | 1 | gsl_jungle01.gsl entry table |
| object | `fe_obj_switch_laz_j.bml` | 370688 | 9056 | 1 | gsl_jungle01.gsl entry table |
| object | `fe_obj_switch_laz_j.gvm` | 380928 | 22016 | 1 | gsl_jungle01.gsl entry table |
| object | `fe_obj_kaifuku_moto_2.bml` | 403456 | 11584 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_hanyousu_body1_j.bml` | 415744 | 8960 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_hanyousu_light_j.bml` | 425984 | 4032 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_hanyousu_light_ao_j.GVM` | 430080 | 608 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_key_jungle.bml` | 432128 | 11584 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_key_jungle_red.gvm` | 444416 | 6896 | 1 | gsl_jungle01.gsl entry table |
| object | `fe_obj_hako02.bml` | 452608 | 11584 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_o_jungle_doormain.bml` | 464896 | 11104 | 1 | gsl_jungle01.gsl entry table |
| object | `o_jungle_doormain.gvm` | 477184 | 98752 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_jungle_mkey.bml` | 577536 | 22784 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_o_rock_jungle.bml` | 602112 | 29024 | 1 | gsl_jungle01.gsl entry table |
| object | `o_rock_jungle_123.GVM` | 632832 | 11104 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_o_grass_jungle.bml` | 645120 | 2816 | 1 | gsl_jungle01.gsl entry table |
| object | `o_grass_jungle.gvm` | 649216 | 8288 | 1 | gsl_jungle01.gsl entry table |
| object | `bg_lightning.gvm` | 659456 | 18944 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_geenest.bml` | 679936 | 18976 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_labo_infocapsule.bml` | 700416 | 9472 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_seabed_turigane.bml` | 710656 | 7520 | 1 | gsl_jungle01.gsl entry table |
| object | `obj_seabed_turigane.gvm` | 718848 | 14576 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_warp.bml` | 735232 | 15072 | 1 | gsl_jungle01.gsl entry table |
| object | `fs_obj_warp.gvm` | 751616 | 9728 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_warpboss_jungle.bml` | 761856 | 24288 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_jungle_nokogiri.bml` | 786432 | 32128 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_jungle_biwamushi.bml` | 819200 | 4736 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_jungle_kamome.bml` | 825344 | 6464 | 1 | gsl_jungle01.gsl entry table |
| object | `obj_jungle_kamome.gvm` | 833536 | 4240 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_obj_seabed_pillar.bml` | 839680 | 7872 | 1 | gsl_jungle01.gsl entry table |
| object | `PlyMotionNpcTown.cpt` | 2238464 | 7948 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_n_delta_w_body.bml` | 2246656 | 52800 | 1 | gsl_jungle01.gsl entry table |
| object | `bm_nctrunk_body.bml` | 2299904 | 33632 | 1 | gsl_jungle01.gsl entry table |

**Ruins 1 (Episode I)** — `gsl_ruins01.gsl`: 50 entries, 9 enemy packs, 36 object packs

| type | pack entry | byte offset | size | count | source |
|---|---|---|---|---|---|
| enemy | `bm_ene_common_all.bml` | 1411072 | 13184 | 1 | gsl_ruins01.gsl entry table |
| enemy | `bm_ene_lappy.bml` | 1425408 | 133568 | 1 | gsl_ruins01.gsl entry table |
| enemy | `bm_ene_bm2_moja.bml` | 1560576 | 276928 | 1 | gsl_ruins01.gsl entry table |
| enemy | `bm_ene_grass.bml` | 1839104 | 128704 | 1 | gsl_ruins01.gsl entry table |
| enemy | `bm_ene_cgrass.bml` | 1968128 | 4864 | 1 | gsl_ruins01.gsl entry table |
| enemy | `bm_ene_re2_flower.bml` | 1974272 | 97472 | 1 | gsl_ruins01.gsl entry table |
| enemy | `bm_ene_bm3_fly.bml` | 2072576 | 122688 | 1 | gsl_ruins01.gsl entry table |
| enemy | `bm_ene_df3_dimedian.bml` | 2195456 | 236640 | 1 | gsl_ruins01.gsl entry table |
| enemy | `bm_ene_re7_berura.bml` | 2433024 | 117760 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_fe_obj_kaifuku_moto.bml` | 90112 | 30688 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_warp.bml` | 120832 | 15072 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_warp.gvm` | 137216 | 9728 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_obj_warpboss.bml` | 147456 | 15488 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_o_mine.bml` | 163840 | 17696 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_lazer2_4m.bml` | 182272 | 13664 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_lazer2.gvm` | 196608 | 6480 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_switch_laz.bml` | 204800 | 6336 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_switch_laz.gvm` | 212992 | 22992 | 1 | gsl_ruins01.gsl entry table |
| object | `abeno_fs_obj001_fosuno.bml` | 237568 | 4032 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_switch.gvm` | 241664 | 30016 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_hanyousu_body1.bml` | 272384 | 6720 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_hanyousu_light.bml` | 280576 | 5056 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_hanyousu_light_ao.GVM` | 286720 | 608 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_fs_obj_do_doa_panel.bml` | 288768 | 7840 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_do_doa_panelr.gvm` | 296960 | 6336 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_fs_obj_ki_doa_panel.bml` | 305152 | 28960 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_ki_doa_panel_r.gvm` | 335872 | 34960 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_tanmatu02.bml` | 372736 | 4320 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_computer.gvm` | 378880 | 14576 | 1 | gsl_ruins01.gsl entry table |
| object | `ChatSensor.prs` | 395264 | 61 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_o_vs2door01l.bml` | 397312 | 35296 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_o_vs2door01lr.gvm` | 434176 | 33424 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_o_vs2container.bml` | 468992 | 35744 | 1 | gsl_ruins01.gsl entry table |
| object | `fs_obj_o_vs2container_r.gvm` | 505856 | 12480 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_o_vs2cont_hahen1_r.gvm` | 520192 | 10384 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj_o_vs2cont_hahen2_r.gvm` | 532480 | 10384 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_o_vs2.bml` | 544768 | 580096 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj306_hashi.bml` | 1126400 | 25440 | 1 | gsl_ruins01.gsl entry table |
| object | `fe_obj321_hashi.bml` | 1153024 | 44288 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_obj_ruins_turiten.bml` | 1198080 | 58624 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_obj_ruins_pillar.bml` | 1257472 | 11168 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_o_trap_ancient01.bml` | 1269760 | 57440 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_obj_door_ruins.bml` | 1329152 | 36384 | 1 | gsl_ruins01.gsl entry table |
| object | `obj_door_ruins_green.gvm` | 1366016 | 33424 | 1 | gsl_ruins01.gsl entry table |
| object | `bm_obj_labo_infocapsule.bml` | 1400832 | 9472 | 1 | gsl_ruins01.gsl entry table |

## e.bin/f.bin spawn record layout (d.dat/e.dat equivalents)

| area | file | size (bytes) | byte offset in gsl_<area>.gsl | first 32 bytes | record layout |
|---|---|---|---|---|---|
| forest01 | `map_forest_e.bin` | 4340 | 12288 | `d4010000840d0000f4100000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| forest01 | `map_forest_f.bin` | 4540 | 18432 | `d40100004c0e0000bc110000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| forest01 | `map_forest_g.bin` | 4532 | 24576 | `d4010000440e0000b4110000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| forest01 | `map_forest_j.bin` | 4300 | 30720 | `d40100005c0d0000cc100000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| forest01 | `map_forest_s.bin` | 4160 | 36864 | `d4010000d00c000040100000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| cave01 | `map_cave_e.bin` | 7444 | 12288 | `d40100005c170000141d0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| cave01 | `map_cave_f.bin` | 7804 | 20480 | `d4010000c41800007c1e0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| cave01 | `map_cave_g.bin` | 7896 | 28672 | `d401000020190000d81e0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| cave01 | `map_cave_j.bin` | 7876 | 36864 | `d40100000c190000c41e0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| cave01 | `map_cave_s.bin` | 7348 | 45056 | `d4010000fc160000b41c0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| machine01 | `map_machine_e.bin` | 4108 | 12288 | `d4010000f00b00000c100000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| machine01 | `map_machine_f.bin` | 4412 | 18432 | `d4010000200d00003c110000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| machine01 | `map_machine_g.bin` | 4380 | 24576 | `d4010000000d00001c110000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| machine01 | `map_machine_j.bin` | 4204 | 30720 | `d4010000500c00006c100000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| machine01 | `map_machine_s.bin` | 4024 | 36864 | `d40100009c0b0000b80f0000ffffffffff00ffff7469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_j.bin` | 18404 | 12288 | `d4010000ec3c0000e4470000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_e.bin` | 19260 | 30720 | `d4010000444000003c4b0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_g.bin` | 20564 | 51200 | `d40100005c45000054500000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_f.bin` | 20148 | 73728 | `d4010000bc430000b44e0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_s.bin` | 20016 | 94208 | `d401000038430000304e0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_j_u.bin` | 18404 | 114688 | `d4010000ec3c0000e4470000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_e_u.bin` | 19260 | 133120 | `d4010000444000003c4b0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_g_u.bin` | 20564 | 153600 | `d40100005c45000054500000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_f_u.bin` | 20148 | 176128 | `d4010000bc430000b44e0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| jungle01 | `map_jungle_s_u.bin` | 20016 | 196608 | `d401000038430000304e0000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| ruins01 | `map_ruin_j.bin` | 13864 | 12288 | `d40100008c31000028360000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| ruins01 | `map_ruin_e.bin` | 14164 | 26624 | `d4010000b832000054370000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| ruins01 | `map_ruin_g.bin` | 14428 | 40960 | `d4010000c03300005c380000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| ruins01 | `map_ruin_f.bin` | 14596 | 57344 | `d40100006834000004390000ffffffffff00ff007469746c652064756d6d7900` | not determined |
| ruins01 | `map_ruin_s.bin` | 14416 | 73728 | `d4010000b433000050380000ffffffffff00ff007469746c652064756d6d7900` | not determined |

These map_* bins are the GC equivalents of the ticket's d.dat/e.dat per-area object/enemy spawn data. Record fields (enemy/object ids, positions, rotations, wave/section) are **not determined**: the layout is undocumented in docs/pso_gc.md and no repository parser exists; raw bytes remain at the offsets above in scratch pso9184/ for a future focused decode.

## Provenance

| column / field | source | parser / tool | byte offsets |
|---|---|---|---|
| c.rel mesh/triangle/vertex counts, flag histogram, bounds, walkable cells | map_<area>_c.rel extracted from the disc | gbox.psomap.collision (via gbox.pso_rom_export) | see c.rel measurements in scratch pso9184/ |
| enemy/object type tables | gsl_<area>.gsl entry tables (0x30-byte entries: char name[0x20], u32 BE offset, u32 BE size) | byte inspection of extracted archives; archive layout per docs/pso_gc.md "GSL area archives" | per-row byte offsets above (verified: every offset+size <= archive size) |
| map e.bin/f.bin sizes/offsets/headers | same gsl entry tables | byte inspection; first 32 bytes dumped per entry | listed in the e.bin/f.bin table above |
| map e.bin/f.bin record layout (ids, positions, rotations, wave/section) | not determined | no repository parser; layout undocumented | - |
| n.rel geometry counts | n.rel via gbox.pso_rom_export reader | not determined - parser returned empty geometry (0 meshes) on this disc | - |

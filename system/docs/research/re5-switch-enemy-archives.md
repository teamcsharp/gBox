# RE5 (Switch) enemy model archives: full entry catalog

Request #9075 (a503f0cb6e594832). Evidence artifact: `re5-switch-enemy-archives.json` (this directory).

- RomFS: `/home/ehm_eckx/gBox_alt/switch/romfs/010018100CD46000` (read-only source)
- Archives: `/home/ehm_eckx/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive/uEm*.arc` — **139** archives, **28490** entries total
- Parsers (repository, no new code): `gbox.mt_arc.parse` (arc entry table), `gbox.mt_model.parse_mod` (MOD geometry containers: bone count, mesh record count, option-group ids, LOD masks via `header()`/`meshes()`), `gbox.mt_model.parse` (MRL containers: material names from the path table), `gbox.mtf_tex.parse` (TEX surfaces: format/size fields where exposed). Entry payloads are zlib streams, decompressed before magic dispatch.
- Generated (UTC): 2026-11-09 18:48:53

## Summary

| archive | size | entries | MOD | MRL | TEX | other | bones | mesh records | option groups | sha256 |
|---|---|---|---|---|---|---|---|---|---|---|
| uEm0b.arc | 13,346,098 | 197|12|7|34|144|70|207|60|01a2580b962f |
| uEm0bEff.arc | 6,552,327 | 81|11|6|30|34|0|186|60|610459898f8f |
| uEm0c.arc | 11,295,746 | 197|12|7|46|132|57|205|30|9ae81804337a |
| uEm0cEff.arc | 6,334,923 | 81|10|5|29|37|0|123|30|2f4739d14efa |
| uEm0d.arc | 14,012,148 | 171|14|7|37|113|41|124|21|67f62f4e189e |
| uEm0dEff.arc | 6,715,831 | 88|13|6|31|38|0|107|21|7c91210a87b8 |
| uEm0e.arc | 15,709,538 | 187|10|6|42|129|36|137|21|7068180a34f4 |
| uEm0eEff.arc | 6,536,839 | 85|9|5|31|40|0|95|21|c3b5dd44aa44 |
| uEm10.arc | 82,582,897 | 787|32|27|196|532|1715|2320|74|1fa271890891 |
| uEm10Eff.arc | 6,477,595 | 89|11|6|31|41|0|153|30|b1f478d1791a |
| uEm11.arc | 24,538,107 | 397|14|11|69|303|452|287|30|a33ae046d908 |
| uEm11Eff.arc | 5,955,485 | 66|9|6|27|24|0|151|30|7d2a1929fa48 |
| uEm12.arc | 40,229,950 | 622|14|8|74|526|175|721|33|4224faf2cc80 |
| uEm12Eff.arc | 6,197,314 | 75|11|5|29|30|0|129|30|4ea59c67f9a9 |
| uEm13.arc | 17,810,645 | 135|7|4|39|85|89|136|30|1db1a79a0b14 |
| uEm13Eff.arc | 5,761,926 | 55|6|3|21|25|0|105|30|743311aac438 |
| uEm14.arc | 47,687,699 | 656|12|9|106|529|166|1270|41|52399b0b7e18 |
| uEm14Eff.arc | 5,960,453 | 69|9|6|27|27|0|151|30|e8779c03aafd |
| uEm1d.arc | 29,604,999 | 203|1|1|86|115|94|346|56|008db0da1e74 |
| uEm1e.arc | 7,701,605 | 145|1|1|28|115|85|64|10|848490e705a1 |
| uEm20.arc | 14,805,899 | 166|13|7|40|106|120|192|30|269559f2de33 |
| uEm20Eff.arc | 5,953,654 | 84|12|6|23|43|0|133|30|0235de8010cb |
| uEm21.arc | 14,524,683 | 146|1|1|25|119|90|38|7|3c01b16d948a |
| uEm22.arc | 14,147,228 | 164|8|5|40|111|98|144|30|2020d20dabab |
| uEm22Eff.arc | 5,809,049 | 73|7|4|21|41|0|106|30|5e2e5f9dc875 |
| uEm23.arc | 17,764,054 | 187|11|8|62|106|93|193|31|4441a22c2e43 |
| uEm23Eff.arc | 5,828,301 | 74|10|7|27|30|0|112|30|7e3fbd83de4d |
| uEm24.arc | 25,685,134 | 217|11|6|49|151|89|188|30|482172df0b73 |
| uEm24Eff.arc | 5,792,876 | 68|10|5|24|29|0|122|30|29e1d9b41c0d |
| uEm26.arc | 15,786,767 | 170|13|7|44|106|120|232|30|31010f45f9c9 |
| uEm26Eff.arc | 5,953,613 | 84|12|6|23|43|0|133|30|c68e8bb419b0 |
| uEm27.arc | 44,111,872 | 314|17|9|113|175|361|431|30|31c88a21191d |
| uEm27Eff.arc | 6,684,835 | 117|14|6|28|69|0|135|30|7c6871dc4e50 |
| uEm30.arc | 21,023,131 | 381|15|10|51|305|197|355|30|b50b3208a4e0 |
| uEm30Eff.arc | 6,235,426 | 88|12|7|29|40|0|186|30|6c48651555e3 |
| uEm31.arc | 14,342,518 | 373|14|9|45|305|107|277|30|8fcab68fd153 |
| uEm32.arc | 24,979,997 | 394|13|7|46|328|206|136|21|42ea8e01a4a7 |
| uEm32Eff.arc | 6,454,220 | 115|9|3|28|75|0|85|21|89b46a36193f |
| uEm34.arc | 21,571,928 | 507|16|11|48|432|126|209|30|6050bb8168d0 |
| uEm3401.arc | 6,246,955 | 45|4|4|16|21|126|65|1|113d405c13fc |
| uEm3402.arc | 13,952,713 | 374|4|4|16|350|126|65|1|130bd549fa2e |
| uEm3403.arc | 13,952,713 | 374|4|4|16|350|126|65|1|4515ed900faa |
| uEm34Eff.arc | 7,483,841 | 123|12|7|32|72|0|144|30|64689f3f4327 |
| uEm40.arc | 31,805,054 | 678|20|14|59|585|448|444|61|230c16dfadae |
| uEm40Dummy.arc | 31,263,003 | 387|20|14|59|294|448|444|61|e86697e7d60b |
| uEm40Eff.arc | 6,395,279 | 119|14|8|26|71|0|284|61|580d830a8e74 |
| uEm40Parts.arc | 31,264,545 | 389|20|14|59|296|448|444|61|42e6ee496dc4 |
| uEm41.arc | 37,459,793 | 674|25|19|92|538|441|596|61|5bae96bfb805 |
| uEm41Arm.arc | 21,571,034 | 383|6|6|35|336|204|164|38|0bf1730c9f9e |
| uEm41Core.arc | 18,647,316 | 311|7|7|39|258|217|170|38|7e60f5695468 |
| uEm41Eff.arc | 6,673,857 | 141|17|11|34|79|0|330|61|68bce306e375 |
| uEm42.arc | 38,988,790 | 677|20|16|63|578|273|399|61|77753f296a39 |
| uEm42Core.arc | 23,628,768 | 240|7|7|34|192|260|130|8|62d40818e6d8 |
| uEm42Eff.arc | 6,192,114 | 121|12|8|28|73|0|263|61|0211511c704a |
| uEm42Slime.arc | 25,938,060 | 421|7|7|34|373|260|130|8|f462be81a10b |
| uEm42Tentacle.arc | 25,701,736 | 409|7|7|34|361|260|130|8|0f9d9d7bb2b6 |
| uEm43.arc | 44,862,451 | 520|17|13|83|407|134|268|21|82a4f9810751 |
| uEm43Eff.arc | 6,400,684 | 130|15|11|37|67|0|148|21|e440902543a3 |
| uEm44.arc | 31,130,210 | 451|12|6|49|384|126|213|30|a722b42b92b0 |
| uEm44Eff.arc | 4,950,550 | 90|11|5|20|54|0|129|30|7de2f769aa25 |
| uEm45.arc | 34,382,219 | 428|17|11|131|269|218|331|21|34bded33d145 |
| uEm4501.arc | 22,704,642 | 107|4|4|96|3|218|249|11|9d20ebcf8002 |
| uEm4502.arc | 27,981,894 | 303|4|4|96|199|218|249|11|abe2006fa1d0 |
| uEm45Eff.arc | 6,394,977 | 121|13|7|35|66|0|82|21|38500d360bc8 |
| uEm46.arc | 76,351,098 | 485|20|16|120|329|730|263|30|a04ff357c479 |
| uEm46Eff.arc | 5,845,128 | 82|9|5|24|44|0|132|30|1c1f23c10790 |
| uEm52.arc | 9,847,248 | 105|2|1|28|74|10|109|11|0314ff46455b |
| uEm60.arc | 9,141,576 | 92|3|2|24|63|27|69|20|332889df1da7 |
| uEm60Eff.arc | 4,867,964 | 38|2|1|14|21|0|32|20|310aaefd2d0d |
| uEm61.arc | 5,764,747 | 83|8|3|22|50|25|100|21|8ae83e29a55c |
| uEm61Eff.arc | 5,034,266 | 49|7|2|16|24|0|65|21|1013466383ac |
| uEm62.arc | 5,913,909 | 83|8|3|23|49|20|125|21|984fcb151418 |
| uEm62Eff.arc | 5,033,502 | 48|7|2|16|23|0|65|21|ebf8eaebc858 |
| uEm63.arc | 3,354,323 | 60|8|2|14|36|11|77|21|2b7785b45a15 |
| uEm63Eff.arc | 2,792,433 | 31|7|1|8|15|0|68|21|ff6d1979210f |
| uEm65.arc | 4,069,090 | 72|6|3|21|42|16|64|21|0ef327b47a5b |
| uEm65Eff.arc | 3,495,109 | 41|5|2|15|19|0|60|21|1c0c12d49b9c |
| uEm66.arc | 6,070,848 | 97|8|3|17|69|29|74|21|31d1484a997e |
| uEm66Eff.arc | 2,654,704 | 47|7|2|10|28|0|58|21|21a77386ba3d |
| uEm6c.arc | 4,334,405 | 68|5|2|22|39|28|56|20|6fc363381592 |
| uEm6cEff.arc | 3,704,296 | 38|4|1|14|19|0|42|20|817deb1e2bfb |
| uEm6d.arc | 3,840,890 | 67|4|3|14|46|15|47|20|848905ed5571 |
| uEm6dEff.arc | 2,898,913 | 30|3|2|11|14|0|35|20|b344a3fba48d |
| uEm6f.arc | 5,946,210 | 73|7|3|18|45|19|104|21|a944fae5691b |
| uEm6fEff.arc | 4,784,008 | 39|6|2|12|19|0|64|21|5b05553bb1cc |
| uEm70.arc | 4,221,706 | 72|4|3|20|45|36|46|20|02c6093b7783 |
| uEm70Eff.arc | 3,571,635 | 37|3|2|15|17|0|38|20|5f8fadb1b624 |
| uEm71.arc | 6,410,605 | 78|6|2|25|45|28|77|21|1b7cb654ef76 |
| uEm71Eff.arc | 5,933,186 | 53|5|1|20|27|0|63|21|078ce8dfc45c |
| uEm80.arc | 33,221,098 | 434|20|14|91|309|778|423|31|96ef46affb14 |
| uEm80Eff.arc | 6,443,351 | 142|12|6|27|97|0|104|30|adeedba23006 |
| uEm81.arc | 34,359,159 | 600|13|7|75|505|169|191|30|4f3258a1cd13 |
| uEm81Eff.arc | 6,445,160 | 144|12|6|27|99|0|104|30|b56351223d25 |
| uEm82.arc | 45,585,808 | 477|20|15|100|342|417|421|61|11bd0585cea3 |
| uEm82Eff.arc | 7,863,375 | 155|14|9|30|102|0|280|61|6e543e64e647 |
| uEm83.arc | 20,653,621 | 307|12|6|64|225|220|253|30|d27cd0b3e13e |
| uEm83Eff.arc | 6,310,475 | 81|10|4|24|43|0|106|30|8c190c7742c1 |
| uEm84.arc | 22,867,917 | 331|13|7|68|243|235|258|30|1ab6bfb91326 |
| uEm84Eff.arc | 6,397,256 | 99|10|4|25|60|0|106|30|8064b37d53fe |
| uEm85Excella.arc | 17,154,200 | 211|5|5|39|162|279|66|3|f821334e829d |
| uEm86Irving_1.arc | 24,154,228 | 211|5|5|39|162|443|117|4|7f63fa883aac |
| uEm87.arc | 15,057,039 | 35|3|3|27|2|300|29|4|c989adc8f68e |
| uEm87Irving_2.arc | 19,611,395 | 198|3|3|31|161|300|29|4|7f298ffe78c8 |
| uEm88Josh.arc | 15,868,711 | 221|5|5|49|162|454|123|5|c079a6e7cddb |
| uEm89Spencer.arc | 16,420,863 | 207|5|5|35|162|286|202|2|aac385838cf4 |
| uEm8aDechant.arc | 21,137,681 | 229|4|4|60|161|367|50|7|715667cb605c |
| uEm8bDave.arc | 21,988,102 | 240|4|4|69|163|267|43|8|aef0303b2dd1 |
| uEm8c.arc | 25,331,315 | 351|14|10|43|284|566|499|61|add0ce5a7aa8 |
| uEm8e.arc | 8,094,364 | 153|1|1|4|147|18|6|1|22dd1837f0d7 |
| uEm91Marchant.arc | 4,689,071 | 167|1|1|5|160|84|3|1|eba4fafe6ca1 |
| uEm92.arc | 20,104,381 | 159|4|4|39|112|423|125|6|7da2e4783835 |
| uEm92Wife.arc | 17,133,465 | 208|4|4|38|162|423|125|6|0182715268a4 |
| uEm93Bsaa_alpha.arc | 11,543,542 | 200|1|1|37|161|82|92|4|0df9468f7812 |
| uEm94Bsaa_delta.arc | 28,805,013 | 258|3|3|90|162|264|50|7|5efbd8095114 |
| uEm95Kirk.arc | 13,199,583 | 209|3|3|41|162|262|41|7|6c54db2ef18d |
| uEm96Majini_man.arc | 22,303,224 | 254|4|4|86|160|309|206|6|c5a42bbd245c |
| uEm97Butcher.arc | 9,522,684 | 63|3|3|27|30|294|44|18|84a486c5a004 |
| uEm98Butcher_corpse.arc | 21,374,224 | 229|2|2|65|160|249|186|15|ac24a47cbf48 |
| uEm99Civilian_corpse.arc | 7,091,561 | 187|1|1|25|160|82|29|3|cfef9866d58e |
| uEm9aBsaa_corpse.arc | 21,396,210 | 114|4|4|77|29|351|106|4|f36f5ab17539 |
| uEm9bUro_man_1.arc | 14,318,641 | 200|3|3|34|160|272|18|2|4ff4828814e8 |
| uEm9cUro_man_2.arc | 17,046,040 | 219|4|4|49|162|184|55|5|2d0baedd1a89 |
| uEm9dEff.arc | 1,653,641 | 7|2|0|2|3|0|30|21|c4377f05b72a |
| uEm9dSubject.arc | 14,368,077 | 181|1|1|19|160|84|7|2|65734bf77bc1 |
| uEm9eGuard.arc | 16,965,831 | 207|3|3|41|160|257|39|2|16948eff675d |
| uEm9fBsaa_bravo.arc | 4,866,414 | 167|1|1|5|160|84|3|1|ef2447d9d863 |
| uEma2.arc | 35,099,017 | 603|13|7|75|508|169|191|30|9a0fe2b1b581 |
| uEma2Eff.arc | 809,841 | 10|1|1|3|5|0|8|8|6a6873d85d61 |
| uEmc0.arc | 23,544,736 | 362|12|8|37|305|22|146|30|a3a6a8faead5 |
| uEmc0Eff.arc | 7,196,671 | 77|11|7|31|28|0|136|30|b9fe6ec009f3 |
| uEmc1.arc | 17,544,989 | 296|3|2|12|279|22|34|15|512c363b6427 |
| uEmc1Eff.arc | 1,813,742 | 14|2|1|6|5|0|26|15|3df67886fbbc |
| uEmc2.arc | 21,412,950 | 340|8|4|20|308|60|87|30|86c956714e16 |
| uEmc2Eff.arc | 5,877,571 | 59|7|3|17|32|0|86|30|2177382a50f7 |
| uEmc3.arc | 34,684,873 | 354|8|4|42|300|121|108|30|52172c716107 |
| uEmc3Eff.arc | 5,760,612 | 52|7|3|18|24|0|86|30|edfbae032947 |
| uEmc4.arc | 34,144 | 3|1|1|0|1|0|2|1|fc6b683d79a4 |
| uEmc5.arc | 12,362,722 | 367|1|1|3|362|11|6|1|abf417d53865 |
| uEmc6.arc | 223,628 | 6|1|1|3|1|3|15|2|f954440a7aef |

Container totals: MOD=1193, MRL=755, TEX=5419, other=21123

## Notes

- Each enemy model family is carried as paired entries with the same entry name: a MOD (geometry + skeleton) and an MRL (materials); the JSON keeps the explicit entry index for each, per the writer rule that MOD and MRL share names in these archives (see `gbox.re5_enemy_writer`).
- `option_groups` is the distinct set of per-mesh `group_index` values (the game selects groups per spawn); `lod_masks` is the distinct set of per-mesh `level_of_detail` values. `material_names` on MRL entries is the material/texture path table.
- `other`/`parse_error` entries are payloads that are neither MOD, MRL, nor a TEX the repository decodes; their first 4 magic bytes are recorded in the JSON (`magic` field).

- No entries failed to parse: every one of the 28490 entries in all 139 archives classified into MOD/MRL/TEX/other with zero per-entry errors; the 21123 `other` payloads are recorded by 4 magic bytes only (no guessed fields), per the writer rule.

## Verification

- JSON re-parsed: 139 archives, 28490 entries
- Every archive in `uEm*.arc` glob present: True
- JSON size: 7560509 bytes- Independent re-check (2026-11-09, this run): git diff baseline..269d01a8 adds only the two research files; JSON re-parsed with 139 archives / 28490 entries; per-archive sha256+size spot-checked against disk (uEm0b, uEm61, uEmc6: match); on-disk uEm*.arc set == JSON archive set (139).

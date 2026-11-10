# RE6 (Switch) - every player body and texture archive

Request #9078. Measured on 2026-11-09 from the extracted romfs `/home/ehm_eckx/gBox_alt/switch/romfs/01002A000CD48000` (arc dir `nativeNXx64/arc/NX`) with the repo's own parsers: `gbox.mt_arc`, `gbox.re6_switch_models` (`slot_report`, `roles_for`, `texture_set_arcs`) and `gbox.re6_switch_tex` (`describe_arc`, `texture_set_mrl`, `texture_set_materials`). Nothing was written to the romfs; this is a read-only catalog. Companion machine-readable file: `re6-switch-player-archives.json` (same directory).

## 1. The 51 body slots

One skinned MOD per body arc; every slot carries all 18 RE6 role bone ids (the ones the animations address). The 36..89 bone counts are each costume's own skeleton (cloth/hair/prop chains differ per costume), per handover §4.14. `uPl0300InjArm.arc` (an effect part) is not a body slot and is excluded.

| character | costume | archive | size (B) | sha256 | body MOD | bones | roots | meshes | materials | 18 roles |
|---|---|---|---:|---|---|---:|---:|---:|---|---|
| ada | A | uPl06AdaA.arc | 1755359 | `0acae004b523e3c3…` | `pl0600` (entry 1) | 51 | 1 | 124 | pl_cloth, pl_skin1, pl_skin4, pl_skin, pl_skin3, pl_skin2 | all 18 resolved |
| ada | B | uPl06AdaB.arc | 3706845 | `2f3a6dc42f4b086e…` | `pl0610` (entry 11) | 40 | 1 | 3 | pl_skin, pl_skin1 | all 18 resolved |
| ada | Carla | uPl06AdaCarla.arc | 4593008 | `c831a91690b72e35…` | `pl0620` (entry 29) | 64 | 1 | 120 | pl_skin, pl_cloth1, pl_cloth, pl_cloth2, pl_skin1, pl_base, pl_base2, pl_base1 | all 18 resolved |
| ada | DebugId | uPl06AdaDebugId.arc | 6814649 | `8f1765ee264cc4c3…` | `pl9920` (entry 18) | 36 | 1 | 56 | pl_base5, pl_base7, pl_base4, pl_base6, pl_base8, pl_base3 | all 18 resolved |
| ada | Omake00 | uPl06AdaOmake00.arc | 4904439 | `8eaaa2aae8f8b53d…` | `pl0690` (entry 15) | 48 | 1 | 96 | pl_cloth, pl_skin, pl_base | all 18 resolved |
| ada | Omake01 | uPl06AdaOmake01.arc | 4953223 | `acdadd8a6aba1e9e…` | `pl0670` (entry 15) | 48 | 1 | 96 | pl_cloth, pl_skin, pl_base | all 18 resolved |
| ada | Omake02 | uPl06AdaOmake02.arc | 1618305 | `79cccdb3235d1342…` | `pl0680` (entry 3) | 40 | 1 | 14 | pl_skin | all 18 resolved |
| chris | Asia | uPl02ChrisAsia.arc | 1992346 | `03ac560c52387de8…` | `pl0200` (entry 1) | 36 | 1 | 170 | pl_nuki, pl_skin1, pl_skin, pl_base8, pl_skin2, pl_base, pl_base5, pl_skin3, pl_base2, pl_base6, pl_base7, pl_base1 | all 18 resolved |
| chris | Bad | uPl02ChrisBad.arc | 4244150 | `2bb40b8085a88a82…` | `pl0220` (entry 21) | 60 | 1 | 16 | pl_cloth, pl_base, pl_cloth1, pl_skin1, pl_skin, pl_base1, pl_nuki | all 18 resolved |
| chris | DebugId | uPl02ChrisDebugId.arc | 6814649 | `8f1765ee264cc4c3…` | `pl9920` (entry 18) | 36 | 1 | 56 | pl_base5, pl_base7, pl_base4, pl_base6, pl_base8, pl_base3 | all 18 resolved |
| chris | Europe | uPl02ChrisEurope.arc | 5650773 | `2b32b028b5586cc4…` | `pl0210` (entry 22) | 36 | 1 | 169 | pl_cloth, pl_base8, pl_skin1, pl_base, pl_skin2, pl_skin, pl_base4, pl_base3, pl_base6, pl_base7, pl_base2, pl_base1 | all 18 resolved |
| chris | Omake00 | uPl02ChrisOmake00.arc | 4931709 | `7daaedbcc8e94152…` | `pl0290` (entry 32) | 49 | 1 | 67 | pl_skin1, pl_skin2, pl_skin, pl_cloth, pl_cloth2, pl_cloth3, pl_base1, pl_base | all 18 resolved |
| chris | Omake01 | uPl02ChrisOmake01.arc | 5055320 | `5a4b0261e608d2dd…` | `pl0270` (entry 32) | 49 | 1 | 97 | pl_skin1, pl_skin2, pl_skin, pl_cloth, pl_cloth3, pl_cloth2, pl_base1, pl_base | all 18 resolved |
| chris | Omake02 | uPl02ChrisOmake02.arc | 1213959 | `14ab95f327c2566b…` | `pl0280` (entry 3) | 68 | 1 | 2 | pl_skin | all 18 resolved |
| helena | Asia | uPl01HelenaAsia.arc | 1885603 | `4eb94f983e504659…` | `pl0110` (entry 1) | 63 | 1 | 105 | pl_base1, pl_skin3, pl_base2, pl_skin2, pl_cloth, pl_base, pl_skin | all 18 resolved |
| helena | Debola | uPl01HelenaDebola.arc | 8815325 | `68f840ec004a12fc…` | `pl0120` (entry 41) | 63 | 1 | 102 | pl_nuki, pl_base1, pl_base3, pl_cloth3, pl_cloth, pl_skin, pl_eyeshadow, pl_cloth1, pl_skin1, pl_skin3, pl_hair_nuki7, pl_hair_nuki1, pl_hair_nuki5, pl_hair_nuki, pl_skin4, XfB_N__E0__m00_ | all 18 resolved |
| helena | DebugId | uPl01HelenaDebugId.arc | 6814649 | `8f1765ee264cc4c3…` | `pl9920` (entry 18) | 36 | 1 | 56 | pl_base5, pl_base7, pl_base4, pl_base6, pl_base8, pl_base3 | all 18 resolved |
| helena | Omake00 | uPl01HelenaOmake00.arc | 4123883 | `0e5c33e6cbad5c60…` | `pl0190` (entry 24) | 51 | 1 | 146 | pl_skin, pl_base, pl_base3, pl_base1, pl_cloth, pl_skin5, pl_skin1 | all 18 resolved |
| helena | Omake01 | uPl01HelenaOmake01.arc | 4123057 | `a61fe434608e7351…` | `pl0170` (entry 24) | 51 | 1 | 146 | pl_skin, pl_base, pl_base1, pl_base3, pl_cloth, pl_skin5, pl_skin1 | all 18 resolved |
| helena | Omake02 | uPl01HelenaOmake02.arc | 1403138 | `c2f43848683a6201…` | `pl0180` (entry 3) | 40 | 1 | 4 | pl_skin | all 18 resolved |
| helena | Usa | uPl01HelenaUsa.arc | 1663471 | `f04534e415aaa7a9…` | `pl0100` (entry 1) | 51 | 1 | 70 | pl_nuki, pl_base1, pl_base3, pl_cloth3, pl_cloth, pl_skin, pl_eyeshadow, pl_cloth1, pl_skin1 | all 18 resolved |
| jake | Asia | uPl04JakeAsia.arc | 1987601 | `a049f6c361865836…` | `pl0420` (entry 1) | 36 | 1 | 195 | pl_skin1, pl_skin3, pl_skin2, pl_base1, pl_base2, pl_cloth, pl_base, pl_skin | all 18 resolved |
| jake | DebugId | uPl04JakeDebugId.arc | 6814649 | `8f1765ee264cc4c3…` | `pl9920` (entry 18) | 36 | 1 | 56 | pl_base5, pl_base7, pl_base4, pl_base6, pl_base8, pl_base3 | all 18 resolved |
| jake | Europe | uPl04JakeEurope.arc | 1956124 | `7838d6e2646e7686…` | `pl0400` (entry 1) | 63 | 1 | 147 | pl_base, pl_cloth1, pl_cloth, pl_cloth2, pl_base1, pl_skin, pl_cloth3, pl_skin4, Scene_Material1 | all 18 resolved |
| jake | Monitor | uPl04JakeMonitor.arc | 6593409 | `8768ebfa7ff77de6…` | `pl0410` (entry 10) | 36 | 1 | 64 | pl_skin, pl_cloth | all 18 resolved |
| jake | Omake00 | uPl04JakeOmake00.arc | 5350483 | `5bf5d9eb3ec9e5d1…` | `pl0490` (entry 31) | 76 | 1 | 132 | pl_base10, pl_base, pl_skin2, pl_skin4, pl_base13, pl_cloth1, pl_cloth, pl_cloth2, pl_base14, pl_skin, pl_base11, pl_base4 | all 18 resolved |
| jake | Omake01 | uPl04JakeOmake01.arc | 5605831 | `f1743cca85c9b4d0…` | `pl0470` (entry 31) | 76 | 1 | 132 | pl_base10, pl_base, pl_skin2, pl_skin4, pl_base13, pl_cloth1, pl_cloth, pl_cloth2, pl_base14, pl_skin, pl_base11, pl_base4 | all 18 resolved |
| jake | Omake02 | uPl04JakeOmake02.arc | 1495285 | `8a7b6cf259ca5054…` | `pl0480` (entry 3) | 36 | 1 | 6 | pl_skin | all 18 resolved |
| jake | Snow | uPl04JakeSnow.arc | 6255507 | `18b1e76b4cda4fd3…` | `pl0430` (entry 27) | 63 | 1 | 145 | pl_snow2, pl_snow1, pl_snow, pl_base1, pl_skin, pl_snow3, pl_cloth3, pl_skin1, Scene_Material1 | all 18 resolved |
| leon | Asia | uPl00LeonAsia.arc | 1729162 | `c5af508bf62f2371…` | `pl0010` (entry 1) | 45 | 1 | 97 | pl_skin1, pl_skin2, pl_base1, pl_base2, pl_cloth1, pl_skin, pl_skin3 | all 18 resolved |
| leon | DebugId | uPl00LeonDebugId.arc | 6814649 | `8f1765ee264cc4c3…` | `pl9920` (entry 18) | 36 | 1 | 56 | pl_base5, pl_base7, pl_base4, pl_base6, pl_base8, pl_base3 | all 18 resolved |
| leon | Omake00 | uPl00LeonOmake00.arc | 4445283 | `791ff5a05880e95d…` | `pl0090` (entry 32) | 56 | 1 | 172 | pl_cloth2, pl_base, pl_nuki, pl_base6, pl_base2, pl_base5, pl_base7, pl_nuki1, pl_nuki3, pl_base3, pl_base8, pl_nuki2, pl_cloth, pl_cloth3, pl_skin1 | all 18 resolved |
| leon | Omake01 | uPl00LeonOmake01.arc | 4922505 | `79a9845220b656f9…` | `pl0070` (entry 33) | 56 | 1 | 172 | pl_cloth2, pl_base, pl_nuki, pl_base6, pl_base2, pl_base5, pl_base7, pl_nuki1, pl_nuki3, pl_base3, pl_base8, pl_nuki2, pl_cloth, pl_cloth3, pl_skin1 | all 18 resolved |
| leon | Omake02 | uPl00LeonOmake02.arc | 1292480 | `61c4fe7672171972…` | `pl0080` (entry 3) | 36 | 1 | 2 | pl_skin | all 18 resolved |
| leon | Usa | uPl00LeonUsa.arc | 1626591 | `05617de7e3999c52…` | `pl0000` (entry 1) | 54 | 1 | 103 | pl_cloth, pl_base2, pl_cloth1, pl_base1, pl_skin | all 18 resolved |
| piers | Asia | uPl03PiersAsia.arc | 4866047 | `87acd1e127da4cad…` | `pl0300` (entry 32) | 42 | 1 | 127 | pl_skin4, pl_nuki, pl_base2, pl_base4, pl_skin7, pl_base, pl_skin3, pl_cloth1, pl_skin, pl_base1, pl_skin5, pl_cloth | all 18 resolved |
| piers | Canon | uPl03PiersCanon.arc | 6995444 | `fd51e51a6a2fc7ec…` | `pl0330` (entry 49) | 89 | 5 | 176 | XfB_N__E0__m00_pl_skin5, XfB_N__E0__m00_pl_cloth1, XfB_N__E0__m00_pl_skin3, XfB_N__E0__m00_pl_cloth, XfB_N__E0__m00_pl_base, XfB_N__E0__m00_pl_base1, XfB_N__E0__m00_pl_base4, XfB_N__E0__m00_pl_skin, XfB_N__E0__m00_pl_base2, XfB_N__E0__m00_pl_hair_nb, XfB_N__E0__m00_pl_skin7, XfB_N__E0__m00_pl_skin4, XfB_N__E0__m00_4, XfB_N__E0__m00_2, XfB_N__E0__m00_3, XfB_N__E0__m00_, XfB_N__E0__m00_1, XfBAN__E1__m00_, shadow | all 18 resolved |
| piers | DebugId | uPl03PiersDebugId.arc | 6814649 | `8f1765ee264cc4c3…` | `pl9920` (entry 18) | 36 | 1 | 56 | pl_base5, pl_base7, pl_base4, pl_base6, pl_base8, pl_base3 | all 18 resolved |
| piers | Europe | uPl03PiersEurope.arc | 4708859 | `0423503b84c56eff…` | `pl0310` (entry 30) | 42 | 1 | 105 | pl_skin4, pl_base2, pl_base4, pl_skin7, pl_base, pl_cloth1, pl_skin, pl_cloth, pl_base1, pl_skin5 | all 18 resolved |
| piers | Omake00 | uPl03PiersOmake00.arc | 5093519 | `f83fbf54d3f3dc90…` | `pl0390` (entry 19) | 42 | 1 | 83 | pl_base7, pl_nuki, pl_skin, pl_skin1, pl_skin2, pl_base8 | all 18 resolved |
| piers | Omake01 | uPl03PiersOmake01.arc | 4978300 | `1d7e25e3766641be…` | `pl0370` (entry 19) | 42 | 1 | 83 | pl_base7, pl_nuki, pl_skin, pl_skin1, pl_skin2, pl_base8 | all 18 resolved |
| piers | Omake02 | uPl03PiersOmake02.arc | 1357209 | `6c126b8071568b8f…` | `pl0380` (entry 3) | 36 | 1 | 2 | pl_skin | all 18 resolved |
| piers | Personal | uPl03PiersPersonal.arc | 4255741 | `2295a5495894ec79…` | `pl0320` (entry 19) | 55 | 1 | 10 | pl_cloth, pl_skin, pl_base, pl_skin1, pl_nuki | all 18 resolved |
| sherry | Asia | uPl05SherryAsia.arc | 1708067 | `7f9c3d955bcd8e07…` | `pl0520` (entry 1) | 50 | 1 | 82 | pl_base1, pl_skin2, pl_skin1, pl_cloth1, pl_nuki, pl_skin, pl_cloth | all 18 resolved |
| sherry | DebugId | uPl05SherryDebugId.arc | 6814649 | `8f1765ee264cc4c3…` | `pl9920` (entry 18) | 36 | 1 | 56 | pl_base5, pl_base7, pl_base4, pl_base6, pl_base8, pl_base3 | all 18 resolved |
| sherry | Europe | uPl05SherryEurope.arc | 1794372 | `2d5ae082e6cceb33…` | `pl0500` (entry 2) | 52 | 1 | 126 | pl_base3, XfBA1_, pl_cloth, pl_cloth1, pl_base, pl_base4, pl_skin1, pl_skin, pl_skin2 | all 18 resolved |
| sherry | Monitor | uPl05SherryMonitor.arc | 3324304 | `f8b208ed1df8ddd7…` | `pl0510` (entry 10) | 56 | 1 | 42 | pl_skin, pl_cloth | all 18 resolved |
| sherry | Omake00 | uPl05SherryOmake00.arc | 4510040 | `ae9cd6c50c7cbefb…` | `pl0590` (entry 30) | 48 | 1 | 134 | pl_nuki, pl_skin, pl_base2, pl_base4, pl_nuki1, pl_base5, pl_cloth1, pl_skin1, pl_base, pl_base6, pl_base7, pl_cloth | all 18 resolved |
| sherry | Omake01 | uPl05SherryOmake01.arc | 4653127 | `16d209cad8a025eb…` | `pl0570` (entry 29) | 48 | 1 | 134 | pl_nuki, pl_skin, pl_base2, pl_base4, pl_nuki1, pl_base5, pl_cloth1, pl_skin1, pl_base, pl_base6, pl_base7, pl_cloth | all 18 resolved |
| sherry | Omake02 | uPl05SherryOmake02.arc | 1383749 | `f7c78033245b6a08…` | `pl0580` (entry 3) | 40 | 1 | 13 | pl_skin | all 18 resolved |
| sherry | Snow | uPl05SherrySnow.arc | 5377425 | `0e0b82a994781623…` | `pl0540` (entry 29) | 52 | 1 | 126 | pl_base3, pl_hair_nuki, pl_snow, pl_cloth1, pl_base, pl_snow2, pl_base4, pl_skin, pl_snow1 | all 18 resolved |

Bone counts: 36..89 (Leon USA 54 is the baseline measured body; Piers' cannon-arm costumes run to 89 with 5 roots).

**Source:** native `arc/NX/uPlXX<Name><Costume>.arc` files, one row per slot above, parsed with `gbox.re6_switch_models.slot_report` (bone count from the MTF MOD header) and `roles_for` (anim-id table of the same header).

## 2. The 7 texture archives (`uPlTex00<XX>_<n>.arc`)

### uPlTex0000_0.arc (4998697 B, sha256 `8f78345b6c0303ab…`)
36 entries (32 TEX, 4 non-TEX: `pl0000_0`, `pl0001_0`, `pl0002_0`, `pl0003_0`). MRL `pl0003_0` v36: 10 materials, 17 textures.

| entry | format | dimensions | mips | tags |
|---|---|---|---:|---|
| `pl0000_00shats_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl0000_00shats_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_00shats_MM` | 0x19  | 256×256 | 9 | MM |
| `pl_VTF` | 0x0e 32-bit float ramp | 128×4 | 1 | VTF |
| `pl0000_50_jacket_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0000_00jacket_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_00jacket_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl_Blood_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_00jacket_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_51_shats_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0000_00Detail_DM` | 0x1f  | 32×32 | 6 | — |
| `pl0000_00pants_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_00pants_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_00pants_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0000_10Hand_NM` | 0x1f  | 256×128 | 9 | NM |
| `pl0000_10Hand_BM` | 0x2b BC3 Y'CbCr albedo | 512×256 | 10 | BM |
| `pl0000_10Hand_MM` | 0x19  | 256×128 | 9 | MM |
| `pl0000_00_earLight` | 0x09 RGBA8 | 64×64 | 7 | — |
| `pl0000_00tear_BM` | 0x2b BC3 Y'CbCr albedo | 8×8 | 4 | BM |
| `pl0000_00tear_MM` | 0x19  | 8×8 | 4 | MM |
| `pl0000_00eyelash_BM` | 0x2b BC3 Y'CbCr albedo | 128×64 | 8 | BM |
| `pl0000_00head_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_00head_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00head_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00eyeCov_NM` | 0x1f  | 64×64 | 7 | NM |
| `pl0000_00eye_BM` | 0x2b BC3 Y'CbCr albedo | 128×128 | 8 | BM |
| `pl0000_00eyeCov_MM` | 0x19  | 64×64 | 7 | MM |
| `pl0000_00eyeCov_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0000_50_hair_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl000_00hair_sft2_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00hair_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00hair_MM` | 0x19  | 512×512 | 10 | MM |

### uPlTex0000_1.arc (5238176 B, sha256 `bea823d56bd8e38b…`)
36 entries (32 TEX, 4 non-TEX: `pl0000_1`, `pl0001_1`, `pl0002_1`, `pl0003_1`). MRL `pl0003_1` v36: 10 materials, 17 textures.

| entry | format | dimensions | mips | tags |
|---|---|---|---:|---|
| `pl0000_00shats_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl0000_72shats_d1_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_00shats_MM` | 0x19  | 256×256 | 9 | MM |
| `pl_VTF` | 0x0e 32-bit float ramp | 128×4 | 1 | VTF |
| `pl0000_50_jacket_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0000_00jacket_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_70jacket_d1_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl_Blood_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_70jacket_d1_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_51_shats_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0000_00Detail_DM` | 0x1f  | 32×32 | 6 | — |
| `pl0000_00pants_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_71pants_d1_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_00pants_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0000_10Hand_NM` | 0x1f  | 256×128 | 9 | NM |
| `pl0000_10Hand_BM` | 0x2b BC3 Y'CbCr albedo | 512×256 | 10 | BM |
| `pl0000_10Hand_MM` | 0x19  | 256×128 | 9 | MM |
| `pl0000_00_earLight` | 0x09 RGBA8 | 64×64 | 7 | — |
| `pl0000_00tear_BM` | 0x2b BC3 Y'CbCr albedo | 8×8 | 4 | BM |
| `pl0000_00tear_MM` | 0x19  | 8×8 | 4 | MM |
| `pl0000_00eyelash_BM` | 0x2b BC3 Y'CbCr albedo | 128×64 | 8 | BM |
| `pl0000_00head_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_00head_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00head_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00eyeCov_NM` | 0x1f  | 64×64 | 7 | NM |
| `pl0000_00eye_BM` | 0x2b BC3 Y'CbCr albedo | 128×128 | 8 | BM |
| `pl0000_00eyeCov_MM` | 0x19  | 64×64 | 7 | MM |
| `pl0000_00eyeCov_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0000_50_hair_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl000_00hair_sft2_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00hair_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00hair_MM` | 0x19  | 512×512 | 10 | MM |

### uPlTex0000_2.arc (5238110 B, sha256 `e203734e36671d76…`)
36 entries (32 TEX, 4 non-TEX: `pl0000_2`, `pl0001_2`, `pl0002_2`, `pl0003_2`). MRL `pl0003_2` v36: 10 materials, 17 textures.

| entry | format | dimensions | mips | tags |
|---|---|---|---:|---|
| `pl0000_00shats_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl0000_72shats_d1_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_00shats_MM` | 0x19  | 256×256 | 9 | MM |
| `pl_VTF` | 0x0e 32-bit float ramp | 128×4 | 1 | VTF |
| `pl0000_50_jacket_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0000_00jacket_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_70jacket_d1_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl_Blood_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_70jacket_d1_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_51_shats_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0000_00Detail_DM` | 0x1f  | 32×32 | 6 | — |
| `pl0000_00pants_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_71pants_d1_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0000_00pants_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0000_10Hand_NM` | 0x1f  | 256×128 | 9 | NM |
| `pl0000_10Hand_BM` | 0x2b BC3 Y'CbCr albedo | 512×256 | 10 | BM |
| `pl0000_10Hand_MM` | 0x19  | 256×128 | 9 | MM |
| `pl0000_00_earLight` | 0x09 RGBA8 | 64×64 | 7 | — |
| `pl0000_00tear_BM` | 0x2b BC3 Y'CbCr albedo | 8×8 | 4 | BM |
| `pl0000_00tear_MM` | 0x19  | 8×8 | 4 | MM |
| `pl0000_00eyelash_BM` | 0x2b BC3 Y'CbCr albedo | 128×64 | 8 | BM |
| `pl0000_00head_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0000_00head_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00head_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00eyeCov_NM` | 0x1f  | 64×64 | 7 | NM |
| `pl0000_00eye_BM` | 0x2b BC3 Y'CbCr albedo | 128×128 | 8 | BM |
| `pl0000_00eyeCov_MM` | 0x19  | 64×64 | 7 | MM |
| `pl0000_00eyeCov_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0000_50_hair_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl000_00hair_sft2_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00hair_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00hair_MM` | 0x19  | 512×512 | 10 | MM |

### uPlTex0010_0.arc (5456024 B, sha256 `206aa9113c22ae67…`)
48 entries (44 TEX, 4 non-TEX: `pl0010_0`, `pl0011_0`, `pl0012_0`, `pl0013_0`). MRL `pl0013_0` v36: 10 materials, 17 textures.

| entry | format | dimensions | mips | tags |
|---|---|---|---:|---|
| `pl0010_25_shoes_NM` | 0x1f  | 128×128 | 8 | NM |
| `pl0010_25_shoes_BM` | 0x2b BC3 Y'CbCr albedo | 256×256 | 9 | BM |
| `pl0010_25_shoes_MM` | 0x19  | 128×128 | 8 | MM |
| `pl0010_24_hand_NM` | 0x1f  | 256×128 | 9 | NM |
| `pl0010_24_hand_BM` | 0x2b BC3 Y'CbCr albedo | 512×256 | 10 | BM |
| `pl_Blood_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_24_hand_MM` | 0x19  | 256×128 | 9 | MM |
| `pl0010_20_vest_NM` | 0x1f  | 512×256 | 10 | NM |
| `leon_vest_DM` | 0x1f  | 32×32 | 6 | — |
| `pl0010_20_vest_BM` | 0x2b BC3 Y'CbCr albedo | 1024×512 | 11 | BM |
| `pl0010_30_shirtsFS_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0010_20_vest_MM` | 0x19  | 512×256 | 10 | MM |
| `pl0010_22_leather_NM` | 0x1f  | 512×256 | 10 | NM |
| `pl0010_22_leather_BM` | 0x2b BC3 Y'CbCr albedo | 1024×512 | 11 | BM |
| `pl0300_21FS2_BM` | 0x2b BC3 Y'CbCr albedo | 32×32 | 6 | BM |
| `pl0010_22_leather_MM` | 0x19  | 256×128 | 9 | MM |
| `pl_VTF` | 0x0e 32-bit float ramp | 128×4 | 1 | VTF |
| `pl0010_50_shairts_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0010_21_shirts_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl_cloth0_DM` | 0x1f  | 128×128 | 8 | — |
| `pl0010_21_shirts_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_21_shirts_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0010_23_bottom_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl0010_23_bottom_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_23_bottom_MM` | 0x19  | 128×128 | 8 | MM |
| `pl0010_16_holster_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0010_16_holster_BM` | 0x2b BC3 Y'CbCr albedo | 256×256 | 9 | BM |
| `pl0010_16_holster_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0010_31_cloth_DM` | 0x1f  | 128×128 | 8 | — |
| `pl0000_00_earLight` | 0x09 RGBA8 | 64×64 | 7 | — |
| `pl0000_00tear_BM` | 0x2b BC3 Y'CbCr albedo | 8×8 | 4 | BM |
| `pl0000_00tear_MM` | 0x19  | 8×8 | 4 | MM |
| `pl0000_00eyelash_BM` | 0x2b BC3 Y'CbCr albedo | 128×64 | 8 | BM |
| `pl0000_00head_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0010_00head_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00head_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00eyeCov_NM` | 0x1f  | 64×64 | 7 | NM |
| `pl0000_00eye_BM` | 0x2b BC3 Y'CbCr albedo | 128×128 | 8 | BM |
| `pl0000_00eyeCov_MM` | 0x19  | 64×64 | 7 | MM |
| `pl0000_00eyeCov_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0000_50_hair_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl000_00hair_sft2_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00hair_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00hair_MM` | 0x19  | 512×512 | 10 | MM |

### uPlTex0010_1.arc (5471879 B, sha256 `52af0ceecc5a1d2a…`)
48 entries (44 TEX, 4 non-TEX: `pl0010_1`, `pl0011_1`, `pl0012_1`, `pl0013_1`). MRL `pl0013_1` v36: 10 materials, 17 textures.

| entry | format | dimensions | mips | tags |
|---|---|---|---:|---|
| `pl0010_25_shoes_NM` | 0x1f  | 128×128 | 8 | NM |
| `pl0010_25_shoes_BM` | 0x2b BC3 Y'CbCr albedo | 256×256 | 9 | BM |
| `pl0010_25_shoes_MM` | 0x19  | 128×128 | 8 | MM |
| `pl0010_24_hand_NM` | 0x1f  | 256×128 | 9 | NM |
| `pl0010_24_hand_BM` | 0x2b BC3 Y'CbCr albedo | 512×256 | 10 | BM |
| `pl_Blood_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_24_hand_MM` | 0x19  | 256×128 | 9 | MM |
| `pl0010_20_vest_NM` | 0x1f  | 512×256 | 10 | NM |
| `leon_vest_DM` | 0x1f  | 32×32 | 6 | — |
| `pl0010_70_vest_d1_BM` | 0x2b BC3 Y'CbCr albedo | 1024×512 | 11 | BM |
| `pl0010_30_shirtsFS_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0010_20_vest_MM` | 0x19  | 512×256 | 10 | MM |
| `pl0010_22_leather_NM` | 0x1f  | 512×256 | 10 | NM |
| `pl0010_22_leather_BM` | 0x2b BC3 Y'CbCr albedo | 1024×512 | 11 | BM |
| `pl0300_21FS2_BM` | 0x2b BC3 Y'CbCr albedo | 32×32 | 6 | BM |
| `pl0010_22_leather_MM` | 0x19  | 256×128 | 9 | MM |
| `pl_VTF` | 0x0e 32-bit float ramp | 128×4 | 1 | VTF |
| `pl0010_50_shairts_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0010_21_shirts_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl_cloth0_DM` | 0x1f  | 128×128 | 8 | — |
| `pl0010_71_shirts_d1_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_21_shirts_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0010_23_bottom_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl0010_23_bottom_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_23_bottom_MM` | 0x19  | 128×128 | 8 | MM |
| `pl0010_16_holster_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0010_16_holster_BM` | 0x2b BC3 Y'CbCr albedo | 256×256 | 9 | BM |
| `pl0010_16_holster_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0010_31_cloth_DM` | 0x1f  | 128×128 | 8 | — |
| `pl0000_00_earLight` | 0x09 RGBA8 | 64×64 | 7 | — |
| `pl0000_00tear_BM` | 0x2b BC3 Y'CbCr albedo | 8×8 | 4 | BM |
| `pl0000_00tear_MM` | 0x19  | 8×8 | 4 | MM |
| `pl0000_00eyelash_BM` | 0x2b BC3 Y'CbCr albedo | 128×64 | 8 | BM |
| `pl0000_00head_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0010_60head_d1_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00head_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00eyeCov_NM` | 0x1f  | 64×64 | 7 | NM |
| `pl0000_00eye_BM` | 0x2b BC3 Y'CbCr albedo | 128×128 | 8 | BM |
| `pl0000_00eyeCov_MM` | 0x19  | 64×64 | 7 | MM |
| `pl0000_00eyeCov_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0000_50_hair_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl000_00hair_sft2_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00hair_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00hair_MM` | 0x19  | 512×512 | 10 | MM |

### uPlTex0010_2.arc (5465379 B, sha256 `bb0805f59bfe3613…`)
48 entries (44 TEX, 4 non-TEX: `pl0010_2`, `pl0011_2`, `pl0012_2`, `pl0013_2`). MRL `pl0013_2` v36: 10 materials, 17 textures.

| entry | format | dimensions | mips | tags |
|---|---|---|---:|---|
| `pl0010_25_shoes_NM` | 0x1f  | 128×128 | 8 | NM |
| `pl0010_25_shoes_BM` | 0x2b BC3 Y'CbCr albedo | 256×256 | 9 | BM |
| `pl0010_25_shoes_MM` | 0x19  | 128×128 | 8 | MM |
| `pl0010_24_hand_NM` | 0x1f  | 256×128 | 9 | NM |
| `pl0010_24_hand_BM` | 0x2b BC3 Y'CbCr albedo | 512×256 | 10 | BM |
| `pl_Blood_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_24_hand_MM` | 0x19  | 256×128 | 9 | MM |
| `pl0010_20_vest_NM` | 0x1f  | 512×256 | 10 | NM |
| `leon_vest_DM` | 0x1f  | 32×32 | 6 | — |
| `pl0010_70_vest_d1_BM` | 0x2b BC3 Y'CbCr albedo | 1024×512 | 11 | BM |
| `pl0010_30_shirtsFS_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0010_20_vest_MM` | 0x19  | 512×256 | 10 | MM |
| `pl0010_22_leather_NM` | 0x1f  | 512×256 | 10 | NM |
| `pl0010_22_leather_BM` | 0x2b BC3 Y'CbCr albedo | 1024×512 | 11 | BM |
| `pl0300_21FS2_BM` | 0x2b BC3 Y'CbCr albedo | 32×32 | 6 | BM |
| `pl0010_22_leather_MM` | 0x19  | 256×128 | 9 | MM |
| `pl_VTF` | 0x0e 32-bit float ramp | 128×4 | 1 | VTF |
| `pl0010_50_shairts_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0010_21_shirts_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl_cloth0_DM` | 0x1f  | 128×128 | 8 | — |
| `pl0010_71_shirts_d1_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_21_shirts_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0010_23_bottom_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl0010_23_bottom_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_23_bottom_MM` | 0x19  | 128×128 | 8 | MM |
| `pl0010_16_holster_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0010_16_holster_BM` | 0x2b BC3 Y'CbCr albedo | 256×256 | 9 | BM |
| `pl0010_16_holster_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0010_31_cloth_DM` | 0x1f  | 128×128 | 8 | — |
| `pl0000_00_earLight` | 0x09 RGBA8 | 64×64 | 7 | — |
| `pl0000_00tear_BM` | 0x2b BC3 Y'CbCr albedo | 8×8 | 4 | BM |
| `pl0000_00tear_MM` | 0x19  | 8×8 | 4 | MM |
| `pl0000_00eyelash_BM` | 0x2b BC3 Y'CbCr albedo | 128×64 | 8 | BM |
| `pl0000_00head_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0010_60head_d1_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0010_61head_d2_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00eyeCov_NM` | 0x1f  | 64×64 | 7 | NM |
| `pl0000_00eye_BM` | 0x2b BC3 Y'CbCr albedo | 128×128 | 8 | BM |
| `pl0000_00eyeCov_MM` | 0x19  | 64×64 | 7 | MM |
| `pl0000_00eyeCov_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0000_50_hair_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl000_00hair_sft2_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00hair_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00hair_MM` | 0x19  | 512×512 | 10 | MM |

### uPlTex0010_3.arc (5488713 B, sha256 `caf9113bc7a25a04…`)
48 entries (44 TEX, 4 non-TEX: `pl0010_3`, `pl0011_3`, `pl0012_3`, `pl0013_3`). MRL `pl0013_3` v36: 10 materials, 17 textures.

| entry | format | dimensions | mips | tags |
|---|---|---|---:|---|
| `pl0010_25_shoes_NM` | 0x1f  | 128×128 | 8 | NM |
| `pl0010_25_shoes_BM` | 0x2b BC3 Y'CbCr albedo | 256×256 | 9 | BM |
| `pl0010_25_shoes_MM` | 0x19  | 128×128 | 8 | MM |
| `pl0010_24_hand_NM` | 0x1f  | 256×128 | 9 | NM |
| `pl0010_75_hand_d1_BM` | 0x2b BC3 Y'CbCr albedo | 512×256 | 10 | BM |
| `pl_Blood_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_24_hand_MM` | 0x19  | 256×128 | 9 | MM |
| `pl0010_20_vest_NM` | 0x1f  | 512×256 | 10 | NM |
| `leon_vest_DM` | 0x1f  | 32×32 | 6 | — |
| `pl0010_72_vest_d2_BM` | 0x2b BC3 Y'CbCr albedo | 1024×512 | 11 | BM |
| `pl0010_30_shirtsFS_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0010_72_vest_d2_MM` | 0x19  | 512×256 | 10 | MM |
| `pl0010_22_leather_NM` | 0x1f  | 512×256 | 10 | NM |
| `pl0010_22_leather_BM` | 0x2b BC3 Y'CbCr albedo | 1024×512 | 11 | BM |
| `pl0300_21FS2_BM` | 0x2b BC3 Y'CbCr albedo | 32×32 | 6 | BM |
| `pl0010_22_leather_MM` | 0x19  | 256×128 | 9 | MM |
| `pl_VTF` | 0x0e 32-bit float ramp | 128×4 | 1 | VTF |
| `pl0010_50_shairts_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl0010_21_shirts_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl_cloth0_DM` | 0x1f  | 128×128 | 8 | — |
| `pl0010_73_shirts_d2_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_21_shirts_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0010_23_bottom_NM` | 0x1f  | 256×256 | 9 | NM |
| `pl0010_74_bottom_d1_BM` | 0x2b BC3 Y'CbCr albedo | 512×512 | 10 | BM |
| `pl0010_23_bottom_MM` | 0x19  | 128×128 | 8 | MM |
| `pl0010_16_holster_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0010_16_holster_BM` | 0x2b BC3 Y'CbCr albedo | 256×256 | 9 | BM |
| `pl0010_16_holster_MM` | 0x19  | 256×256 | 9 | MM |
| `pl0010_31_cloth_DM` | 0x1f  | 128×128 | 8 | — |
| `pl0000_00_earLight` | 0x09 RGBA8 | 64×64 | 7 | — |
| `pl0000_00tear_BM` | 0x2b BC3 Y'CbCr albedo | 8×8 | 4 | BM |
| `pl0000_00tear_MM` | 0x19  | 8×8 | 4 | MM |
| `pl0000_00eyelash_BM` | 0x2b BC3 Y'CbCr albedo | 128×64 | 8 | BM |
| `pl0000_00head_NM` | 0x1f  | 512×512 | 10 | NM |
| `pl0010_62head_d3_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0010_62head_d3_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00eyeCov_NM` | 0x1f  | 64×64 | 7 | NM |
| `pl0000_00eye_BM` | 0x2b BC3 Y'CbCr albedo | 128×128 | 8 | BM |
| `pl0000_00eyeCov_MM` | 0x19  | 64×64 | 7 | MM |
| `pl0000_00eyeCov_BM` | 0x2b BC3 Y'CbCr albedo | 64×64 | 7 | BM |
| `pl0000_50_hair_MVTF` | 0x09 RGBA8 | 128×128 | 8 | MVTF |
| `pl000_00hair_sft2_MM` | 0x19  | 512×512 | 10 | MM |
| `pl0000_00hair_BM` | 0x2b BC3 Y'CbCr albedo | 1024×1024 | 11 | BM |
| `pl0000_00hair_MM` | 0x19  | 512×512 | 10 | MM |

**Source:** the native `uPlTex00<XX>_<n>.arc` archives; each row from `gbox.re6_switch_tex.describe_arc` (TEX header: format, dimensions, mip count), tags from the entry names; the closing MRL from `texture_set_mrl`. Format 0x2B is the BC3 Y'CbCr albedo, 0x09 an RGBA8 mask (`_MVTF`), 0x0E the 32-bit float curve (`_VTF`), per handover §0.1/§2.3.

## 3. Material → texture bindings for five default costumes

For the default costume of Leon, Helena, Chris, Piers and Jake: `gbox.re6_switch_models.texture_set_arcs` finds the archives carrying the costume's texture set (the campaign costumes keep it in separate `uPlTex` archives; the others carry it in the body arc), and `gbox.re6_switch_tex.texture_set_materials` decodes each material's bound textures from the texture-set MRL.

### Leon - default costume `uPl00LeonUsa.arc` (textures in `uPlTex0000_0.arc`, `uPlTex0000_1.arc`, `uPlTex0000_2.arc`)

| MRL | material | bound texture paths |
|---|---|---|
| pl0000_0 | pl_base2 | `pl0000_00shats_NM`<br>`pl0000_00shats_BM`<br>`pl0000_00shats_MM` |
| pl0000_0 | pl_cloth | `pl_VTF`<br>`pl0000_50_jacket_MVTF`<br>`pl0000_00jacket_NM`<br>`pl0000_00jacket_BM`<br>`pl_Blood_BM`<br>`pl0000_00jacket_MM` |
| pl0000_0 | pl_cloth1 | `pl_VTF`<br>`pl0000_51_shats_MVTF`<br>`pl0000_00shats_NM`<br>`pl0000_00Detail_DM`<br>`pl0000_00shats_BM`<br>`pl_Blood_BM`<br>`pl0000_00shats_MM` |
| pl0000_0 | pl_base1 | `pl0000_00pants_NM`<br>`pl0000_00Detail_DM`<br>`pl0000_00pants_BM`<br>`pl0000_00pants_MM` |
| pl0000_0 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl_Blood_BM`<br>`pl0000_10Hand_MM` |
| pl0001_0 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl0000_10Hand_MM` |
| pl0002_0 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl0000_10Hand_MM` |
| pl0003_0 | (name not in title table) | `pl0000_00_earLight` |
| pl0003_0 | (name not in title table) | `pl0000_00tear_BM`<br>`pl0000_00tear_MM` |
| pl0003_0 | (name not in title table) | `pl0000_00eyelash_BM` |
| pl0003_0 | (name not in title table) | `pl0000_00eyelash_BM` |
| pl0003_0 | pl_skin | `pl0000_00head_NM`<br>`pl0000_00head_BM`<br>`pl_Blood_BM`<br>`pl0000_00head_MM` |
| pl0003_0 | pl_base1 | `pl0000_00eyeCov_NM`<br>`pl0000_00eye_BM`<br>`pl0000_00eyeCov_MM` |
| pl0003_0 | (name not in title table) | `pl0000_00eyeCov_NM`<br>`pl0000_00eyeCov_BM`<br>`pl0000_00eyeCov_MM` |
| pl0003_0 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl000_00hair_sft2_MM`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |
| pl0003_0 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |
| pl0003_0 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl000_00hair_sft2_MM`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |
| pl0000_1 | pl_base2 | `pl0000_00shats_NM`<br>`pl0000_72shats_d1_BM`<br>`pl0000_00shats_MM` |
| pl0000_1 | pl_cloth | `pl_VTF`<br>`pl0000_50_jacket_MVTF`<br>`pl0000_00jacket_NM`<br>`pl0000_70jacket_d1_BM`<br>`pl_Blood_BM`<br>`pl0000_70jacket_d1_MM` |
| pl0000_1 | pl_cloth1 | `pl_VTF`<br>`pl0000_51_shats_MVTF`<br>`pl0000_00shats_NM`<br>`pl0000_00Detail_DM`<br>`pl0000_72shats_d1_BM`<br>`pl_Blood_BM`<br>`pl0000_00shats_MM` |
| pl0000_1 | pl_base1 | `pl0000_00pants_NM`<br>`pl0000_00Detail_DM`<br>`pl0000_71pants_d1_BM`<br>`pl0000_00pants_MM` |
| pl0000_1 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl_Blood_BM`<br>`pl0000_10Hand_MM` |
| pl0001_1 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl_Blood_BM`<br>`pl0000_10Hand_MM` |
| pl0002_1 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl_Blood_BM`<br>`pl0000_10Hand_MM` |
| pl0003_1 | (name not in title table) | `pl0000_00_earLight` |
| pl0003_1 | (name not in title table) | `pl0000_00tear_BM`<br>`pl0000_00tear_MM` |
| pl0003_1 | (name not in title table) | `pl0000_00eyelash_BM` |
| pl0003_1 | (name not in title table) | `pl0000_00eyelash_BM` |
| pl0003_1 | pl_skin | `pl0000_00head_NM`<br>`pl0000_00head_BM`<br>`pl_Blood_BM`<br>`pl0000_00head_MM` |
| pl0003_1 | pl_base1 | `pl0000_00eyeCov_NM`<br>`pl0000_00eye_BM`<br>`pl0000_00eyeCov_MM` |
| pl0003_1 | (name not in title table) | `pl0000_00eyeCov_NM`<br>`pl0000_00eyeCov_BM`<br>`pl0000_00eyeCov_MM` |
| pl0003_1 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl000_00hair_sft2_MM`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |
| pl0003_1 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |
| pl0003_1 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl000_00hair_sft2_MM`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |
| pl0000_2 | pl_base2 | `pl0000_00shats_NM`<br>`pl0000_72shats_d1_BM`<br>`pl0000_00shats_MM` |
| pl0000_2 | pl_cloth | `pl_VTF`<br>`pl0000_50_jacket_MVTF`<br>`pl0000_00jacket_NM`<br>`pl0000_70jacket_d1_BM`<br>`pl_Blood_BM`<br>`pl0000_70jacket_d1_MM` |
| pl0000_2 | pl_cloth1 | `pl_VTF`<br>`pl0000_51_shats_MVTF`<br>`pl0000_00shats_NM`<br>`pl0000_00Detail_DM`<br>`pl0000_72shats_d1_BM`<br>`pl_Blood_BM`<br>`pl0000_00shats_MM` |
| pl0000_2 | pl_base1 | `pl0000_00pants_NM`<br>`pl0000_00Detail_DM`<br>`pl0000_71pants_d1_BM`<br>`pl0000_00pants_MM` |
| pl0000_2 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl_Blood_BM`<br>`pl0000_10Hand_MM` |
| pl0001_2 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl0000_10Hand_MM` |
| pl0002_2 | pl_skin | `pl0000_10Hand_NM`<br>`pl0000_10Hand_BM`<br>`pl0000_10Hand_MM` |
| pl0003_2 | (name not in title table) | `pl0000_00_earLight` |
| pl0003_2 | (name not in title table) | `pl0000_00tear_BM`<br>`pl0000_00tear_MM` |
| pl0003_2 | (name not in title table) | `pl0000_00eyelash_BM` |
| pl0003_2 | (name not in title table) | `pl0000_00eyelash_BM` |
| pl0003_2 | pl_skin | `pl0000_00head_NM`<br>`pl0000_00head_BM`<br>`pl_Blood_BM`<br>`pl0000_00head_MM` |
| pl0003_2 | pl_base1 | `pl0000_00eyeCov_NM`<br>`pl0000_00eye_BM`<br>`pl0000_00eyeCov_MM` |
| pl0003_2 | (name not in title table) | `pl0000_00eyeCov_NM`<br>`pl0000_00eyeCov_BM`<br>`pl0000_00eyeCov_MM` |
| pl0003_2 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl000_00hair_sft2_MM`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |
| pl0003_2 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |
| pl0003_2 | (name not in title table) | `pl_VTF`<br>`pl0000_50_hair_MVTF`<br>`pl000_00hair_sft2_MM`<br>`pl0000_00hair_BM`<br>`pl0000_00hair_MM` |

### Helena - default costume `uPl01HelenaUsa.arc` (textures in `uPlTex0100_0.arc`, `uPlTex0100_1.arc`, `uPlTex0100_2.arc`)

| MRL | material | bound texture paths |
|---|---|---|
| pl0100_0 | pl_base1 | `pl0100_00body_NM`<br>`pl0100_00body_BM`<br>`pl0100_00body_MM` |
| pl0100_0 | (name not in title table) | `pl0100_23_prop_NM`<br>`pl0100_23_prop_BM`<br>`pl0100_23_prop_MM` |
| pl0100_0 | pl_cloth1 | `pl_VTF`<br>`pl0100_51_vest_MVTF`<br>`pl0100_26_vest_NM`<br>`BH_cloth_05_DM`<br>`pl0100_26_vest_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_26_vest_MM` |
| pl0100_0 | pl_cloth | `pl_VTF`<br>`pl0100_50_shirt_MVTF`<br>`pl0100_21_shirt_NM`<br>`BH_cloth_05_DM`<br>`pl0100_21_shirt_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_21_shirt_MM` |
| pl0100_0 | pl_skin | `pl0100_00body_NM`<br>`pl0100_00body_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_0 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_00body_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_0 | (name not in title table) | `pl_VTF`<br>`pl0100_23_prop_NM`<br>`pl0100_25_acs_BM`<br>`pl0100_23_prop_MM` |
| pl0100_0 | (name not in title table) | `pl0100_25_acs_BM` |
| pl0100_0 | (name not in title table) | `pl_VTF`<br>`pl0100_00body_NM`<br>`BH_cloth_05_DM`<br>`pl0100_00body_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_0 | (name not in title table) | `pl_VTF`<br>`pl0100_23_prop_NM`<br>`pl0100_25_acs_BM`<br>`pl0100_23_prop_MM` |
| pl0101_0 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_00body_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0102_0 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_00body_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0103_0 | (name not in title table) | `pl_VTF`<br>`pl0100_55hair_00_MVTF`<br>`pl0100_00hair_00sft_MM`<br>`pl0100_00hair_00_BM`<br>`pl0100_00hair_00_MM` |
| pl0103_0 | (name not in title table) | `pl_VTF`<br>`pl0100_56hair_01_MVTF`<br>`pl0100_00hair_00sft_MM`<br>`pl0100_00hair_01_BM`<br>`pl0100_00hair_01_MM` |
| pl0103_0 | (name not in title table) | `pl0100_00eyelash_BM` |
| pl0103_0 | (name not in title table) | `pl0100_00eyelash_BM` |
| pl0103_0 | pl_base1 | `pl0100_00eye_NM`<br>`pl0100_00eye_BM`<br>`pl0100_00eye_MM` |
| pl0103_0 | (name not in title table) | `pl0100_00eyeCov_NM`<br>`pl0100_00eyeCov_BM`<br>`pl0100_00eyeCov_MM` |
| pl0103_0 | pl_skin | `pl0100_00face_NM`<br>`pl0100_00face_BM`<br>`pl_Blood_BM`<br>`pl0100_00face_MM` |
| pl0103_0 | (name not in title table) | `pl0100_00_earLight_BM` |
| pl0103_0 | pl_skin1 | `pl0100_00face_NM`<br>`pl0100_00face_BM`<br>`pl_Blood_BM`<br>`pl0100_00face_MM` |
| pl0100_1 | pl_base1 | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl0100_00body_MM` |
| pl0100_1 | (name not in title table) | `pl0100_23_prop_NM`<br>`pl0100_23_prop_BM`<br>`pl0100_23_prop_MM` |
| pl0100_1 | pl_cloth1 | `pl_VTF`<br>`pl0100_51_vest_MVTF`<br>`pl0100_26_vest_NM`<br>`BH_cloth_05_DM`<br>`pl0100_71_vest_d1_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_26_vest_MM` |
| pl0100_1 | pl_cloth | `pl_VTF`<br>`pl0100_50_shirt_MVTF`<br>`pl0100_21_shirt_NM`<br>`BH_cloth_05_DM`<br>`pl0100_21_shirt_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_21_shirt_MM` |
| pl0100_1 | pl_skin | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_1 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_1 | (name not in title table) | `pl_VTF`<br>`pl0100_23_prop_NM`<br>`pl0100_25_acs_BM`<br>`pl0100_23_prop_MM` |
| pl0100_1 | (name not in title table) | `pl0100_25_acs_BM` |
| pl0100_1 | (name not in title table) | `pl_VTF`<br>`pl0100_00body_NM`<br>`BH_cloth_05_DM`<br>`pl0100_70body_d1_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_1 | (name not in title table) | `pl_VTF`<br>`pl0100_23_prop_NM`<br>`pl0100_25_acs_BM`<br>`pl0100_23_prop_MM` |
| pl0101_1 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0102_1 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0103_1 | (name not in title table) | `pl_VTF`<br>`pl0100_55hair_00_MVTF`<br>`pl0100_00hair_00sft_MM`<br>`pl0100_00hair_00_BM`<br>`pl0100_00hair_00_MM` |
| pl0103_1 | (name not in title table) | `pl_VTF`<br>`pl0100_56hair_01_MVTF`<br>`pl0100_00hair_00sft_MM`<br>`pl0100_00hair_01_BM`<br>`pl0100_00hair_01_MM` |
| pl0103_1 | (name not in title table) | `pl0100_00eyelash_BM` |
| pl0103_1 | (name not in title table) | `pl0100_00eyelash_BM` |
| pl0103_1 | pl_base1 | `pl0100_00eye_NM`<br>`pl0100_00eye_BM`<br>`pl0100_00eye_MM` |
| pl0103_1 | (name not in title table) | `pl0100_00eyeCov_NM`<br>`pl0100_00eyeCov_BM`<br>`pl0100_00eyeCov_MM` |
| pl0103_1 | pl_skin | `pl0100_00face_NM`<br>`pl0100_00face_BM`<br>`pl_Blood_BM`<br>`pl0100_00face_MM` |
| pl0103_1 | (name not in title table) | `pl0100_00_earLight_BM` |
| pl0103_1 | pl_skin1 | `pl0100_00face_NM`<br>`pl0100_00face_BM`<br>`pl_Blood_BM`<br>`pl0100_00face_MM` |
| pl0100_2 | pl_base1 | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl0100_00body_MM` |
| pl0100_2 | (name not in title table) | `pl0100_23_prop_NM`<br>`pl0100_23_prop_BM`<br>`pl0100_23_prop_MM` |
| pl0100_2 | pl_cloth1 | `pl_VTF`<br>`pl0100_51_vest_MVTF`<br>`pl0100_26_vest_NM`<br>`BH_cloth_05_DM`<br>`pl0100_71_vest_d1_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_26_vest_MM` |
| pl0100_2 | pl_cloth | `pl_VTF`<br>`pl0100_50_shirt_MVTF`<br>`pl0100_21_shirt_NM`<br>`BH_cloth_05_DM`<br>`pl0100_21_shirt_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_21_shirt_MM` |
| pl0100_2 | pl_skin | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_2 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_2 | (name not in title table) | `pl_VTF`<br>`pl0100_23_prop_NM`<br>`pl0100_25_acs_BM`<br>`pl0100_23_prop_MM` |
| pl0100_2 | (name not in title table) | `pl0100_25_acs_BM` |
| pl0100_2 | (name not in title table) | `pl_VTF`<br>`pl0100_00body_NM`<br>`BH_cloth_05_DM`<br>`pl0100_70body_d1_BM`<br>`pl0100_31FS_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0100_2 | (name not in title table) | `pl_VTF`<br>`pl0100_23_prop_NM`<br>`pl0100_25_acs_BM`<br>`pl0100_23_prop_MM` |
| pl0101_2 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0102_2 | pl_skin1 | `pl0100_00body_NM`<br>`pl0100_70body_d1_BM`<br>`pl_Blood_BM`<br>`pl0100_00body_MM` |
| pl0103_2 | (name not in title table) | `pl_VTF`<br>`pl0100_55hair_00_MVTF`<br>`pl0100_00hair_00sft_MM`<br>`pl0100_00hair_00_BM`<br>`pl0100_00hair_00_MM` |
| pl0103_2 | (name not in title table) | `pl_VTF`<br>`pl0100_56hair_01_MVTF`<br>`pl0100_00hair_00sft_MM`<br>`pl0100_00hair_01_BM`<br>`pl0100_00hair_01_MM` |
| pl0103_2 | (name not in title table) | `pl0100_00eyelash_BM` |
| pl0103_2 | (name not in title table) | `pl0100_00eyelash_BM` |
| pl0103_2 | pl_base1 | `pl0100_00eye_NM`<br>`pl0100_00eye_BM`<br>`pl0100_00eye_MM` |
| pl0103_2 | (name not in title table) | `pl0100_00eyeCov_NM`<br>`pl0100_00eyeCov_BM`<br>`pl0100_00eyeCov_MM` |
| pl0103_2 | pl_skin | `pl0100_00face_NM`<br>`pl0100_00face_BM`<br>`pl_Blood_BM`<br>`pl0100_00face_MM` |
| pl0103_2 | (name not in title table) | `pl0100_00_earLight_BM` |
| pl0103_2 | pl_skin1 | `pl0100_00face_NM`<br>`pl0100_00face_BM`<br>`pl_Blood_BM`<br>`pl0100_00face_MM` |

### Chris - default costume `uPl02ChrisAsia.arc` (textures in `uPlTex0200_0.arc`, `uPlTex0200_1.arc`, `uPlTex0200_2.arc`, `uPlTex0200_3.arc`, `uPlTex0200_4.arc`)

| MRL | material | bound texture paths |
|---|---|---|
| pl0200_0 | pl_skin1 | `pl0200_01Body_NM`<br>`pl0200_01Body_BM`<br>`pl_Blood_BM`<br>`pl0200_01Body_MM` |
| pl0200_0 | pl_skin | `pl0200_01Body_NM`<br>`pl0200_01Body_BM`<br>`pl_Blood_BM`<br>`pl0200_01Body_MM` |
| pl0200_0 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0200_0 | pl_skin2 | `pl0200_02Armor_NM`<br>`pl0200_02Armor_BM`<br>`pl_Blood_BM`<br>`pl0200_02Armor_MM` |
| pl0200_0 | (name not in title table) | `pl0200_02Armor_NM`<br>`pl0200_02Armor_BM`<br>`pl0200_02Armor_MM` |
| pl0200_0 | (name not in title table) | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_0 | pl_skin3 | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl_Blood_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_0 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_0 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_0 | pl_base2 | `pl0200_03Pants_NM`<br>`BH_cloth_06_DM`<br>`pl0200_03Pants_BM`<br>`pl0200_03Pants_MM` |
| pl0200_0 | pl_base1 | `pl0200_03Pants_NM`<br>`pl0200_03Pants_BM`<br>`pl0200_03Pants_MM` |
| pl0200_0 | (name not in title table) | `pl0300_07Patch_NM`<br>`pl0300_07Patch_NUKI`<br>`pl0300_07Patch_MM` |
| pl0201_0 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0202_0 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0203_0 | pl_skin | `pl0200_00Face_NM`<br>`pl0200_00Face_BM`<br>`pl_Blood_BM`<br>`pl0200_00Face_MM` |
| pl0203_0 | (name not in title table) | `pl0200_00eyeshadow_BM` |
| pl0203_0 | (name not in title table) | `pl0200_00eyelash_BM` |
| pl0203_0 | (name not in title table) | `pl0200_00eye_NM`<br>`pl0200_00eye_BM`<br>`pl0200_00eye_MM` |
| pl0203_0 | (name not in title table) | `pl0200_00eyeCov_NM`<br>`pl0200_00eyeCov_BM`<br>`pl0200_00eyeCov_MM` |
| pl0203_0 | (name not in title table) | `pl_VTF`<br>`pl0200_51_09hair_MVTF`<br>`pl0200_09hair_BM`<br>`pl0200_09hair_MM` |
| pl0203_0 | (name not in title table) | `pl_VTF`<br>`pl0200_53_11hair_MVTF`<br>`pl0200_11hair_BM`<br>`pl0200_11hair_MM` |
| pl0203_0 | (name not in title table) | `pl_VTF`<br>`pl0200_52_10hair_MVTF`<br>`pl0200_10hair_BM`<br>`pl0200_10hair_MM` |
| pl0203_0 | (name not in title table) | `pl_VTF`<br>`pl0200_50_08hair_MVTF`<br>`pl0200_08hair_BM`<br>`pl0200_08hair_MM` |
| pl0203_0 | pl_base1 | `pl_earLight_BM` |
| pl0200_1 | pl_skin1 | `pl0200_01Body_NM`<br>`pl0200_01Body_BM`<br>`pl_Blood_BM`<br>`pl0200_70Body_d1_MM` |
| pl0200_1 | pl_skin | `pl0200_01Body_NM`<br>`pl0200_01Body_BM`<br>`pl_Blood_BM`<br>`pl0200_70Body_d1_MM` |
| pl0200_1 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0200_1 | pl_skin2 | `pl0200_02Armor_NM`<br>`pl0200_02Armor_BM`<br>`pl_Blood_BM`<br>`pl0200_02Armor_MM` |
| pl0200_1 | (name not in title table) | `pl0200_02Armor_NM`<br>`pl0200_02Armor_BM`<br>`pl0200_02Armor_MM` |
| pl0200_1 | (name not in title table) | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_1 | pl_skin3 | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl_Blood_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_1 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_1 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_1 | pl_base2 | `pl0200_03Pants_NM`<br>`pl0200_03Pants_BM`<br>`pl0200_03Pants_MM` |
| pl0200_1 | pl_base1 | `pl0200_03Pants_NM`<br>`pl0200_03Pants_BM`<br>`pl0200_03Pants_MM` |
| pl0200_1 | (name not in title table) | `pl0200_07Patch_NM`<br>`pl0300_07Patch_NUKI`<br>`pl0200_07Patch_MM` |
| pl0201_1 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0202_1 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0203_1 | pl_skin | `pl0200_00Face_NM`<br>`pl0200_00Face_BM`<br>`pl_Blood_BM`<br>`pl0200_60Face_d1_MM` |
| pl0203_1 | (name not in title table) | `pl0200_00eyeshadow_BM` |
| pl0203_1 | (name not in title table) | `pl0200_00eyelash_BM` |
| pl0203_1 | (name not in title table) | `pl0200_00eye_NM`<br>`pl0200_00eye_BM`<br>`pl0200_00eye_MM` |
| pl0203_1 | (name not in title table) | `pl0200_00eyeCov_NM`<br>`pl0200_00eyeCov_BM`<br>`pl0200_00eyeCov_MM` |
| pl0203_1 | (name not in title table) | `pl_VTF`<br>`pl0200_51_09hair_MVTF`<br>`pl0200_09hair_BM`<br>`pl0200_09hair_MM` |
| pl0203_1 | (name not in title table) | `pl_VTF`<br>`pl0200_53_11hair_MVTF`<br>`pl0200_11hair_BM`<br>`pl0200_11hair_MM` |
| pl0203_1 | (name not in title table) | `pl_VTF`<br>`pl0200_52_10hair_MVTF`<br>`pl0200_10hair_BM`<br>`pl0200_10hair_MM` |
| pl0203_1 | (name not in title table) | `pl_VTF`<br>`pl0200_50_08hair_MVTF`<br>`pl0200_08hair_BM`<br>`pl0200_08hair_MM` |
| pl0203_1 | pl_base1 | `pl_earLight_BM` |
| pl0200_2 | pl_skin1 | `pl0200_01Body_NM`<br>`pl0200_01Body_BM`<br>`pl_Blood_BM`<br>`pl0200_70Body_d1_MM` |
| pl0200_2 | pl_skin | `pl0200_01Body_NM`<br>`pl0200_01Body_BM`<br>`pl_Blood_BM`<br>`pl0200_70Body_d1_MM` |
| pl0200_2 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0200_2 | pl_skin2 | `pl0200_02Armor_NM`<br>`pl0200_02Armor_BM`<br>`pl_Blood_BM`<br>`pl0200_02Armor_MM` |
| pl0200_2 | (name not in title table) | `pl0200_02Armor_NM`<br>`pl0200_02Armor_BM`<br>`pl0200_02Armor_MM` |
| pl0200_2 | (name not in title table) | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_2 | pl_skin3 | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl_Blood_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_2 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_2 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_2 | pl_base2 | `pl0200_03Pants_NM`<br>`pl0200_03Pants_BM`<br>`pl0200_03Pants_MM` |
| pl0200_2 | pl_base1 | `pl0200_03Pants_NM`<br>`pl0200_03Pants_BM`<br>`pl0200_03Pants_MM` |
| pl0200_2 | (name not in title table) | `pl0200_07Patch_NM`<br>`pl0300_07Patch_NUKI`<br>`pl0200_07Patch_MM` |
| pl0201_2 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0202_2 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0203_2 | pl_skin | `pl0200_00Face_NM`<br>`pl0200_61Face_d2_BM`<br>`pl_Blood_BM`<br>`pl0200_61Face_d2_MM` |
| pl0203_2 | (name not in title table) | `pl0200_00eyeshadow_BM` |
| pl0203_2 | (name not in title table) | `pl0200_00eyelash_BM` |
| pl0203_2 | (name not in title table) | `pl0200_00eye_NM`<br>`pl0200_00eye_BM`<br>`pl0200_00eye_MM` |
| pl0203_2 | (name not in title table) | `pl0200_00eyeCov_NM`<br>`pl0200_00eyeCov_BM`<br>`pl0200_00eyeCov_MM` |
| pl0203_2 | (name not in title table) | `pl_VTF`<br>`pl0200_51_09hair_MVTF`<br>`pl0200_09hair_BM`<br>`pl0200_09hair_MM` |
| pl0203_2 | (name not in title table) | `pl_VTF`<br>`pl0200_53_11hair_MVTF`<br>`pl0200_11hair_BM`<br>`pl0200_11hair_MM` |
| pl0203_2 | (name not in title table) | `pl_VTF`<br>`pl0200_52_10hair_MVTF`<br>`pl0200_10hair_BM`<br>`pl0200_10hair_MM` |
| pl0203_2 | (name not in title table) | `pl_VTF`<br>`pl0200_50_08hair_MVTF`<br>`pl0200_08hair_BM`<br>`pl0200_08hair_MM` |
| pl0203_2 | pl_base1 | `pl_earLight_BM` |
| pl0200_3 | pl_skin1 | `pl0200_01Body_NM`<br>`pl0200_71Body_d2_BM`<br>`pl_Blood_BM`<br>`pl0200_01Body_MM` |
| pl0200_3 | pl_skin | `pl0200_01Body_NM`<br>`pl0200_71Body_d2_BM`<br>`pl_Blood_BM`<br>`pl0200_01Body_MM` |
| pl0200_3 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_73Hand_d1_BM`<br>`pl0200_07Hand_MM` |
| pl0200_3 | pl_skin2 | `pl0200_02Armor_NM`<br>`pl0200_72Armor_d1_BM`<br>`pl_Blood_BM`<br>`pl0200_02Armor_MM` |
| pl0200_3 | (name not in title table) | `pl0200_02Armor_NM`<br>`pl0200_72Armor_d1_BM`<br>`pl0200_02Armor_MM` |
| pl0200_3 | (name not in title table) | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_3 | pl_skin3 | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl_Blood_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_3 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_3 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_3 | pl_base2 | `pl0200_03Pants_NM`<br>`pl0200_74Pants_d1_BM`<br>`pl0200_03Pants_MM` |
| pl0200_3 | pl_base1 | `pl0200_03Pants_NM`<br>`pl0200_74Pants_d1_BM`<br>`pl0200_03Pants_MM` |
| pl0200_3 | (name not in title table) | `pl0200_07Patch_NM`<br>`pl0300_07Patch_NUKI`<br>`pl0200_07Patch_MM` |
| pl0201_3 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_73Hand_d1_BM`<br>`pl0200_07Hand_MM` |
| pl0202_3 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_73Hand_d1_BM`<br>`pl0200_07Hand_MM` |
| pl0203_3 | pl_skin | `pl0200_00Face_NM`<br>`pl0200_62Face_d3_BM`<br>`pl_Blood_BM`<br>`pl0200_62Face_d3_MM` |
| pl0203_3 | (name not in title table) | `pl0200_00eyeshadow_BM` |
| pl0203_3 | (name not in title table) | `pl0200_00eyelash_BM` |
| pl0203_3 | (name not in title table) | `pl0200_00eye_NM`<br>`pl0200_00eye_BM`<br>`pl0200_00eye_MM` |
| pl0203_3 | (name not in title table) | `pl0200_00eyeCov_NM`<br>`pl0200_00eyeCov_BM`<br>`pl0200_00eyeCov_MM` |
| pl0203_3 | (name not in title table) | `pl_VTF`<br>`pl0200_51_09hair_MVTF`<br>`pl0200_09hair_BM`<br>`pl0200_09hair_MM` |
| pl0203_3 | (name not in title table) | `pl_VTF`<br>`pl0200_53_11hair_MVTF`<br>`pl0200_11hair_BM`<br>`pl0200_11hair_MM` |
| pl0203_3 | (name not in title table) | `pl_VTF`<br>`pl0200_52_10hair_MVTF`<br>`pl0200_10hair_BM`<br>`pl0200_10hair_MM` |
| pl0203_3 | (name not in title table) | `pl_VTF`<br>`pl0200_50_08hair_MVTF`<br>`pl0200_08hair_BM`<br>`pl0200_08hair_MM` |
| pl0203_3 | pl_base1 | `pl_earLight_BM` |
| pl0200_4 | pl_skin1 | `pl0200_01Body_NM`<br>`pl0200_01Body_BM`<br>`pl_Blood_BM`<br>`pl0200_70Body_d1_MM` |
| pl0200_4 | pl_skin | `pl0200_01Body_NM`<br>`pl0200_01Body_BM`<br>`pl_Blood_BM`<br>`pl0200_70Body_d1_MM` |
| pl0200_4 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0200_4 | pl_skin2 | `pl0200_02Armor_NM`<br>`pl0200_02Armor_BM`<br>`pl_Blood_BM`<br>`pl0200_02Armor_MM` |
| pl0200_4 | (name not in title table) | `pl0200_02Armor_NM`<br>`pl0200_02Armor_BM`<br>`pl0200_02Armor_MM` |
| pl0200_4 | (name not in title table) | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_4 | pl_skin3 | `pl0200_04Eqipment_NM`<br>`pl0200_04Eqipment_BM`<br>`pl_Blood_BM`<br>`pl0200_04Eqipment_MM` |
| pl0200_4 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_4 | (name not in title table) | `pl0200_05Knife_NM`<br>`pl0200_05Knife_BM`<br>`pl0200_05Knife_MM` |
| pl0200_4 | pl_base2 | `pl0200_03Pants_NM`<br>`pl0200_03Pants_BM`<br>`pl0200_03Pants_MM` |
| pl0200_4 | pl_base1 | `pl0200_03Pants_NM`<br>`pl0200_03Pants_BM`<br>`pl0200_03Pants_MM` |
| pl0200_4 | (name not in title table) | `pl0200_07Patch_NM`<br>`pl0300_07Patch_NUKI`<br>`pl0200_07Patch_MM` |
| pl0201_4 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0202_4 | (name not in title table) | `pl0200_07Hand_NM`<br>`pl0200_07Hand_BM`<br>`pl0200_07Hand_MM` |
| pl0203_4 | pl_skin | `pl0200_00Face_NM`<br>`pl0200_63Face_d4_BM`<br>`pl_Blood_BM`<br>`pl0200_63Face_d4_MM` |
| pl0203_4 | (name not in title table) | `pl0200_00eyeshadow_BM` |
| pl0203_4 | (name not in title table) | `pl0200_00eyelash_BM` |
| pl0203_4 | (name not in title table) | `pl0200_00eye_NM`<br>`pl0200_00eye_BM`<br>`pl0200_00eye_MM` |
| pl0203_4 | (name not in title table) | `pl0200_00eyeCov_NM`<br>`pl0200_00eyeCov_BM`<br>`pl0200_00eyeCov_MM` |
| pl0203_4 | (name not in title table) | `pl_VTF`<br>`pl0200_51_09hair_MVTF`<br>`pl0200_09hair_BM`<br>`pl0200_09hair_MM` |
| pl0203_4 | (name not in title table) | `pl_VTF`<br>`pl0200_53_11hair_MVTF`<br>`pl0200_11hair_BM`<br>`pl0200_11hair_MM` |
| pl0203_4 | (name not in title table) | `pl_VTF`<br>`pl0200_52_10hair_MVTF`<br>`pl0200_10hair_BM`<br>`pl0200_10hair_MM` |
| pl0203_4 | (name not in title table) | `pl_VTF`<br>`pl0200_50_08hair_MVTF`<br>`pl0200_08hair_BM`<br>`pl0200_08hair_MM` |
| pl0203_4 | pl_base1 | `pl0200_00earLight_BM` |

### Piers - default costume `uPl03PiersAsia.arc` (textures in `uPlTex0300_0.arc`, `uPlTex0300_1.arc`, `uPlTex0300_2.arc`)

| MRL | material | bound texture paths |
|---|---|---|
| pl0300_0 | pl_skin | `pl0300_02vest_NM`<br>`pl0300_02vest_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_02vest_MM` |
| pl0300_0 | pl_skin3 | `pl0300_01shirts_NM`<br>`pl0300_01shirts_BM`<br>`pl_Blood_BM`<br>`pl0300_01shirts_MM` |
| pl0300_0 | pl_cloth | `pl_VTF`<br>`pl0300_01shirts_NM`<br>`BH_cloth_05_DM`<br>`pl0300_01shirts_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_01shirts_MM` |
| pl0300_0 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0300_0 | pl_base2 | `pl0300_04soubi2_NM`<br>`pl0300_04soubi2_BM`<br>`pl0300_04soubi2_MM` |
| pl0300_0 | pl_base1 | `pl0300_05Pants_NM`<br>`BH_cloth_06_DM`<br>`pl0300_05Pants_BM`<br>`pl0300_05Pants_MM` |
| pl0300_0 | (name not in title table) | `pl0300_02vest_NM`<br>`pl0300_02vest_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_02vest_MM` |
| pl0300_0 | pl_cloth1 | `pl_VTF`<br>`pl0300_51Stole_MVTF`<br>`pl0300_10Stole_NM`<br>`pl0300_10Stole_BM`<br>`pl_Blood_BM`<br>`pl0300_10Stole_MM` |
| pl0300_0 | (name not in title table) | `pl0300_03soubi1_NM`<br>`pl0300_03soubi1_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_03soubi1_MM` |
| pl0300_0 | (name not in title table) | `pl0300_05Pants_NM`<br>`pl0300_05Pants_BM`<br>`pl0300_05Pants_MM` |
| pl0300_0 | (name not in title table) | `pl0300_10Stole_NM`<br>`pl0300_10Stole_BM`<br>`pl0300_20FS_BM`<br>`pl_Blood_BM`<br>`pl0300_10Stole_MM` |
| pl0300_0 | (name not in title table) | `pl0300_07Patch_NM`<br>`pl0300_07Patch_NUKI`<br>`pl0300_07Patch_MM` |
| pl0301_0 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0302_0 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0303_0 | (name not in title table) | `pl0300_00eyelash_BM` |
| pl0303_0 | (name not in title table) | `pl0300_00eyeshadow` |
| pl0303_0 | (name not in title table) | `pl0300_00eyeCov_NM`<br>`pl0300_00eye_BM`<br>`pl0300_00eyeCov_MM` |
| pl0303_0 | (name not in title table) | `pl0300_00eyeCov_NM`<br>`pl0300_00eyeCov_BM`<br>`pl0300_00eyeCov_MM` |
| pl0303_0 | pl_skin | `pl0300_00Face_NM`<br>`pl0300_00Face_BM`<br>`pl_Blood_BM`<br>`pl0300_00Face_MM` |
| pl0303_0 | (name not in title table) | `pl0300_00eyelash_BM` |
| pl0303_0 | pl_base1 | `pl_earLight_BM` |
| pl0303_0 | (name not in title table) | `pl_VTF`<br>`pl0300_00Hairtest_NM`<br>`pl0300_00Hairtest_BM`<br>`pl0300_00Hairtest_MM` |
| pl0303_0 | (name not in title table) | `pl_VTF`<br>`pl0300_50Hair_MVTF`<br>`pl0300_00Hair_NM`<br>`pl0300_00Hair_BM`<br>`pl0300_00Hair_MM` |
| pl0300_1 | pl_skin | `pl0300_02vest_NM`<br>`pl0300_02vest_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_02vest_MM` |
| pl0300_1 | pl_skin3 | `pl0300_01shirts_NM`<br>`pl0300_01shirts_BM`<br>`pl_Blood_BM`<br>`pl0300_70shirts_d1_MM` |
| pl0300_1 | pl_cloth | `pl_VTF`<br>`pl0300_01shirts_NM`<br>`BH_cloth_05_DM`<br>`pl0300_01shirts_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_70shirts_d1_MM` |
| pl0300_1 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0300_1 | pl_base2 | `pl0300_04soubi2_NM`<br>`pl0300_04soubi2_BM`<br>`pl0300_04soubi2_MM` |
| pl0300_1 | pl_base1 | `pl0300_05Pants_NM`<br>`BH_cloth_06_DM`<br>`pl0300_05Pants_BM`<br>`pl0300_05Pants_MM` |
| pl0300_1 | (name not in title table) | `pl0300_02vest_NM`<br>`pl0300_02vest_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_02vest_MM` |
| pl0300_1 | pl_cloth1 | `pl_VTF`<br>`pl0300_51Stole_MVTF`<br>`pl0300_10Stole_NM`<br>`pl0300_10Stole_BM`<br>`pl_Blood_BM`<br>`pl0300_10Stole_MM` |
| pl0300_1 | (name not in title table) | `pl0300_03soubi1_NM`<br>`pl0300_03soubi1_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_03soubi1_MM` |
| pl0300_1 | (name not in title table) | `pl0300_05Pants_NM`<br>`pl0300_05Pants_BM`<br>`pl0300_05Pants_MM` |
| pl0300_1 | (name not in title table) | `pl0300_10Stole_NM`<br>`pl0300_10Stole_BM`<br>`pl0300_20FS_BM`<br>`pl_Blood_BM`<br>`pl0300_10Stole_MM` |
| pl0300_1 | (name not in title table) | `pl0300_07Patch_NM`<br>`pl0300_07Patch_NUKI`<br>`pl0300_07Patch_MM` |
| pl0301_1 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0302_1 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0303_1 | (name not in title table) | `pl0300_00eyelash_BM` |
| pl0303_1 | (name not in title table) | `pl0300_00eyeshadow` |
| pl0303_1 | (name not in title table) | `pl0300_00eyeCov_NM`<br>`pl0300_00eye_BM`<br>`pl0300_00eyeCov_MM` |
| pl0303_1 | (name not in title table) | `pl0300_00eyeCov_NM`<br>`pl0300_00eyeCov_BM`<br>`pl0300_00eyeCov_MM` |
| pl0303_1 | pl_skin | `pl0300_00Face_NM`<br>`pl0300_00Face_BM`<br>`pl_Blood_BM`<br>`pl0300_60Face_d1_MM` |
| pl0303_1 | (name not in title table) | `pl0300_00eyelash_BM` |
| pl0303_1 | pl_base1 | `pl_earLight_BM` |
| pl0303_1 | (name not in title table) | `pl_VTF`<br>`pl0300_00Hairtest_NM`<br>`pl0300_00Hairtest_BM`<br>`pl0300_00Hairtest_MM` |
| pl0303_1 | (name not in title table) | `pl_VTF`<br>`pl0300_50Hair_MVTF`<br>`pl0300_00Hair_NM`<br>`pl0300_00Hair_BM`<br>`pl0300_00Hair_MM` |
| pl0300_2 | pl_skin | `pl0300_02vest_NM`<br>`pl0300_02vest_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_02vest_MM` |
| pl0300_2 | pl_skin3 | `pl0300_01shirts_NM`<br>`pl0300_01shirts_BM`<br>`pl_Blood_BM`<br>`pl0300_70shirts_d1_MM` |
| pl0300_2 | pl_cloth | `pl_VTF`<br>`pl0300_01shirts_NM`<br>`BH_cloth_05_DM`<br>`pl0300_01shirts_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_70shirts_d1_MM` |
| pl0300_2 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0300_2 | pl_base2 | `pl0300_04soubi2_NM`<br>`pl0300_04soubi2_BM`<br>`pl0300_04soubi2_MM` |
| pl0300_2 | pl_base1 | `pl0300_05Pants_NM`<br>`BH_cloth_06_DM`<br>`pl0300_05Pants_BM`<br>`pl0300_05Pants_MM` |
| pl0300_2 | (name not in title table) | `pl0300_02vest_NM`<br>`pl0300_02vest_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_02vest_MM` |
| pl0300_2 | pl_cloth1 | `pl_VTF`<br>`pl0300_51Stole_MVTF`<br>`pl0300_10Stole_NM`<br>`pl0300_10Stole_BM`<br>`pl_Blood_BM`<br>`pl0300_10Stole_MM` |
| pl0300_2 | (name not in title table) | `pl0300_03soubi1_NM`<br>`pl0300_03soubi1_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0300_03soubi1_MM` |
| pl0300_2 | (name not in title table) | `pl0300_05Pants_NM`<br>`pl0300_05Pants_BM`<br>`pl0300_05Pants_MM` |
| pl0300_2 | (name not in title table) | `pl0300_10Stole_NM`<br>`pl0300_10Stole_BM`<br>`pl0300_20FS_BM`<br>`pl_Blood_BM`<br>`pl0300_10Stole_MM` |
| pl0300_2 | (name not in title table) | `pl0300_07Patch_NM`<br>`pl0300_07Patch_NUKI`<br>`pl0300_07Patch_MM` |
| pl0301_2 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0302_2 | (name not in title table) | `pl0300_06Hand_NM`<br>`pl0300_06Hand_BM`<br>`pl0300_06Hand_MM` |
| pl0303_2 | (name not in title table) | `pl0300_00eyelash_BM` |
| pl0303_2 | (name not in title table) | `pl0300_00eyeshadow` |
| pl0303_2 | (name not in title table) | `pl0300_00eyeCov_NM`<br>`pl0300_00eye_BM`<br>`pl0300_00eyeCov_MM` |
| pl0303_2 | (name not in title table) | `pl0300_00eyeCov_NM`<br>`pl0300_00eyeCov_BM`<br>`pl0300_00eyeCov_MM` |
| pl0303_2 | pl_skin | `pl0300_00Face_NM`<br>`pl0300_61Face_d2_BM`<br>`pl_Blood_BM`<br>`pl0300_61Face_d2_MM` |
| pl0303_2 | (name not in title table) | `pl0300_00eyelash_BM` |
| pl0303_2 | pl_base1 | `pl_earLight_BM` |
| pl0303_2 | (name not in title table) | `pl_VTF`<br>`pl0300_00Hairtest_NM`<br>`pl0300_00Hairtest_BM`<br>`pl0300_00Hairtest_MM` |
| pl0303_2 | (name not in title table) | `pl_VTF`<br>`pl0300_50Hair_MVTF`<br>`pl0300_00Hair_NM`<br>`pl0300_00Hair_BM`<br>`pl0300_00Hair_MM` |

### Jake - default costume `uPl04JakeAsia.arc` (textures in `uPlTex0420_0.arc`, `uPlTex0420_1.arc`, `uPlTex0420_2.arc`, `uPlTex0420_3.arc`)

| MRL | material | bound texture paths |
|---|---|---|
| pl0420_0 | pl_cloth | `pl_VTF`<br>`pl0420_50_shirts_MVTF`<br>`pl0420_20_shirts_NM`<br>`pl0420_20_shirts_DM`<br>`pl0420_20_shirts_BM`<br>`pl0010_30_shirtsFS_BM`<br>`pl_Blood_BM`<br>`pl0420_20_shirts_MM` |
| pl0420_0 | pl_skin | `pl0420_27_skin_NM`<br>`pl0420_27_skin_BM`<br>`pl_Blood_BM`<br>`pl0420_27_skin_MM` |
| pl0420_0 | pl_skin1 | `pl0420_25_metal_NM`<br>`pl0420_25_metal_BM`<br>`pl_Blood_BM`<br>`pl0420_25_metal_MM` |
| pl0420_0 | pl_skin2 | `pl0420_24_leather_NM`<br>`pl0420_24_leather_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0420_24_leather_MM` |
| pl0420_0 | pl_skin3 | `pl0420_23_boots_NM`<br>`pl0420_23_boots_BM`<br>`pl_Blood_BM`<br>`pl0420_23_boots_MM` |
| pl0420_0 | (name not in title table) | `pl0420_26_gear_NM`<br>`pl0420_26_gear_BM`<br>`pl0420_26_gear_MM` |
| pl0420_0 | pl_base1 | `pl0420_21_pants_NM`<br>`pl0420_21_pants_BM`<br>`pl0420_21_pants_MM` |
| pl0420_0 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0421_0 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0422_0 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0403_0 | (name not in title table) | `pl0400_02_eyelash_BM` |
| pl0403_0 | (name not in title table) | `pl0400_02_eyelash_BM` |
| pl0403_0 | pl_skin | `pl0400_00_head_NM`<br>`pl0400_00_head_BM`<br>`pl_Blood_BM`<br>`pl0400_00_head_MM` |
| pl0403_0 | (name not in title table) | `pl0400_01_eye_NM`<br>`pl0400_01_eye_BM`<br>`pl0400_01_eye_MM` |
| pl0403_0 | (name not in title table) | `pl0400_00eyeCov_NM`<br>`pl0400_00eyeCov_BM`<br>`pl0400_00eyeCov_MM` |
| pl0403_0 | pl_base1 | `pl_earLight_BM` |
| pl0420_1 | pl_cloth | `pl_VTF`<br>`pl0420_50_shirts_MVTF`<br>`pl0420_20_shirts_NM`<br>`pl0420_20_shirts_DM`<br>`pl0420_70_shirts_d1_BM`<br>`pl0010_30_shirtsFS_BM`<br>`pl_Blood_BM`<br>`pl0420_20_shirts_MM` |
| pl0420_1 | pl_skin | `pl0420_27_skin_NM`<br>`pl0420_71_skin_d1_BM`<br>`pl_Blood_BM`<br>`pl0420_71_skin_d1_MM` |
| pl0420_1 | pl_skin1 | `pl0420_25_metal_NM`<br>`pl0420_25_metal_BM`<br>`pl_Blood_BM`<br>`pl0420_25_metal_MM` |
| pl0420_1 | pl_skin2 | `pl0420_24_leather_NM`<br>`pl0420_24_leather_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0420_24_leather_MM` |
| pl0420_1 | pl_skin3 | `pl0420_23_boots_NM`<br>`pl0420_23_boots_BM`<br>`pl_Blood_BM`<br>`pl0420_23_boots_MM` |
| pl0420_1 | (name not in title table) | `pl0420_26_gear_NM`<br>`pl0420_26_gear_BM`<br>`pl0420_26_gear_MM` |
| pl0420_1 | pl_base1 | `pl0420_21_pants_NM`<br>`pl0420_21_pants_BM`<br>`pl0420_21_pants_MM` |
| pl0420_1 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0421_1 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0422_1 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0423_1 | (name not in title table) | `pl0400_02_eyelash_BM` |
| pl0423_1 | (name not in title table) | `pl0400_02_eyelash_BM` |
| pl0423_1 | pl_skin | `pl0400_00_head_NM`<br>`pl0400_00_head_BM`<br>`pl_Blood_BM`<br>`pl0400_61_head_d2_MM` |
| pl0423_1 | (name not in title table) | `pl0400_01_eye_NM`<br>`pl0400_01_eye_BM`<br>`pl0400_01_eye_MM` |
| pl0423_1 | (name not in title table) | `pl0400_00eyeCov_NM`<br>`pl0400_00eyeCov_BM`<br>`pl0400_00eyeCov_MM` |
| pl0423_1 | pl_base1 | `pl_earLight_BM` |
| pl0420_2 | pl_cloth | `pl_VTF`<br>`pl0420_50_shirts_MVTF`<br>`pl0420_20_shirts_NM`<br>`pl0420_20_shirts_DM`<br>`pl0420_70_shirts_d1_BM`<br>`pl0010_30_shirtsFS_BM`<br>`pl_Blood_BM`<br>`pl0420_20_shirts_MM` |
| pl0420_2 | pl_skin | `pl0420_27_skin_NM`<br>`pl0420_71_skin_d1_BM`<br>`pl_Blood_BM`<br>`pl0420_27_skin_MM` |
| pl0420_2 | pl_skin1 | `pl0420_25_metal_NM`<br>`pl0420_25_metal_BM`<br>`pl_Blood_BM`<br>`pl0420_25_metal_MM` |
| pl0420_2 | pl_skin2 | `pl0420_24_leather_NM`<br>`pl0420_24_leather_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0420_24_leather_MM` |
| pl0420_2 | pl_skin3 | `pl0420_23_boots_NM`<br>`pl0420_23_boots_BM`<br>`pl_Blood_BM`<br>`pl0420_23_boots_MM` |
| pl0420_2 | (name not in title table) | `pl0420_26_gear_NM`<br>`pl0420_26_gear_BM`<br>`pl0420_26_gear_MM` |
| pl0420_2 | pl_base1 | `pl0420_21_pants_NM`<br>`pl0420_21_pants_BM`<br>`pl0420_21_pants_MM` |
| pl0420_2 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0421_2 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0422_2 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0423_2 | (name not in title table) | `pl0400_02_eyelash_BM` |
| pl0423_2 | (name not in title table) | `pl0400_02_eyelash_BM` |
| pl0423_2 | pl_skin | `pl0400_00_head_NM`<br>`pl0400_60_head_d1_BM`<br>`pl_Blood_BM`<br>`pl0400_00_head_MM` |
| pl0423_2 | (name not in title table) | `pl0400_01_eye_NM`<br>`pl0400_01_eye_BM`<br>`pl0400_01_eye_MM` |
| pl0423_2 | (name not in title table) | `pl0400_00eyeCov_NM`<br>`pl0400_00eyeCov_BM`<br>`pl0400_00eyeCov_MM` |
| pl0423_2 | pl_base1 | `pl_earLight_BM` |
| pl0420_3 | pl_cloth | `pl_VTF`<br>`pl0420_50_shirts_MVTF`<br>`pl0420_20_shirts_NM`<br>`pl0420_20_shirts_DM`<br>`pl0420_72_shirts_d2_BM`<br>`pl0010_30_shirtsFS_BM`<br>`pl_Blood_BM`<br>`pl0420_20_shirts_MM` |
| pl0420_3 | pl_skin | `pl0420_27_skin_NM`<br>`pl0420_74_skin_d2_BM`<br>`pl_Blood_BM`<br>`pl0420_27_skin_MM` |
| pl0420_3 | pl_skin1 | `pl0420_25_metal_NM`<br>`pl0420_25_metal_BM`<br>`pl_Blood_BM`<br>`pl0420_25_metal_MM` |
| pl0420_3 | pl_skin2 | `pl0420_24_leather_NM`<br>`pl0420_24_leather_BM`<br>`pl0300_21FS2_BM`<br>`pl_Blood_BM`<br>`pl0420_24_leather_MM` |
| pl0420_3 | pl_skin3 | `pl0420_23_boots_NM`<br>`pl0420_23_boots_BM`<br>`pl_Blood_BM`<br>`pl0420_23_boots_MM` |
| pl0420_3 | (name not in title table) | `pl0420_26_gear_NM`<br>`pl0420_26_gear_BM`<br>`pl0420_26_gear_MM` |
| pl0420_3 | pl_base1 | `pl0420_21_pants_NM`<br>`pl0420_73_pants_d1_BM`<br>`pl0420_21_pants_MM` |
| pl0420_3 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0421_3 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0422_3 | pl_base2 | `pl0420_22_glove_NM`<br>`pl0420_22_glove_BM`<br>`pl0420_22_glove_MM` |
| pl0423_3 | (name not in title table) | `pl0400_02_eyelash_BM` |
| pl0423_3 | (name not in title table) | `pl0400_02_eyelash_BM` |
| pl0423_3 | pl_skin | `pl0400_00_head_NM`<br>`pl0400_62_head_d3_BM`<br>`pl_Blood_BM`<br>`pl0400_62_head_d3_MM` |
| pl0423_3 | (name not in title table) | `pl0400_01_eye_NM`<br>`pl0400_01_eye_BM`<br>`pl0400_01_eye_MM` |
| pl0423_3 | (name not in title table) | `pl0400_00eyeCov_NM`<br>`pl0400_00eyeCov_BM`<br>`pl0400_00eyeCov_MM` |
| pl0423_3 | pl_base1 | `pl_earLight_BM` |

**Source:** per-material texture bindings from the texture-set MRLs (v36) of the archives listed per character, decoded with `gbox.re6_switch_tex.texture_set_materials`; material names resolved via the title's material-name table (crc32^0xFFFFFFFF key).

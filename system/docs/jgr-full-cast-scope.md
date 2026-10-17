# JGR Sonic cast and Mario police: required coverage

Operator request: Sonic characters throughout the cast and every gang, Mario characters for all police,
and replacement of Professor K. This includes character-select/title presentations and in-engine cinematic
instances, not just the model used while skating. No complete build meeting this scope is approved yet.

The owned USA disc is game `4187aeab4d67638c`, MK-51058 V1.005. Read-only archive census on 2026-10-14 confirms:

| Resource | Current evidence | Remaining work |
| --- | --- | --- |
| `JETRADIO/PLAYER.AFS` | 16 PLAY/PTEX pairs; existing named slots include the four rival resources | Repair detail and animation continuity; inspect every donor and every relevant draw context |
| `JETRADIO/ENEMY.AFS` | Separate `keikan`, `kidoutai`, `killer`, `bomb`, `kairiki`, `para`, `rocket`, `fire`, `sniper`, `onisima` DAT/TXR pairs, alongside dog/vehicle/effect/pedestrian resources | Bind native actor IDs to these models before classifying all enforcement actors and writing Mario replacements |
| `JETRADIO/ENEMY.AFS` rival resources | Separate `rival1`, `rival2`, `rival3` DAT/TXR pairs | Identify gang memberships and every variation in gameplay and scenes; PLAYER rival leaders do not cover these members |
| `JETRADIO/DEMO*.AFS` | Separate RAM-linked demo DAT and texture entries | Locate duplicate cinematic/presentation model instances and their native pointers/animations |
| Professor K | No verified resource/model binding yet | Locate the model, skeleton, textures and scene instances; choose the Sonic donor, then verify each occurrence |

Archive names alone do not establish which native actor or scene draws them. Keep that distinction in reports.
`replacement_scope` on JGR use/whole-cast plans explicitly lists missing contexts so a successful PLAYER-only
chain cannot be mistaken for a completed whole-world replacement.

The private Amy v11 diagnostic (`jgr_sa2_amy_rose_04_d1b3adaa11d24218`) failed operator visual review #1889:
arms and face are damaged. #1888 separately shows the stock character-select model. A booting ROM and a reduced
offline mesh are insufficient acceptance. Keep feedback, source geometry and edited Blender variants; do not
promote or repeat that reduction as the basis for a complete cast without correcting and inspecting it.

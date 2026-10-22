# Power Stone (USA) Dreamcast — unlock-on-load research checkpoint (request #2214)

Status: **research in progress; no unlock routine deployed, nothing runtime-verified.**
game_id `dd6dab53e0e8166e`, platform dreamcast.

## Owned media
`/mnt/gbox/hyperspin/Arcade/collections/Sega Dreamcast/roms/Power Stone (USA).chd`
extracted with `chdman extractcd` -> `disc.gdi` + disc01.bin / disc02.raw / disc03.bin (original CHD untouched).

## Hashes (sha256)
| file | sha256 |
|---|---|
| disc.gdi | bec2279e6f913025ac2d43c1d2d44a8c15d7f0228cb56816d314b4fdbb6294c3 |
| IP.BIN (32768) | dde15bc534578ae42cdf5e1ab0206e898d3eb566e031602810e7318536d809bc |
| 1ST_READ.BIN (3414344 / 0x341948) | 66003bf4aa549c8b78692080b46ffa1446432762609da9bc8c323633079546a5 |
| OMAKE.BIN | 9e7be10ae14cb34047b047d72225c25fb9b6eb339f9db2b2740c07610789e075 |
| SELE.BIN | b9fda6dbac3c6627195b366569dac57547c710f344e015260b6938ece2513d54 |
| COMMON.BIN | ac2b543009bc04d9a800bbac58254e8c1059be7d9f1c5a8e9106df2cb614877e |
| OPT.BIN | 0501a83aa242b657be6c664b9423533b158caa256e2809f8b98814d84fbc5d7e |

IP.BIN header: `SEGA SEGAKATANA`, maker SEGA ENTERPRISES, `GD-ROM1/1`, region `U`,
**product `T1201N` V1.001 19990805**, title `POWER STONE`, boot `1ST_READ.BIN`.
(Correction to earlier assumption: product is T1201N, not T-1210N.)

## Static findings so far (1ST_READ.BIN, SH-4, load base 0x8C010000)
Capstone has SH4 support (`CS_ARCH_SH`, `CS_MODE_SH4`) for disassembly on the Spark.
Strings (file offset): `TOGATTI.OMAKE GAME.OMAKE NO1.OMAKE NO2` 0x10719a; `OMAKE.BIN` 0x10d268;
`SELE.BIN` 0x10d2bc; `SELECT ENDING` 0x106990; `SAVE / LOAD.EXIT` 0x10c7e8;
debug menu text `... ENDING CHECK`, `STAGE SE..` 0x143fe4/0x143a5d; `KRAKEN`, `BOSS 0/1`, `ENDING` 0x144068;
`SAVE`/`LOAD` 0x1444a4. No direct 4-aligned literal-pool pointers to these strings were found
(strings are reached via tables/offset arithmetic), so flag-block location is still UNKNOWN.

## Inventory (all categories: unknown until flag block traced)
characters / hidden_characters / modes / levels / stages / costumes / items / extras: **unknown**.
Hints only (disc file list, not unlock proof): character BINs AYAME FOKER GANRO GARUD JACK KRAKN RUJYU RYOUM WANG (+A_JACK),
OMAKE.BIN (extras), STG00..0A, PL00..0A_DATA.

## Next step
1. Open `1ST_READ.BIN` (hash above) in REA/Ghidra on an x64 worker (i9-NUC), language `SuperH:LE:32:SH-4a`, base 0x8C010000; reuse existing project.
2. Trace the OMAKE / SELECT ENDING / debug-menu strings and the SAVE/LOAD (VMU) code to the progress-flag block; record RAM addresses.
3. Build `profiles/gamedata/dd6dab53e0e8166e-codes.json` only after a runtime read-back; add test mirroring `tests/test_unlock_on_load_codes.py`.
4. Runtime acceptance on idle i9-NUC/Spark at 2% audio: fresh boot, select/play each item, second launch, rollback.

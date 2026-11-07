# hactool: opening Switch titles inside the project

Status: **integrated and running** (2026-11-07). `hactool 1.4.0` is built from source, installed at
`system/tools/bin/hactool`, wrapped by `gbox/hactool.py`, and exposed to the lab through two routes.

## Why it mattered

The RomFS trees this system worked from were extracted by tooling *outside* the project. That was fine while every
question was about data files - containers, meshes, textures, audio - and fatal as soon as a question needed **code**:
how a texture id in a pack reaches an `imagepackhd` archive is answered by the loader, not by any file, and without the
executable that question could not even be asked. It is the single thing that has blocked the RE4 Switch texture join
through four rounds of hypothesis testing.

## Where the pieces came from

The operator pointed at the share: `\\10.89.1.125\QuickSwap2\Emulation\switch2` (mounted on the Spark at
`/mnt/gbox/quickswap2`), holding `hactool-1.4.0.zip`, `hactool-master.zip` and `hactoolnx.7z`. The zip and the
`hactool-1.4.0.tar.gz` inside the 7z both carry the source tree, so the project builds its own binary rather than trusting
a prebuilt one:

```
apt-get install -y libmbedtls-dev          # hactool 1.4.0 links mbedtls (it also ships the submodule)
cp config.mk.template config.mk && make -j8
install -m755 hactool <project>/system/tools/bin/hactool
```

`hactoolnx.7z` also holds `hactool-1.4.0-win.zip`, which is the Windows build for hosts that need one.

## What the project can do with it now

`gbox/hactool.py`:

| function | what it gives |
|---|---|
| `available()` | the tool, the keys file, whether both are there, and the version - for a page to show |
| `list_files(path)` | the member table of an `nsp`/`nca`/`xci` with sizes, without extracting |
| `unpack_nsp(path, out)` | an `nsp`'s `nca` members, largest first |
| `extract_exefs(path, out)` | `main`, `main.npdm`, `rtld`, `sdk`, `subsdk0` (unpacking the `nsp` first when given one) |
| `decompress_nso(nso, out)` | `main.bin`: the NSO's LZ4 sections expanded to a flat image a code tool reads |
| `extract_romfs(nca, out)` | the whole RomFS - gigabytes, so it is never called by accident |

Routes: `GET /api/decrypt-lab/hactool` (readiness) and `GET /api/decrypt-lab/exefs?title=...` (extract + decompress).

The keys are found at `~/gBox_alt/switch/prod.keys`, then `~/.switch/prod.keys`; `GBOX_HACTOOL` overrides the binary and
`GBOX_HACTOOL=... tools/bin/hactool` is where it lives by default. hactool warns about keys newer than 1.4.0 knows
(`bis_kek_source`, `device_key_4x`, ...). Those warnings are dropped from the wrapper's output and do not affect NSP or
NCA reading - an `nca` header and the exefs need only the older key set.

## Verified on the real title

```
GET /api/decrypt-lab/hactool  -> ready True, version "Built: 08:54:04 Nov  7 2026", keys present
GET /api/decrypt-lab/exefs?title=re4_switch
  main      5,260,117    sdk 5,103,989    subsdk0 3,344,893    rtld 7,353    main.npdm 1,508
  main.bin 11,716,664    sections .text .rodata .rwdata .bss
  out: ~/gBox_alt/gbox-cache/exefs/010099A00BC1E000
```

Reading the `nsp` gives three members: the 12,974,144,512-byte program NCA, the 825,856-byte manual NCA and the
4,096-byte ticket. The exefs comes out of the program NCA's section 0.

## What this changes for the texture join

`main` and `subsdk0` contain **no** `imagepackhd` or `pack.fen` strings (checked in the decompressed images), so the
archives are not addressed by a literal path and are not found by formatting a name either. The id-to-archive resolution
is therefore a **table or a computation in code**, which is exactly what a decompiler answers.

That is the next step, and it is the first time it is possible: `analyze_binary` in `docs/ghidra-service.md` takes a
path and wants `ghidra_home` + JDK 21 - neither installed yet - and `main.bin` is now sitting in the cache waiting for it.

## Tests

`tests/test_hactool.py` (9): the wrapper's command construction, the listing parser, the exefs flow (nsp unpacked then the
program NCA read), refusals (missing file, missing keys, empty result) and the NSO section report. The parsing tests
already found two real bugs - a regex anchored to leading whitespace (which dropped the *first* file of every listing,
because hactool puts it on the `Files:` line) and offsets assumed to be 16 hex digits wide when hactool prints 12.

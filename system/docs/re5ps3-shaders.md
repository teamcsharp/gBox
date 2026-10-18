# RE5 PS3 standard-material shader evidence

`gbox.re5ps3_shaders` is a bounded, read-only tool for the BE BFX `0x2004`
standard-material technique `8727e606`. It maps the six native material
function fields to compiled vertex/fragment programs and records direct
instruction operands, texture instructions and immediate vertex branches.
It does not execute shaders, prove branch reachability or bind runtime
vertex/texture buffers. It does not replace nonfinite UVs or produce a game
export. Full cast, unlocks, sidebar equipment and native gameplay remain open.

From `system/`:

```sh
python -m gbox.re5ps3_shaders OWNED_shader.arc \
  --material 30800000 --material 30844000 --material 40844000 \
  --out NEW_SHADER_EVIDENCE.json
```

A decoded `system\xfshader\XfMaterialStandard` BFX is also accepted. ARC
member identity includes type `50f9db3e`. The JSON records actual source and
decoded SHA256, offsets, opaque header fields/section hashes, selector values,
compiled program hashes and raw instruction bytes. Output is created only
after validation and is exclusive. Original archives and decoded resources
remain unchanged. No game process is started.

## Derivation and bounds

Owned BFX starts with `>4sHHI`: magic `00 58 46 42`, version, technique count,
parameter count. This reader supports one technique. After the 8-byte parameter
records is a 28-byte technique record: hash, five section sizes, opaque word.
The body starts immediately afterward. The Cg section begins at body plus
section sizes 0 and 2; its length is size 1. Size 3 is zero in this supported
layout. Every byte of that section must belong to one contiguous compiled
program. Other section meanings and runtime binding metadata remain opaque.

Body offsets are relative to the body, not the file. The 60-byte header holds
the selector count (twice), six function dimensions, fragment/vertex counts,
and function/selector/program-metadata tables. Each function descriptor has
a string offset, a packed multiplier/count, and enum-string offsets. The
reader validates cumulative multipliers and the full selector table. A
selector packs fragment index in the high 16 bits and vertex index in the
low 16; `ffffffff` means unsupported. Native material field shifts are
28/22/18/14/10/6, four bits each. Reserved bits are not interpreted.

Vertex metadata begins `(code_offset, 0, code_size, input_mask)`; fragment
metadata begins `(code_offset, 0, 0, code_size)`. All 47 vertex and 82 fragment
records in the owned standard resource map exactly to independently located
Cg blobs. The reader checks counts, table/header overlap, strings, relative
extents, contiguous code, profile, revision, size, parameter-free layout,
zero vertex load slot, slot count and vertex input-mask agreement. Selected
instruction streams have exact end/constant bounds. It rejects unsupported
opcodes and indirect vertex inputs. Immediate BRI targets are bounded and
reported without following them. Other control flow is rejected. Limits cap
source size, per-program bytes, material requests and report instruction bytes.

Instruction operands are based on pinned RPCS3 primary code, not inferred
from a shader's declared attribute mask. Vertex words are BE; fragment words
swap 16-bit halves. Used fragment constant operands consume the following
16 bytes as data. A declaration, static operand and an executed pixel result
are distinct facts. This tool supplies the first two.

## Exact owned evidence

USA Gold v02.00 / BLUS30491, game `e7ca89bbeb67360d`:

| Resource | Bytes | SHA256 |
| --- | ---: | --- |
| `nativePS3/system/shader.arc` | 3272907 | `15fabaa9c14c41d3bac8c85286aa6454a86455f36d1e9ebcc2012cf7a29f2f1d` |
| `system\xfshader\XfMaterialStandard` | 5115564 | `8365be586941efd7fce15151546327909c57f593cd0b222f39a44865008f7981` |

The single extraction completed in 468.77 seconds and verified member CRC32
`20562A9D`. The outer 7z size/mtime remained unchanged; no outer-content SHA
was computed or claimed. Durable receipts are under
`~/gbox-pr-audit-20261017/re-export-evidence/re5-shader-evidence-v2/`:
`source-receipt.json`, `resource-inventory.json`, `shader-reader-proof.json`
and `references/shader-reader-source-receipt.json`.

| Material word | Permutation | VS / PS | Direct UV evidence |
| --- | ---: | --- | --- |
| `30800000` | 19 | 3 / 0 | VS instruction 51 references input 8.xy; PS code byte 5264 samples input 4/TEX0 at texture unit 0 |
| `30844000` | 379 | 8 / 9 | VS instructions 51/71 reference input 8.xy; PS byte 7184 samples input 4/TEX0 at unit 0 |
| `40844000` | 380 | 9 / 9 | VS instructions 63/83 reference input 8.xy; same PS9 sample |

Each selected vertex program also contains three BRI instructions. Static
samples are not a trace of a live frame. The evidence contradicts a blanket
claim that these material variants have no UV references; it does not establish
which native buffers the game supplies at runtime or why a specific mesh renders.

The seven-pack census contains 284 nonfinite-UV vertices: Jill 3, Wesker 4,
Excella 277. All 277 affected Excella vertices have authored texture references.
Some affected secondary streams also contain nonfinite components, so choosing
an alternate stream without proving its binding is not a repair. The MOD reader
continues rejecting nonfinite UVs.

## Primary sources

RPCS3 commit `cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3`:

- [Cg binary layouts](https://github.com/RPCS3/rpcs3/blob/cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3/rpcs3/Emu/RSX/Program/CgBinaryProgram.h)
- [Vertex fields](https://github.com/RPCS3/rpcs3/blob/cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3/rpcs3/Emu/RSX/Program/RSXVertexProgram.h) and [operand positions](https://github.com/RPCS3/rpcs3/blob/cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3/rpcs3/Emu/RSX/Program/CgBinaryVertexProgram.cpp)
- [Vertex branch address](https://github.com/RPCS3/rpcs3/blob/cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3/rpcs3/Emu/RSX/Program/VertexProgramDecompiler.cpp#L349-L352)
- [Fragment fields](https://github.com/RPCS3/rpcs3/blob/cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3/rpcs3/Emu/RSX/Program/RSXFragmentProgram.h) and [operand/constant parsing](https://github.com/RPCS3/rpcs3/blob/cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3/rpcs3/Emu/RSX/Program/CgBinaryFragmentProgram.cpp)
- [HALF attribute fetch](https://github.com/RPCS3/rpcs3/blob/cbfcf1f6b5de6aed8db54b9a59a5e99b9277e2b3/rpcs3/Emu/RSX/Program/GLSLSnippets/RSXProg/RSXVertexFetch.glsl#L115-L120)

[Albam's material bitfields](https://github.com/Brachi/albam/blob/d1fda41beeae129fbb26128157511afdee4002ea/albam/engines/mtfw/structs/mod-156.ksy#L197-L204)
provide an independent check of the six material fields. The RE5 BFX envelope
mapping was derived from owned bytes and all 129 program extents, not from a
public specification. No owned game bytes are included in this repository.

## Validation and next engineering step

```sh
GBOX_RE5_EVIDENCE=/path/to/re-export-evidence python -m pytest -q \
  tests/test_re5ps3_shaders.py tests/test_native_engineering.py
```

Synthetic tests cover independent literal instructions, selector halves and
dimensions, corrupt extents/indices, branch targets, embedded constants,
unsupported opcodes, instruction-budget preflight, source preservation and
no output on failure. The optional owned test pins archive/BFX/program hashes,
all three selected pairs, exact input operands, BRI counts and fragment samples.
Run with the owned fixture for release evidence; a skipped fixture is not proof.

Next: locate an existing decrypted exact-build PS3 ELF, attest its hash and
PPC64 BE image/load layout, then inspect offline in Ghidra. Trace MOD vertex
declaration/material-binding code through the RSX attribute setup, primary and
secondary stream bases/strides, and any CPU conversion/fixup before submission.
Compare that actual assembly with the stored half-float UV bytes and the
numeric inputs recorded here. A finite replacement is justified only by that
native path or equivalent independent evidence. No game launch, installation,
save or memory write is part of this investigation.

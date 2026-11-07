# Ghidra on the Spark: built for arm64

Status: **installed and analysing** (2026-11-07). Ghidra 12.2 at `~/gBox_alt/tools/ghidra_12.2_PUBLIC`, with a decompiler
built **for this machine's own architecture**.

## Why this was not a download-and-run

Ghidra ships its decompiler as a native binary and the 12.2 release carries only `linux_x86_64` and `win_x86_64`. The
Spark is **aarch64**, so the analyser starts and then cannot decompile anything - and decompilation is the whole reason
to use it. The release also ships the decompiler's C++ source, so the fix is to build it:

```
cd Ghidra/Features/Decompiler/src/decompile/cpp
mkdir -p ghi_opt sla_opt com_opt com_dbg ghi_dbg sla_dbg test_dbg
make -j16 ARCH_TYPE= OSDIR=linux_arm_64 ghidra_opt sleigh_opt
cp ghidra_opt  ../../../../../../Ghidra/Features/Decompiler/os/linux_arm_64/decompile
cp sleigh_opt  ../../../../../../Ghidra/Features/Decompiler/os/linux_arm_64/sleigh
```

Three details that cost time and are worth keeping:

* **The Makefile says so itself.** Its own comment reads `# TODO: need to revise to support arm64/aarch64 arch`, and
  without `ARCH` set it falls through to `ARCH_TYPE=-m32`, `OSDIR=linux_x86_32`. `ARCH=x86_64` does not help; the way
  through is to blank `ARCH_TYPE` and name `OSDIR=linux_arm_64` on the command line.
* **The default goal is `grammar.cc`.** A bare `make` builds one generated parser and exits successfully, which looks
  like a clean build and produces no binaries. The targets are `ghidra_opt` and `sleigh_opt`.
* **The opt object directories are never created.** `com_opt`/`com_dbg` are made by rules; `ghi_opt`/`sla_opt` are not,
  and the build dies with `can't create ghi_opt/options.o`. Making them first is the whole fix.

Verified: `decompile` 4,187,920 B and `sleigh` 1,078,904 B in `os/linux_arm_64`, and an analysis run that reaches the
decompiler (its own warnings - "Unable to read bytes at ram:…" - only appear once decompilation is actually happening).

`support/*` also arrives non-executable from the zip; `chmod +x support/*` before `analyzeHeadless`.

## The analysis this unblocks

`main.bin` (11,716,664 B, from `GET /api/decrypt-lab/exefs?title=re4_switch`) is the NSO image with its sections
expanded: `.text 0-0x656000`, `.rodata 0x656000-0xae2000`, `.rwdata 0xae2000-0xb2d000`, `.bss 0xb2d000-0x1cc1000`. In
that image **file offset == virtual address**, so it loads as a raw binary at base 0:

```
./analyzeHeadless ~/gBox_alt/ghidra-projects re4sw \
  -import ~/gBox_alt/gbox-cache/exefs/010099A00BC1E000/main.bin \
  -processor "AARCH64:LE:64:v8A" -loader BinaryLoader -loader-baseAddr 0x0 \
  -scriptPath /tmp/ghidra_scripts -postScript TableRefs.java
```

(`AARCH64:LE:64:v8A` - not `ARM:LE:64:v8A`, which 12.2 rejects.)

## The question it is being asked

The texture join. A pack states, per image, `width, height, format, payload size` and a **pack-local** id (every pack
starts in the 40s), and the archives are `imagepackhd/NNNNNNNN.pack.fen`. Nothing in the data says which archive an id
refers to, and neither `main` nor `subsdk0` contains the strings `imagepackhd` or `pack.fen`, so the archives are
addressed by a table or a computation rather than by name.

A static scan for table-shaped data found, at file offset `0xa04c44`, a 421-entry **ascending id → dense index** map
(keys 33..1105 with gaps, values 1..421), immediately followed by more small-pair tables. `TableRefs.java` walks
`0xa04000-0xa09000` for references, names the functions that reach them, and decompiles the first few - the start of
answering what those numbers mean.

## Eighteenth run: the tooling now reaches code, and the first table was not the one (2026-11-07)

Ghidra 12.2 is installed with a decompiler **built for this machine** (see `ghidra-arm64.md`), and `main.bin` is imported
and analysed: 74 functions touch the data region that the static scan flagged.

**The first table is allocator metadata, not textures.** Disassembly around the references says so plainly:

```
0027136c  adrp x8,0xa03000
00271370  add  x8,x8,#0xfe0          ; 0xa03fe0
00271378  ldr  w2,[x8, w24, SXTW #2]  ; a u32 array indexed by w24
002758d8  adrp x8,0xa04000
002758dc  add  x8,x8,#0x8             ; 0xa04008
002758e4  ldr  x27,[x8, x19, LSL #3]  ; a u64 table, then alignment masking and a 4 KiB shift
```
`and x24,x8,x9` against a negated value and `add x0,x24,#0x1,LSL #12` is an arena/alignment computation, not a texture
lookup. So the ascending 421-entry id map at `0xa04c44` is part of the allocator's bookkeeping, and the texture-id table
is elsewhere in a 5 MB executable - which is a *search* problem now, not a blocking one.

**Two facts about the archive side that the census produced:**

* the archive names are **hexadecimal**, eight digits (`00000006`, `4400011c`, `4b000005`), with structured prefixes
  (`430000` x185, `000000` x82, `280000` x56, `3f0001` x48, `440002` x42) - so a name is not a plain index and reading
  the digits as decimal is wrong for anything containing a letter;
* the 32-bit field at offset 8 of the FEN wrapper, which earlier notes called `archive_number`, reads `0xe75b707d` for
  `00000006` and `0xe7935c0f` for `4400011c`. Both start `0xe7`, so it behaves like a **hash of the archive's resource
  name**, not an index. `re4hd_tex.tex_info` should stop calling it an archive number.

**Shape containment was tried and is not an answer.** Using the full census (1,813 archives, 54,276 surfaces), `em16`
(30 images: 13x 256x256, 5x 128x64, 3x 32x32, 3x 64x128) is fully contained by **15** archives, and `em11` (40 images)
by **none**. Shapes do not identify an archive either way.
## Nineteenth run: the decompiler works, and the `.udas` literal is indexed not referenced (2026-11-07)

**The decompiler is real.** A probe over the smallest functions returns actual C - `FUN_00000170` (252 bytes of code)
decompiles to 1,417 characters, `FUN_00000320` to 583 - so the arm64 build is sound and the empty results earlier were
those particular functions, not the tool.

**How the game names resources.** A literal scan plus an operand scan around it says something specific:

* `.udas` sits at `0x6d08ca` and `.acb` at `0x6c8e38` in `main.bin`;
* **nothing references them** - `getReferencesTo` returns zero, and a byte scan for an 8-byte pointer to either address
  finds **no pointer** anywhere in the image;
* an operand scan over `0x6d0700-0x6d0b00` finds `FUN_004f5e50` issuing `add x2,x2,#0x7ca -> 0x6d07ca` and
  `0x6d07bf`, i.e. it works in that **extension-string neighbourhood** by address, while `.udas` itself at `0x6d08ca` is
  reached by nothing at all.

So an extension is taken from a table by **index**, not by name: the loader addresses a base and adds an offset, and the
strings that no instruction names are entries in that table. That is consistent with everything the data side showed
(no `imagepackhd` or `pack.fen` string exists anywhere in the executable) and it is the shape a texture-id table would
have too.

**What the next analysis needs** rather than more scanning: decompile `FUN_004f5e50` and its neighbours properly. They
return empty C at a 180 s budget - enormous functions - so the next attempt needs either a longer budget, or the
`Decompiler` parameter set trimmed (skip the "normalize"/"paramid" passes) so a 10 KB function gives output at all.

The scripts now in `system/adapters/ghidra/scripts/` (`MemSearch`, `AddrScan`, `StrXrefs`, `Decomp`, `DecompProbe`,
`TableRefs`, `TableDisasm`) each answer one question about this binary and are reusable for the other titles.
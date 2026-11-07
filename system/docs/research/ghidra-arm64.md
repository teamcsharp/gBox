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

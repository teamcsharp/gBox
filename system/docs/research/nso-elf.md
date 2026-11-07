# NSO images: the 0x100 that changes every address

Status: **converter working** (2026-11-07). `gbox/nso_elf.py` turns a Switch `main` into an ELF that ordinary tools
open; REA accepted it on the first try (`format: elf`, `architecture: arm64`).

## The mistake this fixes

Every Switch executable is an **NSO0**: a 0x100-byte header followed by three LZ4-compressed sections. `hactool -t nso
--uncompressed=main.bin main` writes the sections out **still behind that header**, so in the output

```
file offset  =  virtual address  +  0x100
```

Two rounds of analysis treated file offset as the virtual address. The proof that it is wrong is small and decisive:

* the literal `".udas"` sits at file offset `0x6d08ca` in `main.bin`;
* Ghidra, disassembling the same file as a raw image at base 0, found an instruction computing `0x6d07ca`
  (`adrp x2, 0x6d0000` + `add x2, x2, #0x7ca`) and **no** instruction reaching `0x6d08ca`;
* `0x6d08ca - 0x100 = 0x6d07ca` - the loader was referencing it all along, one page-and-offset away.

So the earlier conclusion "nothing references `.udas`, it must be table-indexed" was an artefact of the header. The literal
is referenced; the address was wrong.

## What the converter does

`sections()` reads the NSO header and slices the image at `vaddr + 0x100`; `to_elf()` lays those slices into PT_LOAD
segments at their declared virtual addresses, with `.bss` as memory-only.

```
.text    vaddr=0x00000000 size=0x0655850
.rodata  vaddr=0x00656000 size=0x048bbcc
.rwdata  vaddr=0x00ae2000 size=0x004a738
.bss     vaddr=0x00b2c738 size=0x11938c8
```

Two header details cost time and are worth keeping: the data group is **not** laid out like text and rodata - `0x2C` is
a flag, `0x30` is the compressed size, and the memory offset / size / bss sit at `0x34` / `0x38` / `0x3C`. Reading them one
word early gives `.rwdata` a "size" of `0xae2000`, which is its own memory offset.

## Consequences for the tooling

* **Ghidra** can now be driven against a proper ELF instead of a raw image, which also removes the "base 0" assumption
  the earlier scripts made.
* **REA** opens the ELF: `{"format":"elf","kind":"executable","architecture":"arm64","sha256":"c8e8f22f..."}`.
* Its analysis providers still refuse it, for a reason that is about versions and not about the file:

```
ghidra: unsupported_version - "Install a Ghidra 12.1.x release (verified with 12.1.4), or update REA for another
Ghidra line."  install_dir=/home/ehm_eckx/gBox_alt/tools/ghidra_12.2_PUBLIC ... provider_version=12.2
        native_decompiler_path=.../os/linux_arm_64/decompile   java=/usr/lib/jvm/java-21-openjdk-arm64/bin/java
```

Note what that diagnostic says about this project's work: REA found the Ghidra install, the **arm64 decompiler built
here** (`os/linux_arm_64/decompile`) and JDK 21 - it simply pins the 12.1 line. Ghidra 12.1.4 is being installed beside
12.2 so REA can drive it, while the 12.2 + arm64 build stays for the hand-written analysis scripts.

## Reusable detail

REA advertises `GHIDRA_GAMECUBE_DOL_LANGUAGE` among its settings - it can drive an analysis of a GameCube DOL through
Ghidra, which is the format the RE4 GameCube title's executable is in. That is worth trying for the GC side, where
`re4gc_zombies` already writes models.

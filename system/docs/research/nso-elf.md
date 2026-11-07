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

## Twentieth run: the `.udas` lead was debug text (2026-11-07)

With REA driving Ghidra 12.1.4 over the ELF, the question that two rounds of scripts were circling got a clean answer:

```
xrefs to 0x6d07ca   provider: ghidra 12.1.4   evidence: ev_9197d12c8c6719804968afe65a8bd22cd1d7f4c2bb5c75a1ce7ddc40d6636ac0
normalized_result: []        <- nothing references it
```

And reading what is actually at those addresses in the corrected image explains why:

| vaddr | string |
|---|---|
| `0x6d06ca` | `.DeleteOtData() : invalid no[%d] MAX=%d.` |
| `0x6d07ca` | `.udas.[systemQuitCheck] Waiting to file ` |
| `0x6d07bf` | `Contents:/..udas.[systemQuitCheck] Waiti` |

**`.udas` is not a path extension in this binary.** It is three characters inside a debug string, sitting between the tail
of one message and the head of `[systemQuitCheck]`. Nothing references it by address because nothing builds a `.udas`
path by name; the string exists only as text.

That retires the whole "the loader names files by extension, find the loader" line - which had already cost round 33's
instruction scan (whose `add #0x7ca` computed `0x6d06ca`, the *debug* string, not the extension) and this round's xref.
The honest summary is that the string approach had no purchase on this title, and the fix is to stop looking at strings.

**Where the texture join has to go instead.** The executable contains no `imagepackhd`, no `pack.fen`, and no resource-path
format string; the archives are named in hex with structured prefixes. So the mapping is numeric, produced by the resource
manager from ids, and the way in is the **file-open path**: find the code that calls the ROM/filesystem open (the
`nn::fs`-style import or the mounted romfs entry point) and walk back to what builds the name. That is a code question
with a code answer, and the tooling for it now works:

* `nso_elf.py` gives a correct ELF (no 0x100 skew);
* REA + Ghidra 12.1.4 with an arm64 decompiler answers `xrefs`, `list_strings`, `search_strings`,
  `procedure_pseudo_code` and friends against it, with an evidence digest recorded for every answer.

The next attempt should be `list_procedures` / `search_strings` on `"bio4"` or on the mount path, then `xrefs` from the
open call - not another scan of `.rodata` for an extension.
## Twenty-first run: the texture loader exists, and its name was in the wrong case (2026-11-07)

Round 33 concluded "there is no `imagepackhd` string anywhere in the executable" from a byte scan. **That was a case
bug.** The string is there, spelled in camel case:

```
search_strings "imagepack"   -> 3 strings
  0x6c80f7  "ImagePack"
  0x6c8101  "ImagePackHD"
  0x6c8586  "__GXLoadImagePack ERROR : Create Memory Failed...[%d]byte"
xrefs 0x6c8101  ->  0x24c430, 0x24dbe0          two code addresses
```

So the loader is identified by address: **`0x24c430`** and **`0x24dbe0`** reference `ImagePackHD`. Every scan that looked
for lowercase `imagepackhd` was searching for a string that never existed in that form.

The same run shows the shape of the path convention - `BIO4\\text\\` at `0x6c0432` (0 xrefs: it is a data table entry),
`bgm/bio4str.hed`, `bgm/bio4bgm.sbb` (2 xrefs each) - so the title builds paths from parts and a table, and the
`ImagePackHD` part is the one that matters for textures.

Also worth recording because it cost a wrong conclusion: REA's answers put the find in `normalized_result`, and the first
pass parsed `result`. A search that returns three strings and is then read as zero is indistinguishable from "the string
is not there" - which is exactly the mistake that had been carried for four rounds.

**The decompile of `0x24c430` / `0x24dbe0` is running** (`/tmp/rea_imageloader.json`); a Ghidra import of this 11 MB ELF
takes 15-25 minutes on this host and competes with the emulator, so it is left to finish rather than killed. That
function is where a texture id becomes an archive - the last unknown before RE4 Switch skins.
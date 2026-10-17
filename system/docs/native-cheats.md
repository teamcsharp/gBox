# Native cheat entries and verified application

RetroArch native memory cheats use `handler=1`. The `memory_search_size` field
is an enum of log2(bits): 3 is one byte, 4 is two bytes, and 5 is four bytes.
These meanings come from RetroArch's `item_cheat` and
`cheat_manager_setup_search_meta` definitions:

- https://raw.githubusercontent.com/libretro/RetroArch/master/cheat_manager.h
- https://raw.githubusercontent.com/libretro/RetroArch/master/cheat_manager.c

The gBox decoder accepts independent constant writes into the verified 16 MiB
Dreamcast RAM mapping, preserving byte order. It validates unsigned fields and
bounds instead of wrapping invalid addresses. Sub-byte masks, repeats, rumble,
conditional and nonconstant operations remain in the emulator.

All native entries in one session have coherent ownership. Initially disabled,
disjoint constant writes can use gBox. A first write must read back correctly
before the tool reports enabled; original bytes are saved as a rollback artifact.
On enabling a conditional, unsupported operation, or overlapping write, gBox
stops its native freezes synchronously and transfers the complete enabled native
table to RetroArch in index order. Ownership stays with the emulator for that
session. Already-enabled tables start with emulator ownership. This preserves
conditions across disabled rows and conditional chains. Custom code entries are
separate; stored native aliases keep their indices. Replacing a cheat table
retires its previous freezes and refuses stale native aliases.

Search ranks meaningful whole-word overlap, so `unlock every character` finds
named unlock entries without matching unrelated uses of `all`. Results retain
the original database indexes.

The installed `Sega - Dreamcast/Soul Calibur.cht` at SHA256
`587976eec67826419b34f10c83203dfcc86a1aa97746b757141eabf2ae954c7e`
contains five named unlock entries. Each encodes a **two-byte** little-endian
constant, not a four-byte write. Their encodings are covered against that actual
file. This does not prove those addresses apply to every release or that every
character is unlocked. The exact-game live unlock and complete roster request
remain open until native acceptance evidence exists.

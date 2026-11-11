# Round 234: CP9 - the save card layout is cracked; the files extract, the payload is encrypted

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (sixth round), so this is the offline half of the PM document.

## The card layout, measured

The PM notes said the PSO directory entries sit at 0x20C0 "with first-block 0xFFFF (layout not yet cracked)". That is now read off the
bytes:

```
directory entries   start at 0x20C0, 0x40 bytes each   (backup copy at 0x40C0 = +0x2000)
entry +0x00         u32 game code  "GPOE"
entry +0x04         u16 company    "8P"
entry +0x06         u8 banner format, u8 icon count
entry +0x08         32-byte name   ("PSO_SYSTEM", "PSO_CHARACTER", ...)
entry +0x36         u16 first block, BIG endian
entry +0x38         u16 block count, BIG endian
```

The first/block fields are **big-endian**, and the name starts at **+0x08**, not +0x06 - which is why the earlier parser read zeros and
0xFFFF everywhere.

## What that yields

```
directory entries: 5
  PSO_SYSTEM       block  14 x   3    24576 bytes -> PSO_SYSTEM.bin
  PSO_CHARACTER    block  17 x  11    90112 bytes -> PSO_CHARACTER.bin
  PSO_GUILDCARD    block  28 x  10    81920 bytes -> PSO_GUILDCARD.bin
  bh4_system       block   5 x   1     8192 bytes -> bh4_system.bin
  sc2_0.dat        block   6 x   4    32768 bytes -> sc2_0.dat.bin
```

All three PSO save files are extracted to `D:\gBox\pso-ds\memcard\`. That is the CP9 file-level deliverable: the card is readable and its
contents are addressable.

## The payload is encrypted

`PSO_CHARACTER.bin` begins with plain text -

```
PSO EPISODE I & II Plus      CHARACTER_FILE
```

- and everything after the header is high-entropy: **2,257** printable runs and not one of them is a word, the character's name is absent
("BQF" from the old session is gone, and no name appears at all), and there are **zero** runs of technique-sized values in the whole 90 KB.
The payload is encrypted (PSO encrypts its GameCube saves per block), so reading character fields requires the cipher.

## Why this still matters for the other work

Two things were waiting on the save:

* the character's technique array, which would confirm the in-RAM layout at +0x2E7 by an independent route;
* a level/stat record to anchor the character fields without a live game.

Both now need the decryption step first, which is a bounded job: PSO's GC save cipher is a per-block transformation with a seed in the
header, and the plain-text header gives a known-plaintext test (the same header bytes reappear in every PSO save).

## Files

* `memcard_parse2.py` - the working parser (directory at 0x20C0, BE block fields) and extractor
* `char_anchor.py`, `char_text.py` - the anchors that proved the payload is encrypted
* `memcard_find.py` - the search that located the real directory offset

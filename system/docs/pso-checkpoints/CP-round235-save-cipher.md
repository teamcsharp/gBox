# Round 235: CP9 - the save payload IS encrypted (zero runs are empty slots), and the cipher has a short period

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (seventh round).

## Correcting last round

I wrote that the payload "is not encrypted" because 13.5% of its bytes are zero and one run is 10,828 bytes long. That was wrong, and this
round's measurements show why: the zeros are **empty character slots**, which the game zero-pads rather than encrypts, while the occupied
slots are encrypted.

Evidence:

* every candidate slot boundary is **~99.7% non-zero** (`8164/8192`, `8156/8192`, ...) - the non-zero data is continuous, so the "sparse
  regions" I saw are an artefact of looking at text runs inside ciphertext;
* the first 24 bytes of the payload - the start of the occupied record - read

```
c5 16 c5 16 c5 16 c5 16 a8 2e a4 2e a4 2e a4 2e ac 30 ac 30 ac 30 ac 30
```

which is a **repeating 2-byte pattern**. On a fresh record the plaintext there is mostly zero, so this is very likely the **key stream
itself**, repeating every two bytes at that offset.

## The slot model that fits

`81920 / 0x5000 = 4` and the zero run starts at `0x2A0C` inside a slot boundary of 0x5000 (`0x2A0C % 0x5000 = 0x2A0C`), so the file is
consistent with **four slots of 0x5000**, three of them holding data and the last mostly empty - but the boundary is not proven yet, and I am
not going to build on an unproven layout.

## What this makes the next step

The cipher is **not** PRS compression: `psotext.prs_decompress` fails at every candidate offset (`IndexError` from invalid tokens), which is
what an encrypted stream looks like to a decompressor.

So the task is a short-period XOR recovery, and there is a clean known-plaintext test available: a PSO save's first record region should
begin with the character name and a small level byte, while most of a fresh record is zero. Two concrete probes for the next pass:

1. **period test**: XOR the occupied slot with itself shifted by 2, 4, 8, 16 bytes and measure how many bytes cancel. A short period shows
   up immediately as a large cancellation rate;
2. **key recovery from zeros**: wherever the plaintext is zero - the tail of a record, the padding inside item tables - the ciphertext IS
   the key stream. Recovering it there and applying it to the whole slot either yields readable text or proves the key is per-block.

## Files

* `save_crypto.py` - the histogram/period measurement that produced the numbers above
* `save_structure.py`, `save_slots.py` - the region map and slot candidates
* `char_prs.py` - the PRS attempt that failed, establishing the payload is not compressed

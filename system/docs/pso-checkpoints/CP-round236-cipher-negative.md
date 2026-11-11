# Round 236: CP9 - the two simplest save-cipher hypotheses are eliminated by measurement

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (eighth round).

## Probe 1: repeating key - NEGATIVE

XORing the occupied slot against itself at seven shifts:

```
shift   1:     74 equal bytes (0.4%)
shift   2:    118 equal bytes (0.6%)
shift   4:    101 equal bytes (0.5%)
shift   8:     77 equal bytes (0.4%)
shift  16:     90 equal bytes (0.4%)
shift  32:    109 equal bytes (0.5%)
shift 256:     84 equal bytes (0.4%)
```

0.4-0.6% agreement at every shift is chance. **There is no repeating XOR key.** Last round's guess that the opening `c5 16 c5 16 ...` was "the
key stream repeating every two bytes" is therefore wrong - it is a data pattern in whatever transforms this, not a reused key.

## Probe 2: PSO's documented LCG XOR - NEGATIVE

Tried the usual generator (`key = key * 0x41C64E6D + 0x3039`, XOR the high byte) seeded from every plausible header word, both byte orders:

```
best: run 12 printable, 37.7% printable, seed 0xc516c516
control (known-plaintext file header): run 23, 59.4% printable
```

37.7% printable is what **random bytes** score, and the known-plaintext control scores 59.4% - so the scorer discriminates and no attempt
reaches even the control level. **Not this LCG either.**

## What that leaves, and why I am stopping the blind search

The payload is either a **stream cipher keyed per block** (with the seed not in the plaintext header) or **compressed with a scheme other
than PRS** (PRS already failed with invalid tokens at every offset). Both require either the cipher's specification or a much larger
known-plaintext set than one save file offers.

## The pivot that matters more

The card is a **backup**; the authoritative copy of the character is the **live player struct** when the game loads it. That is why the
practical route to every field (techniques, stats, items) is the RAM write path that already works - `write_memory` with a rollback
receipt - and not the save file.

Two concrete facts recorded this round that the save work did establish:

* the card's directory and file layout (round 234: entries at 0x20C0, name at +0x08, big-endian block fields) so the files can be pulled
  and inspected;
* the current card's **PSO_CHARACTER payload contains no plaintext character name at all**, which means the character on the card is either
  encrypted as shown or the current one was not written to this card - worth flagging to the operator, because a save that silently did not
  happen is worse than a cipher.

## Files

* `cipher_probe.py` - period and LCG probes with a printable-run scorer and a known-plaintext control

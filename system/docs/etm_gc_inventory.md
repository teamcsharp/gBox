# Enter the Matrix GameCube Disc 2 archive inventory

`python -m gbox.etm_gc_inventory DISC.gcz --json inventory.json` reads the owned
GMXE70 Disc 2 revision 0 build without modifying the source. The identity check
requires its main.dol SHA256 `4348709361c1c5eae482bd87f5df85d96b82125fd5e3533ed6c1332434b7b58f`
and exact DFU part sizes. It bounds the executable read before following the DOL
section extents. This is an executable/layout identity, not a hash of every disc byte.

The archive has a big-endian directory with 5,874 entries, seeds (22313, 2067, 674),
three duplicate hashes, and data base 0x17000. `wad2.dfu` is 932,722,688 bytes;
`wad2_b.dfu` is empty. The shared reader retains its existing little-endian PS2
defaults. It rejects invalid byte orders, malformed part lists, short reads and
out-of-part ranges, and bounds decompression to the entry's declared output size.
Inventory reads also cap the two header tables before reading their contents.

The GameCube FST adapter declares byte offsets. Shared `image_patches` therefore
does not multiply those offsets by the PS2 sector size. Tests apply replacement
plans to synthetic archive copies in both byte orders; this does not establish
a native GameCube character writer. This CLI never writes archive patches.

Owned-source checks recover 288 model-path records and 387 named actors from
404 actor records. The exact header table hashes are:

| Table | Size | SHA256 |
| --- | ---: | --- |
| ActorHeadersV4.Bin | 38,784 | e83c834e940298f27ac7f5dfab73d4bf7cb84a2e9e2a5ee4edf92288bdbf8977 |
| ModelHeadersV4.Bin | 23,040 | 41ae2707a12e3f8de808c76b265ed64aabf6f46c8c67ccc520bb1987b17c663e |

The existing hash resolves these table names, but none of the listed `.dcn`
model paths currently resolves as an archive entry. The remaining work is to
trace the exact GameCube lookup/storage mapping, extract and validate a native
model, implement replacement, and verify the rebuilt game. A different hash is
one possible explanation, not an established conclusion. PS2 skeleton or texture
details are not evidence of the GameCube model layout.

Request #2017 remains unfinished. The report explicitly exposes
`character_extraction=false`, `character_replacement=false`, and
`gameplay_verified=false`. No runtime adapter, worker routing, or native gameplay
policy changes are included.

Original inventory contribution: PR #519, commit
`e7ef55d570abdc785aeace371f1acf86195a107e`, retained through a normal merge.
The original request records Hermes / DeepSeek v4 Pro; no Spark2 device credit is inferred.

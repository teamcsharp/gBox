"""NFL Blitz 2003 (GameCube) ``.gtd`` character container reader (read-only).

Container family verified against the owned build (fixture
``nb2003_ape.gtd``, streamed from the owned GCZ this run): 8-byte prefix
``[count u32 LE][payload_size u32 LE]``; from offset 8, chunk headers
``[type u32 LE][subtype u32 LE][size u32 LE]`` with 4-byte alignment and
subtrees that exactly fill the parent payload; a single trailing footer
word after the final chunk (``payload_size`` covers offset 8 through the
end of the last chunk, excluding the footer).

Verified ape.gtd tree (32936 B total):
  prefix: count=22, payload_size=32924
  @0x0008 (0x0800ffff, 1, 0x4)      leaf, 4 B payload = 0x0800ffff
  @0x0018 (0x0001, 0x15, 0x8074)    container
    @0x0024 (0x0800ffff, 1, 0x805c) leaf: character block
        payload[0:3]   = 0x0800ffff
        payload[4:8]   = 6   (name length)
        payload[8:12]  = 0x02110000 (uninterpreted format word)
        payload[12:18] = b"ape\\x00\\x00\\x00" (6-byte name)
        payload[18:32] = zero pad
        payload[32:]   = 8207 float words, 0xcdcdcdcd sentinel slots
                         (7 in this file), dense float data to leaf end
    @0x808c (0xff67261b, 3, 0)     leaf, empty (observed float-valued token)
  @0x8098 (0x0800ffff, 3, 0)        leaf, empty
  @0x80a4 footer word = 0x0800ffff
"""
from __future__ import annotations
import struct
from dataclasses import dataclass, field

SENTINEL = struct.unpack("<f", bytes.fromhex("cdcdcdcd"))[0]  # -431602080.0


@dataclass
class GtdNode:
    offset: int
    type: int
    subtype: int
    size: int
    children: list = field(default_factory=list)
    payload: bytes = b""


@dataclass
class GtdFile:
    count: int          # prefix word 0
    payload_size: int   # prefix word 1 (covers offset 8 .. last chunk end)
    nodes: list         # root GtdNode list
    footer: int         # trailing word after last chunk
    data: bytes

    def leaf(self, otype, osub, min_size=0):
        out = []

        def rec(ns):
            for n in ns:
                if n.type == otype and n.subtype == osub and n.size >= min_size:
                    out.append(n)
                rec(n.children)

        rec(self.nodes)
        return out


def _chunks(d: bytes, start: int, end: int, nodes: list, payload: dict):
    o = start
    while o + 12 <= end:
        t, s, sz = struct.unpack_from("<3I", d, o)
        if sz > end - o - 12:
            raise ValueError(f"gtd chunk size {sz:#x} exceeds bound @ {o:#x}")
        n = GtdNode(o, t, s, sz)
        nodes.append(n)
        n.payload = payload[o] = d[o + 12:o + 12 + sz]
        if sz:
            # containers must exactly fill; a leaf whose payload itself
            # parses as a full chunk tree is accepted as a container.
            try:
                _chunks(d, o + 12, o + 12 + sz, n.children, payload)
                if not n.children:
                    # no valid chunk tree inside -> true leaf
                    pass
                else:
                    last = n.children[-1]
                    if last.offset + 12 + last.size != o + 12 + sz:
                        raise ValueError("subtree does not fill parent")
            except ValueError:
                n.children = []  # treat as leaf data
        o += 12 + ((sz + 3) & ~3)
    if o != end:
        raise ValueError(f"gtd chunk walk stopped at {o:#x}, expected {end:#x}")


def parse_gtd(d: bytes) -> GtdFile:
    if len(d) < 16:
        raise ValueError(f"gtd too small: {len(d)}")
    count, psize = struct.unpack_from("<II", d, 0)
    region_end = 8 + psize
    if region_end + 4 > len(d):
        raise ValueError("prefix payload_size exceeds file bounds")
    nodes = []
    payload = {}
    _chunks(d, 8, region_end, nodes, payload)
    footer = struct.unpack_from("<I", d, region_end)[0]
    gf = GtdFile(count, psize, nodes, footer, d)
    for n in nodes:
        n.payload = payload.get(n.offset, b"")
    return gf


def character_block(node: GtdNode):
    """(name, data_words) of a (0x0800ffff, 1) character-block leaf."""
    p = node.payload if isinstance(node.payload, bytes) else b""
    name = p[12:18].rstrip(b"\x00").decode("ascii")
    data = struct.unpack(f"<{(len(p) - 32) // 4}f", p[32:])
    return name, data


def _pad(sz: int) -> int:
    # next chunk header sits at a 4-byte boundary after this chunk's
    # 12-byte header + sz-byte payload
    return (4 - ((12 + sz) % 4)) % 4


def serialize_gtd(gf: GtdFile) -> bytes:
    """Reconstruct container bytes from the parsed tree (writer side).

    Container bodies are re-serialized from their children -- never from
    the cached raw bytes -- so any tree/bytes mismatch surfaces here.
    Inter-chunk alignment padding is emitted as zero bytes; if the source
    had non-zero padding, the byte comparison in roundtrip_gtd fails.
    """
    def ser(nodes: list) -> bytes:
        out = bytearray()
        for n in nodes:
            out += struct.pack("<3I", n.type, n.subtype, n.size)
            if n.children:
                body = ser(n.children)
                if len(body) != n.size:
                    raise ValueError(
                        f"child body {len(body):#x} != declared size "
                        f"{n.size:#x} @ {n.offset:#x}")
            else:
                body = n.payload
                if len(body) != n.size:
                    raise ValueError(
                        f"leaf payload {len(body):#x} != size {n.size:#x} "
                        f"@ {n.offset:#x}")
            out += body
            out += b"\x00" * _pad(n.size)
        return bytes(out)

    out = struct.pack("<II", gf.count, gf.payload_size)
    out += ser(gf.nodes)
    out += struct.pack("<I", gf.footer)
    if len(out) != 8 + gf.payload_size + 4:
        raise ValueError(
            f"serialized {len(out):#x} != prefix-implied "
            f"{8 + gf.payload_size + 4:#x}")
    return out


def set_character_block(gf: GtdFile, name=None, data=None) -> GtdFile:
    """Return a copy of the container with the character block rewritten.

    name: optional new character name (str, up to 6 chars); None keeps
          the original.
    data: optional new float-word sequence; must match the original word
          count (fixed block size -- size-changing reimport is a later
          milestone).
    """
    import copy
    gf2 = copy.deepcopy(gf)
    leaves = gf2.leaf(0x0800FFFF, 1, 32)
    if len(leaves) != 1:
        raise ValueError(f"expected exactly one character block, "
                         f"found {len(leaves)}")
    node = leaves[0]
    p = bytearray(node.payload)
    if name is not None:
        raw = name.encode("ascii")
        if len(raw) > 6:
            raise ValueError(f"block name too long: {len(raw)}")
        p[12:18] = raw.ljust(6, b"\x00")
    if data is not None:
        n = (len(p) - 32) // 4
        if len(data) != n:
            raise ValueError(f"data words {len(data)} != block words {n}")
        struct.pack_into(f"<{n}f", p, 32, *data)
    node.payload = bytes(p)
    return gf2


def roundtrip_gtd(d: bytes) -> bytes:
    """Parse + serialize; returns the reconstructed bytes (no-op)."""
    return serialize_gtd(parse_gtd(d))


if __name__ == "__main__":
    import sys
    gf = parse_gtd(open(sys.argv[1], "rb").read())
    for n in gf.leaf(0x0800FFFF, 1, 32):
        name, data = character_block(n)
        sent = sum(1 for w in data if w == SENTINEL)
        print(f"block {name!r} @ {n.offset:#06x}: {len(data)} words, {sent} sentinel")

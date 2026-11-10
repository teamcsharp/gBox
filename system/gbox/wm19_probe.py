"""WWE WrestleMania XIX (GameCube, GW9E78) read-only probes for model/wrestler/NNN_V.{tex,ymg}.

Findings are from the owned expanded disc (sha256 b84472a4...e8f0). ``.tex``: LE u32 count, 0x10 pad, then count x 0x20 index
entries [name[16], tag 'tpl\\0', u8 w, u8 h, u16 0, u32 LE offset, u32 0]; each blob starts 0x20af30 / 1 / 0xc / 0x14 (GX image
header, 0x40 bytes) and the blobs tile the file back to back. ``.ymg``: 'YOBJ' + BE words; word1 = payload length for the
wrestler-model layout (file is 184 B longer for 000_0) - other files use a nested layout (word1==0x10); not decoded yet.
Pixel formats / geometry are NOT decoded: this is an index/header probe, not a reader.
"""
import struct

TEX_BLOB_MAGIC = 0x0020AF30


def parse_tex(b: bytes) -> list[dict]:
    n = struct.unpack_from("<I", b, 0)[0]
    if not 0 < n < 512 or 0x10 + n * 0x20 > len(b):
        raise ValueError("not a wrestler .tex index")
    ents = []
    for i in range(n):
        o = 0x10 + i * 0x20
        name = b[o:o + 16].split(b"\0")[0].decode("latin-1")
        tag = b[o + 16:o + 20].rstrip(b"\0").decode("latin-1")
        w, h, _pad, off = struct.unpack_from("<BBHI", b, o + 20)
        ents.append({"name": name, "tag": tag, "w": w, "h": h, "off": off})
    for i, e in enumerate(ents):
        e["end"] = ents[i + 1]["off"] if i + 1 < n else len(b)
        if not (0 < e["off"] < e["end"] <= len(b)) or struct.unpack_from(">I", b, e["off"])[0] != TEX_BLOB_MAGIC:
            raise ValueError("bad tex blob %d" % i)
        e["size"] = e["end"] - e["off"]
    return ents


def parse_ymg_header(b: bytes) -> dict:
    if b[:4] != b"YOBJ":
        raise ValueError("not YOBJ")
    w = struct.unpack_from(">15I", b, 4)
    return {"words": w, "layout": "flat" if w[0] > 0x10 else "nested", "payload_len": w[0], "extra": len(b) - w[0]}

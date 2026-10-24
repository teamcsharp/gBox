"""Build NitroFS member manifest for an owned FF4 DS ROM (read-only)."""
import hashlib, json, struct, sys, collections
from gbox.formats.nitro import NitroROM
from gbox.formats.lz import lz10_decompress

def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()

def build(path, hash_prefixes=("OBJ/PC", "MOTION")):
    data = open(path, "rb").read()
    rom = NitroROM(data)
    title = data[:12].rstrip(b"\0").decode("ascii", "replace")
    code = data[12:16].decode("ascii", "replace")
    arm9_off, _, _, arm9_size = struct.unpack_from("<4I", data, 0x20)
    members = []
    for p in sorted(rom.paths()):
        raw = rom.raw(p)
        e = {"path": p, "size": len(raw), "ext": p.rsplit(".", 1)[-1].lower() if "." in p else ""}
        if any(p.lstrip("/").startswith(x) for x in hash_prefixes):
            e["sha256"] = hashlib.sha256(raw).hexdigest()
            e["magic"] = raw[:4].hex()
            if p.endswith(".lz") and raw[:1] == b"\x10":
                d = lz10_decompress(raw)
                e["lz10_size"] = int.from_bytes(raw[1:4], "little")
                e["decomp_size"] = len(d)
                e["decomp_sha256"] = hashlib.sha256(d).hexdigest()
                e["decomp_magic"] = d[:4].decode("ascii", "replace")
                if d[:4] in (b"NMDP", b"NAMP", b"NCAP"):
                    e["body_size"] = int.from_bytes(d[0x18:0x1c], "little")
                    e["section_type"] = int.from_bytes(d[0x14:0x18], "little")
                    e["header_ok"] = e["body_size"] + 0x30 == len(d)
        members.append(e)
    ext = collections.Counter(m["ext"] for m in members)
    return {"source_file": path.rsplit("/", 1)[-1], "source_size": len(data),
            "source_sha256": sha_file(path), "platform": "nds", "container": "NitroFS",
            "byte_order": "little", "offset_base": "file start (FAT offsets absolute)",
            "game_title": title, "game_code": code,
            "arm9": {"rom_offset": arm9_off, "size": arm9_size},
            "file_count": len(members), "ext_counts": dict(ext), "members": members}

if __name__ == "__main__":
    out = build(sys.argv[1])
    json.dump(out, open(sys.argv[2], "w"), indent=1)
    print(out["source_sha256"], out["file_count"], out["ext_counts"])

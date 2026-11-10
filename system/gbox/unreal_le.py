"""Little-endian Unreal (v102 / Midway-licensee 33) package reader for the GameCube
Splinter Cell - Pandora Tomorrow build (.usx/.ukx members, tag 0x9E2A83C1 stored LE).

Verified on dataGCN/Staticmeshes/EMeshCharacter.usx: the packages are NOT UE3 cooked
packages.  They are classic Unreal-engine (UE1/UE2-style) packages: package version
0x66 (102), licensee 0x21, compact-index (FCompactIndex) object references, 1-byte
length-prefixed names, and a variable-length export record.

Summary header (all little-endian int32):
  0x00 tag  0x04 version(lo16)|licensee(hi16)  0x08 package flags
  0x0C name_count  0x10 name_offset  0x14 export_count  0x18 export_offset
  0x1C import_count  0x20 import_offset  0x24 marker 0x0FF0ADDE ...
Name entry : u8 length (includes NUL), ASCII bytes, int32 object flags.
Import rec : u8 class_package, u8 class_name, int32 outer, u8 name  (name idx, 7 bytes;
             indices < 0x40 so single-byte compact indices).
Export rec : ci class, ci super, int32 outer(0 = root, n = export n-1), ci name,
             int32 flags, ci size, ci offset (offset only when size > 0).
Compact index: first byte b: sign=b&0x80, value=b&0x3F, more=b&0x40; each further byte
             contributes (c&0x7F)<<shift (shift starts 6, +7), more=c&0x80.
Class refs <0 mean import[-ref-1]; >0 export[ref-1]; 0 = none.
"""
from __future__ import annotations

import struct

TAG_LE = b"\xc1\x83\x2a\x9e"


def read_ci(d: bytes, p: int) -> tuple[int, int]:
    b = d[p]
    p += 1
    neg = b & 0x80
    v = b & 0x3F
    if b & 0x40:
        sh = 6
        while True:
            c = d[p]
            p += 1
            v |= (c & 0x7F) << sh
            sh += 7
            if not c & 0x80:
                break
    return (-v if neg else v), p


def write_ci(v: int) -> bytes:
    neg = v < 0
    v = abs(v)
    first = (0x80 if neg else 0) | (v & 0x3F)
    v >>= 6
    if not v:
        return bytes([first])
    out = [first | 0x40]
    while True:
        c = v & 0x7F
        v >>= 7
        if v:
            out.append(c | 0x80)
        else:
            out.append(c)
            break
    return bytes(out)


def parse_package(d: bytes) -> dict:
    if d[:4] != TAG_LE:
        raise ValueError("not a little-endian Unreal package")
    version = struct.unpack_from("<I", d, 4)[0]
    pflags = struct.unpack_from("<I", d, 8)[0]
    n_names, name_off, n_exp, exp_off, n_imp, imp_off = struct.unpack_from("<6I", d, 0x0C)
    for lab, v in (("names", n_names), ("exports", n_exp), ("imports", n_imp)):
        if v > 100000:
            raise ValueError(f"{lab} count implausible: {v}")
    for lab, v in (("name", name_off), ("export", exp_off), ("import", imp_off)):
        if not 0 < v < len(d):
            raise ValueError(f"{lab} offset out of range: {v}")
    names = []
    p = name_off
    for _ in range(n_names):
        ln = d[p]
        names.append(d[p + 1:p + 1 + ln].rstrip(b"\0").decode("latin1"))
        p += 1 + ln + 4
    names_end = p

    def nm(i):
        return names[i] if 0 <= i < len(names) else f"?{i}"

    imports = []
    p = imp_off
    for _ in range(n_imp):
        cpk, cls, outer, name = struct.unpack_from("<BBiB", d, p)
        imports.append({"class_package": nm(cpk), "class": nm(cls), "outer": outer, "name": nm(name)})
        p += 7
    exports = []
    p = exp_off
    for i in range(n_exp):
        cls, p = read_ci(d, p)
        sup, p = read_ci(d, p)
        outer = struct.unpack_from("<i", d, p)[0]
        p += 4
        name, p = read_ci(d, p)
        flags = struct.unpack_from("<I", d, p)[0]
        p += 4
        size, p = read_ci(d, p)
        off = 0
        if size > 0:
            off, p = read_ci(d, p)
        if cls < 0 and -cls - 1 < len(imports):
            cname = imports[-cls - 1]["name"]
        elif cls > 0:
            cname = f"export#{cls - 1}"
        else:
            cname = "Class"
        exports.append({"index": i, "class": cname, "super": sup, "outer": outer, "name": nm(name),
                        "flags": flags, "size": size, "offset": off})
    return {"version": version & 0xFFFF, "licensee": version >> 16, "packageFlags": pflags,
            "names": names, "names_end": names_end, "imports": imports, "exports": exports,
            "export_table_end": p, "size": len(d)}


def group_of(pkg: dict, e: dict) -> str:
    o = e["outer"]
    return pkg["exports"][o - 1]["name"] if o > 0 else ""


def export_data(pkg: dict, d: bytes, i: int) -> bytes:
    e = pkg["exports"][i]
    if e["offset"] + e["size"] > len(d):
        raise ValueError("export data out of range")
    return d[e["offset"]:e["offset"] + e["size"]]


def check_chain(pkg: dict) -> bool:
    """Exports with data are laid out back to back from names_end; a real parse must chain."""
    pos = None
    for e in sorted((e for e in pkg["exports"] if e["size"] > 0), key=lambda e: e["offset"]):
        if pos is not None and e["offset"] != pos:
            return False
        pos = e["offset"] + e["size"]
    return True


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    ap.add_argument("--dump", help="export index to write next to --out")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    d = Path(a.package).read_bytes()
    pkg = parse_package(d)
    summ = {k: pkg[k] for k in ("version", "licensee", "size", "names_end", "export_table_end")}
    summ["n_exports"] = len(pkg["exports"])
    summ["chain_ok"] = check_chain(pkg)
    print(json.dumps(summ))
    for e in pkg["exports"]:
        if e["size"] > 1:
            print(e["index"], group_of(pkg, e), e["name"], e["class"], e["offset"], e["size"])
    if a.dump is not None and a.out:
        Path(a.out).write_bytes(export_data(pkg, d, int(a.dump)))


if __name__ == "__main__":
    main()

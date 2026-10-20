import struct
from collections import Counter
from pathlib import Path

import pytest

from gbox import nightfire_inventory as nf

ISO = Path.home() / "gBox_alt/gbox-cache" / "modbase" / "744ba3bc797403bf" / "007 - Nightfire (USA).iso"


def _pack(entries, table=None):
    tab = b"".join(struct.pack("<IB", len(p), t) + n.encode() + b"\0" for t, n, p in entries)
    size = (len(tab) + 31) // 32 * 32 if table is None else table
    return struct.pack(">II", size, len(entries)) + bytes(24) + tab.ljust(size, b"\0") + b"".join(p for _, _, p in entries)


def test_pack_index_locates_every_payload():
    skin = struct.pack("<I", 0x040004CA) + bytes(28)
    data = _pack([(4, "040004ca", skin), (7, "06000087", b"\x1c\x00\x01\x00" + bytes(12)),
                  (13, "GC EXTRA STATIC", b"\xfa" * 32)])
    idx = nf.pack_index(data)
    assert idx["count"] == 3 and idx["table"] % 32 == 0
    a, b, c = idx["entries"]
    assert (a["type"], a["hash"], a["self_hash"], a["offset"]) == (4, "0x040004ca", True, 0x20 + idx["table"])
    assert b["hash"] == "0x06000087" and b["self_hash"] is False
    assert "hash" not in c and c["name"] == "GC EXTRA STATIC"
    assert c["offset"] + c["size"] == len(data)
    assert data[a["offset"]:a["offset"] + a["size"]] == skin


def test_pack_index_rejects_bad_tiling_and_short_tables():
    data = _pack([(4, "04000636", struct.pack("<I", 0x04000636) + bytes(12))])
    with pytest.raises(ValueError):
        nf.pack_index(data[:-1])
    with pytest.raises(ValueError):
        nf.pack_index(data + bytes(32))
    with pytest.raises(ValueError):
        nf.pack_index(_pack([(4, "04000636", bytes(16)), (4, "04000637", bytes(16))], table=16))
    assert nf.pack_index(bytes(32)) == {"table": 0, "count": 0, "entries": []}


def test_edl_header_fields_and_size_check():
    data = b"EDL\x81" + struct.pack(">II", 24, 1234) + struct.pack("<I", 0x3DB619CD) + bytes(8)
    assert nf.edl_header(data) == {"flags": 0x81, "size": 24, "unpacked": 1234, "stamp": 0x3DB619CD}
    with pytest.raises(ValueError):
        nf.edl_header(data + b"\0")
    with pytest.raises(ValueError):
        nf.edl_header(b"EDB" + data[3:])


def test_bigf_index_names_and_bounds():
    names = [b"data\\actors\\models\\c_bond.bin", b"t_bond.tex"]
    body = [b"A" * 10, b"B" * 6]
    header = 16 + sum(8 + len(n) + 1 for n in names)
    rows, off = b"", header
    for n, p in zip(names, body):
        rows += struct.pack(">II", off, len(p)) + n + b"\0"
        off += len(p)
    data = b"BIGF" + struct.pack("<I", off) + struct.pack(">II", len(names), header) + rows + b"".join(body)
    idx = nf.bigf_index(data)
    assert idx["size_matches"] and idx["count"] == 2
    assert [e["name"] for e in idx["entries"]] == [n.decode() for n in names]
    assert data[idx["entries"][1]["offset"]:][:6] == b"B" * 6
    with pytest.raises(ValueError):
        nf.bigf_index(data[:-1])


def test_common_map_pairs_levels_with_shared_packs():
    words = [0x07000005, 0x07E00000, 0x07000006, 0x07E00001, 0x12345678]
    m = nf.common_map(struct.pack(f">{len(words)}I", *words))
    assert m["pairs"] == [["0x07000005", "0x07e00000"], ["0x07000006", "0x07e00001"]]
    assert m["unpaired"] == ["0x12345678"] and m["words"] == 5


def test_driving_actor_assets_groups_models_by_archive():
    bigf = {"driving/mis01.viv": {"entries": [{"name": "data\\actors\\models\\c_bondc1.dat"},
                                              {"name": "data\\actors\\models\\c_bondc1.rel"},
                                              {"name": "data\\actors\\anims\\ped.dat"},
                                              {"name": "data\\sim\\attrib\\attrib.dir"}]},
            "driving/race.viv": {"entries": [{"name": "data\\actors\\models\\C_BONDC1.dat"},
                                             {"name": "data\\actors\\textures\\t_bond.tex"}]}}
    a = nf.driving_actor_assets(bigf)
    assert a["models"] == {"c_bondc1": ["driving/mis01.viv", "driving/race.viv"]}
    assert a["anims"] == {"ped": ["driving/mis01.viv"]} and a["textures"] == {"t_bond": ["driving/race.viv"]}


def test_disc_identity_uses_magic_words_and_bi2_region():
    head, bi2 = bytearray(0x440), bytearray(0x2000)
    head[:6] = b"GO7E69"
    head[0x1C:0x20] = struct.pack(">I", nf.GC_MAGIC)
    head[0x20:0x40] = b"James Bond 007(tm): NightFire(tm)"[:32]
    bi2[0x18:0x1C] = struct.pack(">I", 1)
    ident = nf.disc_identity(bytes(head), bytes(bi2))
    assert (ident["disc_id"], ident["maker"], ident["version"]) == ("GO7E69", "69", 0)
    assert (ident["platform"], ident["region"]) == ("gamecube", "NTSC-U")
    head[0x18:0x1C] = struct.pack(">I", nf.WII_MAGIC)
    assert nf.disc_identity(bytes(head), bytes(bi2))["platform"] == "wii"


def _elf(rodata, addr=0x801A0260, entry=0x80007100):
    shstr = b"\0.rodata\0.shstrtab\0"
    ro_off, str_off = 0x34, 0x34 + len(rodata)
    shoff = (str_off + len(shstr) + 3) // 4 * 4
    hdr = bytearray(0x34)
    hdr[:6] = b"\x7fELF\x01\x02"
    struct.pack_into(">HHI", hdr, 0x10, 2, 20, 1)
    struct.pack_into(">III", hdr, 0x18, entry, 0, shoff)
    struct.pack_into(">HHHHHH", hdr, 0x28, 0x34, 0, 0, 40, 3, 2)
    sh = bytes(40) + struct.pack(">10I", 1, 1, 2, addr, ro_off, len(rodata), 0, 0, 4, 0)
    sh += struct.pack(">10I", 9, 3, 0, 0, str_off, len(shstr), 0, 0, 1, 0)
    return (bytes(hdr) + rodata + shstr).ljust(shoff, b"\0") + sh


def test_elf_strings_report_virtual_addresses():
    ro = b"\0\0\0\0Skin 0x%x not loaded\0Meet Mayhew\0unrelated text\0"
    elf = _elf(ro)
    info = nf.elf_info(elf)
    assert info["entry"] == "0x80007100" and info["symtab"] is False
    assert [s["name"] for s in info["sections"]] == [".rodata", ".shstrtab"]
    hits = {s["text"]: s["vaddr"] for s in nf.elf_strings(elf)}
    assert hits == {"Skin 0x%x not loaded": f"{0x801A0260 + 4:#x}", "Meet Mayhew": f"{0x801A0260 + 25:#x}"}
    with pytest.raises(ValueError):
        nf.elf_sections(b"\x7fELF\x02\x01" + bytes(64))


@pytest.mark.skipif(not ISO.exists() or ISO.stat().st_size != 1459978240, reason="owned Nightfire ISO not unpacked")
def test_owned_disc_layout():
    from gbox.gcdisc import GCDisc

    disc = GCDisc(ISO)
    ident = nf.disc_identity(disc._r(0, 0x440), disc._r(0x440, 0x2000))
    assert (ident["disc_id"], ident["version"], ident["platform"], ident["region"]) == ("GO7E69", 0, "gamecube", "NTSC-U")
    assert len(disc.files) == 315
    pk = nf.pack_index(disc.read("gc/07800001.bin"))
    assert Counter(e["type"] for e in pk["entries"]) == Counter({4: 7, 7: 1})
    assert all(e["self_hash"] for e in pk["entries"] if e["type"] == 4)
    assert nf.edl_header(disc.read("gc/07000001.bin"))["unpacked"] == 9872000

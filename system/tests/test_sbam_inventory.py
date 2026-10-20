import hashlib
import os
import struct

import pytest

from gbox import sbam_inventory as sb


# ----------------------------------------------------------------------------- helpers
def _rec(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    nl = len(name)
    length = 33 + nl + (1 if nl % 2 == 0 else 0)
    r = bytearray(length)
    r[0] = length
    struct.pack_into("<I", r, 2, lba)
    struct.pack_into(">I", r, 6, lba)
    struct.pack_into("<I", r, 10, size)
    struct.pack_into(">I", r, 14, size)
    r[25] = 2 if is_dir else 0
    struct.pack_into("<H", r, 28, 1)
    struct.pack_into(">H", r, 30, 1)
    r[32] = nl
    r[33:33 + nl] = name
    return bytes(r)


def build_iso(files: dict) -> bytes:
    """Tiny ISO9660 image (one sector per directory) for the reader tests."""
    tree: dict = {}
    for path, payload in files.items():
        node = tree
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = payload
    dir_lba, order, nxt = {}, [], [18]

    def alloc_dir(node, parent):
        lba = nxt[0]
        nxt[0] += 1
        dir_lba[id(node)] = lba
        order.append((node, lba, parent))
        for _k, v in sorted(node.items()):
            if isinstance(v, dict):
                alloc_dir(v, lba)

    alloc_dir(tree, 18)
    file_lba = {}

    def alloc_files(node):
        for k, v in sorted(node.items()):
            if isinstance(v, dict):
                alloc_files(v)
            else:
                file_lba[id(v), k] = nxt[0]
                nxt[0] += max(1, (len(v) + 2047) // 2048)

    alloc_files(tree)
    img = bytearray(nxt[0] * 2048)
    for node, lba, parent in order:
        recs = _rec(b"\x00", lba, 2048, True) + _rec(b"\x01", parent, 2048, True)
        for k, v in sorted(node.items()):
            if isinstance(v, dict):
                recs += _rec(k.encode(), dir_lba[id(v)], 2048, True)
            else:
                flba = file_lba[id(v), k]
                recs += _rec(k.encode() + b";1", flba, len(v), False)
                img[flba * 2048:flba * 2048 + len(v)] = v
        img[lba * 2048:lba * 2048 + len(recs)] = recs
    pvd = bytearray(2048)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[8:40] = b"PLAYSTATION".ljust(32)
    pvd[40:72] = b"SUPER_BUST_A_MOVE".ljust(32)
    struct.pack_into("<I", pvd, 80, nxt[0])
    struct.pack_into(">I", pvd, 84, nxt[0])
    pvd[156:190] = _rec(b"\x00", 18, 2048, True)
    pvd[318:446] = b"ACCLAIM_ENTERTAINMENT_INC".ljust(128)
    pvd[813:830] = b"2000102512222900\x00"
    img[16 * 2048:17 * 2048] = pvd
    img[17 * 2048:17 * 2048 + 7] = b"\xffCD001\x01"
    return bytes(img)


def tiny_elf(payload: bytes) -> bytes:
    eh = bytearray(52)
    eh[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<HHIIIIIHHHHHH", eh, 16, 2, 8, 1, 0x100008, 52, 0, 0, 52, 32, 1, 40, 0, 0)
    ph = struct.pack("<8I", 1, 0x1000, 0x100000, 0x100000, len(payload), len(payload), 7, 0x10)
    return bytes(eh) + ph + bytes(0x1000 - 84) + payload


def ra_container(entries: list) -> bytes:
    table_end = 0x18 + 4 * len(entries)
    offs, pos = [], table_end
    for e in entries:
        offs.append(pos)
        pos += len(e)
    header = b"-RA-" + bytes(16) + struct.pack("<I", len(entries)) + struct.pack("<%dI" % len(entries), *offs)
    return header + b"".join(entries)


def tim2_4bpp(w=8, h=2) -> bytes:
    image = bytes(range(w * h // 2))
    clut = bytes(64)
    hdr = struct.pack("<IIIHHBBBBHH", 48 + len(image) + len(clut), len(clut), len(image), 48, 16, 0, 1, 3, 4, w, h) + bytes(24)
    return b"TIM2" + bytes([4, 0]) + struct.pack("<H", 1) + bytes(8) + hdr + image + clut


# ----------------------------------------------------------------------------- CMP3
def test_cmp3_decodes_zero_ring_reference_from_disc_prefix():
    # First CMP3 entry of DATA00/DATA00.DAT: 7 literals then a ring reference (0xFE5, 9) into the
    # zero-filled window, giving a 16-byte TIM2 file header.
    stream = b"CMP3" + struct.pack("<I", 16) + b"\x7fTIM2\x04\x00\x01" + b"\xe5\xf6"
    assert sb.cmp3_decompress(stream) == b"TIM2\x04\x00\x01" + bytes(9)


def test_cmp3_overlapping_reference_repeats_recent_output():
    stream = b"CMP3" + struct.pack("<I", 8) + bytes([0x03]) + b"AB" + bytes([0xEE, 0xF3])
    assert sb.cmp3_decompress(stream) == b"ABABABAB"


def test_cmp3_truncated_stream_raises():
    stream = b"CMP3" + struct.pack("<I", 32) + b"\xffABCDEFGH"
    with pytest.raises(ValueError, match="truncated"):
        sb.cmp3_decompress(stream)
    with pytest.raises(ValueError):
        sb.cmp3_decompress(b"XXXX" + bytes(8))


@pytest.mark.parametrize("n", [0, 1, 7, 8, 9, 1000])
def test_cmp3_literal_encoder_roundtrips(n):
    data = hashlib.sha256(str(n).encode()).digest() * (n // 32 + 1)
    data = data[:n]
    enc = sb.cmp3_compress_literal(data)
    assert enc[:4] == b"CMP3" and struct.unpack_from("<I", enc, 4)[0] == n
    assert sb.cmp3_decompress(enc) == data
    assert len(enc) == 8 + n + (n + 7) // 8


# ----------------------------------------------------------------------------- -RA- / TIM2
def test_parse_ra_entries_and_payloads():
    tim = tim2_4bpp()
    buf = ra_container([sb.cmp3_compress_literal(tim), bytes(32)])
    entries = sb.parse_ra(buf)
    assert [e.codec for e in entries] == ["cmp3", "raw"]
    assert entries[0].offset == 0x20 and entries[0].decoded_size == len(tim)
    assert entries[1].size == 32
    assert sb.ra_entry_payload(buf, entries[0]) == tim
    assert sb.classify_payload(sb.ra_entry_payload(buf, entries[1]), "raw") == "vb_adpcm"


def test_parse_ra_rejects_bad_headers():
    with pytest.raises(ValueError):
        sb.parse_ra(b"-XA-" + bytes(40))
    bad = bytearray(ra_container([bytes(8)]))
    struct.pack_into("<I", bad, 0x18, 0x40)
    with pytest.raises(ValueError, match="first -RA- offset"):
        sb.parse_ra(bytes(bad))


def test_tim2_picture_header():
    pics = sb.tim2_pictures(tim2_4bpp(8, 2))
    assert len(pics) == 1
    p = pics[0]
    assert (p["width"], p["height"], p["bpp"], p["clut_colors"], p["packed_ok"]) == (8, 2, 4, 16, True)


# ----------------------------------------------------------------------------- ELF tables
def _elf_payload() -> bytes:
    names = b"".join(s.ljust(0x20, b"\x00") for s in (b"\\DATA\\DATA00\\DATA01.DAT;1", b"\\DATA\\DATA00\\DATA00.DAT;1"))
    voices = b"".join(s.ljust(0x10, b"\x00") for s in (b"KATZE VOICE", b"MISS T VOICE", b"PUKADON VOICE"))
    return b"\x00" * 16 + names + b"\x00" * 16 + voices + b"\x00" * 8 + b"CATCH-KUN voice\x00"


def test_elf_tables_and_roster():
    elf = tiny_elf(_elf_payload())
    info = sb.elf_info(elf)
    assert info["mips"] and info["entry"] == 0x100008
    tables = sb.elf_dat_tables(elf)
    assert tables["index_table"]["count"] == 2 and tables["index_table"]["order"] == "descending"
    assert sb.elf_file_to_vaddr(info, tables["index_table"]["file_offset"]) == 0x100000 + 16
    roster = {t["table"]: [n["name"] for n in t["names"]] for t in sb.elf_voice_roster(elf)}
    assert roster == {"VOICE": ["KATZE", "MISS T", "PUKADON"], "voice": ["CATCH-KUN"]}


def test_system_cnf_ps2():
    cnf = sb.parse_system_cnf(b"BOOT2 = cdrom0:\\SLUS_201.15;1\nVER = 1.00\nVMODE = NTSC\n")
    assert cnf["platform"] == "ps2" and cnf["boot_file"] == "SLUS_201.15" and cnf["VMODE"] == "NTSC"
    assert sb.parse_system_cnf(b"BOOT = cdrom:\\SLUS_000.01;1\n")["platform"] == "ps1"


# ----------------------------------------------------------------------------- inventory
def test_inventory_on_synthetic_iso(tmp_path):
    dat = ra_container([sb.cmp3_compress_literal(tim2_4bpp()), bytes(48)])
    iso = build_iso({
        "SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_201.15;1\nVER = 1.00\nVMODE = NTSC\n",
        "SLUS_201.15": tiny_elf(_elf_payload()),
        "DATA/DATA00/DATA00.DAT": dat,
        "IOP/PADMAN.IRX": b"irx",
    })
    p = tmp_path / "disc.iso"
    p.write_bytes(iso)
    with sb.Iso9660(str(p)) as reader:
        assert sorted(f.path for f in reader.files) == ["DATA/DATA00/DATA00.DAT", "IOP/PADMAN.IRX", "SLUS_201.15", "SYSTEM.CNF"]
        assert reader.read("\\DATA\\DATA00\\DATA00.DAT;1") == dat
    m = sb.inventory(str(p), source_sha256="ab" * 32, boot_copy_dir=str(tmp_path / "inv"))
    assert m["platform"] == "ps2" and m["boot"]["file"] == "SLUS_201.15"
    assert m["totals"] == {"entries": 2, "tim2": 1, "vb_adpcm": 1, "cmp3": 1, "raw": 1, "tim2_pictures": 1}
    c = m["containers"][0]
    assert c["role"] == "texture_set" and c["signature"] == ["8x2@4"]
    assert c["entries"][0]["pictures"][0]["bpp"] == 4
    assert (tmp_path / "inv" / "SLUS_201.15").read_bytes() == tiny_elf(_elf_payload())
    assert m["iop_modules"][0]["path"] == "IOP/PADMAN.IRX"


REAL_ISO = os.path.expanduser("~/gBox_alt/gbox-cache/ps2/6cd93f2e36885f31/disc.iso")


@pytest.mark.skipif(not os.path.exists(REAL_ISO), reason="owned Super Bust-A-Move ISO not staged")
def test_owned_disc_layout_and_first_container():
    with sb.Iso9660(REAL_ISO) as iso:
        assert len(iso.files) == 161
        cnf = sb.parse_system_cnf(iso.read("SYSTEM.CNF"))
        assert cnf["boot_file"] == sb.SERIAL and cnf["VMODE"] == "NTSC"
        assert hashlib.sha256(iso.read(sb.SERIAL)).hexdigest() == sb.KNOWN["boot_elf_sha256"]
        buf = iso.read("DATA/DATA00/DATA00.DAT")
    entries = sb.parse_ra(buf)
    assert len(entries) == 11 and all(e.codec == "cmp3" for e in entries)
    payloads = [sb.ra_entry_payload(buf, e) for e in entries]
    assert all(p[:4] == b"TIM2" and len(p) == e.decoded_size for p, e in zip(payloads, entries))

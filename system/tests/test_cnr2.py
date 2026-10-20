import struct

import pytest

from gbox import cnr2


def _fpk(entries):
    table = 0x10
    off = table + 0x30 * len(entries)
    body, rows = b"", b""
    for name, stored, size in entries:
        rows += name.encode().ljust(0x20, b"\0") + struct.pack(">4I", 0, off + len(body), len(stored), size)
        body += stored
    total = off + len(body)
    return struct.pack(">4I", 0x3F13, len(entries), table, total) + rows + body


def test_fpk_index_reads_table():
    d = _fpk([("chr/nrt/0000.seq", b"\x84\x00abc", 40), ("chr/nrt/0000.brplt", b"x" * 8, 8)])
    idx = cnr2.fpk_index(d)
    assert [e["name"] for e in idx] == ["chr/nrt/0000.seq", "chr/nrt/0000.brplt"]
    assert idx[0]["offset"] == 0x70 and idx[0]["stored"] == 5 and idx[0]["size"] == 40 and idx[0]["compressed"]
    assert not idx[1]["compressed"]
    assert d[idx[1]["offset"]:idx[1]["offset"] + 8] == b"x" * 8


def test_fpk_index_rejects_bad_size():
    d = _fpk([("a", b"1", 1)])
    with pytest.raises(ValueError):
        cnr2.fpk_index(d + b"\0")


def _group(names_ptrs):
    """Index group bytes with name/data pointers relative to the group start (filled by caller offsets)."""
    n = len(names_ptrs)
    g = struct.pack(">2I", 8 + 16 * (n + 1), n) + struct.pack(">4H2I", 0xFFFF, 0, 1, 0, 0, 0)
    for i, (name_rel, data_rel) in enumerate(names_ptrs):
        g += struct.pack(">4H2I", i, 0, 0, 0, name_rel, data_rel)
    return g


def _brres_with_mdl0():
    # layout: header 0x10 | root block at 0x10 ("root", size, group) | sub-group | MDL0 | bones group | names
    root = 0x10
    rg = root + 8                         # root group (1 folder)
    fg = rg + 8 + 32                      # folder group (1 model)
    mdl = fg + 8 + 32
    mdl_len = 0x10 + 13 * 4 + 4
    bg = mdl + mdl_len                    # bones group (2 bones)
    names = bg + 8 + 48
    strs = [b"3DModels(NW4R)", b"body", b"hip", b"spine"]
    name_at, cur = [], names
    blob = b""
    for s in strs:
        cur += 4
        name_at.append(cur)
        blob += struct.pack(">I", len(s)) + s + b"\0" * (4 - len(s) % 4)
        cur = names + len(blob)
    d = bytearray(b"\0" * (names + len(blob)))
    d[0:16] = b"bres\xfe\xff\0\0" + struct.pack(">IHH", len(d), root, 2)
    d[root:root + 8] = b"root" + struct.pack(">I", fg - root)
    d[rg:fg] = _group([(name_at[0] - rg, fg - rg)])
    d[fg:mdl] = _group([(name_at[1] - fg, mdl - fg)])
    secs = [0] * 13
    secs[1] = bg - mdl
    d[mdl:bg] = b"MDL0" + struct.pack(">2Ii", mdl_len, 11, -mdl) + struct.pack(">13i", *secs) + b"\0" * 4
    d[bg:names] = _group([(name_at[2] - bg, 0), (name_at[3] - bg, 0)])
    d[names:] = blob
    return bytes(d)


def test_brres_index_counts_mdl0_bones():
    idx = cnr2.brres_index(_brres_with_mdl0())
    body = idx["3DModels(NW4R)"]["body"]
    assert body["magic"] == "MDL0" and body["version"] == 11
    assert body["bones"] == 2 and body["bone_names"] == ["hip", "spine"]


def test_brres_index_rejects_little_endian():
    with pytest.raises(ValueError):
        cnr2.brres_index(b"bres\xff\xfe" + b"\0" * 32)


DISC = cnr2.Path.home() / "gBox_alt/gbox-cache/modbase/00063327fc44eced/disc/DATA/files"


@pytest.mark.skipif(not (DISC / "chr/nrt/0000.brres").is_file(), reason="extracted RNYEDA disc not on this node")
def test_real_disc_naruto_costume():
    idx = cnr2.brres_index((DISC / "chr/nrt/0000.brres").read_bytes())
    m = idx["3DModels(NW4R)"]["0000"]
    assert m["version"] == 11 and m["bones"] == 91 and "nrt_tex01" in m["textures"]
    names = [e["name"] for e in cnr2.fpk_index((DISC / "fpack/chr/nrt/0000.fpk").read_bytes())]
    assert names[:2] == ["chr/nrt/0000.seq", "chr/nrt/0000.brres"] and len(names) == 25
    assert len(cnr2.characters(DISC)) == 44


# nrt/0000.fpk entry 0: the codec sample from the checkpoint (compressed -> seq header).
PRS_SAMPLE = bytes.fromhex("8400ff116ffc40ffe5000132")
PRS_SAMPLE_OUT = bytes.fromhex("000000110000004000000040")


def test_prs_decompress_codec_sample():
    assert cnr2.prs_decompress(PRS_SAMPLE, 12) == PRS_SAMPLE_OUT


def test_prs_decompress_rejects_truncated_stream():
    with pytest.raises(ValueError):
        cnr2.prs_decompress(b"\x84\x00\xff\x11\x6f\xfc\x40\xff", 12)  # sample cut off mid-copy


def _fpk_checksummed(entries):
    table = 0x10
    off = table + 0x30 * len(entries)
    body, rows = b"", b""
    for name, stored, size in entries:
        rows += name.encode().ljust(0x20, b"\0") + struct.pack(">4I", 0, off + len(body), len(stored), size)
        body += stored
    total = off + len(body)
    return struct.pack(">4I", sum(body) & 0xFFFF, len(entries), table, total) + rows + body


def test_fpk_decompress_passthrough_and_checksum():
    # 8 literal bytes: flag 0xFF = 8 literal bits, then the payload (stored 9 != orig 8).
    lit = b"\xff12345678"
    d = _fpk_checksummed([("chr/aka/0000.brtex", b"", 0), ("chr/nrt/0000.seq", lit, 8)])
    assert struct.unpack_from(">I", d, 0)[0] == cnr2.fpk_checksum(d)
    out = dict(cnr2.fpk_decompress(d))
    assert out["chr/aka/0000.brtex"] == b""  # stored == original entries pass through
    assert out["chr/nrt/0000.seq"] == b"12345678"


@pytest.mark.skipif(not (DISC / "chr/nrt/0000.brres").is_file(), reason="extracted RNYEDA disc not on this node")
def test_real_disc_fpk_decompress_byte_equal():
    fpk = (DISC / "fpack/chr/nrt/0000.fpk").read_bytes()
    assert struct.unpack_from(">I", fpk, 0)[0] == cnr2.fpk_checksum(fpk)
    got = dict(cnr2.fpk_decompress(fpk))
    for name in ["0000.seq", "0000.brres", "0000.mot", "0000.brtex", "0000.brplt"]:
        assert got[f"chr/nrt/{name}"] == (DISC / "chr/nrt" / name).read_bytes()
    assert got["chr/nrt/0000.brres"] == (DISC / "chr/nrt/0000.brres").read_bytes()  # 307200 B oracle


def test_prs_compress_roundtrip_sample():
    assert cnr2.prs_decompress(cnr2.prs_compress(PRS_SAMPLE_OUT), len(PRS_SAMPLE_OUT)) == PRS_SAMPLE_OUT


def test_prs_compress_roundtrip_varied():
    import random
    rng = random.Random(0)
    cases = [
        b"",
        b"\0",
        b"\0" * 300,                                   # RLE: exercises short + long copies
        bytes(range(256)) * 4,                          # no repeats -> all literals
        b"ababababababab" * 40,                         # long repeated run
        bytes(rng.randrange(256) for _ in range(10000)),  # incompressible-ish
        (b"nrt_tex01" * 40000)[:400000],               # large with periodic structure
    ]
    for data in cases:
        assert cnr2.prs_decompress(cnr2.prs_compress(data), len(data)) == data


def test_fpk_pack_roundtrip_and_checksum():
    entries = [("chr/nrt/0000.seq", b"\x00\x00\x00\x11" * 5), ("chr/nrt/0000.brplt", b"\xab" * 512),
               ("chr/aka/0000.brtex", b""), ("chr/aka/0000.brres", bytes(range(256)) * 3)]
    d = cnr2.fpk_pack(entries)
    assert struct.unpack_from(">I", d, 0)[0] == cnr2.fpk_checksum(d)
    assert dict(cnr2.fpk_decompress(d)) == {n: r for n, r in entries}


def test_fpk_pack_stored_raw_entries():
    # compress=False stores non-empty entries raw (stored == size); fpk_decompress passes them through.
    entries = [("chr/nrt/0000.brplt", b"\x01\x02\x03\x04"), ("chr/nrt/0000.seq", b"hello world")]
    d = cnr2.fpk_pack(entries, compress=False, allow_unverified_raw=True)
    assert [e["compressed"] for e in cnr2.fpk_index(d)] == [False, False]
    assert struct.unpack_from(">I", d, 0)[0] == cnr2.fpk_checksum(d)
    assert dict(cnr2.fpk_decompress(d)) == dict(entries)


def test_fpk_pack_rejects_bad_name():
    with pytest.raises(ValueError):
        cnr2.fpk_pack([("a" * 0x20, b"x")])


@pytest.mark.skipif(not (DISC / "chr/nrt/0000.brres").is_file(), reason="extracted RNYEDA disc not on this node")
def test_real_disc_fpk_repack_noop_roundtrip():
    fpk = (DISC / "fpack/chr/nrt/0000.fpk").read_bytes()
    entries = cnr2.fpk_decompress(fpk)              # (name, raw) for all 25 entries
    repacked = cnr2.fpk_pack(entries)               # recompress + recompute checksum
    # The repacked stream must decompress to exactly the same payloads (writer no-op round trip).
    assert dict(cnr2.fpk_decompress(repacked)) == dict(entries)
    assert struct.unpack_from(">I", repacked, 0)[0] == cnr2.fpk_checksum(repacked)
    got = dict(cnr2.fpk_decompress(repacked))
    for name in ["0000.seq", "0000.brres", "0000.mot", "0000.brtex", "0000.brplt"]:
        assert got[f"chr/nrt/{name}"] == (DISC / "chr/nrt" / name).read_bytes()


def test_unverified_nonempty_raw_fallback_requires_explicit_opt_in():
    for compress in (True, False):
        with pytest.raises(ValueError, match='not verified'):
            cnr2.fpk_pack([('a', b'x')], compress=compress)


def test_repack_preserves_original_bytes_and_changes_only_requested_member():
    entries = [('first', bytes(range(128))*8), ('second', b'unchanged'*100)]
    source = cnr2.fpk_pack(entries)
    assert cnr2.fpk_repack(source, {}) == source
    assert cnr2.fpk_repack(source, dict(entries)) == source
    changed = b'a'*1024
    result = cnr2.fpk_repack(source, {'first': changed})
    assert len(result) == len(source)
    assert cnr2.fpk_decompress(result) == [('first', changed), entries[1]]
    before, after = cnr2.fpk_index(source), cnr2.fpk_index(result)
    assert before[1] == after[1]
    e = before[1]
    assert result[e['offset']:e['offset']+e['stored']] == source[e['offset']:e['offset']+e['stored']]
    assert cnr2.fpk_checksum(result) == struct.unpack_from('>I', result)[0]


def test_repack_rejects_unknown_member_growth_and_bad_checksum():
    source = cnr2.fpk_pack([('first', b'a'*1024)])
    for changes in ({'missing':b'x'}, {'first':bytes(range(256))*4}):
        with pytest.raises(ValueError):
            cnr2.fpk_repack(source, changes)
    corrupt = bytearray(source)
    corrupt[-1] ^= 1
    with pytest.raises(ValueError, match='checksum'):
        cnr2.fpk_repack(bytes(corrupt), {})


@pytest.mark.skipif(not (DISC / 'fpack/chr/nrt/0000.fpk').is_file(), reason='owned RNYEDA pack not mounted')
def test_owned_fpk_actual_byte_identical_noop_and_changed_member():
    source = (DISC / 'fpack/chr/nrt/0000.fpk').read_bytes()
    entries = cnr2.fpk_decompress(source)
    assert cnr2.fpk_repack(source, dict(entries)) == source
    name, raw = entries[0]
    # A changed payload proves the container writer, not gameplay-valid content.
    changed = b'\0'*len(raw)
    result = cnr2.fpk_repack(source, {name:changed})
    assert cnr2.fpk_decompress(result) == [(name,changed), *entries[1:]]
    assert result != source and len(result) == len(source)

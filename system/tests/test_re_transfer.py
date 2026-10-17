"""gbox.re_transfer: function names learned in one title carry over to sibling titles through masked body hashes."""
import struct

from fastapi.testclient import TestClient

from gbox import re_lab, re_transfer as T


class Store:
    def __init__(self):
        self.d = {}

    def put(self, kind, id, body):
        self.d[(kind, id)] = body

    def get(self, kind, id):
        return self.d.get((kind, id))

    def all(self, kind):
        return [v for (k, _i), v in self.d.items() if k == kind]


SH4 = "SuperH4:LE:32:default"
PPC = "PowerPC:BE:32:default"
BASE = 0x8C010000


def sh4_body(bsr1=0x010, bsr2=0x020, disp=0x5242):
    """20 SH-4 instructions; two bsr calls whose displacement depends on where the callees sit."""
    return [0x4F22, 0x2FE6, 0x6EF3, 0xD101, 0xB000 | bsr1, 0x0009, disp, 0x6043, 0x8801, 0x8B02,
            0xE401, 0xB000 | bsr2, 0x0009, 0x7004, 0x6103, 0x2412, 0x6EF6, 0x4F26, 0x000B, 0x6EF6]


def sh4_image(funcs, size=0x800):
    ws = [0x0009] * (size // 2)
    for off, body in funcs:
        ws[off // 2:off // 2 + len(body)] = body
    return struct.pack(f"<{len(ws)}H", *ws)


def ppc_body(hi=0x8027, lo=0x1234, call=0x100, sda=0x4FA4, frame=0x24):
    return [0x9421FFE0, 0x7C0802A6, 0x90010000 | frame, 0x3C600000 | hi, 0x38630000 | lo, 0x80830010,
            0x48000001 | call, 0x80AD0000 | sda, 0x7C651B78, 0x80010000 | frame, 0x7C0803A6, 0x38210020, 0x4E800020]


def ppc_image(funcs, size=0x400):
    ws = [0x60000000] * (size // 4)
    for off, body in funcs:
        ws[off // 4:off // 4 + len(body)] = body
    return struct.pack(f">{len(ws)}I", *ws)


GAME_A = {"game_id": "aaaa", "title": "Title A (JP)", "platform": "dreamcast"}
GAME_B = {"game_id": "bbbb", "title": "Title B (US)", "platform": "dreamcast"}


def test_masked_body_transfers_across_relocated_build_and_records_hypothesis():
    s = Store()
    a = sh4_image([(0x100, sh4_body())])
    r = T.learn(s, "Title A (JP)", a, BASE, SH4, [{"address": f"{BASE + 0x100:08x}", "size": 40, "name": "FUN_x"}],
                names={"0x8C010100": "chr_load"})
    assert r["added"] == 1 and r["arch"] == "sh4"
    # same body elsewhere, other call displacements; a near-twin with one changed displacement-load must not match
    b = sh4_image([(0x340, sh4_body(0x1F0, 0x2A4)), (0x500, sh4_body(disp=0x5243))])
    out = T.transfer(s, GAME_B, b, BASE, SH4)
    assert [h["address"] for h in out["recorded"]] == ["0x8C010340"]
    f = [x for x in re_lab.dossier(s, GAME_B)["findings"] if x["address"] == "0x8C010340"][0]
    assert f["name"] == "chr_load" and f["status"] == "hypothesis" and "Title A (JP)" in f["role"]


def test_ppc_masks_relocated_addresses_but_not_frame_offsets():
    s = Store()
    T.learn(s, "A", ppc_image([(0x40, ppc_body())]), 0x80003100, PPC,
            [{"address": 0x80003140, "size": 52, "name": "ItemMgr_count"}])
    b = ppc_image([(0x80, ppc_body(0x8028, 0x5678, 0x2F0, 0x5000)), (0x200, ppc_body(frame=0x28))])
    fns = [{"address": "0x80003180", "size": 52}, {"address": "0x80003300", "size": 52}]
    for functions in (None, fns):                                   # brute scan and Ghidra entry list agree
        hits = T.match(T.library(s, "ppc-be"), b, 0x80003100, PPC, functions)["hits"]
        assert list(hits) == [0x80003180]
    out = T.transfer(s, GAME_B, b, 0x80003100, PPC, fns, record=False)
    assert out["named"] == 1 and out["coverage"] == 0.5


def test_ambiguous_duplicate_short_and_auto_names_are_never_transferred():
    s = Store()
    a = sh4_image([(0x100, sh4_body()), (0x300, sh4_body(0x40, 0x50)), (0x500, [0x4F22, 0x000B, 0x0009])])
    r = T.learn(s, "A", a, BASE, SH4, [{"address": BASE + 0x100, "size": 40, "name": "load_a"},
                                       {"address": BASE + 0x300, "size": 40, "name": "load_b"},
                                       {"address": BASE + 0x500, "size": 6, "name": "tiny"},
                                       {"address": BASE + 0x600, "size": 40, "name": "FUN_8c010600"}])
    assert (r["added"], r["ambiguous"], r["too_short"], r["unnamed"]) == (1, 1, 1, 1)
    assert T.transfer(s, GAME_B, a, BASE, SH4)["named"] == 0      # one body, two names: ambiguous
    s2 = Store()
    T.learn(s2, "A", a, BASE, SH4, [{"address": BASE + 0x100, "size": 40, "name": "load_a"}])
    dup = T.transfer(s2, GAME_B, a, BASE, SH4)                     # body present twice in the target
    assert dup["named"] == 0 and dup["duplicates"][0]["name"] == "load_a"


def test_documented_findings_are_confirmed_not_overwritten():
    s = Store()
    T.learn(s, "A", sh4_image([(0x100, sh4_body())]), BASE, SH4, [{"address": BASE + 0x100, "size": 40, "name": "chr_load"}])
    re_lab.record(s, GAME_B, "function", "0x8C010200", "chr_load", "engineer verified", "documented", actor="seed")
    out = T.transfer(s, GAME_B, sh4_image([(0x200, sh4_body(0x77, 0x99))]), BASE, SH4)
    assert out["confirmed"] == [{"address": "0x8C010200", "name": "chr_load", "known": "chr_load"}]
    f = [x for x in re_lab.dossier(s, GAME_B)["findings"] if x["address"] == "0x8C010200"][0]
    assert f["status"] == "documented" and f["role"] == "engineer verified"


def test_elf_segments_map_virtual_addresses():
    body = ppc_image([(0, ppc_body())], size=0x40)
    hdr = bytearray(52)
    hdr[:6] = b"\x7fELF\x01\x02"
    struct.pack_into(">I", hdr, 28, 52)
    struct.pack_into(">HH", hdr, 42, 32, 1)
    ph = struct.pack(">IIIIIIII", 1, 84, 0x80400000, 0x80400000, len(body), len(body), 5, 4)
    elf = bytes(hdr) + ph + body
    assert T.segments(elf) == [(0x80400000, body)]
    s = Store()
    assert T.learn(s, "A", elf, 0, PPC, [{"address": "ram:80400000", "size": 52, "name": "f"}])["added"] == 1


def test_unsupported_processor_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        T.arch_of("ARM:LE:32:v7")


def test_server_learn_then_transfer(cfg):
    from gbox.server import create_app
    from gbox.store import Store as RealStore
    client = TestClient(create_app(cfg), headers={"Authorization": f"Bearer {cfg.token()}"})
    st = RealStore(cfg.data_dir)
    st.upsert_catalog([GAME_A | {"library": "t"}, GAME_B | {"library": "t"}])
    a = st.put_artifact(sh4_image([(0x100, sh4_body())]), "a.bin", "application/octet-stream", {}).sha256
    b = st.put_artifact(sh4_image([(0x400, sh4_body(0x3, 0x4))]), "b.bin", "application/octet-stream", {}).sha256
    re_lab.record(st, GAME_A, "function", "0x8C010100", "chr_load", "verified", "documented", actor="seed")
    r = client.post("/api/re/dossier/aaaa/signatures/learn", json={
        "exe_artifact": a, "processor": SH4, "base": "0x8c010000",
        "functions": [{"address": "8c010100", "size": 40, "name": "FUN_8c010100"}]})
    assert r.status_code == 200 and r.json()["added"] == 1
    assert client.get("/api/re/signatures").json()["sh4"]["bodies"] == 1
    r = client.post("/api/re/dossier/bbbb/signatures/transfer", json={"exe_artifact": b, "processor": SH4,
                                                                       "base": "0x8c010000"})
    assert r.status_code == 200 and r.json()["recorded"][0]["address"] == "0x8C010400"
    assert any(f["name"] == "chr_load" for f in client.get("/api/re/dossier/bbbb").json()["findings"])
    assert client.post("/api/re/dossier/bbbb/signatures/transfer",
                       json={"exe_artifact": "0" * 64, "processor": SH4}).status_code == 404


def _symtab_elf(code: bytes, vaddr: int, syms):
    """Minimal big-endian ELF32: one PT_LOAD + .symtab/.strtab sections."""
    strtab = b"\0" + b"".join(n.encode() + b"\0" for n, _a, _s in syms)
    symtab, pos = bytes(16), 1
    for n, a, sz in syms:
        symtab += struct.pack(">IIIBBH", pos, a, sz, 0x12, 0, 1)
        pos += len(n) + 1
    code_off = 52 + 32
    sym_off = code_off + len(code)
    str_off = sym_off + len(symtab)
    sh_off = str_off + len(strtab)
    hdr = bytearray(52)
    hdr[:6] = b"\x7fELF\x01\x02"
    struct.pack_into(">II", hdr, 28, 52, sh_off)
    struct.pack_into(">HHHH", hdr, 42, 32, 1, 40, 3)
    ph = struct.pack(">IIIIIIII", 1, code_off, vaddr, vaddr, len(code), len(code), 5, 4)
    sh = bytes(40) + struct.pack(">IIIIIIIIII", 0, 2, 0, 0, sym_off, len(symtab), 2, 0, 4, 16) \
        + struct.pack(">IIIIIIIIII", 0, 3, 0, 0, str_off, len(strtab), 0, 0, 1, 0)
    return bytes(hdr) + ph + code + symtab + strtab + sh


def test_debug_elf_names_itself_and_server_reads_study_elf(cfg, tmp_path):
    from pathlib import Path
    from gbox.server import create_app
    from gbox.store import Store as RealStore
    elf = _symtab_elf(ppc_image([(0, ppc_body())], size=0x40), 0x80400000, [("DVDOpen", 0x80400000, 52)])
    assert T.elf_functions(elf) == [{"address": 0x80400000, "size": 52, "name": "DVDOpen"}]
    st = RealStore(cfg.data_dir)
    st.upsert_catalog([GAME_A | {"library": "t"}, GAME_B | {"library": "t"}])
    root = Path(cfg.data_dir) / "analysis"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.elf").write_bytes(elf)
    (root / "b.elf").write_bytes(ppc_image([(0x100, ppc_body(0x8100, 0x10, 0x88, 0x10))]))
    client = TestClient(create_app(cfg), headers={"Authorization": f"Bearer {cfg.token()}"})
    r = client.post("/api/re/dossier/aaaa/signatures/learn", json={"exe_rel": "a.elf", "processor": PPC})
    assert r.status_code == 200 and r.json()["added"] == 1             # no functions passed: .symtab used
    r = client.post("/api/re/dossier/bbbb/signatures/transfer",
                    json={"exe_rel": "b.elf", "processor": PPC, "base": "0x80500000"})
    assert r.json()["recorded"] == [{"address": "0x80500100", "name": "DVDOpen", "bytes": 52, "from": "Title A (JP)"}]
    assert client.post("/api/re/dossier/bbbb/signatures/transfer",
                       json={"exe_rel": "../../etc/passwd", "processor": PPC}).status_code == 404


def test_agent_transfer_op_uses_the_studied_executable():
    from gbox.agent import Agent as Tools

    class R:
        def __init__(self, j):
            self.j = j

        def json(self):
            return self.j

    class Api:
        posts = []

        def get(self, path):
            return R({"executable": {"sha256": "ab" * 32, "rel": "x/y.elf", "processor": SH4, "base": "0x8c010000"}})

        def post(self, path, json=None):
            self.posts.append((path, json))
            return R({"arch": "sh4", "library": 9, "named": 1, "recorded": [{"address": "0x8C010400"}], "confirmed": []})

    t = Tools.__new__(Tools)
    t.api = Api()
    t._re_gid = lambda g: "bbbb"
    out = t.re_dossier(op="transfer")
    assert out["recorded"] == 1 and Api.posts[0][0] == "/api/re/dossier/bbbb/signatures/transfer"
    assert Api.posts[0][1] == {"exe_artifact": "ab" * 32, "exe_rel": "x/y.elf", "processor": SH4, "base": "0x8c010000"}

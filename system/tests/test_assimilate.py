"""gbox.assimilate: the fingerprinter (synthetic listings per engine, real disc listings, ELF symbols), the knowledge
base, leave-one-out accuracy over the titles gBox already assimilated, the tool, and the readiness-queue hook."""
import importlib.util
import struct
from collections import Counter

import pytest

from gbox import assimilate as A, hermes_work_queue as q
from gbox.assimilate_kb import KNOWN_TITLES


def listing(files, strings=(), platform="", title="", known=None):
    """files: [(path, head bytes, {inner signature: count})]"""
    fs = [{"path": p, "head": h + bytes(16), "inner": Counter(inner or {})} for p, h, inner in files]
    return A.fingerprint_evidence(A.evidence(fs, list(strings), [], platform, title), known)


SIG = {k: v[3] for k, v in A.SIGNATURES.items()}

ENGINE_CASES = {
    "ninja": ([("PL/BODY.NJ", SIG["njcm"], {}), ("PL/TEX.PVM", SIG["pvmh"], {"pvrt": 4}), ("PL/MOT.NJM", SIG["nmdm"], {})],
              [], "dreamcast"),
    "renderware": ([("MODELS/GTA.IMG", b"", {"rw_clump": 40, "rw_txd": 30}), ("MODELS/X.TXD", SIG["rw_txd"], {})],
                   ["RenderWare Graphics 3.4"], "ps2"),
    "unreal4": ([("Game/Content/Paks/a.pak", b"", {}), ("Game/Content/b.uasset", SIG["ue_pkg_le"], {})],
                ["++UE4+Release-4.26"], "windows_native"),
    "unreal3": ([("USRDIR/CookedPS3/Startup.xxx", SIG["ue_pkg_be"], {}), ("USRDIR/CookedPS3/Game.xxx", SIG["ue_pkg_be"], {})],
                ["intAMyPawnexecFire"], "ps3"),
    "eagl": ([("maps/m1.ngc", SIG["ngc_restable"], {}), ("data.viv", SIG["bigf"], {})], ["BOA_ExpandInplace"], "gamecube"),
    "eurocom": ([("gc/00000001.bin", SIG["edl"], {}), ("gc/00000002.bin", SIG["edl"], {})], ["HT_File"], "gamecube"),
    "mt_framework": ([("arc/pl0000.arc", SIG["mt_arc"], {"mt_mod": 2, "mt_tex": 5})], [], "xbox360"),
    "cri": ([("DATA/A.AFS", SIG["afs"], {}), ("SOUND/B.ADX", b"\x80\0", {})], ["CRI Middleware"], "ps2"),
    "tecmo": ([("DATA/X.BIN", b"", {})], ["(C)TECMO LTD."], "xbox"),
    "aki": ([("DATA/DATA.BIN", b"", {})], ["AKI Corporation"], "ps2"),
    "yukes": ([("E.PAC", SIG["dpac"], {"emd": 3})], ["Yuke's Co., Ltd."], "psx"),
    "shiny": ([("data/a.bin", b"", {})], ["Shiny Entertainment, Inc."], "ps2"),
    "namco": ([("chr/a.nud", SIG["ndp3"], {}), ("chr/a.nut", SIG["ntp3"], {})], [], "ps3"),
    "nintendo_n64": ([("rom@00100000", SIG["mio0"], {}), ("rom@00200000", SIG["mio0"], {})], [], "n64"),
    "konami": ([("MGS/STAGE.DIR", b"", {})], ["KONAMI"], "psx"),
}


@pytest.mark.parametrize("engine", sorted(ENGINE_CASES))
def test_generic_rules_name_each_engine_without_any_knowledge(engine):
    files, strings, plat = ENGINE_CASES[engine]
    fp = listing(files, strings, plat, known=[])
    assert fp["engines"][0]["engine"] == engine, fp["engines"][:3]
    assert fp["engines"][0]["why"]


def test_formats_are_ranked_by_kind():
    fp = listing([("A.AFS", SIG["afs"], {"njcm": 9, "pvrt": 20, "nmdm": 2}), ("B.AFS", SIG["afs"], {}),
                  ("C.PRS", b"", {}), ("D.GZ", SIG["gzip"], {})], platform="dreamcast", known=[])
    assert fp["containers"][0] == {"id": "afs", "format": "CRI AFS archive", "files": 2}
    assert fp["models"][0]["id"] == "njcm" and fp["textures"][0]["id"] == "pvrt" and fp["animations"][0]["id"] == "nmdm"
    assert fp["codecs"][0]["id"] == "gzip"
    assert "gbox.formats.texture (twiddle) + gbox.ninja.pvr_decode" in fp["proposal"]["shared"]


def test_learning_from_assimilated_titles_points_at_their_reader():
    # an unseen Yuke's PS1 wrestler: no marker strings, only the containers SmackDown 2 taught gBox
    fp = listing([("ED2H.PAC", SIG["dpac"], {"emd": 4, "tim": 8}), ("M2.PAC", SIG["dpac"], {"yk_mot": 2})],
                 platform="psx", title="WWF SmackDown! (USA)")
    assert fp["engines"][0]["engine"] == "yukes" and fp["engines"][0]["learned"] > 0
    assert fp["nearest_titles"][0]["id"] == "sd2_ps1"
    assert fp["proposal"]["start_from"] == "gbox.yukes_sd"
    assert "from . import yukes_sd as ref" in fp["proposal"]["skeleton"]
    compile(fp["proposal"]["skeleton"], "skeleton.py", "exec")


def test_leave_one_out_accuracy_on_the_assimilated_titles():
    r = A.evaluate()
    assert r["titles"] == len(KNOWN_TITLES) >= 40
    assert r["engine_top1"] >= 0.85, r["misses"]
    assert r["neighbour_top1"] >= 0.8
    learned = A.evaluate(rules=False)
    assert learned["engine_top1"] >= 0.7                    # the KB alone carries most of it


def test_knowledge_base_is_consistent():
    ids = [t["id"] for t in KNOWN_TITLES]
    assert len(ids) == len(set(ids))
    for t in KNOWN_TITLES:
        assert t["engines"] and t["reader"].startswith("gbox.")
        assert importlib.util.find_spec(t["reader"]) is not None, t["reader"]
        for _p, head, inner in t["files"]:
            assert head is None or head in A.SIGNATURES
            assert all(i in A.SIGNATURES for i in inner)
        assert set(t["techniques"]) <= {p["id"] for p in __import__("gbox.re_seeds").re_seeds.PLAYBOOKS}


def elf_with_symbols(names, be=False):
    e = ">" if be else "<"
    strtab = b"\0" + b"".join(n.encode() + b"\0" for n in names)
    syms = bytes(16)
    off = 1
    for n in names:
        syms += struct.pack(e + "IIIBBH", off, 0x80001000, 4, 0x12, 0, 1)
        off += len(n) + 1
    shoff = 0x34
    data_off = shoff + 3 * 40
    hdr = bytearray(0x34)
    hdr[0:4], hdr[4], hdr[5], hdr[6] = b"\x7fELF", 1, 2 if be else 1, 1
    struct.pack_into(e + "I", hdr, 0x20, shoff)
    struct.pack_into(e + "HH", hdr, 0x2E, 40, 3)
    sh = bytes(40)
    sh += struct.pack(e + "10I", 0, 2, 0, 0, data_off, len(syms), 2, 1, 4, 16)
    sh += struct.pack(e + "10I", 0, 3, 0, 0, data_off + len(syms), len(strtab), 0, 0, 1, 0)
    return bytes(hdr) + sh + syms + strtab


def test_elf_symbols_feed_the_engine_markers():
    exe = elf_with_symbols(["RwEngineOpen", "RpClumpRender", "main"], be=True)
    assert A.elf_symbols(exe) == ["RwEngineOpen", "RpClumpRender", "main"]
    ev = A.evidence([], A.exe_strings(exe), A.elf_symbols(exe), "ps2")
    assert "marker:renderware" in A.tokens(ev)


def test_fingerprint_of_a_real_disc_image(tmp_path):
    from tests.test_formats import build_iso
    iso = build_iso({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_999.99;1\n",
                     "SLUS_999.99": elf_with_symbols(["RwEngineOpen"]) + b"RenderWare Graphics\0",
                     "MODELS": {"GTA3.IMG": struct.pack("<III", 0x10, 0x100, 0x1003FFFF) * 8,
                                "GTA3.DIR": bytes(64)}, "ANIM": {"PED.IFP": b"ANPK" + bytes(60)}})
    p = tmp_path / "game.iso"
    p.write_bytes(iso)
    fp = A.fingerprint_path(p, "ps2", "Grand Theft Auto III")
    assert fp["kind"] == "iso9660" and fp["executable"] == "SLUS_999.99"
    assert fp["engines"][0]["engine"] == "renderware"
    assert {"rw_clump", "anpk"} <= {r["id"] for r in fp["models"] + fp["animations"]}
    assert fp["nearest_titles"][0]["id"] == "gta3_ps2"


def test_metadata_fingerprint_and_ticket_fingerprint_never_raise():
    fp = A.metadata_fingerprint("Sonic Adventure DX (USA)", "gamecube")
    assert fp["source"] == "metadata" and fp["engines"][0]["engine"] == "ninja"

    def api(path):
        raise ConnectionError("control plane down")
    c = A.ticket_fingerprint("a" * 16, "Dead or Alive 3", "xbox", api=api)
    assert c["source"] == "metadata" and "control plane down" in " ".join(c["notes"])
    assert c["nearest_titles"][0]["id"].startswith("doa2") and c["summary"].startswith("[metadata]")


def test_tool_is_registered_and_runs(tmp_path):
    import gbox.tools  # noqa: F401  (loads the tool modules)
    from gbox.registry import REGISTRY, Ctx
    from gbox.config import Config
    assert "assimilate" in REGISTRY
    from tests.test_formats import build_gc_disc
    p = tmp_path / "gc.iso"
    p.write_bytes(build_gc_disc({"a/b.nj": b"NJCM" + bytes(12), "a/c.gvm": b"GVMH" + bytes(12)}))
    ctx = Ctx(Config())
    out = REGISTRY["assimilate"].fn(A.AssimilateIn(op="fingerprint", path=str(p)), ctx)
    assert out["result"]["engines"][0]["engine"] == "ninja" and ctx.artifacts[0][0] == "fingerprint.json"
    ev = REGISTRY["assimilate"].fn(A.AssimilateIn(op="evaluate"), ctx)["result"]
    assert ev["engine_top1"] >= 0.85 and "learned_only" in ev


# ---------------------------------------------------------------- readiness queue hook

P = "c" * 16
G = "a" * 16


def test_new_readiness_ticket_carries_the_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_HERMES_DISPATCH_STATE", str(tmp_path))
    data = {"version": 1, "items": {}, "parent_request_id": P}
    item = {"lane": "favorite", "game_id": G, "title": "Phantasy Star Online", "platform": "dreamcast"}
    data["items"]["favorite:" + G] = item
    seen, posted = [], []
    monkeypatch.setattr(q, "FINGERPRINT", lambda gid, title, plat, api=None, max_files=0: seen.append(gid) or
                        {"source": "disc", "summary": "[disc] engine Sega Ninja SDK (0.99)", "start_from": "gbox.pso_player"})
    monkeypatch.setattr(q, "_api", lambda path, body=None: posted.append(body) or {"id": "f" * 16, "number": 9})
    q._ensure_request(data, item, [{"id": P}])
    ctx = posted[0]["context"]
    assert seen == [G] and ctx["assimilation_fingerprint"]["start_from"] == "gbox.pso_player"
    assert "engine Sega Ninja SDK" in posted[0]["body"] and item["fingerprint"]["source"] == "disc"
    assert "Assimilation fingerprint attached" in q._prompt(item | {"request_id": "f" * 16, "number": 9})


def test_fingerprint_failure_never_blocks_the_ticket(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_HERMES_DISPATCH_STATE", str(tmp_path))
    data = {"version": 1, "items": {}, "parent_request_id": P}
    item = {"lane": "favorite", "game_id": G, "title": "Game", "platform": "psx"}

    def boom(*a, **k):
        raise RuntimeError("disc unreadable")
    monkeypatch.setattr(q, "FINGERPRINT", boom)
    posted = []
    monkeypatch.setattr(q, "_api", lambda path, body=None: posted.append(body) or {"id": "f" * 16, "number": 9})
    q._ensure_request(data, item, [{"id": P}])
    assert item["request_id"] == "f" * 16
    assert posted[0]["context"]["assimilation_fingerprint"]["summary"] == "fingerprint unavailable"
    assert "run assimilate op=fingerprint" in q._prompt(item)


def test_default_hook_falls_back_to_metadata_when_the_api_refuses(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_HERMES_DISPATCH_STATE", str(tmp_path))
    monkeypatch.setattr(q, "FINGERPRINT", None)

    def api(path, body=None):
        if body is None:
            raise AssertionError(path)                       # read-only API unavailable in this test
        return {"id": "f" * 16, "number": 3}
    monkeypatch.setattr(q, "_api", api)
    item = {"lane": "favorite", "game_id": G, "title": "Jet Grind Radio (USA)", "platform": "dreamcast"}
    q._ensure_request({"version": 1, "items": {}, "parent_request_id": P}, item, [{"id": P}])
    fp = item["fingerprint"]
    assert fp["source"] == "metadata" and fp["nearest_titles"][0]["id"] == "jgr_dc"

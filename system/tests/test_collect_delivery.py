"""#2407: a collect that ran on a PC (the Spark could not take it) ships its entries back to the library.

pack_entry / deliver_entries on the PC, import_entry / _collect_accept on the control plane; nothing outside the
entry folder is ever written."""
import hashlib
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from gbox import characters as C


def _entry(root, slug):
    d = root / slug
    (d / "textures").mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"slug": slug, "name": slug.title(), "model": "model.glb"}))
    (d / "model.glb").write_bytes(b"glTF" + bytes(range(32)))
    (d / "textures" / "skin.png").write_bytes(b"\x89PNG skin")
    return d


class _Ctx:
    def __init__(self):
        self.artifacts = []

    def artifact(self, name, data, media_type, **prov):
        self.artifacts.append((name, data, media_type, prov))


def test_an_entry_round_trips_through_a_delivery_tar(tmp_path, monkeypatch):
    monkeypatch.delenv("GBOX_CHARACTERS", raising=False)
    src, dst = tmp_path / "pc", tmp_path / "spark"
    _entry(src, "beat")
    ctx = _Ctx()
    delivered = C.deliver_entries(ctx, src, ["beat", "missing"])
    assert delivered[0]["slug"] == "beat" and delivered[0]["sha256"] == hashlib.sha256(ctx.artifacts[0][1]).hexdigest()
    assert delivered[1] == {"slug": "missing", "error": f"no collection entry missing under {src}"}
    assert ctx.artifacts[0][0] == "collection-beat.tar" and ctx.artifacts[0][3]["kind"] == "collection-entry"
    names = C.import_entry(dst, "beat", ctx.artifacts[0][1])
    assert sorted(names) == ["meta.json", "model.glb", "textures/skin.png"]
    assert (dst / "beat" / "textures" / "skin.png").read_bytes() == b"\x89PNG skin"
    assert json.loads((dst / "beat" / "meta.json").read_text())["model"] == "model.glb"
    assert not [p for p in dst.iterdir() if p.name.startswith(".beat.part")], "no leftover working folder"


def test_a_delivered_entry_replaces_the_old_one_and_lands_through_the_acceptance_hook(tmp_path, monkeypatch):
    monkeypatch.delenv("GBOX_CHARACTERS", raising=False)
    src = tmp_path / "pc"
    _entry(src, "gum")
    lib = tmp_path / "cache" / "characters"
    old = _entry(lib, "gum")
    (old / "stale.bin").write_bytes(b"old")
    data = C.pack_entry(src, "gum")
    store = SimpleNamespace(read_artifact=lambda sha: data if sha == hashlib.sha256(data).hexdigest() else None,
                            config=SimpleNamespace(cache=str(tmp_path / "cache")))
    out = SimpleNamespace(result={"delivered": [{"slug": "gum", "sha256": hashlib.sha256(data).hexdigest()},
                                                {"slug": "lost", "sha256": "0" * 64}, {"slug": "failed", "error": "x"}]})
    assert C._collect_accept(store, out, "worker") == ["gum"]
    assert not (lib / "gum" / "stale.bin").exists(), "the delivered entry replaces the old folder"
    assert (lib / "gum" / "model.glb").is_file()
    assert C._collect_accept(store, SimpleNamespace(result={"status": "ok"}), "worker") == [], "nothing delivered: nothing changes"


def test_an_entry_tar_may_only_hold_plain_files_inside_the_entry(tmp_path):
    dst = tmp_path / "spark"
    for bad in ("../escape.txt", "/abs.txt"):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name in ("meta.json", bad):
                info = tarfile.TarInfo(name)
                info.size = 2
                tar.addfile(info, io.BytesIO(b"{}"))
        with pytest.raises(ValueError, match="refusing entry member"):
            C.import_entry(dst, "evil", buf.getvalue())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("model.glb")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(ValueError, match="needs meta.json"):
        C.import_entry(dst, "half", buf.getvalue())
    assert not dst.exists() or not any(dst.iterdir()), "a refused import writes nothing"

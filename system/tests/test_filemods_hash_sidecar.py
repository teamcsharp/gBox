"""Mod manifests keep their digests across a restart, so the first launch after one doesn't re-hash a disc image."""
import hashlib
import json

from gbox import filemods


def test_digests_survive_a_restart(tmp_path, monkeypatch):
    d = tmp_path / "mods" / "g1" / "cast_x"
    d.mkdir(parents=True)
    (d / ".gbox-mod.json").write_text("{}")
    (d / "Game.iso").write_bytes(b"x" * 4096)
    want = hashlib.sha256(b"x" * 4096).hexdigest()

    first = {f["path"]: f["sha256"] for f in filemods._files(d, hashes=True)}
    assert first["Game.iso"] == want
    side = json.loads(filemods._hash_sidecar(d).read_text())
    assert side["Game.iso"][2] == want
    assert not (d / filemods._hash_sidecar(d).name).exists()      # beside the folder, never in its manifest

    filemods._HASHES.clear()                                      # a restarted service
    monkeypatch.setattr(filemods.hashlib, "file_digest", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-hashed")))
    again = {f["path"]: f["sha256"] for f in filemods._files(d, hashes=True)}
    assert again == first
    assert [f["path"] for f in filemods._files(d)] == [".gbox-mod.json", "Game.iso"]


def test_changed_file_is_rehashed(tmp_path):
    d = tmp_path / "m"
    d.mkdir()
    f = d / "a.bin"
    f.write_bytes(b"one")
    filemods._files(d, hashes=True)
    filemods._HASHES.clear()
    f.write_bytes(b"two!")
    got = filemods._files(d, hashes=True)[0]["sha256"]
    assert got == hashlib.sha256(b"two!").hexdigest()

"""gbox.switch_romfs_extract: the parallel writer works with an Nca-shaped collaboration object."""
from types import SimpleNamespace

from gbox import switch_romfs_extract as X


class FakeNca:
    header = {"sections": [{"index": 0, "fs_type": 3}]}
    _romfs_at = 0

    def romfs(self):
        return {"header": {"data_offset": 0}, "files": []}

    def read_section(self, index, offset, size):
        assert index == 0
        return bytes([size % 256]) * size


def test_extract_writes_every_entry_and_counts_bytes(tmp_path):
    entries = [{"path": f"a/b{i}.bin", "offset": i, "size": i + 1} for i in range(20)]
    out = X.extract(FakeNca(), entries, tmp_path / "tree", threads=4)
    assert out["files"] == 20 and out["bytes"] == sum(e["size"] for e in entries)
    written = sorted((tmp_path / "tree").rglob("*.bin"))
    assert len(written) == 20
    assert written[0].read_bytes() == bytes([written[0].stat().st_size % 256]) * written[0].stat().st_size


def test_extract_creates_nested_directories(tmp_path):
    out = X.extract(FakeNca(), [{"path": "nativeNXx64/arc/NX/x.arc", "offset": 0, "size": 8}],
                    tmp_path / "tree", threads=1)
    target = tmp_path / "tree" / "nativeNXx64" / "arc" / "NX" / "x.arc"
    assert target.is_file() and len(target.read_bytes()) == 8


def test_extract_reports_the_thread_count(tmp_path):
    out = X.extract(FakeNca(), [], tmp_path / "empty", threads=3)
    assert out == {"files": 0, "bytes": 0, "threads": 3, "out": str(tmp_path / "empty")}

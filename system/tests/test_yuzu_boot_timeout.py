from gbox.adapters import yuzu_boot_seconds, yuzu_log_tail


def test_boot_timeout_honoured():
    assert yuzu_boot_seconds(None) == 60
    assert yuzu_boot_seconds(90.0) == 90
    assert yuzu_boot_seconds("bad") == 60
    assert yuzu_boot_seconds(3) == 10


def test_log_tail(tmp_path):
    f = tmp_path / "yuzu_log.txt"
    f.write_text("\n".join(f"line{i}" for i in range(30)))
    t = yuzu_log_tail(f, 3)
    assert "line29" in t and "line26" not in t
    assert "no yuzu log" in yuzu_log_tail(tmp_path / "missing.txt")
    f.write_text("")
    assert "empty" in yuzu_log_tail(f)

from gbox.mercs import strategy, tuning


def test_apply_reads_strategy_each_round(tmp_path, monkeypatch):
    path = tmp_path / "strategy.json"
    monkeypatch.setattr(strategy, "PATH", path)
    monkeypatch.setattr(strategy.apply_saved, "__defaults__", (path,))
    monkeypatch.setattr(strategy.status, "__defaults__", (path,))
    monkeypatch.setattr(strategy.handle, "__defaults__", (None, None, None, path))
    stats = {}
    tuning.apply("re5", "x", stats, base=str(tmp_path))
    assert "survive=" in stats["strategy"]
    first = tuning.strategy_stack("re5")
    assert first["survive"]["enabled"]
    strategy.handle("re5", values={"survive": {"enabled": False}})
    stats2 = {}
    tuning.apply("re5", "x", stats2, base=str(tmp_path))
    assert "survive=" not in stats2["strategy"]
    assert not tuning.strategy_stack("re5")["survive"]["enabled"]

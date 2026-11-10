import importlib.util, pathlib
_p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "next_tetris_source_probe.py"
_s = importlib.util.spec_from_file_location("next_tetris_source_probe", _p)
m = importlib.util.module_from_spec(_s); _s.loader.exec_module(m)

def test_selftest_runs():
    m._selftest()

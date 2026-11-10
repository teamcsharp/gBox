import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def test_art_probe_decodes_all_streams():
    r = subprocess.run([sys.executable, os.path.join(HERE, "..", "gbox", "six_pak", "art_probe.py")],
                       capture_output=True, text=True, timeout=300, cwd=os.path.join(HERE, ".."))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: PASS" in r.stdout
    assert "sonic_intro_patterns   cart=0x29f27a" in r.stdout and "tiles= 525" in r.stdout
    assert r.stdout.count("roundtrip=OK") == 7

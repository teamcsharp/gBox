import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "..", "gbox", "six_pak", "inventory_probe.py")

def test_inventory_probe_passes():
    r = subprocess.run([sys.executable, os.path.abspath(PROBE)],
                       capture_output=True, text=True, timeout=300,
                       cwd=os.path.join(HERE, ".."))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: PASS" in r.stdout
    # exact owned-source identity must be printed
    assert "121f7c8be8a4ba1d22d96494835a25973baaacd9ad3f54c1887c4512f994b82e" in r.stdout
    assert "0x29f27a" in r.stdout  # verified native target asset (Sonic intro art)

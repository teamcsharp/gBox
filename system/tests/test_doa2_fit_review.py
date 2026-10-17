import numpy as np

from gbox import doa2_swap, fit_events, re4gc_enemies, sm64_swap


def test_refinement_comparison_uses_the_best_fit_instead_of_the_last_failed_candidate(monkeypatch):
    def geometry(n):
        return [{"pos": np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]]),
                 "tris": np.tile([0, 1, 2], (n, 1)), "jid": np.zeros(3, int)}]
    def encode(chr_data, bin_data, prims, profile, **kwargs):
        n = len(prims[0]["tris"])
        if n > 599:
            raise ValueError(f"CHR budget exceeded: {n} > 599")
        return {"report": {"triangles": n, "chr_bytes": n}, "files": {}}
    monkeypatch.setattr(doa2_swap, "encode_parts", encode)
    monkeypatch.setattr(sm64_swap, "write_rigged", lambda prims, target, path, name: path)
    monkeypatch.setattr(re4gc_enemies, "decimate", lambda src, dst, amount: dst)
    monkeypatch.setattr(sm64_swap, "read_rigged", lambda path: geometry(int(path.stem[3:])))
    comparisons = []
    monkeypatch.setattr(fit_events, "comparison", lambda before, after, **kw: comparisons.append((before, after, kw)))
    result = doa2_swap.encode_budgeted(b"chr", b"bin", geometry(1000), {}, {}, 600)
    assert result["report"]["triangles"] == 592
    assert "exceeded" in result["report"]["lod_attempts"][-1]["result"]
    before, after, data = comparisons[0]
    assert len(before[0]["tris"]) == 1000 and len(after[0]["tris"]) == 592
    assert data["limits"]["original_failure"].startswith("CHR budget exceeded")

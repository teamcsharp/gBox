from gbox.chrono_cross_decomp_findings import FINDINGS as d


def test_findings_pin_exe_and_no_unlock_claim():
    assert d["source_exe_sha256"].startswith("9a5453bf")
    assert d["functions_decompiled"] == 1240
    assert any("research_pending" in f for f in d["findings"])
    assert "cd_driver_state_0x8006af0c_0x8006af70" in d["table_region_referrers"]

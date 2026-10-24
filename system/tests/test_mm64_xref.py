import hashlib, os, pytest
from gbox import mm64_inventory as m, mm64_xref as x

ROM = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/USA/Mega Man 64 (USA).zip"
pytestmark = pytest.mark.skipif(not os.path.exists(ROM), reason="owned ROM not present")


@pytest.fixture(scope="module")
def rom():
    src, r = m.load(ROM)
    assert src["sha256"] == "65b94d0bff869aa93b0a16e7d2dcdcc85724fb3df7ea7c394c88fc317ea03d3c"
    return r


def test_loader_xrefs(rom):
    dirs = {r["func_ram"] for r in x.refs_to(rom, {x.DIR_RAM})}
    assert dirs == {x.LOADER_BY_ID, x.LOADER_ALL}
    bases = {r["func_ram"] for r in x.refs_to(rom, {x.ARCHIVE_BASE})}
    assert bases == dirs


def test_resource_table_binds_ids_to_entries(rom):
    t = x.resource_table(rom)
    assert len(t) == 1675
    assert t[:445] == list(range(445))
    assert set(t) == set(range(445))
    assert all(t.count(e) >= 1 for e in range(445))
    assert max(t) == 444

import struct
import yaml

from gbox.mercs.titles import re5_hooks as H
from gbox import re5_mods_tool as T
from test_re5_mods import FakeRE5, fresh_originals  # noqa: F401


def test_boot_hook_is_hash_pinned_and_preserves_other_patches(tmp_path):
    (tmp_path/"patches").mkdir()
    p=tmp_path/"patches"/"BLUS30491_patch.yml"
    p.write_text(yaml.safe_dump({"Version":"1.2","other":{"test":{"Patch":[]}}}))
    c=tmp_path/"patch_config.yml"
    c.write_text(yaml.safe_dump({"other":{"unchanged":True}}))
    H.install(tmp_path)
    data=yaml.safe_load(p.read_text()); cfg=yaml.safe_load(c.read_text())
    assert data["other"]=={"test":{"Patch":[]}}
    assert cfg["other"]=={"unchanged":True}
    # RPCS3 requires the address scalar to retain its hexadecimal spelling.
    assert data[H.HASH][H.NAME]["Patch"]==[
        ["be32",f"0x{H.SITE:08x}",f"0x{H.PATCHED:08x}"],
        ["be32",f"0x{H.START_SITE:08x}",f"0x{H.NOP:08x}"]]
    assert cfg[H.HASH][H.NAME]["All"]["All"]["All"]["Enabled"]
    assert p.with_suffix('.yml.gbox-mercs-backup').exists()


def test_unlock_changes_only_availability_never_scores():
    m=FakeRE5();g=T.RE5(m)
    toc,slot,save=0x1690000,0x1910010,0x38879660
    m.u32(0x1714c1c,toc);m.u32(toc-0x7fec,slot);m.u32(slot,save);m.u32(save+0x24,0)
    m.u32(save+0xa4,0);m.u32(save+0x108,9);m.u32(save+0x10c,1);m.u32(save+0x3f70,1)
    before=g.rd(save+0x110,1000)
    result=H.unlock(g)
    assert result["verified"] and len(result["changed"])==3
    assert g.u32(save+0x108)==0x3ff and g.u32(save+0x10c)==0xff
    assert g.u32(save+0xa4)==0 and g.rd(save+0x110,1000)==before
    assert H.unlock(g)["changed"]==[]

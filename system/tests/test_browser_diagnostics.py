from pathlib import Path
import psutil
from scripts import browser_diagnostics as D


class Process:
    def __init__(self,args,name='msedge.exe'):self.args=args;self.process_name=name
    def cmdline(self):return self.args
    def name(self):return self.process_name
    def username(self):return psutil.Process().username()


def test_legacy_inventory_never_adopts_user_edge_or_electron(tmp_path,monkeypatch):
    monkeypatch.setattr(D.tempfile,'gettempdir',lambda:str(tmp_path))
    owned=tmp_path/'gbox-tk-test123'
    args=['edge.exe','--headless','--user-data-dir='+str(owned)]
    assert D.legacy_root(Process(args))
    assert not D.legacy_root(Process(args,name='gBox.exe'))
    assert not D.legacy_root(Process(['edge.exe','--user-data-dir='+str(owned)]))
    assert not D.legacy_root(Process(args+['--type=renderer']))
    assert not D.legacy_root(Process(['edge.exe','--headless','--user-data-dir='+str(tmp_path/'valuable-user-profile')]))
    assert not D.legacy_root(Process(['edge.exe','--headless','--user-data-dir='+str(tmp_path/'nested'/'gbox-tk-test123')]))

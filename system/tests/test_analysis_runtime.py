import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from gbox import analysis_runtime as R,provision,rea,ghidra_bridge as G

def jdk(root,version='21.0.12',arch='amd64',compiler=True):
    (root/'bin').mkdir(parents=True)
    suffix='.exe' if os.name=='nt' else ''
    for tool in (('java','javac') if compiler else ('java',)):(root/'bin'/(tool+suffix)).touch()
    (root/'release').write_text(f'JAVA_VERSION="{version}"\nOS_ARCH="{arch}"\n')
    return root

@pytest.mark.parametrize('version,arch,compiler,valid',[
    ('21.0.12','amd64',True,True),('25','aarch64',True,True),('17.0.9','amd64',True,False),
    ('21','x86',True,False),('21','amd64',False,False),('unknown','amd64',True,False)])
def test_full_jdk_version_and_architecture(tmp_path,version,arch,compiler,valid):
    assert R.valid_java_home(jdk(tmp_path/'jdk',version,arch,compiler)) is valid

def config(tmp_path,monkeypatch,explicit=None):
    monkeypatch.setattr(provision,'jdk21',lambda cfg:None)
    monkeypatch.setattr(R.shutil,'which',lambda _:None)
    return SimpleNamespace(runtime=tmp_path,rea_env=explicit or {})

def test_stale_inherited_home_uses_existing_valid_runtime(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);good=jdk(tmp_path/'jdk-21-good')
    jdk(tmp_path/'jdk-99-broken',compiler=False)
    monkeypatch.setenv('JAVA_HOME','stale-inherited')
    env={'JAVA_HOME':os.environ['JAVA_HOME'],'PRESERVE':'yes'}
    assert R.apply_java_home(cfg,env)['JAVA_HOME']==str(good.resolve())
    assert os.environ['JAVA_HOME']=='stale-inherited' and env['PRESERVE']=='yes'

def test_explicit_home_is_preserved_even_when_unavailable(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch,{'JAVA_HOME':'explicit-missing'});jdk(tmp_path/'jdk-21')
    assert R.apply_java_home(cfg,{'JAVA_HOME':'explicit-missing'})['JAVA_HOME']=='explicit-missing'

def test_valid_inherited_home_has_priority(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);good=jdk(tmp_path/'inherited');jdk(tmp_path/'jdk-21')
    assert R.apply_java_home(cfg,{'JAVA_HOME':str(good)})['JAVA_HOME']==str(good)

def test_no_valid_local_copy_preserves_unavailability(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);jdk(tmp_path/'jdk-21',compiler=False)
    assert R.apply_java_home(cfg,{'JAVA_HOME':'missing'})=={'JAVA_HOME':'missing'}
    assert R.apply_java_home(cfg,{})=={}

def test_path_compiler_can_locate_existing_jdk(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);good=jdk(tmp_path/'installed')
    monkeypatch.setattr(R.shutil,'which',lambda _:str(good/'bin'/'javac'))
    assert R.apply_java_home(cfg,{})['JAVA_HOME']==str(good.resolve())

def test_both_analysis_services_use_same_repaired_child_environment(tmp_path,monkeypatch):
    cfg=config(tmp_path,monkeypatch);cfg.ghidra_home=None
    good=jdk(tmp_path/'jdk-21');monkeypatch.setenv('JAVA_HOME','bad-inherited')
    monkeypatch.setattr(G,'ghidra_install_dir',lambda _:None)
    assert G.Session(cfg).env()['JAVA_HOME']==str(good.resolve())
    monkeypatch.setattr(rea,'unavailable',lambda _:None)
    monkeypatch.setattr(provision,'ghidra_home',lambda _:None)
    class Captured(Exception):pass
    def popen(*a,**kw):
        assert kw['env']['JAVA_HOME']==str(good.resolve())
        assert os.environ['JAVA_HOME']=='bad-inherited'
        raise Captured()
    monkeypatch.setattr(rea.subprocess,'Popen',popen)
    with pytest.raises(Captured):rea.Session(cfg)._start()

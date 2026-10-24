"""Independent P2 routing must never fall back to the human's controller1."""
from types import SimpleNamespace
import pytest
import yaml

from gbox import adapters as A, rpcs3_coop as C
from gbox.config import Config
from gbox.registry import Unsupported
from test_rpcs3_windows_input import launch  # noqa: F401


def ready(ad, tmp_path, pid=42):
    ad.proc=SimpleNamespace(pid=pid,poll=lambda:None)
    ad.teammate_player=2
    C.install(ad,tmp_path/'pads.yml',A.RPCS3_KEYBOARD_INPUT,A._RPCS3_CFG_NAMES)
    C.launched(ad)
    assert ad.teammate_pad_status()['verified']


def test_windows_p2_launch_preserves_operator_default_and_distinct_p1_mapping(launch):
    ad,argv,_=launch(teammate_player=2)
    p=launch.home/'config/input_configs/global'
    default=(p/'Default.yml').read_text()
    data=yaml.safe_load((p/(C.CONFIG_NAME+'.yml')).read_text())
    assert data['Player 1 Input']==yaml.safe_load(default)['Player 1 Input']
    assert data['Player 2 Input']['Handler']=='Keyboard'
    assert data['Player 2 Input']['Config']['Cross']=='F13'
    assert argv[argv.index('--input-config')+1]==C.CONFIG_NAME
    assert ad.teammate_pad_status()['verified'] and not ad.keyboard_pad


def test_windows_next_new_adapter_consumes_explicit_profile_preparation(launch):
    first,_,_=launch()
    p=launch.home/'config/input_configs/global/Default.yml';before=p.read_bytes()
    assert first.prepare_teammate_pad()['requires_relaunch']
    second,argv,_=launch()
    assert second is not first and second.teammate_pad_status()['verified']
    assert argv[argv.index('--input-config')+1]==C.CONFIG_NAME
    assert p.read_bytes()==before


def test_prepare_while_running_only_saves_intent_without_touching_live_config(tmp_path):
    ad=A.RPCS3Adapter(Config(data_dir=tmp_path));ad.proc=SimpleNamespace(pid=42,poll=lambda:None)
    ad.home=tmp_path/'profile'
    p=tmp_path/'pads.yml';p.write_text(A.RPCS3_KEYBOARD_INPUT);before=p.read_bytes()
    result=ad.prepare_teammate_pad()
    assert result['requires_relaunch'] and not result['prepared'] and not result['verified']
    assert ad.teammate_player==2 and p.read_bytes()==before
    assert not hasattr(ad,'_teammate_pad_launch')
    assert C.preparation(ad)['enabled']


def test_preparation_survives_new_adapter_and_disable_preserves_player_one(tmp_path):
    cfg=Config(data_dir=tmp_path);first=A.RPCS3LinuxAdapter(cfg);first.home.mkdir(parents=True)
    p=first.home/'input_configs/global/Default.yml';p.parent.mkdir(parents=True)
    p.write_text('Player 1 Input:\n  Handler: Evdev\n  Device: Human physical pad\n')
    before=yaml.safe_load(p.read_text())['Player 1 Input']
    first.prepare_teammate_pad()
    second=A.RPCS3LinuxAdapter(cfg)
    assert second is not first and getattr(second,'teammate_player',None) is None
    second.write_settings()
    assert yaml.safe_load(p.read_text())['Player 2 Input']['Config']['Cross']=='F13'
    assert yaml.safe_load(p.read_text())['Player 1 Input']==before
    second.prepare_teammate_pad(enabled=False)
    third=A.RPCS3LinuxAdapter(cfg);third.write_settings()
    data=yaml.safe_load(p.read_text())
    assert data['Player 1 Input']==before and 'Player 2 Input' not in data
    assert third._teammate_pad_config is None


def test_invalid_or_foreign_profile_marker_never_auto_enables_controller2(tmp_path):
    ad=A.RPCS3LinuxAdapter(Config(data_dir=tmp_path));ad.home.mkdir(parents=True)
    C.marker(ad).write_text('{broken')
    assert C.preparation(ad) is None
    C.marker(ad).write_text('{"version":1,"player":2,"enabled":true,"home":"another-profile"}')
    assert C.preparation(ad) is None
    ad.write_settings()
    assert ad._teammate_pad_config is None


def test_windows_p2_posts_only_independent_keys_and_rejects_entire_mixed_batch(tmp_path,monkeypatch):
    ad=A.RPCS3Adapter(Config(data_dir=tmp_path));ready(ad,tmp_path)
    posted=[];monkeypatch.setattr(ad,'_game_window',lambda:99)
    monkeypatch.setattr(ad,'_post_key',lambda *args:posted.append(args))
    assert ad.send_input_player([{'key':'cross'},{'key':'lup','player':2}])=={'sent':2,'player':2}
    assert posted==[(99,0x7C,True),(99,ord('4'),True)]
    for bad in ([{'key':'cross'},{'key':'lup','player':1}], [{'key':'cross','player':True}],
                [{'key':'pause'}], [{'key':'cross','down':'false'}]):
        with pytest.raises(Unsupported):ad.send_input_player(bad)
        assert len(posted)==2
    with pytest.raises(Unsupported):ad.send_input_player([{'key':'cross'}],player=1)


def test_unprepared_or_mutated_launch_never_sends_p2_input(tmp_path,monkeypatch):
    ad=A.RPCS3Adapter(Config(data_dir=tmp_path));posted=[]
    monkeypatch.setattr(ad,'_post_key',lambda *args:posted.append(args))
    with pytest.raises(Unsupported):ad.send_input_player([{'key':'cross'}])
    ready(ad,tmp_path)
    (tmp_path/'pads.yml').write_text('changed')
    with pytest.raises(Unsupported):ad.send_input_player([{'key':'cross'}])
    assert posted==[]
    ready(ad,tmp_path);ad.proc.pid=43
    assert not ad.teammate_pad_status()['verified']


def test_configuration_keeps_all_other_players_and_rejects_keyboard_collisions():
    text=A.RPCS3_KEYBOARD_INPUT+'Player 3 Input:\n  Handler: XInput\n  Device: Pad3\n'
    data=yaml.safe_load(C.configuration(text,A._RPCS3_CFG_NAMES))
    assert data['Player 1 Input']==yaml.safe_load(text)['Player 1 Input']
    assert data['Player 3 Input']==yaml.safe_load(text)['Player 3 Input']
    with pytest.raises(Unsupported,match='conflict'):
        C.configuration(text.replace('Cross: X','Cross: F13'),A._RPCS3_CFG_NAMES)
    with pytest.raises(Unsupported,match='conflict'):
        C.configuration(text.replace('Cross: X','Cross: Ctrl+f13'),A._RPCS3_CFG_NAMES)


def test_linux_p2_keys_are_independent_and_do_not_rewrite_port_to_one(tmp_path,monkeypatch):
    ad=A.RPCS3LinuxAdapter(Config(data_dir=tmp_path));ready(ad,tmp_path)
    calls=[];monkeypatch.setattr(ad,'_maybe_focus_game_window',lambda:None)
    monkeypatch.setattr(ad,'_xdo',lambda *args:calls.append(args))
    assert ad.send_input_player([{'key':'cross'},{'key':'cross','down':False},{'key':'lup'}])['player']==2
    assert calls==[('keydown','F13','sleep','.06','keyup','F13','keydown','4')]
    assert ad.send_input_player([{'key':'rleft'},{'key':'rright'}])['sent']==2
    assert calls[-1]==('keydown','bracketleft','keydown','bracketright')
    with pytest.raises(Unsupported):ad.send_input_player([{'key':'cross','player':1}])
    assert len(calls)==2


def test_linux_optin_preserves_existing_player_one_controller(tmp_path):
    ad=A.RPCS3LinuxAdapter(Config(data_dir=tmp_path));ad.home.mkdir(parents=True)
    p=ad.home/'input_configs/global/Default.yml';p.parent.mkdir(parents=True)
    p.write_text('Player 1 Input:\n  Handler: Evdev\n  Device: Human physical pad\n')
    before=yaml.safe_load(p.read_text())['Player 1 Input']
    ad.prepare_teammate_pad();ad.write_settings()
    data=yaml.safe_load(p.read_text())
    assert data['Player 1 Input']==before and data['Player 2 Input']['Handler']=='Keyboard'
    assert not ad.teammate_pad_status()['prepared']  # Writing a file is not a native launch.

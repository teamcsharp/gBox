"""Port collision recovery owns only the failed launch, never a responding peer."""
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import adapters, game_audio as ga
from gbox.config import Config, EmulatorConfig, GameAudioConfig
from test_game_audio import FakeProc, log


def launch(monkeypatch, tmp_path, outcomes, *, foreign_status=False, configured=True):
    monkeypatch.setattr(adapters, 'HOST_OS', 'windows')
    monkeypatch.setattr(adapters, '_audio_release', lambda ad: None)
    monkeypatch.setattr(adapters, '_examine_ok', lambda *a: False)
    from gbox import gamepads, graphics, memory_card_sessions
    monkeypatch.setattr(gamepads, 'emulator_environment', lambda env: env)
    monkeypatch.setattr(gamepads, 'retroarch_driver', lambda exe: 'sdl3')
    monkeypatch.setattr(graphics, 'get', lambda *a: {})
    monkeypatch.setattr(graphics, 'retroarch_opts', lambda *a: {})
    monkeypatch.setattr(memory_card_sessions, 'launched', lambda ad: None)
    monkeypatch.setattr(adapters.provision, 'retroarch_exe', lambda cfg: str(tmp_path/'retroarch.exe'))
    cfg = Config(data_dir=tmp_path, runtime_dirs={'windows':str(tmp_path/'runtime')})
    ad = adapters.RetroArchAdapter(EmulatorConfig(core='flycast'), config=cfg if configured else None,
                                  platform='dreamcast', port=50123)
    monkeypatch.setattr(ad, '_audio_plan', lambda: {'ga':GameAudioConfig(), 'chain':['xaudio','wasapi','null'], 'sel':None})
    monkeypatch.setattr(ad, 'install_cheats', lambda *a: [])
    monkeypatch.setattr(ad, '_argv', lambda rom: ['retroarch', *(['--config',str(ad._write_cfg())] if configured else []),
                                               '-L','flycast',rom])
    launches = []; killed = []; closed = []; queried = []
    ad.display = SimpleNamespace(name='owned-display', close=lambda:closed.append(True))
    def popen(_ad, argv, **kw):
        text = Path(argv[argv.index('--config')+1]).read_text() if '--config' in argv else ''
        driver = text.split('audio_driver = "')[1].split('"')[0] if text else ad.audio_driver
        outcome = outcomes[min(len(launches),len(outcomes)-1)]
        proc = FakeProc(ad.log_path, log('netcmd_bind_failed.log') if outcome=='netcmd' else 'owned attempt '+outcome)
        remote_port = text.split('network_remote_base_port = "')[1].split('"')[0] if text else None
        launches.append({'driver':driver,'port':ad.addr[1],'remote_port':remote_port,'log':str(ad.log_path),
                         'proc':proc,'outcome':outcome,'argv':list(argv)})
        kw['stdout'].close()
        return proc
    monkeypatch.setattr(adapters, '_popen', popen)
    monkeypatch.setattr(adapters, '_kill_tree', lambda proc:(killed.append(proc),proc.kill()) if proc else None)
    if foreign_status:
        def query(timeout):
            queried.append(ad.addr[1])
            return {'running':True,'state':'PLAYING','content':'other game'}
        monkeypatch.setattr(ad,'query_runtime',query)
    else:
        def wait(watch):
            outcome=launches[-1]['outcome']
            watch.reason = 'bind failed' if outcome=='netcmd' else 'audio stalled' if outcome=='fallback' else None
            return outcome, {'state':'PLAYING'} if outcome=='ready' else None
        monkeypatch.setattr(ad,'_wait_boot',wait)
    return ad, launches, killed, closed, queried


@pytest.mark.parametrize('running',[False,True])
def test_own_bind_failure_wins_over_a_peer_status(running):
    watch=ga.BootWatch(0)
    watch.observe(log('netcmd_bind_failed.log'),1)
    assert watch.decide(1,running)=='netcmd'
    assert 'command interface' in watch.reason


def test_bind_failure_never_accepts_or_queries_the_conflicting_peer(monkeypatch,tmp_path):
    ad,attempts,killed,closed,queried=launch(monkeypatch,tmp_path,['netcmd','ready'],foreign_status=True)
    out=ad.launch_game('owned.chd')
    assert len(attempts)==2
    assert attempts[0]['port']!=attempts[1]['port']
    assert attempts[0]['remote_port']==attempts[1]['remote_port']
    assert attempts[0]['argv'][-3:]==attempts[1]['argv'][-3:]==['-L','flycast','owned.chd']
    assert queried==[attempts[1]['port']]
    assert killed==[attempts[0]['proc']] and attempts[1]['proc'].alive
    assert not closed
    assert out['port']==attempts[1]['port']
    assert Path(attempts[0]['log']).read_text()==log('netcmd_bind_failed.log')
    assert not (ad.config.runtime/ga.STATE_FILE).exists()


def test_port_retry_preserves_the_current_audio_fallback(monkeypatch,tmp_path):
    ad,attempts,killed,closed,queried=launch(monkeypatch,tmp_path,['fallback','netcmd','ready'])
    out=ad.launch_game('owned.chd')
    assert [a['driver'] for a in attempts]==['xaudio','wasapi','wasapi']
    assert [a['driver'] for a in out['audio']['attempts']]==[a['driver'] for a in attempts]
    assert [a['port'] for a in out['audio']['attempts']]==[a['port'] for a in attempts]
    assert out['audio']['driver']=='wasapi'
    assert ga.first_driver(ad.config.runtime,None,24)=='wasapi'
    assert len(killed)==2 and attempts[-1]['proc'].alive and not closed


def test_repeated_bind_failure_stops_after_two_port_retries_without_audio_fallback(monkeypatch,tmp_path):
    ad,attempts,killed,closed,queried=launch(monkeypatch,tmp_path,['netcmd'])
    with pytest.raises(RuntimeError,match='network command interface'):
        ad.launch_game('owned.chd')
    assert len(attempts)==3
    assert len({a['port'] for a in attempts})==3
    assert [a['driver'] for a in attempts]==['xaudio']*3
    assert all(not a['proc'].alive for a in attempts) and closed
    assert all(Path(a['log']).read_text()==log('netcmd_bind_failed.log') for a in attempts)
    assert not (ad.config.runtime/ga.STATE_FILE).exists()


def test_without_owned_config_bind_failure_is_explicit_and_not_retried(monkeypatch,tmp_path):
    ad,attempts,killed,closed,queried=launch(monkeypatch,tmp_path,['netcmd'],configured=False)
    with pytest.raises(RuntimeError,match='network command interface'):
        ad.launch_game('owned.chd')
    assert len(attempts)==1 and not attempts[0]['proc'].alive and closed


@pytest.mark.parametrize('failure',['allocate','config','cancel'])
def test_port_retry_preparation_failure_cleans_only_the_owned_attempt(monkeypatch,tmp_path,failure):
    ad,attempts,killed,closed,queried=launch(monkeypatch,tmp_path,['netcmd','ready'])
    def fail(*a,**kw):raise RuntimeError('injected '+failure)
    if failure=='allocate':monkeypatch.setattr(ad,'_rebind_port',fail)
    elif failure=='config':
        original=ad._write_cfg
        monkeypatch.setattr(ad,'_write_cfg',lambda:fail() if attempts else original())
    else:ad.progress=lambda pct,message:fail() if 'fresh port' in message else None
    with pytest.raises(RuntimeError,match='injected '+failure):ad.launch_game('owned.chd')
    assert len(attempts)==1 and not attempts[0]['proc'].alive and closed


def test_rebind_preserves_an_unrelated_udp_listener():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
        peer.bind(('127.0.0.1',0));old=peer.getsockname()[1]
        ad=adapters.RetroArchAdapter(EmulatorConfig(core='x'),port=old)
        ad._rebind_port()
        assert ad.addr[0]=='127.0.0.1' and ad.addr[1]!=old
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sender:
            sender.sendto(b'peer remains alive',peer.getsockname())
        peer.settimeout(1)
        assert peer.recv(100)==b'peer remains alive'

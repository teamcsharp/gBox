"""Installer edits are exercised only against temporary fixture files."""
import importlib.util
from pathlib import Path
import sys

import pytest

PATH=Path(__file__).resolve().parents[1]/'install_gateway.py'
spec=importlib.util.spec_from_file_location('pine_install_gateway_fixture',PATH)
G=importlib.util.module_from_spec(spec);sys.modules[spec.name]=G;spec.loader.exec_module(G)

APP='''import os

async def unrelated():
    return uvicorn.Config(PublicListenerGate(app), host="0.0.0.0", port=1234)

@app.on_event("startup")
async def _startup_public_door() -> None:
    if not PUBLIC_ENABLED or PUBLIC_PORT == STATION_PORT:
        return
    try:
        import uvicorn
        config = uvicorn.Config(PublicListenerGate(app), host="0.0.0.0",
                                port=PUBLIC_PORT, access_log=False)
        server = uvicorn.Server(config)
        asyncio.create_task(server.serve())
    except Exception:
        pass

def later():
    return "untouched"
'''

COMPOSE='''name: preserved
services:
  other:
    environment:
      SPARK_PUBLIC_PORT: '9999'
      SECRET: "do not reserialize: # exact bytes"
  spark-agent:
    image: fixture
    env_file:
      - private.env
    environment:
      # Preserve comments and quoted values exactly.
      TZ: America/Chicago
      SECRET: "sensitive: # fixture only"
      MULTILINE: >-
        keep this text
    volumes:
      - ./spark-agent:/app
  after:
    environment:
      UNRELATED: yes
volumes:
  preserved: {}
'''


def hashes(plan):
    return {'expected_app_sha256':G.digest(plan[0].before),'expected_compose_sha256':G.digest(plan[1].before)}


@pytest.fixture
def stack(tmp_path):
    (tmp_path/'spark-agent').mkdir()
    (tmp_path/'spark-agent/app.py').write_bytes(APP.encode())
    (tmp_path/'compose.yaml').write_bytes(COMPOSE.encode())
    return tmp_path


def test_existing_app_change_is_scoped_and_idempotent():
    changed=G.patch_existing_app(APP)
    assert changed.count(G.NEW)==1 and changed.count(G.OLD)==1
    assert changed.replace(G.NEW,G.OLD)==APP
    assert G.patch_existing_app(changed)==changed
    crlf=APP.replace('\n','\r\n')
    assert G.patch_existing_app(crlf).replace(G.NEW,G.OLD)==crlf


@pytest.mark.parametrize('text',[
    APP.replace('async def _startup_public_door','def _startup_public_door'),
    APP+APP,
    APP.replace('host="0.0.0.0"','host="127.0.0.1"'),
    APP.replace('import os\n',''),
    APP.replace('        config = '+G.OLD,'        config = unknown('),
])
def test_unexpected_app_refuses(text):
    with pytest.raises(ValueError):G.patch_existing_app(text)


def test_compose_preserves_every_other_byte_and_targets_one_service():
    changed=G.patch_compose(COMPOSE)
    added="      SPARK_PUBLIC_PORT: '18097'\n      PINE_GBOX_PUBLIC_BACKEND_HOST: '127.0.0.1'\n"
    assert changed.replace(added,'',1)==COMPOSE
    assert G.patch_compose(changed)==changed
    assert "SPARK_PUBLIC_PORT: '9999'" in changed
    assert G.patch_compose(COMPOSE.replace('\n','\r\n')).replace(added.replace('\n','\r\n'),'',1)==COMPOSE.replace('\n','\r\n')


@pytest.mark.parametrize('text',[
    COMPOSE.replace('  spark-agent:','  renamed:'),
    COMPOSE.replace('    environment:\n      #','    environment: {}\n      #'),
    COMPOSE.replace('      TZ: America/Chicago',"      SPARK_PUBLIC_PORT: '8097'"),
    COMPOSE.replace('      TZ: America/Chicago',"      SPARK_PUBLIC_PORT: '18097'\n      SPARK_PUBLIC_PORT: '18097'"),
    COMPOSE.replace('      TZ: America/Chicago','      - TZ=America/Chicago'),
    COMPOSE.replace('      TZ: America/Chicago','      <<: *shared'),
    COMPOSE.replace('      TZ: America/Chicago',"      'SPARK_PUBLIC_PORT': '18097'"),
    COMPOSE.replace('    environment:\n      #','    environment:\n    environment:\n      #'),
    COMPOSE.replace('  spark-agent:\n','  spark-agent:\n  spark-agent:\n'),
    COMPOSE.replace('      TZ:', '\tTZ:'),
])
def test_unexpected_or_conflicting_compose_refuses(text):
    with pytest.raises(ValueError):G.patch_compose(text)


def test_prepare_is_read_only_and_install_backs_up_only_two_reviewed_files(stack):
    plan=G.prepare(stack)
    assert all(item.summary()['changed'] for item in plan)
    assert not (stack/'spark-agent/backups').exists()
    assert (stack/'compose.yaml').read_bytes()==COMPOSE.encode()
    receipt=G.install(stack,**hashes(plan))
    assert receipt['restarted'] is False and len(receipt['changed'])==2
    backup=Path(receipt['backup'])
    assert (backup/'spark-agent/app.py').read_bytes()==APP.encode()
    assert (backup/'compose.yaml').read_bytes()==COMPOSE.encode()
    assert sorted(str(p.relative_to(backup)) for p in backup.rglob('*') if p.is_file())==['compose.yaml','spark-agent/app.py']
    assert G.install(stack,**hashes(G.prepare(stack)))=={'changed':[],'backup':None,'restarted':False}


def test_hash_mismatch_and_invalid_second_file_never_write_first(stack):
    with pytest.raises(ValueError):G.install(stack,expected_app_sha256='0'*64,expected_compose_sha256='0'*64)
    assert not (stack/'spark-agent/backups').exists()
    (stack/'compose.yaml').write_text('services: {}\n')
    with pytest.raises(ValueError):G.prepare(stack)
    assert (stack/'spark-agent/app.py').read_bytes()==APP.encode()


def test_replace_failure_rolls_back_first_active_file(stack,monkeypatch):
    plan=G.prepare(stack);original=G.atomic_replace
    def fail(path,raw,mode):
        if path==stack/'compose.yaml' and raw!=COMPOSE.encode():raise OSError('synthetic failure')
        original(path,raw,mode)
    monkeypatch.setattr(G,'atomic_replace',fail)
    with pytest.raises(OSError):G.install(stack,**hashes(plan))
    assert (stack/'spark-agent/app.py').read_bytes()==APP.encode()
    assert (stack/'compose.yaml').read_bytes()==COMPOSE.encode()


def test_error_after_atomic_replace_is_also_rolled_back(stack,monkeypatch):
    plan=G.prepare(stack);original=G.atomic_replace;failed=False
    def fail(path,raw,mode):
        nonlocal failed
        original(path,raw,mode)
        if path==stack/'compose.yaml' and not failed:
            failed=True;raise OSError('synthetic post-replace fsync failure')
    monkeypatch.setattr(G,'atomic_replace',fail)
    with pytest.raises(OSError):G.install(stack,**hashes(plan))
    assert (stack/'spark-agent/app.py').read_bytes()==APP.encode()
    assert (stack/'compose.yaml').read_bytes()==COMPOSE.encode()

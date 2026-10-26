"""scripts/deploy_main.sh keeps genuine share-side edits but overwrites stale copies of older main versions.

The guard used to compare a differing share file only with the previously deployed main, so a share copy that
had fallen behind to an OLDER main commit counted as a "share edit" and blocked every later change to that file
(gbox/characters.py sat at main 90433ea for 18 hours). These tests run the script's own classify/share_edited
functions in bash against a throwaway git repository and share folder.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'deploy_main.sh'
BASH = shutil.which('bash')
pytestmark = pytest.mark.skipif(not BASH or not shutil.which('git'), reason='needs bash and git')


def _functions():
    text = SCRIPT.read_text(encoding='utf-8').replace('\r\n', '\n')
    depth = re.search(r'^HISTORY_DEPTH=.*$', text, re.M).group(0)
    bodies = [re.search(r'^%s\(\) \{.*?^\}$' % name, text, re.M | re.S).group(0)
              for name in ('share_edited', 'classify')]
    return '\n'.join([depth, *bodies])


def _git(repo, *args):
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.autocrlf=false',
                    *args], check=True, capture_output=True)


@pytest.fixture
def deploy(tmp_path):
    src, dst = tmp_path / 'src', tmp_path / 'share'
    (src / 'system' / 'gbox').mkdir(parents=True)
    dst.mkdir()
    subprocess.run(['git', 'init', '-q', str(src)], check=True)
    versions = ['def f():\n    return 1\n', 'def f():\n    return 2\n', 'def f():\n    return 3\n']
    for i, body in enumerate(versions):
        for name in ('stale.py', 'edited.py', 'same.py', 'new.py'):
            (src / 'system' / 'gbox' / name).write_bytes(body.encode())
        _git(src, 'add', '-A')
        _git(src, 'commit', '-q', '-m', f'v{i + 1}')
    crlf = lambda s: s.replace('\n', '\r\n').encode()
    (dst / 'gbox').mkdir()
    (dst / 'gbox' / 'stale.py').write_bytes(crlf(versions[0]))           # an OLDER main version, CRLF on the share
    (dst / 'gbox' / 'edited.py').write_bytes(crlf('def f():\n    return 42  # hot fix on the share\n'))
    (dst / 'gbox' / 'same.py').write_bytes(crlf(versions[2]))            # equal to HEAD

    def classify(rel):
        script = tmp_path / 'guard.sh'
        script.write_bytes(('python3() { "$DEPLOY_TEST_PYTHON" "$@"; }\n' + _functions()
                            + '\nclassify "$1"\nprintf "%s|%s" "$ACTION" "$GUARD_RULE"\n').encode())
        env = os.environ | {'SRC': src.as_posix(), 'DST': dst.as_posix(),
                            'DEPLOY_TEST_PYTHON': Path(sys.executable).as_posix()}
        out = subprocess.run([BASH, script.as_posix(), rel], env=env, capture_output=True, text=True, check=True)
        return out.stdout.split('|', 1)
    return classify


def test_stale_copy_of_an_older_main_version_is_overwritten(deploy):
    action, rule = deploy('gbox/stale.py')
    assert action == 'stale'
    assert rule.startswith('stale copy of main ')


def test_genuine_share_edit_is_kept(deploy):
    action, rule = deploy('gbox/edited.py')
    assert action == 'edit'
    assert 'matches none of the last 200 main versions' in rule


def test_share_equal_to_head_is_a_no_op(deploy):
    assert deploy('gbox/same.py')[0] == 'same'


def test_missing_share_file_is_deployed(deploy):
    assert deploy('gbox/new.py')[0] == 'new'


def test_deploy_loop_uses_the_history_rule():
    text = SCRIPT.read_text(encoding='utf-8')
    assert 'stale) changed+=' in text and 'edit) kept+=' in text
    assert '$PREV:system/$rel' not in text          # the old previous-deploy-only comparison is gone


def _invoke_deploy(tmp_path, *args):
    # The first git command records its arguments and aborts. Even the explicit
    # path never contacts a remote, copies source files or restarts a service.
    probe = tmp_path / 'git-called'
    lock = tmp_path / 'deploy.lock'
    script = ('git() { printf "%s\\n" "$*" >> "$DEPLOY_TEST_PROBE"; return 73; }\n'
              'flock() { return 0; }\n' + SCRIPT.read_text(encoding='utf-8'))
    env = os.environ | {'GBOX_SRC': (tmp_path / 'missing-src').as_posix(),
                        'GBOX_DST': (tmp_path / 'missing-share').as_posix(),
                        'GBOX_DEPLOY_LOCK': lock.as_posix(), 'DEPLOY_TEST_PROBE': probe.as_posix()}
    result = subprocess.run([BASH, '-s', '--', *args], input=script, env=env,
                            cwd=tmp_path, capture_output=True, text=True)
    return result, probe, lock


@pytest.mark.parametrize('args', [(), ('--no-restart',), ('--help',)])
def test_unrequested_deployment_never_reaches_files_or_network(tmp_path, args):
    result, probe, lock = _invoke_deploy(tmp_path, *args)
    assert result.returncode == 0, result.stderr
    assert '--deploy' in result.stdout
    assert not probe.exists() and not lock.exists()
    assert not (tmp_path / 'missing-src').exists() and not (tmp_path / 'missing-share').exists()


def test_unknown_deployment_argument_is_rejected_without_changes(tmp_path):
    result, probe, lock = _invoke_deploy(tmp_path, '--deploy', '--force')
    assert result.returncode == 2
    assert 'Unknown argument' in result.stderr
    assert not probe.exists() and not lock.exists()


@pytest.mark.parametrize('args', [('--deploy',), ('--deploy', '--no-restart'), ('--no-restart', '--deploy')])
def test_explicit_deployment_reaches_the_transfer_path(tmp_path, args):
    result, probe, lock = _invoke_deploy(tmp_path, *args)
    assert result.returncode == 73, result.stderr
    assert probe.read_text().startswith('clone -q ')
    assert lock.exists()


# --- bot-only deploys reload the bots in place instead of restarting gbox.service (docs/hot-update.md) ---------------------
SYSTEM = SCRIPT.parents[1]


def _function(name):
    text = SCRIPT.read_text(encoding='utf-8').replace('\r\n', '\n')
    return re.search(r'^%s\(\) \{.*?^\}$' % name, text, re.M | re.S).group(0)


def _env(tmp_path, **kw):
    path = os.pathsep.join([str(SYSTEM), os.environ.get('PYTHONPATH', '')])
    return os.environ | {'DST': tmp_path.as_posix(), 'PY': Path(sys.executable).as_posix(), 'PYTHONPATH': path,
                         'PENDING': (tmp_path / 'restart-pending').as_posix(),
                         'RELOAD_PENDING': (tmp_path / 'reload-pending').as_posix()} | kw


def _activation(tmp_path, *files, pending=False, reload_pending=False, **env):
    for name, on in (('restart-pending', pending), ('reload-pending', reload_pending)):
        (tmp_path / name).unlink(missing_ok=True)
        if on:
            (tmp_path / name).write_text('')
    script = tmp_path / 'activation.sh'
    script.write_bytes((_function('activation_for') + '\nactivation_for "$@"\nprintf "%s" "$ACTIVATION"\n').encode())
    out = subprocess.run([BASH, script.as_posix(), *files], env=_env(tmp_path, **env), capture_output=True, text=True,
                         check=True)
    return out.stdout


def test_a_pure_bot_change_reloads_and_anything_else_restarts(tmp_path):
    assert _activation(tmp_path, 'gbox/mercs/titles/re5_combat.py', 'gbox/mercs/titles/re5_ps3.py') == 'reload'
    assert _activation(tmp_path, 'gbox/re4_merc_bot.py', 'gbox/re4_threats.py', 'gbox/mercs/round_map.py') == 'reload'
    assert _activation(tmp_path, 'gbox/mercs/titles/re5_combat.py', 'gbox/screensaver.py') == 'restart'
    assert _activation(tmp_path, 'gbox/server.py') == 'restart'
    assert _activation(tmp_path, 'gbox/mercs/warm_boot.py') == 'restart', 'the warm pool is not bot logic'
    assert _activation(tmp_path, 'profiles/gamedata/BLUS30491-ram.json') == 'restart'


def test_pending_activations_and_a_broken_classifier(tmp_path):
    assert _activation(tmp_path) == 'none'
    assert _activation(tmp_path, reload_pending=True) == 'reload', 'a deferred reload is retried'
    assert _activation(tmp_path, 'gbox/mercs/titles/re5_combat.py', pending=True) == 'restart', 'a deferred restart wins'
    assert _activation(tmp_path, reload_pending=True, pending=True) == 'restart'
    assert _activation(tmp_path, 'gbox/mercs/titles/re5_combat.py', PY=(tmp_path / 'no-python').as_posix()) == \
        'restart', 'no classifier: the old behaviour'


def _bot_reload(tmp_path, answers, token=True):
    """deploy_main.sh's bot_reload with curl answering the canned route answers in turn (sleep and log stubbed)."""
    if token:
        (tmp_path / 'gbox-data').mkdir(exist_ok=True)
        (tmp_path / 'gbox-data' / 'api_token').write_text('tok')
    (tmp_path / 'answers.txt').write_text(''.join(a + '\n' for a in answers))
    (tmp_path / 'count').write_text('0')
    (tmp_path / 'curl.log').unlink(missing_ok=True)
    script = tmp_path / 'reload.sh'
    script.write_bytes((
        'curl() { printf "%s\\n" "$*" >> "$CURL_LOG"; n=$(( $(cat "$COUNT") + 1 )); echo "$n" > "$COUNT"; '
        'sed -n "${n}p" "$ANSWERS"; }\n'
        'sleep() { :; }\nlog() { :; }\n' + _function('bot_reload')
        + '\nbot_reload\nprintf "%s|%s" "$RELOAD_RESULT" "$RELOAD_WHY"\n').encode())
    env = _env(tmp_path, CURL_LOG=(tmp_path / 'curl.log').as_posix(), COUNT=(tmp_path / 'count').as_posix(),
               ANSWERS=(tmp_path / 'answers.txt').as_posix(), GBOX_WORKER='lilspark',
               API_BASE='http://127.0.0.1:8765')
    out = subprocess.run([BASH, script.as_posix()], env=env, capture_output=True, text=True, check=True).stdout
    calls = (tmp_path / 'curl.log').read_text().splitlines() if (tmp_path / 'curl.log').exists() else []
    return out.split('|', 1), calls


def _answer(**result):
    import json
    return json.dumps({'job_id': 'j', 'state': 'succeeded', 'result': result})


def test_the_deploy_asks_this_hosts_worker_to_reload(tmp_path):
    (kind, why), calls = _bot_reload(tmp_path, [_answer(ok=True, reason='2 bot module(s) reloaded; 1 of 1 autobot(s) back in 1.8 s')])
    assert (kind, why) == ('reloaded', '2 bot module(s) reloaded; 1 of 1 autobot(s) back in 1.8 s')
    assert len(calls) == 1 and 'http://127.0.0.1:8765/api/workers/lilspark/bot-reload' in calls[0]
    assert 'x-gbox-actor: deploy' in calls[0] and 'Authorization: Bearer tok' in calls[0] and '"wait_s"' in calls[0]


def test_a_busy_worker_is_retried_then_deferred(tmp_path):
    busy = _answer(ok=False, retry=True, reason='a MercMode round preparation is running on w1-x')
    (kind, _), calls = _bot_reload(tmp_path, [busy, busy, _answer(ok=True, reason='done')])
    assert kind == 'reloaded' and len(calls) == 3
    (kind, why), calls = _bot_reload(tmp_path, [busy] * 6)
    assert kind == 'busy' and 'round preparation' in why and len(calls) == 4


def test_refused_and_failed_reloads(tmp_path):
    (kind, why), _ = _bot_reload(tmp_path, [_answer(ok=False, reason='gbox.mercs_bot does not import: SyntaxError')])
    assert kind == 'refused' and 'does not import' in why, 'old modules kept: no restart'
    (kind, _), _ = _bot_reload(tmp_path, [_answer(ok=False, restart=True, reason='not bot modules')])
    assert kind == 'failed', 'only a restart applies it'
    (kind, why), _ = _bot_reload(tmp_path, ['{"detail": "lilspark runs gBox code without bot_reload"}'])
    assert kind == 'failed' and 'without bot_reload' in why
    (kind, _), calls = _bot_reload(tmp_path, [''])
    assert kind == 'failed' and len(calls) == 1, 'no answer at all (route down): the restart path'
    fresh = tmp_path / 'no-token'
    fresh.mkdir()
    (kind, why), calls = _bot_reload(fresh, [], token=False)
    assert kind == 'failed' and 'api_token' in why and calls == []


def test_the_deploy_never_restarts_for_a_reload_it_could_do():
    text = SCRIPT.read_text(encoding='utf-8')
    reload_branch = text[text.index('if [ "$ACTIVATION" = reload ]; then\n  bot_reload'):text.index('LAST_RESTART=')]
    assert 'systemctl' not in reload_branch
    assert 'reloaded)' in reload_branch and 'busy)' in reload_branch and 'refused)' in reload_branch
    assert 'exit 1' in reload_branch.split('refused)')[1].split(';;')[0], 'broken bot code: an error, never a restart'
    assert 'rm -f "$PENDING" "$RELOAD_PENDING"' in text, 'a restart covers a pending reload'

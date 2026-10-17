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
        script.write_bytes((_functions() + '\nclassify "$1"\nprintf "%s|%s" "$ACTION" "$GUARD_RULE"\n').encode())
        env = os.environ | {'SRC': src.as_posix(), 'DST': dst.as_posix()}
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

import json
import subprocess
from types import SimpleNamespace

import pytest

from gbox import hermes_delivery as delivery


@pytest.fixture
def tracked_repo(tmp_path, monkeypatch):
    origin, repo = tmp_path / 'origin', tmp_path / 'repo'
    def git(*args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
    git('init', '--bare', str(origin))
    git('init', '-b', 'main', str(repo))
    git('config', 'user.name', 'Test', cwd=repo)
    git('config', 'user.email', 'test@example.invalid', cwd=repo)
    (repo / 'system/gbox').mkdir(parents=True)
    (repo / 'system/tests').mkdir()
    (repo / 'system/gbox/value.py').write_text('VALUE = 1\n')
    (repo / 'system/tests/test_value.py').write_text('import runpy\ndef test_value():\n    assert runpy.run_path("gbox/value.py")["VALUE"] == 2\n')
    git('add', '.', cwd=repo); git('commit', '-m', 'baseline', cwd=repo)
    git('remote', 'add', 'origin', str(origin), cwd=repo); git('push', '-u', 'origin', 'main', cwd=repo)
    monkeypatch.setenv('GBOX_HERMES_REPO', str(repo))
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'state'))
    return repo, origin, git


def test_prepare_reuses_dirty_workspace_without_losing_patch(tracked_repo):
    first = delivery.prepare('abcdef0123456789', 12)
    from pathlib import Path
    changed = Path(first['workdir']) / 'gbox/value.py'
    changed.write_text('VALUE = 2\n')
    second = delivery.prepare('abcdef0123456789', 12)
    assert second['reused'] and first['branch'] == second['branch']
    assert changed.read_text() == 'VALUE = 2\n'


def test_failed_validation_never_commits_or_publishes(tracked_repo):
    _, _, git = tracked_repo
    task = delivery.prepare('abcdef0123456789', 12)
    with pytest.raises(RuntimeError, match='failed'):
        delivery.publish(task['request_id'], 'Fix value', ['system/gbox/value.py'], ['tests/test_value.py'])
    assert git('rev-parse', 'HEAD', cwd=task['path']) == task['baseline']
    assert 'published_at' not in json.loads(delivery._record_path(task['request_id']).read_text())
    with pytest.raises(ValueError, match='explicit source'):
        delivery.publish(task['request_id'], 'No secrets', ['../../credentials'], [])


def test_publish_runs_tests_and_pushes_actual_commit_before_pr(tracked_repo, monkeypatch):
    _, origin, git = tracked_repo
    from pathlib import Path
    task = delivery.prepare('abcdef0123456789', 12)
    (Path(task['workdir']) / 'gbox/value.py').write_text('VALUE = 2\n')
    real_run = subprocess.run
    def fake_gh(args, **kw):
        if args[0] != 'gh': return real_run(args, **kw)
        if args[1:3] == ['pr', 'view']:
            return SimpleNamespace(returncode=1, stdout='', stderr='')
        assert args[1:3] == ['pr', 'create'] and '--draft' in args
        assert git('rev-parse', 'refs/heads/' + task['branch'], cwd=origin) != task['baseline']
        return SimpleNamespace(returncode=0, stdout='https://github.com/teamcsharp/gBox/pull/123\n', stderr='')
    monkeypatch.setattr(delivery.subprocess, 'run', fake_gh)
    result = delivery.publish(task['request_id'], 'Fix value', ['system/gbox/value.py'], ['tests/test_value.py'])
    assert '1 passed' in result['checks'][0]
    assert result['commit'] == git('rev-parse', 'refs/heads/' + task['branch'], cwd=origin)
    assert result['url'].endswith('/pull/123')

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
    monkeypatch.setenv('GBOX_HERMES_HOME', str(tmp_path / 'missing-hermes'))
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
    record = delivery._record_path(task['request_id'])
    saved = json.loads(record.read_text()); saved['local_model'] = {'label': 'local model', 'labelled': True}
    record.write_text(json.dumps(saved))
    (Path(task['workdir']) / 'gbox/value.py').write_text('VALUE = 2\n')
    real_run = subprocess.run
    def fake_gh(args, **kw):
        if args[0] != 'gh': return real_run(args, **kw)
        if args[1:3] == ['pr', 'list']:
            assert args[args.index('--state') + 1] == 'open'
            return SimpleNamespace(returncode=0, stdout='[]', stderr='')
        if args[1:3] == ['pr', 'view']:
            return SimpleNamespace(returncode=0, stdout=json.dumps(_pull(task, git)), stderr='')
        assert args[1:3] == ['pr', 'create'] and '--draft' in args
        assert git('rev-parse', 'refs/heads/' + task['branch'], cwd=origin) != task['baseline']
        return SimpleNamespace(returncode=0, stdout='https://github.com/teamcsharp/gBox/pull/123\n', stderr='')
    monkeypatch.setattr(delivery.subprocess, 'run', fake_gh)
    result = delivery.publish(task['request_id'], 'Fix value', ['system/gbox/value.py'], ['tests/test_value.py'])
    assert '1 passed' in result['checks'][0]
    assert result['commit'] == git('rev-parse', 'refs/heads/' + task['branch'], cwd=origin)
    assert result['url'].endswith('/pull/123')
    assert result['provenance']['status'] == 'unknown'
    assert 'local_model' not in result  # no inherited claim from an earlier global route
    receipt = delivery.state_dir() / 'publications' / ('123-' + result['commit'] + '.json')
    assert json.loads(receipt.read_text())['provenance'] == result['provenance']


def test_resumed_publication_updates_existing_pr_after_push(tracked_repo, monkeypatch):
    _, origin, git = tracked_repo
    from pathlib import Path
    task = delivery.prepare('abcdef0123456789', 12)
    (Path(task['workdir']) / 'gbox/value.py').write_text('VALUE = 2\n')
    real_run, updates = subprocess.run, []
    title = 'Revised fix: literal $(value) and `details`'

    def fake_gh(args, **kw):
        if args[0] != 'gh':
            return real_run(args, **kw)
        if args[1:3] == ['pr', 'list']:
            return SimpleNamespace(returncode=0, stdout=json.dumps([_pull(task, git)]), stderr='')
        if args[1:3] == ['pr', 'view']:
            return SimpleNamespace(returncode=0, stdout=json.dumps(_pull(task, git)), stderr='')
        assert args[1:3] == ['api', 'repos/teamcsharp/gBox/pulls/123']
        assert args[3:5] == ['--method', 'PATCH']
        assert git('rev-parse', 'refs/heads/' + task['branch'], cwd=origin) != task['baseline']
        updates.append(json.loads(Path(args[args.index('--input') + 1]).read_text(encoding='utf-8')))
        return SimpleNamespace(returncode=0, stdout='{}', stderr='')

    monkeypatch.setattr(delivery.subprocess, 'run', fake_gh)
    result = delivery.publish(task['request_id'], title, ['system/gbox/value.py'], ['tests/test_value.py'])
    assert len(updates) == 1 and updates[0]['title'] == title
    assert title in updates[0]['body'] and '1 passed' in updates[0]['body']
    assert result['commit'] == git('rev-parse', 'refs/heads/' + task['branch'], cwd=origin)


def _pull(task, git, number=123, **changes):
    return {'url': f'https://github.com/teamcsharp/gBox/pull/{number}', 'number': number,
            'state': 'OPEN', 'headRefName': task['branch'],
            'headRefOid': git('rev-parse', 'HEAD', cwd=task['path']),
            'baseRefName': 'main', 'isCrossRepository': False} | changes


def _merge_task_into_origin(task, origin, git):
    # The completed task's original commit is now on main, just as after a
    # merge-commit integration. The existing workspace keeps its old tracking ref.
    git('add', 'system/gbox/value.py', cwd=task['path'])
    git('commit', '-m', 'First delivered task', cwd=task['path'])
    first = git('rev-parse', 'HEAD', cwd=task['path'])
    git('push', 'origin', 'HEAD:refs/heads/main', cwd=task['path'])
    assert git('rev-parse', 'origin/main', cwd=task['path']) == first
    # Simulate a stale fetch ref in a workspace prepared before the integration.
    git('update-ref', 'refs/remotes/origin/main', task['baseline'], cwd=task['path'])
    assert git('rev-parse', 'refs/heads/main', cwd=origin) == first
    return first


@pytest.mark.parametrize('old_state', ['MERGED', 'CLOSED'])
def test_new_changes_after_previous_pr_ended_get_new_open_review(tracked_repo, monkeypatch, old_state):
    from pathlib import Path
    _, origin, git = tracked_repo
    task = delivery.prepare('abcdef0123456789', 12)
    source = Path(task['workdir']) / 'gbox/value.py'
    source.write_text('VALUE = 2\n')
    first = _merge_task_into_origin(task, origin, git)
    source.write_text('VALUE = 3\n')
    (Path(task['workdir']) / 'tests/test_value.py').write_text(
        'import runpy\ndef test_value():\n    assert runpy.run_path("gbox/value.py")["VALUE"] == 3\n')
    real_run, created, historical_reads = subprocess.run, [], []

    def fake_gh(args, **kw):
        if args[0] != 'gh':
            return real_run(args, **kw)
        if args[1:3] == ['pr', 'list']:
            assert args[args.index('--state') + 1] == 'open'
            return SimpleNamespace(returncode=0, stdout='[]', stderr='')
        if args[1:3] == ['pr', 'create']:
            created.append(args)
            return SimpleNamespace(returncode=0, stdout='https://github.com/teamcsharp/gBox/pull/124\n', stderr='')
        if args[1:3] == ['pr', 'view']:
            if args[3] == task['branch']:
                historical_reads.append(args)
                return SimpleNamespace(returncode=0,
                    stdout=json.dumps(_pull(task, git, state=old_state, headRefOid=first)), stderr='')
            assert args[3] == '124'
            return SimpleNamespace(returncode=0, stdout=json.dumps(_pull(task, git, 124)), stderr='')
        pytest.fail('An ended pull request must never be updated')

    monkeypatch.setattr(delivery.subprocess, 'run', fake_gh)
    result = delivery.publish(task['request_id'], 'Continue replacement support',
        ['system/gbox/value.py', 'system/tests/test_value.py'], ['tests/test_value.py'])
    assert len(created) == 1 and not historical_reads
    assert result['pr_number'] == 124 and result['pr_state'] == 'OPEN'
    assert result['base_head'] == first and result['commit'] != first
    assert git('rev-parse', 'refs/heads/' + task['branch'], cwd=origin) == result['commit']


def test_merged_unchanged_workspace_is_not_published_as_new_work(tracked_repo, monkeypatch):
    from pathlib import Path
    _, origin, git = tracked_repo
    task = delivery.prepare('abcdef0123456789', 12)
    (Path(task['workdir']) / 'gbox/value.py').write_text('VALUE = 2\n')
    first = _merge_task_into_origin(task, origin, git)
    real_run = subprocess.run

    def no_github(args, **kw):
        assert args[0] != 'gh', 'No new source changes should reach GitHub'
        return real_run(args, **kw)

    monkeypatch.setattr(delivery.subprocess, 'run', no_github)
    with pytest.raises(RuntimeError, match='No task commit'):
        delivery.publish(task['request_id'], 'Already integrated',
                         ['system/gbox/value.py'], ['tests/test_value.py'])
    assert git('rev-parse', 'origin/main', cwd=task['path']) == first
    assert 'published_at' not in json.loads(delivery._record_path(task['request_id']).read_text())


def test_pr_lookup_failure_never_creates_duplicate_review(tracked_repo, monkeypatch):
    from pathlib import Path
    _, _, git = tracked_repo
    task = delivery.prepare('abcdef0123456789', 12)
    (Path(task['workdir']) / 'gbox/value.py').write_text('VALUE = 2\n')
    real_run, github = subprocess.run, []

    def failed_lookup(args, **kw):
        if args[0] != 'gh':
            return real_run(args, **kw)
        github.append(args)
        assert args[1:3] == ['pr', 'list']
        return SimpleNamespace(returncode=1, stdout='', stderr='temporary transport error')

    monkeypatch.setattr(delivery.subprocess, 'run', failed_lookup)
    with pytest.raises(RuntimeError, match='no publication claimed'):
        delivery.publish(task['request_id'], 'Preserved fix', ['system/gbox/value.py'], ['tests/test_value.py'])
    assert len(github) == 1
    assert 'published_at' not in json.loads(delivery._record_path(task['request_id']).read_text())


@pytest.mark.parametrize('bad', [
    {'state': 'MERGED'}, {'state': 'CLOSED'}, {'headRefOid': '0' * 40},
    {'baseRefName': 'other'}, {'headRefName': 'unrelated'}, {'isCrossRepository': True},
])
def test_publication_requires_open_exact_head_readback(tracked_repo, monkeypatch, bad):
    from pathlib import Path
    _, _, git = tracked_repo
    task = delivery.prepare('abcdef0123456789', 12)
    (Path(task['workdir']) / 'gbox/value.py').write_text('VALUE = 2\n')
    real_run = subprocess.run

    def changed_readback(args, **kw):
        if args[0] != 'gh':
            return real_run(args, **kw)
        if args[1:3] == ['pr', 'list']:
            return SimpleNamespace(returncode=0, stdout='[]', stderr='')
        if args[1:3] == ['pr', 'create']:
            return SimpleNamespace(returncode=0, stdout='https://github.com/teamcsharp/gBox/pull/123\n', stderr='')
        assert args[1:3] == ['pr', 'view']
        return SimpleNamespace(returncode=0, stdout=json.dumps(_pull(task, git, **bad)), stderr='')

    monkeypatch.setattr(delivery.subprocess, 'run', changed_readback)
    with pytest.raises(RuntimeError, match='exact pushed commit'):
        delivery.publish(task['request_id'], 'Readback guard', ['system/gbox/value.py'], ['tests/test_value.py'])
    assert 'published_at' not in json.loads(delivery._record_path(task['request_id']).read_text())


@pytest.mark.parametrize('new_test',[False,True])
def test_named_changed_tests_are_in_the_pushed_commit(tracked_repo,monkeypatch,new_test):
    from pathlib import Path
    _,origin,git=tracked_repo
    task=delivery.prepare('abcdef0123456789',12)
    system=Path(task['workdir'])
    (system/'gbox/value.py').write_text('VALUE = 7\n')
    name='tests/test_new_value.py' if new_test else 'tests/test_value.py'
    text='import runpy\ndef test_value():\n    assert runpy.run_path("gbox/value.py")["VALUE"] == 7\n'
    (system/name).write_text(text)
    real_run=subprocess.run
    def fake_gh(args,**kw):
        if args[0]!='gh':return real_run(args,**kw)
        if args[1:3]==['pr','list']:return SimpleNamespace(returncode=0,stdout='[]',stderr='')
        if args[1:3]==['pr','view']:return SimpleNamespace(returncode=0,stdout=json.dumps(_pull(task,git)),stderr='')
        assert args[1:3]==['pr','create']
        assert name in Path(args[args.index('--body-file')+1]).read_text()
        return SimpleNamespace(returncode=0,stdout='https://github.com/teamcsharp/gBox/pull/123\n',stderr='')
    monkeypatch.setattr(delivery.subprocess,'run',fake_gh)
    result=delivery.publish(task['request_id'],'Preserve regression',['system/gbox/value.py'],[name])
    assert git('show',result['commit']+':system/'+name,cwd=origin)==text.strip()
    assert '1 passed' in result['checks'][0]


def test_omitted_test_helper_blocks_before_commit_and_keeps_work(tracked_repo):
    from pathlib import Path
    _,_,git=tracked_repo;task=delivery.prepare('abcdef0123456789',12);system=Path(task['workdir'])
    (system/'gbox/value.py').write_text('VALUE = 2\n')
    helper=system/'tests/owned_fixture.py';helper.write_text('SOURCE = "owned"\n')
    with pytest.raises(ValueError,match='owned_fixture.py'):
        delivery.publish(task['request_id'],'Incomplete handoff',['system/gbox/value.py'],['tests/test_value.py'])
    assert git('rev-parse','HEAD',cwd=task['path'])==task['baseline']
    assert helper.read_text()=='SOURCE = "owned"\n'

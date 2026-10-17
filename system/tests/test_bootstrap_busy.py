from pathlib import Path
import os
import platform
import shutil
import subprocess

import pytest
from gbox import hermes_activation


@pytest.mark.parametrize('reason,code', [('Waiting for active gBox worker jobs to finish.', 75),
                                        ('Waiting for a complete canonical activation safety snapshot.', 75), ('', 0)])
def test_bootstrap_preflight_uses_canonical_work_guard(monkeypatch, tmp_path, reason, code):
    monkeypatch.setattr(hermes_activation, 'activation_snapshot', lambda root, api: {'reason': reason})
    assert hermes_activation.check_idle(tmp_path) == code


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('bash'), reason='Linux bootstrap')
def test_busy_bootstrap_never_installs_or_restarts(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    script = scripts / 'bootstrap-linux.sh'
    script.write_bytes((Path(__file__).parents[1] / 'scripts/bootstrap-linux.sh').read_bytes())
    bins = tmp_path / 'bin'
    bins.mkdir()
    log = tmp_path / 'called'
    for name, body in {'systemctl': 'exit 0', 'sudo': 'echo unsafe >> "$CHECK_LOG"; exit 1'}.items():
        p = bins / name
        p.write_text('#!/bin/sh\n' + body + '\n')
        p.chmod(0o755)
    venv = tmp_path / ('.venv-linux-' + platform.machine()) / 'bin'
    venv.mkdir(parents=True)
    p = venv / 'python'
    p.write_text('#!/bin/sh\necho "$*" >> "$CHECK_LOG"\nexit 75\n')
    p.chmod(0o755)
    result = subprocess.run(['bash', str(script)], env={**os.environ, 'PATH':str(bins)+os.pathsep+os.environ['PATH'],
                                                       'CHECK_LOG':str(log)}, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == ['-m gbox.hermes_activation --check-idle ' + str(tmp_path)]

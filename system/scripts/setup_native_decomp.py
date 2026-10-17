"""Explicit, pinned tool installation for order #2396. Does not restart gBox or run model APIs.

Run from system/: python scripts/setup_native_decomp.py --engine all
Existing installations are reused only after their receipt is checked. New source builds use two jobs.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox import config, provision
from gbox.native_decomp import UPSTREAM
from gbox.native_decomp_runtime import read_json, sha, write_json


def run(args, cwd=None, env=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=900,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(result.stdout[-6000:])
    return result.stdout


def checkout(engine, dest):
    upstream = UPSTREAM[engine]
    run(['git', 'init', dest])
    run(['git', 'remote', 'add', 'origin', upstream['url']], dest)
    run(['git', 'fetch', '--depth', '1', 'origin', upstream['reviewed_revision']], dest)
    run(['git', 'checkout', '--detach', 'FETCH_HEAD'], dest)
    return run(['git', 'rev-parse', 'HEAD'], dest).strip()


def install_language(home, ghidra, java):
    """Upstream's additive language installer, with an exact 12.1.4 bsr compatibility check."""
    script = home / 'targets/dreamcast_sh4/ghidra_lang/install_lang.py'
    spec = importlib.util.spec_from_file_location('gbox_sh4_installer', script)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    languages = ghidra / 'Ghidra/Processors/SuperH4/data/languages'
    stock = languages / 'SuperH4.sinc'; before = sha(stock)
    text = stock.read_text(encoding='utf-8')
    corrected = mod.BSR_NEW.replace('{\n\n', '{\n')
    if mod.BSR_OLD not in text and text.count(corrected) == 1:
        mod.BSR_OLD = corrected  # 12.1.4 already writes PR; never patch its stock files
    oldargv, oldjava = sys.argv, os.environ.get('JAVA_HOME')
    try:
        sys.argv = [str(script), str(ghidra)]
        if java:
            os.environ['JAVA_HOME'] = str(java)
        mod.main()
    finally:
        sys.argv = oldargv
        if oldjava is None:
            os.environ.pop('JAVA_HOME', None)
        else:
            os.environ['JAVA_HOME'] = oldjava
    if sha(stock) != before:
        raise RuntimeError('Stock SH-4 language changed')
    return {'stock_sha256': before, 'patched_sla_sha256': sha(languages / 'SuperH4_tc_le.sla')}


def windows_vcvars():
    for base in (Path('C:/Program Files (x86)'), Path('C:/Program Files')):
        root = base / 'Microsoft Visual Studio'
        for year in ('2022', '2019'):
            for edition in ('BuildTools', 'Community', 'Professional', 'Enterprise'):
                p = root / year / edition / 'VC/Auxiliary/Build/vcvars64.bat'
                if p.is_file():
                    return p
    return None


def rex_release(dest):
    arch = platform.machine().lower()
    arch = 'arm64' if arch in ('aarch64', 'arm64') else 'amd64' if arch in ('amd64', 'x86_64') else arch
    host = 'win' if os.name == 'nt' else 'linux' if sys.platform.startswith('linux') else 'mac'
    asset = f'rexglue-sdk-0.10.0-{host}-{arch}.zip'
    url = 'https://api.github.com/repos/rexglue/rexglue-sdk/releases/tags/v0.10.0'
    request = urllib.request.Request(url, headers={'User-Agent': 'gBox native decomp setup'})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    item = next((a for a in release['assets'] if a['name'] == asset), None)
    if not item:
        raise RuntimeError('No official RexGlue release for ' + host + '-' + arch)
    archive = dest.parent / asset
    with urllib.request.urlopen(item['browser_download_url'], timeout=120) as response, archive.open('wb') as out:
        shutil.copyfileobj(response, out, 1 << 20)
    digest = sha(archive)
    expected = item.get('digest')
    if expected and expected != 'sha256:' + digest:
        raise RuntimeError('RexGlue asset digest mismatch')
    dest.mkdir()
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest.resolve()) or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe release archive member')
            z.extract(info, dest)
            if os.name != 'nt' and (info.external_attr >> 16) & 0o111:
                target.chmod(target.stat().st_mode | 0o111)
    exe = next(p for p in dest.rglob('rexglue.exe' if os.name == 'nt' else 'rexglue') if p.is_file())
    version = run([exe, '--version']).strip()
    return {'home': str(exe.parent.parent), 'asset': asset, 'sha256': digest, 'version': version}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['all', *UPSTREAM], default='all')
    parser.add_argument('--config', default='gbox.toml')
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    os.chdir(config_path.parent)
    cfg = config.load(config_path); root = Path(cfg.runtime).resolve() / 'decomp-tools'
    root.mkdir(parents=True, exist_ok=True)
    local = root / 'gbox-local.json'; installed = read_json(local) if local.exists() else {}
    for engine in (list(UPSTREAM) if args.engine == 'all' else [args.engine]):
        dest = root / {'decomp_pipeline': 'DecompPipeline', 'xenonrecomp': 'XenonRecomp', 'rexglue': 'rexglue-sdk'}[engine]
        receipt = dest / 'gbox-install.json'
        if receipt.exists():
            data = read_json(receipt)
            if data.get('reviewed_revision') != UPSTREAM[engine]['reviewed_revision']:
                raise RuntimeError('Existing installation revision differs: ' + str(dest))
            installed[engine] = data['settings']; write_json(local, installed)
            print(engine, 'already installed', dest); continue
        if dest.exists():
            raise RuntimeError('Unmanaged or incomplete installation; inspect before retry: ' + str(dest))
        settings = {'home': str(dest)}
        detail = {}
        if engine == 'rexglue':
            detail = rex_release(dest); settings['home'] = detail['home']
        else:
            detail['commit'] = checkout(engine, dest)
        if engine == 'xenonrecomp':
            run(['git', 'submodule', 'update', '--init', '--recursive', '--depth', '1'], dest)
            run(['cmake', '-S', dest, '-B', dest / 'build', '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                 '-DCMAKE_C_COMPILER=clang', '-DCMAKE_CXX_COMPILER=clang++'])
            run(['cmake', '--build', dest / 'build', '--target', 'XenonAnalyse', 'XenonRecomp', '-j', '2'])
        if engine == 'decomp_pipeline':
            ghidra = Path(cfg.ghidra_home or '')
            if not (ghidra / 'support').is_dir() and os.name == 'nt':
                choices = sorted(Path(cfg.runtime).glob('ghidra_*_PUBLIC'))
                if choices: ghidra = choices[-1]
            java = provision.jdk21(cfg)
            if not (ghidra / 'support').is_dir() or not java:
                raise RuntimeError('Existing Ghidra and full JDK21 are required; configure before setup')
            settings.update(ghidra_home=str(ghidra.resolve()), java_home=str(java))
            detail['language'] = install_language(dest, ghidra, java)
            if os.name == 'nt' and (vcvars := windows_vcvars()):
                settings['vcvars'] = str(vcvars)
        write_json(receipt, {**UPSTREAM[engine], 'settings': settings, 'detail': detail})
        installed[engine] = settings; write_json(local, installed)
        print(engine, 'installed', settings['home'])


if __name__ == '__main__':
    main()

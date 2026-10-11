import json

from gbox import provision, rea


def test_windows_setup_keeps_structured_rea_receipt_and_finishes(cfg, monkeypatch):
    """REA returns path/version, not detail; logging must not abort setup."""
    receipt = {'step': 'rea', 'status': 'ok', 'path': 'private/rea', 'version': 'fixture'}
    monkeypatch.setattr(rea, 'install', lambda _: receipt.copy())
    monkeypatch.setattr(provision, 'HOST_OS', 'windows')
    monkeypatch.setattr(provision, 'PREFETCH_CORES', [])
    monkeypatch.setattr(provision, 'ensure_ffmpeg', lambda: provision._receipt('ffmpeg', 'ok', 'fixture'))
    monkeypatch.setattr(provision, 'retroarch_exe', lambda _: 'fixture-retroarch')
    monkeypatch.setattr(provision, 'check_blender', lambda _: provision._receipt('blender', 'ok'))
    monkeypatch.setattr(provision, 'install_blender_addon', lambda _: provision._receipt('blender-addon', 'ok'))
    messages = []
    receipts = provision.setup(cfg, with_ghidra=False, log=messages.append)
    assert receipts[0] == receipt
    assert receipts[-1]['step'] == 'blender-addon'
    assert 'private/rea' in messages[0]
    saved = next(cfg.data_dir.glob('provision-windows-*.json'))
    assert json.loads(saved.read_text()) == receipts

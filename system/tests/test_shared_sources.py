import hashlib
import json
import pytest
from gbox import shared_sources as S


def test_missing_runtime_code_is_referenced_without_overwriting_checkout(tmp_path):
    runtime, checkout, refs = [tmp_path / n for n in ('runtime', 'checkout', 'refs')]
    (runtime / 'gbox').mkdir(parents=True)
    (checkout / 'system/gbox').mkdir(parents=True)
    (runtime / 'gbox/writer.py').write_text('LIVE = True\n')
    (runtime / 'gbox/changed.py').write_text('LIVE = True\n')
    (checkout / 'system/gbox/changed.py').write_text('LOCAL = True\n')
    (runtime / 'api_token').write_text('secret')
    result = S.references(checkout, refs, runtime)
    manifest = json.loads(open(result['manifest']).read())
    assert result['differences'] == 2
    assert not (checkout / 'system/gbox/writer.py').exists()
    assert (checkout / 'system/gbox/changed.py').read_text() == 'LOCAL = True\n'
    for entry in manifest['differences']:
        from pathlib import Path
        assert hashlib.sha256(Path(entry['reference']).read_bytes()).hexdigest() == entry['sha256']
    assert 'secret' not in json.dumps(manifest)


@pytest.mark.parametrize('path', ['../api_token', 'gbox/../api_token', '/etc/passwd', 'gbox/config.toml'])
def test_source_endpoint_restricts_to_code(tmp_path, path):
    with pytest.raises(ValueError):
        S.read(path, tmp_path)

"""Exercise the actual Java encoder with the control characters found in games."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_ghidra_strings_round_trip_as_strict_json(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required to execute the Ghidra export encoder')
    source = (Path(__file__).parents[1] / 'adapters/ghidra/ExportAnalysis.java').read_text()
    method = source[source.index('    private static String q('):source.index('    @Override')]
    probe = '''public class QuoteProbe {
METHOD
    public static void main(String[] args) {
        StringBuilder value = new StringBuilder();
        for (int i = 0; i < 32; i++) value.append((char)i);
        value.append("\\\"\\\\").append((char)0x96ea).appendCodePoint(0x1f600);
        System.out.println(q(value.toString()));
    }
}
'''.replace('METHOD', method)
    (tmp_path / 'QuoteProbe.java').write_text(probe, encoding='utf-8')
    subprocess.run([javac, 'QuoteProbe.java'], cwd=tmp_path, check=True, capture_output=True, timeout=30)
    result = subprocess.run([java, '-Dfile.encoding=UTF-8', '-cp', str(tmp_path), 'QuoteProbe'],
                            check=True, capture_output=True, timeout=30)
    assert json.loads(result.stdout) == ''.join(map(chr, range(32))) + '"\\雪😀'

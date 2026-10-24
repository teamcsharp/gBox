import json
from pathlib import Path

P = Path(__file__).resolve().parent.parent / 'docs/unlock-research/7815f5fed884d651-mega-man-64-usa.md'


def test_mm64_research_is_honestly_unverified():
    d = json.loads(P.read_text().split('```json\n')[1].split('```')[0])
    assert d['game_id'] == '7815f5fed884d651' and d['verified'] is False
    assert len(d['executable']['sha256']) == 64
    assert {h['category'] for h in d['hypotheses']} <= {'items', 'modes'}
    for h in d['hypotheses']:
        for addr, val in h['writes']:
            assert addr.startswith('0x8') and val.startswith('0x')

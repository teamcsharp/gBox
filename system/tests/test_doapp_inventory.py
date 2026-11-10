"""Focused verification of the Dead Or Alive ++ (Japan) owned-source inventory proof."""
import hashlib, json, re, sys, unittest, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent if HERE.name == 'tests' else HERE
GID = 'a19b4e641b155364'
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class OwnedSourceInventoryProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev = json.loads((WS / 'profiles/gamedata/a19b4e641b155364-inventory.json').read_text())
        cls.led = json.loads((WS / 'profiles/gamedata/a19b4e641b155364-owned-source.json').read_text())
        cls.caps = json.loads((WS / 'profiles/gamedata/game-capabilities.json').read_text())

    def test_owned_source_digest_is_streamed_from_the_archive(self):
        self.assertEqual(sha_file(self.ev['source']['path']), self.ev['source']['sha256'])
        self.assertEqual(self.ev['source']['sha256'], self.led['source_sha256'])
        self.assertTrue(HEX64.fullmatch(self.ev['source']['sha256']))

    def test_archive_member_digests_match_the_owned_zip(self):
        with zipfile.ZipFile(self.ev['source']['path']) as z:
            for member in self.ev['archive_members']:
                h = hashlib.sha256()
                with z.open(member['name']) as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b''):
                        h.update(chunk)
                self.assertEqual(h.hexdigest(), member['sha256'])
                self.assertEqual(len(member['sha256']), 64)

    def test_counts_are_11_fighters_x_4_costumes_over_280_file_table_entries(self):
        c = self.ev['counts']
        self.assertEqual(c['file_table_entries'], 280)
        self.assertEqual(c['fighters'], 11)
        self.assertEqual(c['costumes'], 44)
        self.assertEqual(c['distinct_costume_file_indices'], 44)
        self.assertTrue(self.ev['derived']['file_table_matches_snapshot'])
        self.assertTrue(self.ev['derived']['fighters_match_snapshot'])

    def test_costume_slots_are_counted_table_entries_not_filename_guesses(self):
        table = {r['index']: r for r in self.ev['file_table']}
        seen = set()
        for slot in self.ev['costume_slots']:
            rec = table[slot['file_index']]
            self.assertGreater(rec['size'], 0)
            self.assertTrue(rec['head'])
            self.assertNotIn(slot['file_index'], seen)
            seen.add(slot['file_index'])
        self.assertEqual(len(seen), 44)

    def test_capability_proof_passes_the_verified_evidence_gate(self):
        if str(WS) not in sys.path:
            sys.path.insert(0, str(WS))
        from gbox import game_capabilities as gc
        proof = gc.bundled_evidence({'game_id': GID})['source_inventory']
        self.assertTrue(gc.verified_evidence(proof, 'source_inventory'))
        self.assertEqual(proof['scope'], 'full_source')
        self.assertEqual(proof['expected'], proof['verified'])
        self.assertTrue(HEX64.fullmatch(proof['source_sha256']))
        for digest in proof['artifact_sha256']:
            self.assertTrue(HEX64.fullmatch(digest))

    def test_capability_describe_reports_source_inventory_verified(self):
        if str(WS) not in sys.path:
            sys.path.insert(0, str(WS))
        from gbox import game_capabilities as gc
        cap = gc.describe({'game_id': GID})['operations']['source_inventory']
        self.assertEqual(cap['status'], 'verified')
        self.assertTrue(cap['full_source_verified'])

    def test_recorded_artifact_digests_match_the_published_files(self):
        proof = self.caps['games'][GID]['source_inventory']
        published = {sha_file(WS / 'profiles/gamedata/a19b4e641b155364-inventory.json'),
                     sha_file(WS / 'profiles/gamedata/a19b4e641b155364-owned-source.json')}
        for digest in proof['artifact_sha256']:
            self.assertIn(digest, published)


if __name__ == '__main__':
    unittest.main()

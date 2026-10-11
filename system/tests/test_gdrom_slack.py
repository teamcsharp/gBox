import unittest
from gbox.gdrom_slack import plan_modified_slack

S=2048


class ModifiedIsoSlackTests(unittest.TestCase):
    def test_overflowing_sup_reuses_only_shrunk_chr_tail(self):
        original={'A.CHR':(100,20*S),'A.SUP':(120,2*S),'ORIGINAL.BIN':(122,4*S)}
        result=plan_modified_slack(original,{'A.CHR':5*S,'A.SUP':4*S},track_start=100,track_end=200)
        rows={r['file']:r for r in result['plan']}
        self.assertEqual(rows['A.CHR']['lba'],100)
        self.assertEqual(rows['A.SUP']['lba'],105)
        self.assertEqual(rows['A.SUP']['donor']['file'],'A.CHR')
        self.assertEqual(result['report']['sacrificed_resources'],[])

    def test_unmodified_alias_pins_original_extent(self):
        original={'A.CHR':(100,20*S),'UNMODIFIED_ALIAS':(100,20*S),
                  'A.SUP':(120,2*S),'B.BIN':(122,10*S),'END':(132,S)}
        changes={'A.CHR':3*S,'A.SUP':4*S,'B.BIN':S}
        result=plan_modified_slack(original,changes,track_start=100)
        rows={r['file']:r for r in result['plan']}
        self.assertNotEqual(rows['A.CHR']['lba'],100)
        self.assertGreaterEqual(rows['A.CHR']['lba'],123)
        self.assertEqual(result['report']['original_aliases_protected'][0]['unmodified_names'],['UNMODIFIED_ALIAS'])
        self.assertTrue(all(r['lba']>=120 for r in result['plan']))

    def test_unmodified_alias_cannot_be_sacrificed_when_no_other_tail_exists(self):
        original={'A.CHR':(100,20*S),'UNMODIFIED_ALIAS':(100,20*S),'A.SUP':(120,2*S)}
        with self.assertRaisesRegex(ValueError,'preserve all original'):
            plan_modified_slack(original,{'A.CHR':S,'A.SUP':4*S},track_start=100)

    def test_all_modified_identical_aliases_share_only_identical_content(self):
        original={'A.CHR':(100,20*S),'B.CHR':(100,20*S),'NEXT':(120,S)}
        data=b'a'*(3*S)
        result=plan_modified_slack(original,{'A.CHR':data,'B.CHR':data},track_start=100)
        self.assertEqual([r['lba'] for r in result['plan']],[100,100])
        self.assertEqual(result['plan'][0]['shared_modified_aliases'],['A.CHR','B.CHR'])

    def test_all_modified_different_aliases_receive_nonoverlapping_extents(self):
        original={'A.CHR':(100,20*S),'B.CHR':(100,20*S),'NEXT':(120,S)}
        result=plan_modified_slack(original,{'A.CHR':b'a'*S,'B.CHR':b'b'*S},track_start=100)
        self.assertEqual([r['lba'] for r in result['plan']],[100,101])
        self.assertNotEqual(result['plan'][0]['shared_modified_aliases'],result['plan'][1]['shared_modified_aliases'])

    def test_last_file_tail_stops_at_original_allocation_not_track_end(self):
        original={'A.SUP':(100,2*S),'A.CHR':(102,10*S)}
        result=plan_modified_slack(original,{'A.SUP':5*S,'A.CHR':S},track_start=100,track_end=1000)
        moved=next(r for r in result['plan'] if r['file']=='A.SUP')
        self.assertEqual(moved['lba'],103)
        self.assertEqual(moved['donor']['original_extent_end'],112)
        self.assertFalse(result['report']['unused_track_tail_consumed'])
        with self.assertRaisesRegex(ValueError,'no modified'):
            plan_modified_slack(original,{'A.SUP':11*S,'A.CHR':S},track_start=100,track_end=1000)

    def test_reserved_directory_sectors_are_split_out_of_modified_tail(self):
        original={'A.SUP':(100,2*S),'A.CHR':(102,10*S)}
        result=plan_modified_slack(original,{'A.SUP':5*S,'A.CHR':S},track_start=100,
                                   reserved_ranges=[(105,107)])
        moved=next(r for r in result['plan'] if r['file']=='A.SUP')
        self.assertEqual(moved['lba'],107)
        with self.assertRaisesRegex(ValueError,'metadata'):
            plan_modified_slack(original,{'A.CHR':S},track_start=100,reserved_ranges=[(102,103)])

    def test_two_pass_planning_is_independent_of_mapping_iteration_order(self):
        original={'A.CHR':(100,20*S),'A.SUP':(120,2*S),'B.SUP':(122,2*S),'NEXT':(124,S)}
        changes={'A.CHR':S,'B.SUP':4*S,'A.SUP':5*S}
        a=plan_modified_slack(original,changes,track_start=100)
        b=plan_modified_slack(dict(reversed(list(original.items()))),dict(reversed(list(changes.items()))),track_start=100)
        self.assertEqual(a,b)

    def test_unchanged_chr_and_shortened_sup_are_not_donors(self):
        original={'A.CHR':(100,20*S),'A.SUP':(120,10*S),'B.SUP':(130,2*S)}
        with self.assertRaisesRegex(ValueError,'no modified'):
            plan_modified_slack(original,{'A.SUP':S,'B.SUP':4*S},track_start=100)

    def test_outside_track_overlap_and_unknown_file_reject_before_write(self):
        original={'A.CHR':(100,10*S),'NEXT':(110,S)}
        with self.assertRaisesRegex(ValueError,'outside'):
            plan_modified_slack(original,{'A.CHR':S},track_start=101)
        with self.assertRaisesRegex(ValueError,'crosses'):
            plan_modified_slack(original,{'A.CHR':S},track_start=100,track_end=105)
        with self.assertRaisesRegex(ValueError,'not on'):
            plan_modified_slack(original,{'UNKNOWN':S},track_start=100)


if __name__=='__main__':unittest.main()

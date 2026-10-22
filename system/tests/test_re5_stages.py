import unittest

from gbox.mercs.titles import re5_stages as S

COUNTS = {"public_assembly": 9, "mines": 8, "village": 8, "ancient_ruins": 10,
          "experimental_facility": 8, "missile_area": 11, "ship_deck": 11, "prison": 12}


class StagePlans(unittest.TestCase):
    def test_all_eight_stages(self):
        self.assertEqual(set(S.STAGES), set(COUNTS))

    def test_hourglass_counts_and_totals(self):
        for key, n in COUNTS.items():
            plan = S.STAGES[key]
            self.assertEqual(len(plan.hourglasses), n, key)
            self.assertEqual(S.hourglass_seconds(key), plan.hourglass_total, key)

    def test_legs_cover_whole_round_and_bonus_legs_match_hourglasses(self):
        for key, plan in S.STAGES.items():
            for kills in range(0, 150):
                self.assertTrue(S.route_legs(key, kills), (key, kills))
            for leg in plan.legs:
                self.assertLessEqual(leg.start, leg.end)
                self.assertIn(leg.bonus, (0, 30, 60, 90))
            self.assertLessEqual(sum(l.bonus for l in plan.legs), plan.hourglass_total, key)

    def test_next_bonus(self):
        self.assertEqual(S.next_bonus("public_assembly", 0).goal, "north_shack")
        self.assertEqual(S.next_bonus("public_assembly", 141).goal, "south_building_ladder")
        self.assertIsNone(S.next_bonus("public_assembly", 150))


if __name__ == "__main__":
    unittest.main()

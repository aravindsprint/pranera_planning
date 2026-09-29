import unittest

from pranera_planning.reservation_math import (
    allowed_issue_qty, clean_roll, location_room, location_summary, remaining_qty, same_project,
)


class TestReservationMath(unittest.TestCase):
    def test_remaining_never_negative(self):
        self.assertEqual(remaining_qty(10, 4), 6)
        self.assertEqual(remaining_qty(10, 12), 0)

    def test_project_match_is_case_insensitive(self):
        self.assertTrue(same_project("26PTIN1558", "26ptin1558"))
        self.assertFalse(same_project("26PTIN1558", None))
        self.assertFalse(same_project("", ""))

    def test_reserved_stock_is_off_limits_to_other_projects(self):
        res = [{"production_project": "B", "reserved_qty": 60, "issued_qty": 0}]
        allowed, free, own, total = allowed_issue_qty(100, res, "A")
        self.assertEqual((allowed, free, own, total), (40, 40, 0, 60))

    def test_owner_may_use_its_reservation_plus_free(self):
        res = [{"production_project": "B", "reserved_qty": 60, "issued_qty": 0}]
        allowed, *_ = allowed_issue_qty(100, res, "b")
        self.assertEqual(allowed, 100)

    def test_issued_part_of_a_reservation_stops_blocking(self):
        # B reserved 60 and has already taken 30 (so stores hold 70): 30 still reserved.
        res = [{"production_project": "B", "reserved_qty": 60, "issued_qty": 30}]
        allowed, free, own, _ = allowed_issue_qty(70, res, "A")
        self.assertEqual((allowed, free, own), (40, 40, 0))

    def test_over_reserved_batch_never_goes_negative(self):
        res = [{"production_project": "B", "reserved_qty": 60, "issued_qty": 0}]
        allowed, free, *_ = allowed_issue_qty(20, res, "A")
        self.assertEqual((allowed, free), (0, 0))


    # ── warehouse + batch + roll ─────────────────────────────────────────────
    def test_junk_roll_numbers_are_blank(self):
        self.assertEqual(clean_roll(" 204353 "), "204353")
        self.assertEqual(clean_roll("0.000000000"), "")
        self.assertEqual(clean_roll(None), "")

    def test_yarn_room_is_warehouse_level(self):
        res = [{"roll_no": "", "reserved_qty": 30, "issued_qty": 0}]
        self.assertEqual(location_room(100, {}, res), 70)

    def test_numbered_roll_room_is_that_roll_only(self):
        rolls = {"R1": 25, "R2": 24}
        res = [{"roll_no": "R1", "reserved_qty": 25, "issued_qty": 0}]
        self.assertEqual(location_room(100, rolls, res, "R1"), 0)
        self.assertEqual(location_room(100, rolls, res, "R2"), 24)

    def test_unnumbered_stock_backs_rolls_the_ledger_has_not_seen(self):
        # 100 in the warehouse, 49 of it on numbered rolls -> 51 unnumbered.
        rolls = {"R1": 25, "R2": 24, "OLD": -20}          # OLD left labelled, came in unlabelled
        s = location_summary(100, rolls, [{"roll_no": "NEW", "reserved_qty": 30, "issued_qty": 0}])
        self.assertEqual(s["unnumbered"], {"qty": 51, "reserved": 30, "free": 21})
        self.assertNotIn("OLD", s["rolls"])
        self.assertEqual(location_room(100, rolls, [], "NEW"), 51)

    def test_roll_room_never_exceeds_warehouse_room(self):
        rolls = {"R1": 25}
        res = [{"roll_no": "X", "reserved_qty": 90, "issued_qty": 0}]
        self.assertEqual(location_room(100, rolls, res, "R1"), 10)

    def test_roll_reserved_for_another_project_is_blocked(self):
        rolls = {"R1": 25}
        res = [{"production_project": "B", "roll_no": "R1", "reserved_qty": 25, "issued_qty": 0}]
        allowed, free, *_ = allowed_issue_qty(100, res, "A", rolls, "R1")
        self.assertEqual((allowed, free), (0, 75))
        allowed, *_ = allowed_issue_qty(100, res, "A", rolls, "R2")     # another roll is fine
        self.assertEqual(allowed, 75)
        allowed, *_ = allowed_issue_qty(100, res, "B", rolls, "R1")     # owner: not roll-capped
        self.assertEqual(allowed, 100)

    def test_partly_reserved_roll_releases_only_the_rest(self):
        rolls = {"R1": 25}
        res = [{"production_project": "B", "roll_no": "R1", "reserved_qty": 10, "issued_qty": 0}]
        allowed, *_ = allowed_issue_qty(100, res, "A", rolls, "R1")
        self.assertEqual(allowed, 15)


    # ── produced stock belongs to the project it was made for ───────────────
    def test_owner_may_use_unreserved_stock(self):
        allowed, free, *_ = allowed_issue_qty(100, [], "A", owner="A")
        self.assertEqual((allowed, free), (100, 100))

    def test_other_project_needs_a_reservation(self):
        allowed, free, *_ = allowed_issue_qty(100, [], "B", owner="A")
        self.assertEqual((allowed, free), (0, 100))

    def test_other_project_gets_exactly_what_is_reserved_for_it(self):
        res = [{"production_project": "B", "reserved_qty": 30, "issued_qty": 10}]
        allowed, *_ = allowed_issue_qty(100, res, "B", owner="A")
        self.assertEqual(allowed, 20)
        allowed, *_ = allowed_issue_qty(100, res, "A", owner="A")      # owner keeps the rest
        self.assertEqual(allowed, 80)
        allowed, *_ = allowed_issue_qty(100, res, "C", owner="A")      # a third project: nothing
        self.assertEqual(allowed, 0)

    def test_owner_match_is_case_insensitive(self):
        allowed, *_ = allowed_issue_qty(50, [], "25prod001", owner="25PROD001")
        self.assertEqual(allowed, 50)

    def test_foreign_owned_roll_gets_no_spare_balance(self):
        rolls = {"R1": 25}
        res = [{"production_project": "C", "roll_no": "R1", "reserved_qty": 10, "issued_qty": 0}]
        allowed, *_ = allowed_issue_qty(100, res, "B", rolls, "R1", owner="A")
        self.assertEqual(allowed, 0)


if __name__ == "__main__":
    unittest.main()

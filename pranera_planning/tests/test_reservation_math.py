import unittest

from pranera_planning.reservation_math import allowed_issue_qty, remaining_qty, same_project


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


if __name__ == "__main__":
    unittest.main()

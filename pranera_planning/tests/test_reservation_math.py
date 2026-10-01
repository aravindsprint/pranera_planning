import unittest

from pranera_planning.reservation_math import (
    allowed_issue_qty, clean_roll, location_room, location_summary, place_packed_rolls, purchase_shortfall, deepest_minimum, remaining_qty, reserved_first, summarise_free_stock, allocate_issues,
    same_project,
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


    def test_foreign_owned_batch_only_the_reserved_roll(self):
        rolls = {"R1": 500, "R4": 400}
        res = [{"production_project": "B", "roll_no": "R4", "reserved_qty": 400, "issued_qty": 0}]
        allowed, *_ = allowed_issue_qty(1900, res, "B", rolls, "R4", owner="A")
        self.assertEqual(allowed, 400)
        allowed, *_ = allowed_issue_qty(1900, res, "B", rolls, "R1", owner="A")   # a roll not reserved for B
        self.assertEqual(allowed, 0)
        allowed, *_ = allowed_issue_qty(1900, res, "A", rolls, "R1", owner="A")   # the owner, any free roll
        self.assertEqual(allowed, 1500)

    # ── knitted rolls from Roll Packing Lists ────────────────────────────────
    def test_rolls_go_to_the_warehouse_the_batch_was_delivered_to(self):
        placed, uncertain = place_packed_rolls(
            {"A": 50, "B": 100}, [("R1", 25, "A"), ("R2", 25, "A")])
        self.assertEqual(placed, {"A": {"R1": 25, "R2": 25}})
        self.assertEqual(uncertain, set())

    def test_rolls_the_ledger_has_moved_are_left_to_the_ledger(self):
        placed, _ = place_packed_rolls({"A": 25}, [("R1", 25, "A"), ("R2", 25, "A")], seen={"R1"})
        self.assertEqual(placed, {"A": {"R2": 25}})

    def test_batch_that_left_stores_places_nothing(self):
        placed, _ = place_packed_rolls({}, [("R1", 25, "A")])
        self.assertEqual(placed, {})
        placed, _ = place_packed_rolls({"A": 0}, [("R1", 25, "A")])
        self.assertEqual(placed, {})

    def test_rolls_left_out_for_lack_of_room_are_flagged(self):
        packed = [(str(100 + i), 25, "A") for i in range(1, 21)]          # 20 rolls, 500 kg
        placed, uncertain = place_packed_rolls({"A": 400}, packed)       # 100 kg left unnumbered
        self.assertEqual(len(placed["A"]), 16)
        self.assertEqual(uncertain, {"A"})

    def test_fulfilled_rolls_are_left_out_exactly(self):
        packed = [(str(100 + i), 25, "A") for i in range(1, 21)]
        gone = {"101", "102", "103", "104"}
        placed, uncertain = place_packed_rolls({"A": 400}, packed, seen=gone)
        self.assertEqual(sorted(placed["A"]), [str(n) for n in range(105, 121)])
        self.assertEqual(uncertain, set())

    def test_partly_issued_without_numbers_is_flagged(self):
        placed, uncertain = place_packed_rolls({"A": 30}, [("R1", 25, "A"), ("R2", 25, "A")])
        self.assertEqual(placed, {"A": {"R1": 25, "R2": 25}})
        self.assertEqual(uncertain, {"A"})

    def test_target_gone_falls_back_to_the_fullest_warehouse(self):
        placed, _ = place_packed_rolls({"A": 0, "B": 10, "C": 60}, [("R1", 25, "A")])
        self.assertEqual(placed, {"C": {"R1": 25}})


    # ── a project must use its own reservation first ─────────────────────────
    RES = [{"name": "PSR-9", "batch_no": "1234", "warehouse": "Stores", "roll_no": "", "usable_qty": 2000}]

    def test_issuing_the_reserved_batch_is_fine(self):
        r = reserved_first(self.RES, [{"batch_no": "1234", "warehouse": "Stores", "qty": 500}])
        self.assertFalse(r["breach"])
        self.assertEqual((r["covered"], r["outside"]), (500, 0))

    def test_another_batch_while_reservation_waits_is_a_breach(self):
        r = reserved_first(self.RES, [{"batch_no": "5678", "warehouse": "Stores", "qty": 500}])
        self.assertTrue(r["breach"])

    def test_reserved_batch_from_another_warehouse_is_a_breach(self):
        r = reserved_first(self.RES, [{"batch_no": "1234", "warehouse": "Stores 2", "qty": 500}])
        self.assertTrue(r["breach"])

    def test_extra_beyond_the_reservation_is_fine_once_it_is_all_used(self):
        lines = [{"batch_no": "1234", "warehouse": "Stores", "qty": 2000},
                 {"batch_no": "5678", "warehouse": "Stores", "qty": 500}]
        self.assertFalse(reserved_first(self.RES, lines)["breach"])
        lines[0]["qty"] = 1500
        self.assertTrue(reserved_first(self.RES, lines)["breach"])

    def test_reservation_whose_stock_is_gone_is_not_insisted_on(self):
        res = [dict(self.RES[0], usable_qty=0)]
        self.assertFalse(reserved_first(res, [{"batch_no": "5678", "warehouse": "Stores", "qty": 500}])["breach"])

    def test_roll_reservation_needs_that_roll(self):
        res = [{"name": "PSR-1", "batch_no": "G1", "warehouse": "Stores", "roll_no": "R4", "usable_qty": 400}]
        self.assertTrue(reserved_first(res, [{"batch_no": "G1", "warehouse": "Stores", "roll_no": "R1", "qty": 400}])["breach"])
        self.assertFalse(reserved_first(res, [{"batch_no": "G1", "warehouse": "Stores", "roll_no": "R4", "qty": 400}])["breach"])
        self.assertFalse(reserved_first(res, [{"batch_no": "G1", "warehouse": "Stores", "roll_no": "", "qty": 400}])["breach"])


    # ── issues against reservations ──────────────────────────────────────────
    def R(self, name, roll, qty, t=0):
        return {"name": name, "roll_no": roll, "reserved_qty": qty, "creation": t}

    def L(self, roll, qty, t=1):
        return {"roll_no": roll, "qty": qty, "creation": t}

    def test_unnumbered_issue_fills_roll_reservations_oldest_first(self):
        res = [self.R(f"PSR-{n}", str(n), 25, t=n) for n in (101, 102, 103, 104)]
        got = allocate_issues(res, [self.L("", 100, t=200)])            # your Send to Subcontractor
        self.assertEqual(got, {"PSR-101": 25, "PSR-102": 25, "PSR-103": 25, "PSR-104": 25})
        got = allocate_issues(res, [self.L("", 60, t=200)])
        self.assertEqual(got, {"PSR-101": 25, "PSR-102": 25, "PSR-103": 10, "PSR-104": 0})

    def test_numbered_issue_counts_only_for_its_roll(self):
        res = [self.R("A", "101", 25), self.R("B", "102", 25)]
        self.assertEqual(allocate_issues(res, [self.L("102", 25)]), {"A": 0, "B": 25})
        self.assertEqual(allocate_issues(res, [self.L("999", 25)]), {"A": 0, "B": 0})

    def test_issue_before_a_reservation_does_not_count_for_it(self):
        res = [self.R("old", "101", 25, t=0), self.R("new", "102", 25, t=5)]
        self.assertEqual(allocate_issues(res, [self.L("", 50, t=3)]), {"old": 25, "new": 0})

    def test_batch_reservation_counts_every_line(self):
        res = [self.R("yarn", "", 2000)]
        self.assertEqual(allocate_issues(res, [self.L("", 500), self.L("R9", 100)]), {"yarn": 600})


    # ── free stock before buying ────────────────────────────────────────────
    def test_free_stock_grouped_by_project(self):
        rows = [
            {"batch_no": "B1", "project": "25PUR001", "free_qty": 975},
            {"batch_no": "B2", "project": "25PUR001", "free_qty": 0},        # nothing free: ignored
            {"batch_no": "B3", "project": "26PTIN1645", "free_qty": 1200},
            {"batch_no": "B4", "project": "25prod001", "free_qty": 50},      # the asker's own (any case)
            {"batch_no": "B5", "project": None, "free_qty": 30},
        ]
        s = summarise_free_stock(rows, for_project="25PROD001")
        self.assertEqual((s["own"], s["elsewhere"], s["unassigned"]), (50, 2175, 30))
        self.assertEqual([(p["project"], p["free_qty"], p["batches"]) for p in s["projects"]],
                         [("26PTIN1645", 1200, 1), ("25PUR001", 975, 1)])

    def test_free_stock_lists_top_projects_only(self):
        rows = [{"batch_no": f"B{i}", "project": f"P{i}", "free_qty": 10 + i} for i in range(8)]
        s = summarise_free_stock(rows, top=5)
        self.assertEqual(len(s["projects"]), 5)
        self.assertEqual(s["more_projects"], 3)
        self.assertEqual(s["projects"][0]["project"], "P7")


    # ── Purchase Material Request: buy only the shortfall ─────────────────────
    def test_buy_only_what_free_stock_cannot_cover(self):
        r = purchase_shortfall(2000, 975)
        self.assertEqual((r["free_counted"], r["max_request"], r["breach"]), (975, 1025, True))
        # lowering the qty without reserving still leaves the 975 free — only 50 more may be bought
        self.assertTrue(purchase_shortfall(1025, 975)["breach"])
        # once the 975 is reserved for the project it is no longer free: the 1025 goes through
        self.assertFalse(purchase_shortfall(1025, 0)["breach"])

    def test_free_stock_covering_everything_leaves_nothing_to_buy(self):
        r = purchase_shortfall(800, 975)
        self.assertEqual((r["max_request"], r["breach"]), (0, True))

    def test_small_leftovers_are_ignored(self):
        r = purchase_shortfall(2000, 20, ignore_below=25)
        self.assertEqual((r["free_counted"], r["max_request"], r["breach"]), (0, 2000, False))
        self.assertTrue(purchase_shortfall(2000, 25, ignore_below=25)["breach"])     # at the minimum, it counts

    def test_nothing_free_nothing_to_block(self):
        self.assertFalse(purchase_shortfall(500, 0)["breach"])

    def test_minimum_comes_from_the_nearest_group_above(self):
        mins = [(1, 100, 50), (10, 20, 25)]              # e.g. ALL ITEM GROUPS 50, YARN 25
        self.assertEqual(deepest_minimum((12, 13), mins), 25)
        self.assertEqual(deepest_minimum((30, 31), mins), 50)
        self.assertEqual(deepest_minimum((200, 201), mins), 0)
        self.assertEqual(deepest_minimum(None, mins), 0)


if __name__ == "__main__":
    unittest.main()

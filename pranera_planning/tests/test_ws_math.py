"""ws_math: capacity from the Workstation, load from bookings, the earliest slot and machine fit."""
import unittest
from datetime import date

from pranera_planning import ws_math as W

# a knitting machine: 25 kg/h × 20 h × 1 job = 500 kg a day, Sunday 2026-11-08 a holiday
KM = {"kg_per_hour": 25, "hours": 20, "parallel": 1, "holidays": {date(2026, 11, 8)}, "stage": "Knitting", "dia": 30, "gauge": 24}


class TestCapacity(unittest.TestCase):
    def test_per_day_and_holidays(self):
        self.assertEqual(W.capacity_on(KM, "2026-11-07"), 500)
        self.assertEqual(W.capacity_on(KM, "2026-11-08"), 0)

    def test_duration_skips_holidays(self):
        end, n = W.duration_for(KM, 2000, "2026-11-06")       # 4 working days: 6, 7, (8 off), 9, 10
        self.assertEqual((end, n), (date(2026, 11, 11), 4))

    def test_no_kg_per_hour_means_unknown(self):
        self.assertIsNone(W.duration_for({**KM, "kg_per_hour": 0}, 100, "2026-11-06"))


class TestLoad(unittest.TestCase):
    def test_spread_over_working_days(self):
        b = [{"workstation": "KM-12", "qty": 1500, "planned_start": "2026-11-07", "planned_end": "2026-11-10"}]
        load = W.load(b, {"KM-12": KM}, "2026-11-01", "2026-11-30")
        self.assertEqual(load, {("KM-12", date(2026, 11, 7)): 750.0, ("KM-12", date(2026, 11, 9)): 750.0})

    def test_over_capacity_days(self):
        booked = {date(2026, 11, 6): 300.0}
        self.assertEqual(W.over_days(KM, booked, 500, "2026-11-06", "2026-11-07"), [(date(2026, 11, 6), 800.0, 500.0)])
        self.assertEqual(W.over_days(KM, booked, 200, "2026-11-06", "2026-11-07"), [])


class TestSlot(unittest.TestCase):
    def test_earliest_slot_waits_for_room(self):
        booked = {date(2026, 11, 6): 500.0, date(2026, 11, 7): 500.0}       # full for two days
        self.assertEqual(W.earliest_slot(KM, booked, 1000, "2026-11-06"), (date(2026, 11, 9), date(2026, 11, 11)))


class TestFit(unittest.TestCase):
    def test_stage_dia_gauge(self):
        self.assertEqual(W.fits({"stage": "Knitting", "dia": 30, "gauge": 24}, KM), [])
        why = W.fits({"stage": "Knitting", "dia": 34, "gauge": 28}, KM)
        self.assertEqual(len(why), 2)
        self.assertTrue(W.fits({"stage": "Dyeing"}, KM))
        self.assertEqual(W.fits({"stage": "knitting"}, KM), [])               # no dia on the item: no check

    def test_unit_must_match(self):
        flat = {**KM, "uom": "Pcs", "dia": None}
        circ = {**KM, "uom": "Kgs"}
        self.assertEqual(W.fits({"stage": "Knitting", "uom": "Pcs"}, flat), [])
        self.assertEqual(len(W.fits({"stage": "Knitting", "uom": "Kgs"}, flat)), 1)     # fabric on a collar machine
        self.assertEqual(len(W.fits({"stage": "Knitting", "uom": "Pcs"}, circ)), 1)     # collars on a circular machine
        self.assertEqual(W.fits({"stage": "Knitting", "uom": "kgs"}, circ), [])         # case ignored
        self.assertEqual(W.fits({"stage": "Knitting", "uom": "Pcs"}, KM), [])           # machine without a unit: any


if __name__ == "__main__":
    unittest.main()

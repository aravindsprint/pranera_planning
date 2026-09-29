"""Pure reservation arithmetic. No frappe imports, so it can be unit-tested anywhere.

A reservation always sits at one stock *location*:
  yarn and other batch items   (warehouse, batch)
  fabric / collar / cuff       (warehouse, batch, roll)

Numbered rolls come from the stock ledger (Stock Entry Detail's roll no.). Rolls very often
arrive in a warehouse unnumbered and only get a number when they leave, so a warehouse's
stock is split into numbered rolls with a positive balance there, plus an "unnumbered"
remainder. A reservation on a roll number the ledger doesn't show in that warehouse is
carved out of the unnumbered remainder.
"""
import re

EPS = 1e-6


def same_project(a, b):
    """Project names compare case-insensitively (the DB does, and batch names are inconsistent)."""
    return bool(a) and bool(b) and str(a).casefold() == str(b).casefold()


def clean_roll(value):
    """Roll no. as typed on stock entries: trimmed; blank and junk zeros ("0.000000000") -> ""."""
    s = str(value or "").strip()
    return "" if re.fullmatch(r"0*\.?0*", s) else s


def remaining_qty(reserved_qty, issued_qty):
    return max(0.0, float(reserved_qty or 0) - float(issued_qty or 0))


def _rem(r):
    if "remaining_qty" in r:
        return float(r["remaining_qty"] or 0)
    return remaining_qty(r.get("reserved_qty"), r.get("issued_qty"))


def location_summary(available, roll_balances, reservations):
    """What is held and what is free at one (batch, warehouse).

    available      qty of the batch in this warehouse
    roll_balances  {roll_no: ledger balance in this warehouse}; {} for non-roll items
    reservations   active reservations at this warehouse: [{"roll_no", "reserved_qty",
                   "issued_qty"} or {"roll_no", "remaining_qty"}]

    Returns {
      "reserved":   remaining reserved at this warehouse, all rolls together
      "free":       what may still be reserved here in total
      "rolls":      {roll_no: {"qty", "reserved", "free"}} numbered rolls in stock here
      "unnumbered": {"qty", "reserved", "free"} stock here with no roll no. in the ledger
    }
    """
    available = max(0.0, float(available or 0))
    total = sum(_rem(r) for r in reservations)
    wh_free = max(0.0, available - total)

    known = {k: float(v) for k, v in (roll_balances or {}).items() if k and float(v) > EPS}
    rolls = {}
    for roll, qty in sorted(known.items()):
        held = sum(_rem(r) for r in reservations if r.get("roll_no") == roll)
        rolls[roll] = {"qty": qty, "reserved": held, "free": min(wh_free, max(0.0, qty - held))}

    unnum_qty = max(0.0, available - sum(known.values()))
    unnum_held = sum(_rem(r) for r in reservations if r.get("roll_no") and r.get("roll_no") not in known)
    unnumbered = {"qty": unnum_qty, "reserved": unnum_held, "free": min(wh_free, max(0.0, unnum_qty - unnum_held))}

    return {"reserved": total, "free": wh_free, "rolls": rolls, "unnumbered": unnumbered}


def location_room(available, roll_balances, reservations, roll_no=None):
    """How much more can be reserved at one (batch, warehouse) — or on one roll there."""
    s = location_summary(available, roll_balances, reservations)
    if not roll_no:
        return s["free"]
    if roll_no in s["rolls"]:
        return s["rolls"][roll_no]["free"]
    return s["unnumbered"]["free"]


def allowed_issue_qty(available, reservations, project, roll_balances=None, roll_no=None):
    """How much of a batch may be issued to `project` from one warehouse right now.

    available     qty of the batch in that warehouse
    reservations  active reservations at that warehouse:
                  [{"production_project", "reserved_qty", "issued_qty", "roll_no"?}]
    project       the production project that wants to issue
    roll_no       the roll being issued, if the line names one. A roll reserved for another
                  project can't be issued to this one beyond what's left on it unreserved.

    Returns (allowed, free, own_remaining, total_remaining):
      free       unreserved stock in the warehouse, usable by any project
      own        what is still reserved for `project` itself in the warehouse
      allowed    free + own, further capped for a roll reserved to someone else
    """
    total = own = 0.0
    for r in reservations:
        rem = _rem(r)
        total += rem
        if same_project(r["production_project"], project):
            own += rem
    free = max(0.0, float(available or 0) - total)
    allowed = free + own

    if roll_no:
        on_roll = [r for r in reservations if r.get("roll_no") == roll_no]
        others = sum(_rem(r) for r in on_roll if not same_project(r["production_project"], project))
        if others > EPS:
            mine = sum(_rem(r) for r in on_roll if same_project(r["production_project"], project))
            balance = max(0.0, float((roll_balances or {}).get(roll_no) or 0))
            allowed = min(allowed, max(0.0, balance - others - mine) + mine)

    return allowed, free, own, total

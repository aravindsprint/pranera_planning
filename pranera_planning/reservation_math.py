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


def allowed_issue_qty(available, reservations, project, roll_balances=None, roll_no=None, owner=None):
    """How much of a batch may be issued to `project` from one warehouse right now.

    available     qty of the batch in that warehouse
    reservations  active reservations at that warehouse:
                  [{"production_project", "reserved_qty", "issued_qty", "roll_no"?}]
    project       the production project that wants to issue
    roll_no       the roll being issued, if the line names one. A roll reserved for another
                  project can't be issued to this one beyond what's left on it unreserved;
                  a roll of a batch owned by another project only as far as it is reserved
                  for this one.
    owner         the project the batch was produced for, if any. Unreserved stock of an
                  owned batch is the owner's: any other project may take only what is
                  reserved for it.

    Returns (allowed, free, own_remaining, total_remaining):
      free       unreserved stock in the warehouse, usable by any project
      own        what is still reserved for `project` itself in the warehouse
      allowed    free + own (own only, for a batch owned by another project), further
                 capped for a roll reserved to someone else
    """
    total = own = 0.0
    for r in reservations:
        rem = _rem(r)
        total += rem
        if same_project(r["production_project"], project):
            own += rem
    free = max(0.0, float(available or 0) - total)
    foreign = bool(owner) and not same_project(owner, project)
    allowed = (0.0 if foreign else free) + own

    if roll_no:
        on_roll = [r for r in reservations if r.get("roll_no") == roll_no]
        mine = sum(_rem(r) for r in on_roll if same_project(r["production_project"], project))
        others = sum(_rem(r) for r in on_roll if not same_project(r["production_project"], project))
        if foreign:
            # Another project's produced roll: only the part reserved for this project.
            allowed = min(allowed, mine)
        elif others > EPS:
            balance = max(0.0, float((roll_balances or {}).get(roll_no) or 0))
            allowed = min(allowed, max(0.0, balance - others - mine) + mine)

    return allowed, free, own, total


def place_packed_rolls(room, packed, seen=()):
    """Place rolls from the knitting roll register (Roll Packing Lists) into warehouses.

    room    {warehouse: qty of the batch there not already on a numbered roll}
    packed  [(roll_no, weight, target warehouse or None)] in packing order
    seen    roll nos. to leave out: moved by the stock ledger (they follow the ledger), or
            whose reservation has been fulfilled (issued, so gone)

    Each roll goes to its target warehouse if the batch still has unnumbered stock there,
    else to the warehouse with the most. Nothing is placed once the batch has no
    unnumbered stock left anywhere (it has left stores).

    Returns ({warehouse: {roll_no: weight}}, {warehouse, ...} where the rolls don't match
    what is still unnumbered — part of the batch left without roll numbers, so the list is
    a guess: some listed rolls may be gone, or some gone rolls may be listed).
    """
    room = {wh: float(q) for wh, q in room.items()}
    placed, uncertain, left_out = {}, set(), False
    for roll, weight, target in packed:
        if roll in seen or not room:
            continue
        wh = target if room.get(target, 0) > EPS else max(room, key=room.get)
        if room[wh] <= EPS:
            left_out = True
            continue
        if weight > room[wh] + EPS:
            uncertain.add(wh)
        placed.setdefault(wh, {})[roll] = placed.get(wh, {}).get(roll, 0.0) + float(weight)
        room[wh] -= float(weight)
    if left_out:
        # Some rolls didn't fit what is still unnumbered here: part of the batch left
        # without roll numbers, and which rolls went is a guess.
        uncertain |= set(placed)
    return placed, uncertain


def reserved_first(reservations, lines):
    """Does an entry issue an item to a project from outside that project's own reservations
    while those reservations still have stock waiting?

    reservations  the project's Active reservations of one item:
                  [{"name", "batch_no", "warehouse", "roll_no", "usable_qty"}], where
                  usable_qty = what is still reserved AND still physically at that location
                  (a reservation whose stock has gone can't be insisted on)
    lines         the entry's issue lines of that item to that project:
                  [{"batch_no", "warehouse", "roll_no", "qty"}]

    A line draws on a reservation at the same batch and warehouse — and the same roll, when
    both name one (a line with no roll no. can draw on a roll reservation of its batch).
    Whatever a line can't place on a reservation is "outside".

    Returns {"covered", "outside", "usable", "breach"}: breach is True when something is
    issued from outside while the reservations are not fully used by this entry. Issuing
    more than is reserved is fine — once the reserved stock is all being used.
    """
    left = {r["name"]: max(0.0, float(r.get("usable_qty") or 0)) for r in reservations}
    usable = sum(left.values())
    covered = outside = 0.0
    for line in lines:
        qty = float(line["qty"] or 0)
        for r in reservations:
            if qty <= EPS:
                break
            if r["batch_no"] != line["batch_no"] or r["warehouse"] != line["warehouse"]:
                continue
            if r.get("roll_no") and line.get("roll_no") and r["roll_no"] != line["roll_no"]:
                continue
            take = min(qty, left[r["name"]])
            left[r["name"]] -= take
            covered += take
            qty -= take
        outside += max(0.0, qty)
    return {
        "covered": covered,
        "outside": outside,
        "usable": usable,
        "breach": outside > EPS and covered < usable - EPS,
    }


def allocate_issues(reservations, lines):
    """How much of each reservation has been issued, for ONE batch, warehouse and project.

    reservations  [{"name", "roll_no", "reserved_qty", "creation"}] — Active and Fulfilled
    lines         [{"roll_no", "qty", "creation"}] issues of that batch, from that warehouse,
                  to that project

    Only lines made after a reservation was created count towards it.
      batch reservation (no roll)  every line counts
      roll reservation             a line naming that roll counts in full; a line naming no
                                   roll (batches often move as a whole, without roll numbers)
                                   fills the project's roll reservations oldest first, up to
                                   what each reserved. A line naming another roll counts
                                   towards none of them.
    Returns {name: issued_qty}.
    """
    issued = {r["name"]: 0.0 for r in reservations}
    rolls = sorted((r for r in reservations if r.get("roll_no")), key=lambda r: r["creation"])
    for r in reservations:
        if not r.get("roll_no"):
            issued[r["name"]] = sum(float(l["qty"] or 0) for l in lines if l["creation"] >= r["creation"])
    for r in rolls:
        issued[r["name"]] = sum(
            float(l["qty"] or 0) for l in lines
            if l.get("roll_no") == r["roll_no"] and l["creation"] >= r["creation"]
        )
    for l in sorted((l for l in lines if not l.get("roll_no")), key=lambda l: l["creation"]):
        qty = float(l["qty"] or 0)
        for r in rolls:
            if qty <= EPS:
                break
            if r["creation"] > l["creation"]:
                continue
            take = min(qty, max(0.0, float(r["reserved_qty"] or 0) - issued[r["name"]]))
            issued[r["name"]] += take
            qty -= take
    return issued


def summarise_free_stock(batch_rows, for_project=None, top=5):
    """Group free stock of one item by the project it belongs to.

    batch_rows   [{"batch_no", "project" (or None), "free_qty"}] — free = in stores minus
                 what active reservations still hold there
    for_project  the project asking (e.g. on a Purchase Material Request): its own free
                 stock is reported separately, not as stock to reserve from elsewhere

    Returns {"own", "elsewhere", "unassigned", "projects": [{"project", "free_qty",
    "batches"}] (largest first, at most `top`), "more_projects": n}.
    """
    own = unassigned = 0.0
    by_project = {}
    for r in batch_rows:
        q = float(r.get("free_qty") or 0)
        if q <= EPS:
            continue
        p = r.get("project")
        if not p:
            unassigned += q
        elif for_project and same_project(p, for_project):
            own += q
        else:
            e = by_project.setdefault(p, {"project": p, "free_qty": 0.0, "batches": 0})
            e["free_qty"] += q
            e["batches"] += 1
    ranked = sorted(by_project.values(), key=lambda e: -e["free_qty"])
    return {
        "own": own,
        "elsewhere": sum(e["free_qty"] for e in ranked),
        "unassigned": unassigned,
        "projects": ranked[:top],
        "more_projects": max(0, len(ranked) - top),
    }


def purchase_shortfall(requested, usable_free, ignore_below=0.0):
    """How much a Purchase Material Request may ask for, given stock already free.

    requested     qty the request asks for (one item, one project)
    usable_free   stock of that item free to reserve for that project right now
    ignore_below  leftovers smaller than this don't count (a few odd kilos shouldn't block
                  a purchase)

    Returns {"free_counted", "max_request", "breach"}: the request may ask for at most
    requested - free_counted; breach when it asks for more.
    """
    requested = max(0.0, float(requested or 0))
    usable_free = max(0.0, float(usable_free or 0))
    free_counted = usable_free if usable_free + EPS >= float(ignore_below or 0) else 0.0
    max_request = max(0.0, requested - free_counted)
    return {"free_counted": free_counted, "max_request": max_request, "breach": requested > max_request + EPS}


def deepest_minimum(group_bounds, minimums):
    """The "ignore leftovers below" minimum for an item group: the one set on the nearest
    group above it in the tree (the group itself counts), else 0.

    group_bounds  (lft, rgt) of the item's group
    minimums      [(lft, rgt, min_qty)] of the groups that have a minimum set
    """
    if not group_bounds:
        return 0.0
    lft, rgt = group_bounds
    best = None
    for g_lft, g_rgt, qty in minimums:
        if g_lft <= lft and g_rgt >= rgt and (best is None or g_lft > best[0]):
            best = (g_lft, float(qty or 0))
    return best[1] if best else 0.0

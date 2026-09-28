"""Pure reservation arithmetic. No frappe imports, so it can be unit-tested anywhere."""

EPS = 1e-6


def same_project(a, b):
    """Project names compare case-insensitively (the DB does, and batch names are inconsistent)."""
    return bool(a) and bool(b) and str(a).casefold() == str(b).casefold()


def remaining_qty(reserved_qty, issued_qty):
    return max(0.0, float(reserved_qty or 0) - float(issued_qty or 0))


def allowed_issue_qty(available, reservations, project):
    """How much of a batch may be issued to `project` right now.

    available     qty of the batch in issuable (non-WIP, non-subcontractor) warehouses
    reservations  active reservations on the batch:
                  [{"production_project", "reserved_qty", "issued_qty"}]
    project       the production project that wants to issue

    Returns (allowed, free, own_remaining, total_remaining):
      free       unreserved stock, usable by any project
      own        what is still reserved for `project` itself
      allowed    free + own
    """
    total = own = 0.0
    for r in reservations:
        rem = remaining_qty(r["reserved_qty"], r["issued_qty"])
        total += rem
        if same_project(r["production_project"], project):
            own += rem
    free = max(0.0, float(available or 0) - total)
    return free + own, free, own, total

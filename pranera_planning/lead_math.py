"""Lead days for bought items, and what they mean for open and new Purchase Orders.
No frappe imports, so it can be unit-tested anywhere.

Where an item's lead days come from is a ranked list in Re-order Settings (Supplier lead
days). Each source can be switched off; the first source switched on that has a number wins:

    supplier_item   the item's Supplier Items row for the supplier (Item › Supplier Items › Lead days)
    supplier        the supplier's usual lead days (Supplier › Usual lead days)
    item            the item's own Lead Time Days
    group           the item-group rule's Lead days when bought

Only the two supplier sources say anything about one particular supplier, so only they may
block a Purchase Order; the others only warn.
"""
from datetime import date, datetime, timedelta

SUPPLIER_ITEM, SUPPLIER, ITEM, GROUP = "supplier_item", "supplier", "item", "group"
DEFAULT_ORDER = [SUPPLIER_ITEM, SUPPLIER, ITEM, GROUP]
SUPPLIER_SOURCES = {SUPPLIER_ITEM, SUPPLIER}
LABELS = {
    SUPPLIER_ITEM: "Supplier Items row",
    SUPPLIER: "Supplier's usual lead days",
    ITEM: "Item's Lead Time Days",
    GROUP: "Item-group rule",
}
KEY_OF = {v: k for k, v in LABELS.items()}

# What to do for an item with no Default Supplier (Re-order Settings › no_default_supplier)
LATEST_PO, MOST_BOUGHT, NO_SUPPLIER = "Latest Purchase Order", "Most bought from", "No supplier"
FALLBACKS = [LATEST_PO, MOST_BOUGHT, NO_SUPPLIER]

# Before that fallback, an item with no Default Supplier but with Item Lead Days rows (its
# Supplier Items rows with lead days) uses one of those suppliers
# (Re-order Settings › item_rows_pick)
SLOWEST, FASTEST, DONT_USE = "Slowest", "Fastest", "Don't use"
ITEM_ROW_PICKS = [SLOWEST, FASTEST, DONT_USE]


def pick_row_supplier(rows, how):
    """The supplier to plan with from an item's [(supplier, lead days)]: the slowest (safe:
    more stock) or the fastest (lean). Ties go to the supplier name first in order. None when
    there are no rows or how is Don't use."""
    rows = [(s, float(d)) for s, d in rows if s and float(d or 0) > 0]
    if not rows or how not in (SLOWEST, FASTEST):
        return None
    sign = -1 if how == SLOWEST else 1
    return sorted(rows, key=lambda r: (sign * r[1], r[0]))[0][0]


def source_order(rows):
    """The enabled source keys in rank order, from the settings rows [{"source", "enabled"}]
    (source is a label or a key). No rows at all = the default order, all on."""
    rows = list(rows or [])
    if not rows:
        return list(DEFAULT_ORDER)
    out = []
    for r in rows:
        key = KEY_OF.get(r.get("source"), r.get("source"))
        if key in LABELS and key not in out and int(r.get("enabled") or 0):
            out.append(key)
    return out


def pick_lead(order, values):
    """(days, source key) — the first source in `order` with a positive number in `values`
    ({source key: days}); (0.0, None) when none has one."""
    for key in order:
        try:
            days = float(values.get(key) or 0)
        except (TypeError, ValueError):
            days = 0.0
        if days > 0:
            return days, key
    return 0.0, None


def describe(days, source, supplier=None, supplier_from=None):
    """One line for the report's workings: where the lead days came from."""
    if not source:
        return "No lead days found in any source switched on"
    text = f"{LABELS[source]}"
    if source in SUPPLIER_SOURCES and supplier:
        text += f" for {supplier}"
    if supplier and supplier_from and supplier_from != "default":
        text += f" (no default supplier: {supplier_from})"
    return text


def _d(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def split_on_order(po_lines, today, lead_days):
    """Split open Purchase Order lines into what arrives in time and what arrives later.

    po_lines   [(item, open qty, required by, purchase order)]
    lead_days  {item: days} — an order placed today arrives after this many days

    A line counts as in time when its Required By is on or before today + the item's lead
    days: a Purchase Order due later than a new order placed today would arrive doesn't
    protect the stock. Items with no lead days keep every line in time (nothing to compare).
    Returns ({item: qty arriving later}, {item: [(purchase order, qty, required by)]})."""
    later, lines = {}, {}
    today = _d(today)
    for item, qty, required_by, po in po_lines:
        days = float(lead_days.get(item) or 0)
        if days <= 0 or not required_by or float(qty or 0) <= 0:
            continue
        if _d(required_by) > today + timedelta(days=days):
            later[item] = later.get(item, 0.0) + float(qty)
            lines.setdefault(item, []).append((po, float(qty), str(_d(required_by))))
    return later, lines


def later_note(lines, uom=""):
    """'1,500 Kgs on PO-0123 due 2026-11-14; …' for the report."""
    unit = f" {uom}" if uom else ""
    return "; ".join(f"{qty:,.0f}{unit} on {po} due {due}" for po, qty, due in sorted(lines, key=lambda x: x[2]))


def earliest_date(order_date, days, grace=0):
    """The earliest Required By a supplier taking `days` can meet, less `grace` days."""
    return _d(order_date) + timedelta(days=max(0.0, float(days or 0) - float(grace or 0)))


def late_lines(rows, order_date, grace, lead_for):
    """[{"idx", "item_code", "required_by", "earliest", "days", "source", "blocks"}] for the
    Purchase Order rows whose Required By is before order date + lead days − grace.

    rows      [{"idx", "item_code", "schedule_date"}]
    lead_for  item -> (days, source key)
    blocks    True only when the days came from a supplier source."""
    out = []
    for r in rows:
        if not r.get("item_code") or not r.get("schedule_date"):
            continue
        days, source = lead_for(r["item_code"])
        if not days:
            continue
        earliest = earliest_date(order_date, days, grace)
        if _d(r["schedule_date"]) < earliest:
            out.append({"idx": r.get("idx"), "item_code": r["item_code"], "required_by": str(_d(r["schedule_date"])),
                        "earliest": str(earliest), "days": days, "source": source,
                        "blocks": source in SUPPLIER_SOURCES})
    return out

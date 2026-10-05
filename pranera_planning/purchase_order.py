"""Purchase Order lead time check (doc_events: validate, before_submit,
before_update_after_submit).

A line's Required By may not be earlier than the order date + the supplier's lead days for
that item − grace days (Re-order Settings › Supplier lead days). The lead days are found the
same way the re-order report finds them, but always for this order's supplier.

    On save (draft)        an orange notice, so a draft can still be saved and fixed.
    On submit, Block mode  refused — unless the user has an override role (the same roles as
                           the free-stock check, Stock Reservation Settings) and has filled
                           in Lead time override reason, which is recorded as a comment.
    Update Items           the same, for the lines whose Required By changed.
    Warn mode              the notice only. Off: nothing.

Only lead days that come from the supplier (its Supplier Items row or its usual lead days)
block; the Item's or the item group's lead days say nothing about this supplier and only warn.
Job-work (subcontracted) orders are skipped: their timing is the stages' Days used. A failure
in the check itself never stops the order; it is logged and shown.
"""
import frappe
from frappe import _

from pranera_planning.lead_math import SUPPLIER_SOURCES, late_lines

TITLE_BLOCK = "Too early for this supplier"
TITLE_WARN = "Required By earlier than the supplier's lead time"


def check_lead_time(doc, method=None):
    if doc.get("is_subcontracted") or not doc.get("supplier"):
        return
    submitting = method == "before_submit"
    updating = method == "before_update_after_submit"
    if not submitting and not updating and getattr(doc, "_action", None) == "submit":
        return                                            # before_submit will run the check
    try:
        from pranera_planning.reorder import load_settings
        cfg = load_settings()
        lead_cfg = cfg["lead"]
        if lead_cfg["check"] == "Off":
            return
        rows = list(doc.get("items") or [])
        if updating:
            rows = _changed_rows(doc, rows)
        late = find_late(doc, rows, cfg)
        if not late:
            return

        from pranera_planning.reservation import mr_check_settings
        can_override = bool(mr_check_settings()["roles"] & set(frappe.get_roles()))
        reason = (doc.get("lead_time_override_reason") or "").strip()
        blocking = [x for x in late if x["blocks"]]
        message = late_message(doc.supplier, late)

        if not (submitting or updating) or lead_cfg["check"] != "Block" or not blocking:
            frappe.msgprint(message, title=_(TITLE_WARN), indicator="orange", wide=True)
            return
        if can_override and reason:
            doc.add_comment("Comment", _("Required By earlier than {0}'s lead time (override by {1}): {2}").format(
                doc.supplier, frappe.session.user, frappe.utils.escape_html(reason)))
            frappe.msgprint(_("Submitted with an override: Required By is earlier than the supplier's lead time."),
                            indicator="orange", alert=True)
            return
        if can_override:
            frappe.throw(message + "<br><br>" + _("To accept it anyway, fill in <b>Lead time override reason</b> and submit again."),
                         title=_(TITLE_BLOCK))
        frappe.throw(message, title=_(TITLE_BLOCK))
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(title="Lead time check on Purchase Order failed")
        frappe.msgprint(_("The lead time check could not run, so this order was not checked. "
                          "Please report it — details are in the Error Log."),
                        title=_("Lead time check skipped"), indicator="orange")


def _changed_rows(doc, rows):
    """Update Items: only lines that are new or whose Required By changed."""
    before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
    if not before:
        return rows
    old = {r.name: str(r.schedule_date) for r in (before.get("items") or [])}
    return [r for r in rows if old.get(r.name) != str(r.schedule_date)]


def find_late(doc, rows, cfg):
    """late_lines for the order's rows, with lead days for this order's supplier."""
    from pranera_planning.lead_time import group_days_for, resolve
    codes = list({r.item_code for r in rows if r.get("item_code")})
    if not codes:
        return []
    info = {i.name: i for i in frappe.get_all("Item", filters={"name": ["in", codes]},
                                                fields=["name", "item_group", "lead_time_days"])}
    group_days = group_days_for([i.item_group for i in info.values()], cfg["rules"])
    leads = resolve(codes, info, group_days, cfg["lead"], supplier=doc.supplier)
    return late_lines([{"idx": r.get("idx"), "item_code": r.get("item_code"), "schedule_date": r.get("schedule_date")}
                       for r in rows],
                      doc.get("transaction_date"), cfg["lead"]["grace"],
                      lambda code: (leads[code]["days"], leads[code]["source"]) if code in leads else (0.0, None))


def _fmt(d):
    try:
        return frappe.utils.formatdate(d)
    except Exception:
        return str(d)


def late_message(supplier, late):
    from pranera_planning.lead_math import GROUP, ITEM
    said = {ITEM: _("the item's Lead Time Days is {0}"), GROUP: _("the item-group rule says {0} days")}
    lines = []
    for x in late:
        days = int(x["days"]) if float(x["days"]).is_integer() else x["days"]
        where = (_("this supplier usually takes {0} days").format(days) if x["source"] in SUPPLIER_SOURCES
                 else said[x["source"]].format(days))
        line = _("Row {0} · {1}: Required By {2}, but {3}, so the earliest is <b>{4}</b>.").format(
            x["idx"], x["item_code"], _fmt(x["required_by"]), where, _fmt(x["earliest"]))
        if not x["blocks"]:
            line += " " + _("(A warning only: these lead days are not this supplier's own.)")
        lines.append(line)
    return (_("<b>{0}</b>").format(frappe.utils.escape_html(supplier)) + "<br>" + "<br>".join(lines) + "<br><br>"
            + _("Change Required By to the earliest date shown or later, or buy from a supplier who can deliver in time."))

"""Made-to-order Sales Orders get their project automatically.

Sales Order › Made to order (a tick box) decides it; orders without the tick — stock sales,
Shopify and Unicommerce orders — are left exactly as they are.

On submit, with the tick:
  - Project left empty → a new made-to-order project is created — Production when any ordered item
    is made (has an active BOM), Purchase when every item is bought — named after the
    Sales Order, with its Customer, Sales Order and delivery date, and the Sales Order's Project
    is set to it (linked both ways).
  - Project chosen → that project is linked: marked made to order, given this Sales Order (and the
    customer if it has none). A project already tied to a different Sales Order is refused on save:
    a made-to-order project is one customer's order.
  - Amending a cancelled order → the amended order takes over the original's project.
On cancel: the project's Active reservations that nothing has been issued against yet are
Released (stock nobody will use for a cancelled order must not stay held). Then a project this
order created and nothing else uses (no remaining reservations, requests or orders) is set to
Cancelled; one still in use stays open, with a comment saying why.
"""
from urllib.parse import quote

import frappe
from frappe.utils import flt
from frappe import _

MTO = "Made to order"


def _has(doctype, field):
    return frappe.db.has_column(doctype, field)


def _project_of_order(doc):
    """The project this order should use: the one chosen, else the original's when amending."""
    if doc.get("project"):
        return doc.project
    if doc.get("amended_from"):
        return frappe.db.get_value("Project", {"sales_order": doc.amended_from}, "name")
    return None


def validate(doc, method=None):
    """Refuse, before submit, a made-to-order project that already belongs to another order."""
    if not doc.get("made_to_order") or not doc.get("project"):
        return
    other = frappe.db.get_value("Project", doc.project, "sales_order")
    if other and other not in (doc.name, doc.get("amended_from")):
        frappe.throw(_("Project {0} is already the project of Sales Order {1}. A made-to-order project is one customer's "
                       "order: leave Project empty to create a new one, or choose another project.").format(doc.project, other),
                     title=_("Project belongs to another order"))


def on_submit(doc, method=None):
    if not doc.get("made_to_order"):
        return
    project = _project_of_order(doc)
    if project:
        _link(project, doc)
    else:
        project = _create(doc)
    if doc.get("project") != project:
        doc.db_set("project", project, update_modified=False)
    url = f"/planning-app/project-planning?project={quote(project)}&tab=plan"
    frappe.msgprint(_('This order\'s project is <a href="/app/project/{0}">{0}</a>. Plan it in '
                      '<a href="{1}">Project Planning</a>.').format(frappe.utils.escape_html(project), url),
                    title=_("Made-to-order project"), indicator="green")


def project_type_for(doc):
    """Production when the order has an item made here (an active, submitted BOM), else Purchase."""
    items = list({r.item_code for r in (doc.get("items") or []) if r.get("item_code")})
    if items and not frappe.get_all("BOM", filters={"item": ["in", items], "is_active": 1, "docstatus": 1},
                                    pluck="item", limit=1):
        return "Purchase"
    return "Production"


def _create(doc):
    values = {
        "doctype": "Project", "project_name": doc.name, "project_type": project_type_for(doc), "status": "Open",
        "company": doc.company, "customer": doc.customer, "sales_order": doc.name,
        "expected_end_date": doc.get("delivery_date"),
    }
    if _has("Project", "planning_order_type"):
        values["planning_order_type"] = MTO
    project = frappe.get_doc(values)
    project.flags.ignore_permissions = True        # a system step of submitting the order, not the user's own create
    project.insert()
    project.add_comment("Comment", _("Created from Sales Order {0} (made to order).").format(doc.name))
    return project.name


def _link(project, doc):
    fields = ["sales_order", "customer", "status", "project_type"]
    if _has("Project", "planning_order_type"):
        fields.append("planning_order_type")
    p = frappe.db.get_value("Project", project, fields, as_dict=True)
    if not p:
        frappe.throw(_("Project {0} not found.").format(project))
    updates = {}
    if not p.sales_order or p.sales_order == doc.get("amended_from"):
        updates["sales_order"] = doc.name
    if not p.customer:
        updates["customer"] = doc.customer
    if not p.project_type:
        updates["project_type"] = project_type_for(doc)
    if "planning_order_type" in p and p.planning_order_type != MTO:
        updates["planning_order_type"] = MTO
    if p.status == "Cancelled":
        updates["status"] = "Open"                  # an amended order reopens its project
    if updates:
        frappe.db.set_value("Project", project, updates)


def _in_use(project):
    """What already uses the project (for the cancel decision), as short labels."""
    checks = [
        ("Project Stock Reservation", {"production_project": project, "status": ["in", ["Active", "Fulfilled"]]}, _("reservations")),
        ("Work Order", {"project": project, "docstatus": ["<", 2]}, _("Work Orders")),
    ]
    used = [label for dt, filters, label in checks if frappe.db.exists(dt, filters)]
    if frappe.db.sql("""SELECT 1 FROM `tabMaterial Request Item` mri JOIN `tabMaterial Request` mr ON mr.name = mri.parent
                        WHERE mri.project = %s AND mr.docstatus < 2 LIMIT 1""", project):
        used.append(_("Material Requests"))
    if frappe.db.sql("""SELECT 1 FROM `tabPurchase Order Item` poi JOIN `tabPurchase Order` po ON po.name = poi.parent
                        WHERE poi.project = %s AND po.docstatus < 2 LIMIT 1""", project):
        used.append(_("Purchase Orders"))
    return used


def release_unissued(project, sales_order):
    """Release the project's Active reservations with nothing issued against them yet.
    (released, kept): how many were released, and how many stay because some was issued."""
    from pranera_planning.reservation import get_reservation_state
    rows = frappe.get_all("Project Stock Reservation", filters={"production_project": project, "status": "Active"},
                          fields=["name", "batch_no"])
    if not rows:
        return 0, 0
    issued = {r["name"]: flt(r.get("issued_qty")) for st in get_reservation_state({r.batch_no for r in rows}).values()
              for r in st["reservations"]}
    released = kept = 0
    for r in rows:
        if issued.get(r.name, 0) > 1e-6:
            kept += 1
            continue
        frappe.db.set_value("Project Stock Reservation", r.name, {
            "status": "Released", "released_on": frappe.utils.now_datetime(),
            "remarks": _("Released: Sales Order {0} was cancelled.").format(sales_order)})
        released += 1
    return released, kept


def on_cancel(doc, method=None):
    project = doc.get("project")
    if not doc.get("made_to_order") or not project:
        return
    p = frappe.db.get_value("Project", project, ["project_name", "sales_order", "status"], as_dict=True)
    if not p or p.sales_order != doc.name:
        return
    released, kept = release_unissued(project, doc.name)
    used = _in_use(project)
    if released or kept:
        frappe.get_doc("Project", project).add_comment("Comment", _(
            "Sales Order {0} was cancelled: {1} reservation(s) released; {2} kept because stock was already issued against them."
        ).format(doc.name, released, kept))
    if used:
        frappe.get_doc("Project", project).add_comment(
            "Comment", _("Sales Order {0} was cancelled; the project stays open because it already has {1}.").format(
                doc.name, ", ".join(used)))
        return
    created_here = p.project_name == doc.name or doc.name.startswith(f"{p.project_name}-")   # amended: SO-…-00012-1
    if created_here and p.status != "Cancelled":
        frappe.db.set_value("Project", project, "status", "Cancelled")

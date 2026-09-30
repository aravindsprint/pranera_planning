import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from pranera_planning.reservation import (
    batch_source_project, get_reservation_state, is_pool_warehouse, is_roll_item,
    reservations_at,
)
from pranera_planning.reservation_math import EPS, clean_roll, location_room, same_project

SOURCE_TYPES = ("Purchase", "Production")


class ProjectStockReservation(Document):
    def validate(self):
        if flt(self.reserved_qty) <= 0:
            frappe.throw(_("Reserved Qty must be greater than zero."))

        self.validate_batch()
        self.validate_location()
        self.validate_project_types()
        self.validate_unique_active()
        if self.status == "Active":
            self.validate_capacity()
        self.released_on = (self.released_on or now_datetime()) if self.status == "Released" else None
        self.fulfilled_on = (self.fulfilled_on or now_datetime()) if self.status == "Fulfilled" else None

    def validate_batch(self):
        batch_item = frappe.db.get_value("Batch", self.batch_no, "item")
        if batch_item != self.item_code:
            frappe.throw(_("Batch {0} belongs to item {1}, not {2}.").format(self.batch_no, batch_item, self.item_code))

        project = batch_source_project(self.batch_no)
        if not project:
            frappe.throw(_("Batch {0} belongs to no project: it wasn't purchased under one (Purchase Receipt) or produced for exactly one (Work Order / Subcontracting Receipt).").format(self.batch_no))
        if not same_project(project, self.purchase_project):
            frappe.throw(_("Batch {0} belongs to project {1}, not {2}.").format(self.batch_no, project, self.purchase_project))

    def validate_location(self):
        """Yarn and other batch items are reserved at warehouse + batch; roll items (fabric,
        collar, cuff) at warehouse + batch + roll."""
        if not self.warehouse:
            frappe.throw(_("Warehouse is required — a reservation is held at one warehouse."))
        if not is_pool_warehouse(self.warehouse):
            frappe.throw(_("{0} is a WIP / subcontractor / direct delivery warehouse; stock there can't be reserved.").format(self.warehouse))

        self.roll_no = clean_roll(self.roll_no)
        if is_roll_item(self.item_code):
            if not self.roll_no:
                frappe.throw(_("{0} is a roll item (fabric / collar / cuff) — choose the roll to reserve.").format(self.item_code))
        elif self.roll_no:
            frappe.throw(_("{0} is not a roll item — it is reserved by warehouse and batch only, leave Roll No blank.").format(self.item_code))

    def validate_project_types(self):
        """The stock comes from a Purchase or a Production project; it is reserved for a
        Production project, where it gets consumed. This is what actually stops the two pickers on the
        page being mixed up — that's a dropdown filter, which only helps if nobody types
        or pastes a project name directly.

        Uses Project's own standard project_type field (Link -> Project Type), not a
        custom field — Purchase and Production are two new Project Type records this app
        ships as a fixture, alongside whatever Project Types already exist on the site.

        The project stock is reserved *for* must be typed Production and Open. That is
        checked only when a reservation is created: a project completed later must not
        stop its reservation from being released.

        An unclassified *source* project (project_type blank) is let through with a
        warning; one typed some other way (Internal, External, ...) is blocked.
        """
        purchase_type = frappe.db.get_value("Project", self.purchase_project, "project_type")

        if purchase_type and purchase_type not in SOURCE_TYPES:
            frappe.throw(_("{0} is typed as {1}, not Purchase or Production — check you have the right project.").format(self.purchase_project, purchase_type))

        if self.is_new() and same_project(self.production_project, self.purchase_project):
            frappe.throw(_("This stock already belongs to {0} — reserve it for a different project.").format(self.production_project))

        if self.is_new():
            production_type, production_status = frappe.db.get_value(
                "Project", self.production_project, ["project_type", "status"]
            ) or (None, None)
            if production_type != "Production":
                frappe.throw(_("{0} is typed as {1}, not Production — stock can only be reserved for a Production project.").format(
                    self.production_project, production_type or _("(not set)")))
            if production_status != "Open":
                frappe.throw(_("{0} is {1} — stock can only be reserved for an Open project.").format(
                    self.production_project, production_status))

        unclassified = [self.purchase_project] if not purchase_type else []
        if unclassified:
            frappe.msgprint(_(
                "Project Type is not set on {0}. Set it on the Project record so a mix-up here gets caught automatically."
            ).format(", ".join(unclassified)), indicator="orange", alert=True)

    def validate_unique_active(self):
        """One Active row per (warehouse, batch, roll, project, sales_order) — a project may hold a pooled
        reservation and a separate Sales-Order-linked reservation on the same batch side by
        side; that's two different commitments, not a duplicate."""
        if self.status != "Active":
            return
        clash = frappe.db.exists("Project Stock Reservation", {
            "status": "Active", "batch_no": self.batch_no,
            "warehouse": self.warehouse, "roll_no": self.roll_no or "",
            "production_project": self.production_project,
            "sales_order": self.sales_order or "",
            "name": ["!=", self.name],
        })
        if clash:
            frappe.throw(_("{0} already reserves this stock ({1}) for {2}. Edit that reservation to change the quantity.").format(clash, self.location_label(), self.production_project))

    def location_label(self):
        return " / ".join(p for p in (self.warehouse, self.batch_no, self.roll_no and f"roll {self.roll_no}") if p)

    def validate_capacity(self):
        """The unissued part of this reservation must fit in what the other reservations
        leave free at the same warehouse — and, for a roll, on the same roll.

        A request that doesn't fully fit is capped to what's available rather than rejected
        outright — Requested Qty keeps the original ask visible so the gap isn't silently
        absorbed. Only a batch with truly nothing left is rejected outright.

        Capping only re-runs when Reserved Qty is actually being set or changed. An
        unrelated save (editing Remarks, say) must not silently grow an already-capped
        reservation just because room has since opened up elsewhere — that would be a
        surprising side effect of saving, not something anyone asked for.
        """
        state = get_reservation_state([self.batch_no], exclude=self.name if not self.is_new() else None)[self.batch_no]
        loc = state["locations"].get(self.warehouse, {"available": 0.0, "rolls": {}})
        others_here = reservations_at(state, self.warehouse)
        others = sum(r["remaining_qty"] for r in others_here)
        room = location_room(loc["available"], loc["rolls"], others_here, self.roll_no)

        issued = 0.0
        if not self.is_new():
            current = get_reservation_state([self.batch_no])[self.batch_no]["reservations"]
            issued = next((r["issued_qty"] for r in current if r["name"] == self.name), 0.0)
            if flt(self.reserved_qty) + EPS < issued:
                frappe.throw(_("{0:g} has already been issued against this reservation, so it cannot be reduced below that.").format(issued))

        if not (self.is_new() or self.has_value_changed("reserved_qty")):
            return

        asked = flt(self.reserved_qty)
        max_legal = issued + max(room, 0)

        if max_legal <= EPS:
            frappe.throw(_(
                "{0} has nothing available for a new reservation "
                "({1:g} in {2}, {3:g} already reserved there for other projects)."
            ).format(self.location_label(), loc["available"], self.warehouse, others))

        if asked > max_legal + EPS:
            self.requested_qty = asked
            self.reserved_qty = max_legal
            frappe.msgprint(_(
                "Only {0:g} of {1} is available — reserved {0:g} instead of the {2:g} requested."
            ).format(max_legal, self.location_label(), asked), indicator="orange", alert=True)
        else:
            self.requested_qty = self.requested_qty or asked

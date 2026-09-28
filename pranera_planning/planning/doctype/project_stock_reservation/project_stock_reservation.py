import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from pranera_planning.reservation import (
    get_batch_purchase_project, get_reservation_state,
)
from pranera_planning.reservation_math import EPS, same_project


class ProjectStockReservation(Document):
    def validate(self):
        if flt(self.reserved_qty) <= 0:
            frappe.throw(_("Reserved Qty must be greater than zero."))

        self.validate_batch()
        self.validate_unique_active()
        if self.status == "Active":
            self.validate_capacity()
        if self.status == "Released":
            self.released_on = self.released_on or now_datetime()
        else:
            self.released_on = None

    def validate_batch(self):
        batch_item = frappe.db.get_value("Batch", self.batch_no, "item")
        if batch_item != self.item_code:
            frappe.throw(_("Batch {0} belongs to item {1}, not {2}.").format(self.batch_no, batch_item, self.item_code))

        project = get_batch_purchase_project(self.batch_no)
        if not project:
            frappe.throw(_("Batch {0} has no purchase project (no submitted Purchase Receipt with a project).").format(self.batch_no))
        if not same_project(project, self.purchase_project):
            frappe.throw(_("Batch {0} was purchased under project {1}, not {2}.").format(self.batch_no, project, self.purchase_project))

    def validate_unique_active(self):
        """One Active row per (batch, project, sales_order) — a project may hold a pooled
        reservation and a separate Sales-Order-linked reservation on the same batch side by
        side; that's two different commitments, not a duplicate."""
        if self.status != "Active":
            return
        clash = frappe.db.exists("Project Stock Reservation", {
            "status": "Active", "batch_no": self.batch_no,
            "production_project": self.production_project,
            "sales_order": self.sales_order or "",
            "name": ["!=", self.name],
        })
        if clash:
            frappe.throw(_("{0} already reserves this batch for {1}. Edit that reservation to change the quantity.").format(clash, self.production_project))

    def validate_capacity(self):
        """The unissued part of this reservation must fit in what the other reservations
        leave free.

        A request that doesn't fully fit is capped to what's available rather than rejected
        outright — Requested Qty keeps the original ask visible so the gap isn't silently
        absorbed. Only a batch with truly nothing left is rejected outright.

        Capping only re-runs when Reserved Qty is actually being set or changed. An
        unrelated save (editing Remarks, say) must not silently grow an already-capped
        reservation just because room has since opened up elsewhere — that would be a
        surprising side effect of saving, not something anyone asked for.
        """
        state = get_reservation_state([self.batch_no], exclude=self.name if not self.is_new() else None)[self.batch_no]
        others = sum(r["remaining_qty"] for r in state["reservations"])
        room = state["available"] - others

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
                "Batch {0} has nothing available for a new reservation "
                "({1:g} in stores, {2:g} already reserved for other projects)."
            ).format(self.batch_no, state["available"], others))

        if asked > max_legal + EPS:
            self.requested_qty = asked
            self.reserved_qty = max_legal
            frappe.msgprint(_(
                "Only {0:g} of batch {1} is available — reserved {0:g} instead of the {2:g} requested."
            ).format(max_legal, self.batch_no, asked), indicator="orange", alert=True)
        else:
            self.requested_qty = self.requested_qty or asked

"""Reservations are now marked Fulfilled once fully issued. Catch up the Active ones
that were already fully issued before that existed."""
import frappe

from pranera_planning.reservation import refresh_fulfilment


def execute():
    batches = frappe.get_all("Project Stock Reservation", filters={"status": "Active"}, pluck="batch_no", distinct=True)
    if batches:
        refresh_fulfilment(batches)

app_name = "pranera_planning"
app_title = "Pranera Planning"
app_publisher = "Pranera Services & Solutions"
app_description = "Planning module for Pranera ERP"
app_email = "admin@pranera.in"
app_license = "MIT"

required_apps = ["erpnext"]

# Apps screen tile (Frappe v15 "/apps" launcher)
add_to_apps_screen = [
    {
        "name": "pranera_planning",
        "logo": "/assets/pranera_planning/images/favicon.svg",
        "title": "Planning",
        "route": "/planning-app",
    }
]

# Every /planning-app/<anything> URL is served by www/planning-app.html so the
# Vue router can handle deep links and browser refreshes.
website_route_rules = [
    {"from_route": "/planning-app/<path:app_path>", "to_route": "planning-app"},
]

# Project stock reservation: stops stock reserved for one production project being
# issued to another — covers yarn, fabric at any processing stage, chemicals, or
# finished goods, whatever batch-tracked item it is.
# Kill switch without a redeploy: set "project_stock_reservation_enforcement": 0 in
# site_config.json.
doc_events = {
    "Stock Entry": {
        "validate": "pranera_planning.reservation.validate_stock_entry",
        "on_submit": [
            "pranera_planning.reservation.update_fulfilment",
            "pranera_planning.reservation.move_reservations",
        ],
        "on_cancel": [
            "pranera_planning.reservation.restore_moved_reservations",
            "pranera_planning.reservation.update_fulfilment",
        ],
    },
    "Work Order": {
        "on_submit": "pranera_planning.reservation.clear_warehouse_cache",
    },
    "Subcontracting Order": {
        "on_submit": "pranera_planning.reservation.clear_warehouse_cache",
    },
    "Material Request": {
        "validate": "pranera_planning.reservation.check_material_request",
        "before_submit": "pranera_planning.reservation.check_material_request",
    },
    "Delivery Note": {
        "validate": "pranera_planning.reservation.check_delivery",
    },
    "Sales Invoice": {
        "validate": "pranera_planning.reservation.check_delivery",
    },
    "Sales Order": {
        "validate": "pranera_planning.sales_order.validate",
        "on_submit": "pranera_planning.sales_order.on_submit",
        "on_cancel": "pranera_planning.sales_order.on_cancel",
    },
    # Lead time check: a line's Required By can't be earlier than the order date + the
    # supplier's lead days (Re-order Settings › Supplier lead days). Also when Update Items
    # changes dates on a submitted order.
    "Purchase Order": {
        "validate": "pranera_planning.purchase_order.check_lead_time",
        "before_submit": "pranera_planning.purchase_order.check_lead_time",
        "before_update_after_submit": "pranera_planning.purchase_order.check_lead_time",
    },
    "Roll Wise Pick List": {
        "on_submit": "pranera_planning.reservation.refresh_from_pick_list",
        "on_cancel": "pranera_planning.reservation.refresh_from_pick_list",
    },
}

# Project.project_type (Link -> Project Type) is a STANDARD field, already on the form —
# no Custom Field needed. What's missing is two option records: your Project Type list
# today is Other / External / Internal, so this adds "Purchase" and "Production" as two
# more, purely additive — the existing three are untouched. `bench migrate` creates them
# if missing; nothing else in this filter, so no other app's Project Type records are
# ever exported here.
fixtures = [
    {"doctype": "Project Type", "filters": [["name", "in", ["Purchase", "Production"]]]},
]

scheduler_events = {
    "daily": [
        "pranera_planning.reservation.refresh_all_fulfilment",
        "pranera_planning.reorder.recalculate_all",
    ],
}

# A fresh install marks every patch as already run, so run the one-off setup directly too.
after_install = [
    "pranera_planning.patches.setup_material_request_check.execute",
    "pranera_planning.patches.setup_planning_fields.execute",
    "pranera_planning.patches.add_saved_plan_field.execute",
    "pranera_planning.patches.add_sales_order_mto_field.execute",
    "pranera_planning.patches.add_supplier_lead_days.execute",
]

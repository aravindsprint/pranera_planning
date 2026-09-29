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
        "on_submit": "pranera_planning.reservation.update_fulfilment",
        "on_cancel": "pranera_planning.reservation.update_fulfilment",
    },
    "Work Order": {
        "on_submit": "pranera_planning.reservation.clear_warehouse_cache",
    },
    "Subcontracting Order": {
        "on_submit": "pranera_planning.reservation.clear_warehouse_cache",
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
    ],
}

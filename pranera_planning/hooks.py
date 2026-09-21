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

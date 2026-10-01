"""Re-order Settings: starting values, and the three fabric stages with EMPTY lead days.
Real re-order levels shouldn't rest on example figures — set Days used per stage (the
learned medians beside it are a guide). Existing values are left as they are."""
import frappe


def execute():
    s = frappe.get_single("Re-order Settings")
    defaults = {"history_days": 90, "near_margin": 10, "default_safety_days": 5, "default_cover_days": 30,
                "default_round_to": 1, "lead_history_months": 6, "stock_project_period": "Quarter",
                "stock_project_pattern": "{YY}STK-{FAMILY}-{PERIOD}"}
    for field, value in defaults.items():
        if not s.get(field):
            s.set(field, value)
    have = {(r.stage or "").strip().lower() for r in s.stage_leads}
    for stage in ("Knitting", "Dyeing", "Finishing"):
        if stage.lower() not in have:
            s.append("stage_leads", {"stage": stage})
    s.flags.ignore_permissions = True
    s.save()

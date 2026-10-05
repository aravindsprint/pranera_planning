"""Lead days per stage, by route: each stage now has In-house days (override_days, the old
Days used) and Job work days (jobwork_override_days).

- A stage whose usual route is Job work had its Days used meant for job work: moved to Job work days.
- A stage entered twice (one row per route) becomes one row: the In-house row's days go to In-house
  days, the Job work row's to Job work days; the first row's usual route and services stay, and the
  other row's services are added. Safe to run again.
"""
import frappe


def execute():
    frappe.reload_doc("planning", "doctype", "re_order_stage_lead", force=True)
    frappe.reload_doc("planning", "doctype", "re_order_settings", force=True)
    s = frappe.get_single("Re-order Settings")
    kept, by_stage = [], {}
    for r in s.get("stage_leads") or []:
        if r.route == "Job work" and r.override_days and not r.jobwork_override_days:
            r.jobwork_override_days, r.override_days = r.override_days, None
        key = (r.stage or "").strip().lower()
        first = by_stage.get(key)
        if not key or not first:
            by_stage[key] = r
            kept.append(r)
            continue
        if r.override_days and not first.override_days:
            first.override_days = r.override_days
        if r.jobwork_override_days and not first.jobwork_override_days:
            first.jobwork_override_days = r.jobwork_override_days
        services = [x.strip() for x in ((first.job_work_services or "") + "," + (r.job_work_services or "")).split(",") if x.strip()]
        first.job_work_services = ", ".join(dict.fromkeys(services))
    s.set("stage_leads", kept)
    for i, r in enumerate(kept, 1):
        r.idx = i
    s.flags.ignore_permissions = True
    s.save()

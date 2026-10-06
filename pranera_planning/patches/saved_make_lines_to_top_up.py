"""Plans saved before "Make qty is used once" still carry Make qty lines, which a re-plan would
order again. Turn each into Top up to the same quantity (the level that plan aimed at, when the
project held nothing before it). Safe to run again: only make lines change."""
import json

import frappe


def execute():
    if not frappe.db.has_column("Project", "saved_plan"):
        return
    for name, raw in frappe.get_all("Project", filters={"saved_plan": ["like", '%"make"%']},
                                    fields=["name", "saved_plan"], as_list=True):
        try:
            plan = json.loads(raw or "{}")
        except ValueError:
            continue
        lines, changed = [], False
        for ln in plan.get("lines") or []:
            if ln.get("mode") == "make":
                ln = {**ln, "mode": "top_up"}
                changed = True
            lines.append(ln)
        if changed:
            plan["lines"] = lines
            frappe.db.set_value("Project", name, "saved_plan", json.dumps(plan), update_modified=False)

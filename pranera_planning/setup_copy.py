"""Copy the planning setup from one site to another (erptest → erp), as a JSON file in the app.

What it carries
  Re-order Settings      every setting and its tables: group rules, stage lead days (learned
                         and entered), seasons, lead-day sources, warehouse for planned requests;
                         not the last-run stamps
  Supplier               Usual lead days
  Workstation            Planning stage, Output per hour, Planning UOM, dia, gauge and
                         Production Capacity, for machines that have a planning stage
  site_config.json       every project_stock_reservation_* key (stage prefixes and the rest)

Usage, from frappe-bench:
  bench --site erptest.pranera.in execute pranera_planning.setup_copy.export_setup
      writes apps/pranera_planning/pranera_planning/setup/planning_setup.json
  bench --site erp.pranera.in execute pranera_planning.setup_copy.apply_setup --kwargs "{'dry_run': 1}"
      shows what would change, writes nothing
  bench --site erp.pranera.in execute pranera_planning.setup_copy.apply_setup
      applies it; then restart (sudo supervisorctl restart all) and run
      bench --site erp.pranera.in execute pranera_planning.reorder.recalculate_all

On a site without a shell (Frappe Cloud) run apply_from_desk from the browser console on /app,
first with dry_run 1. Site config written there may be reset by a deploy: also add the
project_stock_reservation_* keys under the site's Config in the dashboard.

Records the target site doesn't have (an item group, warehouse, supplier or workstation) are
skipped and listed, never created. Applying twice changes nothing the second time.
"""
import json
import os

import frappe
from frappe.utils import flt

SETTINGS = "Re-order Settings"
SKIP_SETTINGS = {"last_run", "last_run_items"}
STD = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "parent", "parentfield",
       "parenttype", "doctype", "_user_tags", "_comments", "_assign", "_liked_by", "_seen"}
WS_FIELDS = ("planning_stage", "kg_per_hour", "planning_uom", "machine_dia", "machine_gauge", "production_capacity")
CONF_PREFIX = "project_stock_reservation_"
LAYOUT = ("Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Fold")


def default_path():
    return frappe.get_app_path("pranera_planning", "setup", "planning_setup.json")


# ── export ────────────────────────────────────────────────────────────────────

def export_setup(path=None):
    path = path or default_path()
    data = {
        "from_site": frappe.local.site,
        "exported_on": str(frappe.utils.now_datetime()),
        "reorder_settings": _settings_dict(),
        "supplier_lead_days": {s.name: s.usual_lead_days for s in frappe.get_all(
            "Supplier", filters={"usual_lead_days": [">", 0]}, fields=["name", "usual_lead_days"], order_by="name")},
        "workstations": _workstations(),
        "site_config": {k: v for k, v in sorted(frappe.get_site_config().items()) if k.startswith(CONF_PREFIX)},
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True, default=str)
        f.write("\n")
    summary = {"file": path, "suppliers": len(data["supplier_lead_days"]), "workstations": len(data["workstations"]),
               "stage_rows": len(data["reorder_settings"].get("stage_leads") or []),
               "group_rules": len(data["reorder_settings"].get("group_rules") or []),
               "site_config_keys": list(data["site_config"])}
    print(json.dumps(summary, indent=1))
    return summary


def _settings_dict():
    doc = frappe.get_single(SETTINGS)
    meta = frappe.get_meta(SETTINGS)
    out = {}
    for df in meta.fields:
        if df.fieldtype in LAYOUT or df.fieldname in SKIP_SETTINGS:
            continue
        if df.fieldtype == "Table":
            out[df.fieldname] = [{k: v for k, v in row.as_dict().items() if k not in STD} for row in doc.get(df.fieldname)]
        else:
            out[df.fieldname] = doc.get(df.fieldname)
    return out


def _workstations():
    have = [f for f in WS_FIELDS if frappe.db.has_column("Workstation", f)]
    return {w.name: {f: w.get(f) for f in have} for w in frappe.get_all(
        "Workstation", filters={"planning_stage": ["is", "set"]}, fields=["name"] + have, order_by="name")}


# ── apply ─────────────────────────────────────────────────────────────────────

def apply_setup(path=None, dry_run=0):
    path = path or default_path()
    with open(path) as f:
        data = json.load(f)
    dry = bool(int(dry_run or 0))
    report = {"site": frappe.local.site, "from": data.get("from_site"), "exported_on": data.get("exported_on"),
              "dry_run": dry, "changed": {}, "skipped": {}}

    _apply_site_config(data.get("site_config") or {}, report, dry)
    _apply_settings(data.get("reorder_settings") or {}, report, dry)
    _apply_suppliers(data.get("supplier_lead_days") or {}, report, dry)
    _apply_workstations(data.get("workstations") or {}, report, dry)

    if dry:
        frappe.db.rollback()
    else:
        frappe.db.commit()
        frappe.clear_cache()
    print(json.dumps(report, indent=1, default=str))
    return report


def _apply_site_config(conf, report, dry):
    from frappe.installer import update_site_config
    current = frappe.get_site_config()
    changed = [k for k, v in conf.items() if current.get(k) != v]
    if changed and not dry:
        for k in changed:
            update_site_config(k, conf[k])
    report["changed"]["site_config"] = changed
    if changed:
        report["note"] = ("Site config keys were written to site_config.json. On Frappe Cloud also add them under "
                          "the site's Config in the dashboard, or the next deploy may drop them.")


def _apply_settings(src, report, dry):
    s = frappe.get_single(SETTINGS)
    meta = frappe.get_meta(SETTINGS)
    skipped, changed = [], []

    wh = src.get("default_warehouse")
    if wh and not frappe.db.exists("Warehouse", wh):
        skipped.append(f"Warehouse for planned requests: {wh} (no such warehouse)")
        src = {**src, "default_warehouse": s.get("default_warehouse")}

    for key, value in src.items():
        df = meta.get_field(key)
        if not df or key in SKIP_SETTINGS:
            continue
        if df.fieldtype == "Table":
            rows = value or []
            if key == "group_rules":
                keep = [r for r in rows if r.get("item_group") and frappe.db.exists("Item Group", r["item_group"])]
                skipped += [f"Group rule: item group {r.get('item_group')} (not on this site)" for r in rows if r not in keep]
                rows = keep
            old = [{k: v for k, v in r.as_dict().items() if k not in STD} for r in s.get(key)]
            if _norm(old) != _norm(rows):
                changed.append(f"{key} ({len(old)} → {len(rows)} rows)")
                s.set(key, [])
                for r in rows:
                    s.append(key, r)
        elif _norm(s.get(key)) != _norm(value):
            changed.append(key)
            s.set(key, value)

    if changed and not dry:
        s.flags.ignore_permissions = True
        s.save()
    report["changed"]["reorder_settings"] = changed
    report["skipped"]["reorder_settings"] = skipped


def _apply_suppliers(days, report, dry):
    changed, missing = 0, []
    current = dict(frappe.get_all("Supplier", filters={"name": ["in", list(days)]}, fields=["name", "usual_lead_days"],
                                  as_list=True)) if days else {}
    for name, d in days.items():
        if name not in current:
            missing.append(name)
        elif int(current[name] or 0) != int(d or 0):
            changed += 1
            if not dry:
                frappe.db.set_value("Supplier", name, "usual_lead_days", int(d or 0), update_modified=False)
    report["changed"]["supplier_lead_days"] = changed
    report["skipped"]["suppliers_not_on_this_site"] = missing


def _apply_workstations(wss, report, dry):
    have = {f for f in WS_FIELDS if frappe.db.has_column("Workstation", f)}
    changed, missing = [], []
    for name, values in wss.items():
        if not frappe.db.exists("Workstation", name):
            missing.append(name)
            continue
        values = {k: v for k, v in values.items() if k in have}
        if values.get("planning_uom") and not frappe.db.exists("UOM", values["planning_uom"]):
            values.pop("planning_uom")
        cur = frappe.db.get_value("Workstation", name, list(values), as_dict=True) or {}
        diff = {k: v for k, v in values.items() if _norm(cur.get(k)) != _norm(v)}
        if diff:
            changed.append(name)
            if not dry:
                frappe.db.set_value("Workstation", name, diff)
    report["changed"]["workstations"] = changed
    report["skipped"]["workstations_not_on_this_site"] = missing


def _norm(x):
    """Compare values the way the database stores them: None/'' and 0/0.0 alike."""
    if isinstance(x, list):
        return [_norm(r) for r in x]
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in sorted(x.items()) if _norm(v) not in (None, "", 0)}
    if isinstance(x, (int, float)):
        return flt(x)
    if x is None:
        return None
    return str(x)


@frappe.whitelist(methods=["POST"])
def apply_from_desk(dry_run=1):
    """The same as apply_setup, for a site without a shell (Frappe Cloud): from the browser
    console on /app, frappe.call("pranera_planning.setup_copy.apply_from_desk", {dry_run: 1})."""
    frappe.only_for("System Manager")
    return apply_setup(dry_run=dry_run)

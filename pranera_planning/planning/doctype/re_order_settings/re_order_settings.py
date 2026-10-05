import frappe
from frappe import _
from frappe.model.document import Document


class ReorderSettings(Document):
    def validate(self):
        from pranera_planning.reorder_math import duplicate_stages
        dups = duplicate_stages([r.as_dict() for r in self.get("stage_leads") or []])
        if dups:
            frappe.throw(_("Each stage can appear only once: {0}. Put its in-house and job-work days in the same row.")
                         .format(", ".join(dups)))

frappe.ui.form.on("Re-order Settings", {
  refresh(frm) {
    frm.add_custom_button(__("Recalculate now"), () => {
      frappe.call("pranera_planning.reorder.recalculate_now").then((r) => frappe.show_alert({ message: r.message, indicator: "blue" }));
    });
    frm.add_custom_button(__("Open report"), () => window.open("/planning-app/reorder-report", "_blank"));
  },
});

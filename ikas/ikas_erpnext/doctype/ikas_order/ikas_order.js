// Copyright (c) 2026, Logedosoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("IKAS Order", {
    refresh(frm) {
        if (frm.doc.status === "Failed") {
            frm.add_custom_button("Retry", () => {
                frm.set_value("status", "New");
                frm.set_value("retry_count", 0);
                frm.set_value("error_type", "");
                frm.set_value("error_message", "");
                frm.save();
            });
        }
    }
});

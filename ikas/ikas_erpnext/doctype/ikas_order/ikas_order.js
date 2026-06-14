// Copyright (c) 2026, Logedosoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("IKAS Order", {
    refresh(frm) {
        if (frm.doc.status === "New" || frm.doc.status === "Failed") {
            frm.add_custom_button("Process", () => {
                frm.disable_save();
                frappe.call({
                    method: "ikas.ikas_utils.process_single_ikas_order",
                    args: { str_docname: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Processing order..."),
                    callback(r) {
                        frm.enable_save();
                        if (r.message.op_result) {
                            frappe.msgprint(r.message.op_message);
                        } else {
                            frappe.msgprint({
                                title: __("Processing Failed"),
                                indicator: "red",
                                message: r.message.op_message
                            });
                        }
                        frm.reload_doc();
                    },
                    error() {
                        frm.enable_save();
                        frm.reload_doc();
                    }
                });
            }, __("Actions"));
        }

        if (frm.doc.status === "Failed") {
            frm.add_custom_button("Retry", () => {
                frm.set_value("status", "New");
                frm.set_value("retry_count", 0);
                frm.set_value("error_type", "");
                frm.set_value("error_message", "");
                frm.save();
            }, __("Actions"));
        }
    }
});

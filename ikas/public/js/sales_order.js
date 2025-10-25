/* LOGEDOSOFT@2025
Sales Order IKAS button
*/

function get_ikas_order(frm) {
    frappe.prompt({
        label: __('Order ID'),
        fieldname: 'order_id',
        fieldtype: 'Int'
    }, (values) => {
        frappe.call({
            method: 'ikas.ikas_utils.process_ikas_order',
            args: {
                order_id: values.order_id,
				doc: frm.doc
            },
            callback: (r) => {
                if (!r.message.op_result) {
                    frappe.throw(r.message.op_message);
                } else {
					frappe.model.sync(r.message.doc);
					frm.dirty();
					frm.refresh_fields(["items", "roll_count", "total_weight"]); 
                    frappe.msgprint(__('Sales Order bilgileri IKAS verisi ile dolduruldu.'));
                }
            }
        })
    });
}

frappe.ui.form.on("Sales Order", {
    refresh(frm) {
        if (frm.doc.__islocal === 1) {
            frm.add_custom_button(
                __("IKAS Sales Order"),
                () => get_ikas_order(frm)
            );
        }
    }
});

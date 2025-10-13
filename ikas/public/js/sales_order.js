/*LOGEDOSOFT@2025
Sales Order IKAS button
*/

function get_ikas_order(frm) {
	//Ask user order id in frappe dialog then call get_ikas_order_info in ikas_utils.py
	frappe.prompt({
		label: __('Order ID'),
		fieldname: 'order_id',
		fieldtype: 'Int'
	}, (values) => {
		frappe.call({
			method: 'ikas.ikas_utils.get_ikas_order_info',
			args: {
				order_id: values.order_id
			},
			callback: (r) => {
				console.log(r);
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
				//__("Stock Reservation")
			);
		}
	}
});
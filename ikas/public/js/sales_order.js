/*LOGEDOSOFT@2025
Sales Order IKAS button
*/

function get_ikas_order(frm) {
	//Ask user order id in frappe dialog then call get_order_info in ikas_utils.py
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
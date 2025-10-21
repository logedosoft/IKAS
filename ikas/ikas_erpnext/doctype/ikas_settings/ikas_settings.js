frappe.ui.form.on("IKAS Settings", {
	connection_check(frm) {
		frappe.call({
			method: "ikas.ikas_utils.get_ikas_auth_token_py",
			callback: (r) => {
				if (!r.message || r.message.op_result === false) {
					frappe.throw(r.message ? r.message : "Sunucudan yanıt alınamadı!");
				} else {
					frappe.msgprint({
						title: "Bağlantı Başarılı ✅",
						message: "Access Token alındı ve form kaydedildi.",
						indicator: "green"
					});

					// Formu yenile (güncel token'ı göstermek için)
					frm.reload_doc();
				}
			},
			error: (err) => {
				frappe.msgprint({
					title: "Hata ❌",
					message: "Bağlantı sırasında hata oluştu: " + err.message,
					indicator: "red"
				});
			}
		});
	}
});

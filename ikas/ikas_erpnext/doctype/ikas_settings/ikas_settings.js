function get_ikas_auth_token(frm, store_name, client_id, client_secret) {
	frappe.call({
		method: 'ikas.ikas_utils.process_ikas_auth',
		args: {
			store_name: store_name,
			client_id: client_id,
			client_secret: client_secret
		},
		callback: (r) => {
			if (!r.message || r.message.op_result === false) {
				frappe.throw(r.message ? r.message.op_message : "Sunucudan yanıt alınamadı!");
			} else {
				// Token ve geçerlilik tarihini form alanlarına yaz
				frm.set_value("token", r.message.auth_token);
				frm.set_value("token_valid_upto", frappe.datetime.now_datetime());

				// Alanları ekranda güncelle
				frm.refresh_field("token");
				frm.refresh_field("token_valid_upto");

				// Formu kaydet ve kayıttan sonra mesaj göster
				frm.save().then(() => {
					frappe.msgprint({
						title: "Bağlantı Başarılı ✅",
						message: "Access Token alındı ve form kaydedildi.",
						indicator: "green"
					});
				}).catch((err) => {
					frappe.msgprint({
						title: "Hata ❌",
						message: "Form kaydedilirken hata oluştu: " + err.message,
						indicator: "red"
					});
				});
			}
		}
	});
}


frappe.ui.form.on("IKAS Settings", {
	connection_check(frm) {
		const store_name = frm.doc.store_name;
		const client_id = frm.doc.client_id;
		const client_secret = frm.doc.client_secret;

		if (!store_name || !client_id || !client_secret) {
			frappe.msgprint("⚠️ Lütfen Store Name, Client ID ve Client Secret alanlarını doldurun!");
			return;
		}

		get_ikas_auth_token(frm, store_name, client_id, client_secret);
	}
});

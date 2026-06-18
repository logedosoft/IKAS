# -*- coding: utf-8 -*-
# LOGEDOSOFT

import frappe, json
from frappe.utils import now_datetime
from datetime import datetime, timedelta
import math


def _truncate_error_message(str_message, int_max_length=200):
	if not str_message:
		return ""
	if len(str_message) <= int_max_length:
		return str_message
	return str_message[:int_max_length - 3] + "..."


def process_ikas_auth(store_name, client_id, client_secret):

    # Buraya IKAS API token alma mantığını yaz
    import requests
    api_url = f"{store_name}"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {
			"grant_type": "client_credentials",
			"client_id": client_id,
			"client_secret": client_secret
		}
    
    response = requests.post(api_url, data=payload, headers=headers ,timeout=3)
   
    if response.status_code != 200:
        return {"op_result": False, "op_message": f"Token API failed: {response.text}"}
    data = response.json()
	
    return {"op_result": True, "auth_token": data.get("access_token")}


def get_valid_token():
	"""Return a valid IKAS API token.

	Checks Redis cache first; if miss, reads IKAS Settings from DB.
	Refreshes via OAuth when expired and persists the new token for
	server-restart resilience. Uses a distributed lock to prevent
	multiple workers from refreshing simultaneously.
	"""
	str_cache_key = "ikas_access_token"
	token = frappe.cache().get_value(str_cache_key)
	if token:
		return token

	str_lock_key = "ikas_token_refresh_lock"
	if frappe.cache().get_value(str_lock_key):
		import time
		time.sleep(1)
		token = frappe.cache().get_value(str_cache_key)
		if token:
			return token

	frappe.cache().set_value(str_lock_key, True, expires_in_sec=10)

	try:
		settings = frappe.get_single("IKAS Settings")
		token = settings.token
		token_valid_upto = settings.token_valid_upto
		now = datetime.now()
		bln_needs_refresh = False

		if not token_valid_upto or str(token_valid_upto) in ["0001-01-01 00:00:00", "0001-01-01"]:
			bln_needs_refresh = True
		else:
			if isinstance(token_valid_upto, str):
				try:
					token_valid_upto = datetime.strptime(token_valid_upto, "%Y-%m-%d %H:%M:%S")
				except Exception:
					token_valid_upto = now - timedelta(hours=5)
			if now > token_valid_upto:
				bln_needs_refresh = True

		if bln_needs_refresh:
			dct_result = process_ikas_auth(settings.store_name, settings.client_id, settings.get_password("client_secret"))
			if dct_result.get("op_result"):
				token = dct_result.get("auth_token")
				settings.token = token
				settings.token_valid_upto = now + timedelta(hours=4)
				settings.save(ignore_permissions=True)
			else:
				frappe.log_error("IKAS Token Refresh Failed", dct_result.get("op_message", ""))
				token = None

		if token:
			frappe.cache().set_value(str_cache_key, token, expires_in_sec=14400)
	finally:
		frappe.cache().delete_value(str_lock_key)

	return token


def fetch_ikas_orders():
	"""Scheduler: fetch IKAS orders into staging docs. Runs every 10 min."""
	import requests

	settings = frappe.get_single("IKAS Settings")
	token = get_valid_token()
	if not token:
		frappe.log_error("IKAS Fetcher", "No valid token available")
		return 0
	start_date = settings.automatic_transfer_start_date
	last_order_no = settings.last_order_no or ""

	if not start_date:
		frappe.log_error("IKAS Fetcher", "automatic_transfer_start_date is not set")
		return 0

	from datetime import datetime
	from frappe.utils import getdate
	dt_start = datetime.combine(getdate(start_date), datetime.min.time())
	start_date_millis = int(dt_start.timestamp() * 1000)

	api_url = "https://api.myikas.com/api/v1/admin/graphql"
	headers = {
		"Content-Type": "application/json",
		"Authorization": f"Bearer {token}"
	}

	lst_new_records = []
	int_page = 1
	int_max_pages = 50
	str_highest_order_no = last_order_no

	while int_page <= int_max_pages:
		query = f"""
		query {{
			listOrder(
				orderedAt: {{ gte: {start_date_millis} }}
				pagination: {{ limit: 50, page: {int_page} }}
			) {{
				data {{
					id
					orderNumber
					orderedAt
					totalPrice
					totalFinalPrice
					currencyCode
					status
					customer {{
						id
						email
						firstName
						lastName
						phone
						isGuestCheckout
					}}
					billingAddress {{
						addressLine1
						addressLine2
						city {{ code id name }}
						company
						country {{ code id iso2 iso3 name }}
						district {{ code id name }}
						firstName
						id
						identityNumber
						lastName
						phone
						postalCode
						state {{ code id name }}
						taxNumber
						taxOffice
					}}
					shippingAddress {{
						addressLine1
						addressLine2
						city {{ code id name }}
						company
						country {{ code id iso2 iso3 name }}
						district {{ code id name }}
						firstName
						id
						identityNumber
						lastName
						phone
						postalCode
						state {{ code id name }}
						taxNumber
						taxOffice
					}}
					orderLineItems {{
						id
						createdAt
						currencyCode
						discount {{ amount amountType reason }}
						discountPrice
						finalPrice
						price
						quantity
						status
						taxValue
						variant {{
							barcodeList
							brand {{ id name }}
							id
							name
							sku
							variantValues {{ variantTypeName variantValueName }}
						}}
					}}
					shippingLines {{ price taxValue title }}
					taxLines {{ price rate }}
					orderAdjustments {{
						amount
						amountType
						name
						type
					}}
				}}
			}}
		}}
		"""
		try:
			response = requests.post(api_url, json={"query": query}, headers=headers, timeout=30)
			response.raise_for_status()
			dct_result = response.json()
		except Exception as e:
			frappe.log_error("IKAS Fetcher API Error", frappe.get_traceback())
			break

		if "errors" in dct_result:
			frappe.log_error("IKAS Fetcher GraphQL Error", frappe.as_json(dct_result["errors"]))
			break

		lst_orders = dct_result.get("data", {}).get("listOrder", {}).get("data", [])
		if not lst_orders:
			break

		for dct_order in lst_orders:
			try:
				str_order_number = dct_order.get("orderNumber")

				if last_order_no and int(str_order_number) <= int(last_order_no):
					continue

				bln_exists = frappe.db.exists(
					"IKAS Order",
					{"order_number": str_order_number}
				)
				if bln_exists:
					continue

				int_ordered_at = dct_order.get("orderedAt")
				if isinstance(int_ordered_at, int):
					dt_ordered = datetime.fromtimestamp(int_ordered_at / 1000)
				else:
					continue

				doc_ikas_order = frappe.new_doc("IKAS Order")
				doc_ikas_order.source1 = "IKAS"
				doc_ikas_order.order_number = str_order_number
				doc_ikas_order.ordered_at = dt_ordered
				doc_ikas_order.customer_email = dct_order.get("customer", {}).get("email")
				doc_ikas_order.total_amount = dct_order.get("totalFinalPrice") or 0
				doc_ikas_order.currency = dct_order.get("currencyCode")
				doc_ikas_order.status = "New"
				doc_ikas_order.save(ignore_permissions=True)

				doc_payload = frappe.new_doc("IKAS Order Payload")
				doc_payload.ikas_order = doc_ikas_order.name
				doc_payload.raw_payload = frappe.as_json(dct_order)
				doc_payload.fetched_at = now_datetime()
				doc_payload.save(ignore_permissions=True)

				lst_new_records.append(doc_ikas_order.name)
				if int(str_order_number) > int(str_highest_order_no or 0):
					str_highest_order_no = str_order_number
			except Exception as e:
				frappe.log_error("IKAS Fetcher Order Error", f"{dct_order.get('orderNumber', '?')}: {e}")

		int_page += 1

	if str_highest_order_no and str_highest_order_no != last_order_no:
		settings.last_order_no = str_highest_order_no
		settings.save(ignore_permissions=True)

	return len(lst_new_records)


def _process_ikas_staged_order(doc_ecommerce_order):
	"""Process a single IKAS-staged order into an ERPNext Sales Order.

	Fetches full order detail if the payload is minimal, then delegates to
	process_ikas_order for SO creation.
	"""
	dctResult = frappe._dict({"op_result": False, "error_type": "GENERIC", "op_message": ""})

	lst_payloads = frappe.get_all(
		"IKAS Order Payload",
		filters={"ikas_order": doc_ecommerce_order.name},
		fields=["name", "raw_payload"]
	)
	if not lst_payloads:
		frappe.throw(f"No IKAS Order Payload found for {doc_ecommerce_order.name}")

	doc_payload = frappe.get_doc("IKAS Order Payload", lst_payloads[0].name)
	dct_raw = json.loads(doc_payload.raw_payload) if isinstance(doc_payload.raw_payload, str) else (doc_payload.raw_payload or {})

	bln_has_billing = "billingAddress" in dct_raw or "orderLineItems" in dct_raw
	if not bln_has_billing:
		dct_full = get_ikas_order_info(doc_ecommerce_order.order_number)
		if not dct_full.get("op_result"):
			frappe.throw(f"Failed to fetch full order detail: {dct_full.get('op_message')}")
		lst_order_data = dct_full.get("order_info", {}).get("data", {}).get("listOrder", {}).get("data", [])
		if not lst_order_data:
			frappe.throw(f"Order {doc_ecommerce_order.order_number} not found in IKAS")
		dct_raw = lst_order_data[0]
		doc_payload.raw_payload = frappe.as_json(dct_raw)
		doc_payload.save(ignore_permissions=True)

	doc_sales_order = frappe.new_doc("Sales Order")
	doc_sales_order.customer = frappe.get_single("IKAS Settings").customer_name
	doc_sales_order.po_no = doc_ecommerce_order.order_number

	str_ordered_at = dct_raw.get("orderedAt", "")
	if isinstance(str_ordered_at, int):
		str_date = datetime.fromtimestamp(str_ordered_at / 1000).strftime("%Y-%m-%d %H:%M:%S")
	else:
		str_date = str(str_ordered_at)
	doc_sales_order.transaction_date = str_date
	doc_sales_order.delivery_date = str_date

	doc_json = frappe.as_json(doc_sales_order)

	dct_process_result = process_ikas_order(doc_ecommerce_order.order_number, doc_json, save_doc=True, order_data=dct_raw)

	if dct_process_result.get("op_result"):
		str_so_name = frappe.db.get_value("Sales Order", {"po_no": doc_ecommerce_order.order_number}, "name")
		if str_so_name:
			dctResult['op_result'] = True
			dctResult['sales_order'] = str_so_name
		else:
			dctResult['error_type'] = "GENERIC"
			dctResult['op_message'] = "Sales Order was saved but could not be retrieved by po_no"
	else:
		dctResult['error_type'] = dct_process_result.get("error_type", "GENERIC")
		dctResult['op_message'] = dct_process_result.get("op_message", "")

	return dctResult


@frappe.whitelist()
def process_single_ikas_order(str_docname):
	dctResult = frappe._dict({"op_result": False, "op_message": ""})

	doc = frappe.get_doc("IKAS Order", str_docname)
	if doc.source1 != "IKAS":
		dctResult["op_message"] = "No processor for source"
		return dctResult

	doc.status = "Processing"
	doc.error_type = None
	doc.error_message = None
	doc.retry_count = 0
	doc.save(ignore_permissions=True)

	dct_process_result = _process_ikas_staged_order(doc)

	if dct_process_result.get("op_result"):
		doc.status = "Completed"
		doc.sales_order = dct_process_result.get("sales_order")
		dctResult["op_result"] = True
		dctResult["op_message"] = f"Sales Order {doc.sales_order} created."
	else:
		doc.error_type = dct_process_result.get("error_type", "GENERIC")
		doc.error_message = _truncate_error_message(dct_process_result.get("op_message", ""))
		doc.retry_count = (doc.retry_count or 0) + 1
		doc.status = "Failed" if doc.retry_count >= 3 else "New"
		dctResult["op_message"] = doc.error_message

	doc.save(ignore_permissions=True)
	return dctResult


def process_staged_orders():
	"""Scheduler: process New IKAS Order records. Runs every 3 min."""
	lst_orders = frappe.get_all(
		"IKAS Order",
		filters={"status": "New"},
		order_by="ordered_at ASC",
		limit_page_length=20
	)

	for dct_order in lst_orders:
		try:
			doc = frappe.get_doc("IKAS Order", dct_order.name)
			doc.status = "Processing"
			doc.error_type = None
			doc.error_message = None
			doc.save(ignore_permissions=True)

			try:
				if doc.source1 == "IKAS":
					dct_process_result = _process_ikas_staged_order(doc)
					if dct_process_result.get("op_result"):
						doc.status = "Completed"
						doc.sales_order = dct_process_result.get("sales_order")
					else:
						doc.error_type = dct_process_result.get("error_type", "GENERIC")
						doc.error_message = _truncate_error_message(dct_process_result.get("op_message", ""))
						doc.retry_count = (doc.retry_count or 0) + 1
						doc.status = "Failed" if doc.retry_count >= 3 else "New"
				else:
					doc.status = "Skipped"
					doc.error_type = "GENERIC"
					doc.error_message = "No processor for source"

			except Exception as e:
				doc.error_type = "GENERIC"
				doc.error_message = _truncate_error_message(frappe.get_traceback())
				doc.retry_count = (doc.retry_count or 0) + 1
				doc.status = "Failed" if doc.retry_count >= 3 else "New"

			doc.save(ignore_permissions=True)
		except Exception as e:
			frappe.log_error("IKAS Processor Record Error", f"{dct_order.name}: {e}")


def get_ikas_order_info(order_id):
    import requests

    token = get_valid_token()
    if not token:
        return {"op_result": False, "op_message": "IKAS token alınamadı"}

    api_url = "https://api.myikas.com/api/v1/admin/graphql"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {token}"
    }

    # GraphQL query, f-string ile order_id yerleştiriliyor
    query = f"""
    query {{
      listOrder(orderNumber: {{eq: "{order_id}"}}) {{
        data {{
          billingAddress {{
            addressLine1
            addressLine2
            city {{ code id name }}
            company
            country {{ code id iso2 iso3 name }}
            district {{ code id name }}
            firstName
            id
            identityNumber
            isDefault
            lastName
            phone
            postalCode
            state {{ code id name }}
            taxNumber
            taxOffice
          }}
          branch {{ id name }}
          branchSessionId
          cancelReason
          cancelledAt
          clientIp
          createdAt
          currencyCode
          currencyRates {{ code originalRate rate }}
          customer {{ email firstName id isGuestCheckout lastName phone }}
          deleted
          giftPackageLines {{ price taxValue }}
          giftPackageNote
          host
          id
          invoices {{ appId appName createdAt id invoiceNumber storeAppId type }}
          isGiftPackage
          merchantId
          note
          orderAdjustments {{
            amount
            amountType
            appliedOrderLines {{ amount appliedQuantity orderLineId }}
            campaignId
            couponId
            name
            order
            type
          }}
          orderLineItems {{
            createdAt
            currencyCode
            deleted
            discount {{ amount amountType reason }}
            discountPrice
            finalPrice
            id
            options {{
              name
              productOptionId
              productOptionsSetId
              type
              values {{ name price value }}
            }}
            originalOrderLineItemId
            price
            quantity
            status
            statusUpdatedAt
            stockLocationId
            taxValue
            updatedAt
            variant {{
              barcodeList
              brand {{ id name }}
              categories {{ categoryPath {{ id name }} id name }}
              id
              mainImageId
              name
              prices {{ buyPrice currency discountPrice priceListId sellPrice }}
              productId
              sku
              slug
              tagIds
              taxValue
              type
              variantValues {{ order variantTypeId variantTypeName variantValueId variantValueName }}
            }}
          }}
          orderNumber
          orderPackageSequence
          orderPackageStatus
          orderPackages {{
            createdAt
            deleted
            errorMessage
            id
            note
            orderLineItemIds
            orderPackageFulfillStatus
            orderPackageNumber
            stockLocationId
            trackingInfo {{ barcode cargoCompany isSendNotification trackingLink trackingNumber }}
            updatedAt
          }}
          orderPaymentStatus
          orderSequence
          orderTagIds
          orderedAt
          paymentMethods {{ price type }}
          priceList {{ id name }}
          salesChannel {{ id name type }}
          shippingAddress {{
            addressLine1
            addressLine2
            city {{ code id name }}
            company
            country {{ code id iso2 iso3 name }}
            district {{ code id name }}
            firstName
            id
            identityNumber
            isDefault
            lastName
            phone
            postalCode
            state {{ code id name }}
            taxNumber
            taxOffice
          }}
          shippingLines {{ isRefunded price shippingSettingsId shippingZoneRateId taxValue title }}
          shippingMethod
          staff {{ email firstName lastName }}
          status
          storefront {{ id name }}
          storefrontRouting {{ domain id locale path priceListId }}
          storefrontTheme {{ id name themeId themeVersionId }}
          taxLines {{ price rate }}
          terminalId
          totalFinalPrice
          totalPrice
          updatedAt
          userAgent
        }}
      }}
    }}
    """
    response = requests.post(api_url, json={"query": query}, headers=headers,timeout=3)


    if response.status_code != 200:
        dctResult = {
            'op_result': False,
            'op_message': f"Get Order API failed with status {response.status_code}. Reason: {response.text}"
        }
    else:
        dctResult = {
            'op_result': True,
            'order_info': response.json()
        }

    #print(dctResult)
    return dctResult


def _find_linked_address(dct_addr_filters, str_link_doctype=None, str_link_name=None):
    """Find Address matching dct_addr_filters, optionally linked via Dynamic Link.

    link_doctype/link_name live on tabDynamic Link, NOT on tabAddress.
    We first resolve linked Address names, then filter Address by its own columns.
    """
    bln_has_link = str_link_doctype is not None
    if bln_has_link:
        dct_link = {"parenttype": "Address", "link_doctype": str_link_doctype}
        if str_link_name:
            dct_link["link_name"] = str_link_name
        lst_linked = frappe.get_all("Dynamic Link", filters=dct_link, fields=["parent"])
        lst_names = [d.parent for d in lst_linked]
        if not lst_names:
            str_address_name = None
        else:
            dct_local = dict(dct_addr_filters)
            dct_local["name"] = ["in", lst_names]
            str_address_name = frappe.db.get_value("Address", dct_local, "name")
    else:
        str_address_name = frappe.db.get_value("Address", dct_addr_filters, "name")
    return str_address_name




@frappe.whitelist()
def process_ikas_order(order_id, doc, save_doc=True, order_data=None):
    """
    IKAS siparişini işler. Hata olursa detay Frappe loguna yazılır,
    kullanıcıya basit bir mesaj döner.
    """
    dctResult = {
        'op_result': False,
        'op_message': '',
        'doc': None
    }

    try:
        # save_doc parametresini boolean'a çevir
        if isinstance(save_doc, str):
            save_doc = save_doc.lower() in ['true', '1', 'yes']

        # doc zaten dict ise json.loads yapma
        if isinstance(doc, dict):
            doc= frappe.get_doc(doc)
        else:
            doc= frappe.get_doc(json.loads(doc))
        ikas_settings = frappe.get_single("IKAS Settings")

        customer_name_setting = ikas_settings.customer_name

        if order_data is not None:
            if isinstance(order_data, str):
                order_data = json.loads(order_data)
            order = order_data
        else:
            dctOrderInfo = get_ikas_order_info(order_id)

            if not dctOrderInfo.get('op_result'):
                dctResult['op_message'] = "IKAS sipariş alınamadı."
                return dctResult

            order_list = dctOrderInfo.get('order_info', {}).get('data', {}).get('listOrder', {}).get('data', [])
            if not order_list:
                dctResult['op_message'] = "Sipariş numarası bulunamadı."
                return dctResult

            order = order_list[0]

        # Daha önce aktarılmış mı
        existing_sos = frappe.get_all("Sales Order", filters={"po_no": order_id}, fields=["name"])
        if existing_sos:
            dctResult['op_result'] = True
            dctResult['op_message'] = f"Bu sipariş zaten aktarılmış: {existing_sos[0].name}"
            return dctResult

        # Müşteri ve adres işlemleri
        try:
            customer_data = order.get('customer', {})
            first_name = customer_data.get('firstName', '')
            last_name = customer_data.get('lastName', '')
            str_email = customer_data.get('email', '').strip()
            str_phone = customer_data.get('phone', '').strip()

            dct_shipping = order.get('shippingAddress', {})
            str_ship_addr1 = dct_shipping.get('addressLine1', '')
            str_ship_city = dct_shipping.get('city', {}).get('name', '')

            existing_address_name = _find_linked_address(
                {"email_id": str_email, "phone": str_phone, "city": str_ship_city, "address_line1": str_ship_addr1},
                "Customer", customer_name_setting
            ) if customer_name_setting else None

            if not existing_address_name:
                existing_address_name = _find_linked_address(
                    {"email_id": str_email},
                    "Customer", customer_name_setting
                ) if customer_name_setting else None

            if not existing_address_name and not customer_name_setting:
                existing_address_name = _find_linked_address(
                    {"email_id": str_email},
                    "Customer"
                )

            dct_billing = order.get('billingAddress', {})
            bln_billing_differs = bool(
                dct_billing and (
                    dct_billing.get('addressLine1') != dct_shipping.get('addressLine1')
                    or dct_billing.get('city', {}).get('name') != dct_shipping.get('city', {}).get('name')
                )
            )

            billing_address_name = None
            if customer_name_setting:
                if existing_address_name:
                    docAddress = frappe.get_doc("Address", existing_address_name)
                    existing_link = any(link.link_name == customer_name_setting and link.link_doctype == "Customer"
                                        for link in docAddress.links)
                    if not existing_link:
                        docAddress.append("links", {
                            "link_doctype": "Customer",
                            "link_name": customer_name_setting
                        })
                        docAddress.save(ignore_permissions=True)
                    customer_for_order = customer_name_setting
                    shipping_address_name = existing_address_name
                    if bln_billing_differs:
                        billing_address_name = create_address(order, customer_name_setting, first_name, last_name, "Billing")
                else:
                    shipping_address_name = create_address(order, customer_name_setting, first_name, last_name, "Shipping")
                    if bln_billing_differs:
                        billing_address_name = create_address(order, customer_name_setting, first_name, last_name, "Billing")
                    customer_for_order = customer_name_setting
            else:
                if existing_address_name:
                    link_list = frappe.get_all(
                        "Dynamic Link",
                        filters={"parent": existing_address_name, "link_doctype": "Customer"},
                        fields=["link_name"]
                    )
                    existing_customer = link_list[0].link_name if link_list else None

                    if existing_customer:
                        customer_for_order = existing_customer
                        shipping_address_name = existing_address_name
                        if bln_billing_differs:
                            billing_address_name = create_address(order, existing_customer, first_name, last_name, "Billing")
                    else:
                        docCustomer = frappe.new_doc('Customer')
                        docCustomer.customer_name = f"{first_name} {last_name.strip()}"
                        docCustomer.customer_type = "Company"
                        docCustomer.customer_group = "Individual"
                        docCustomer.save()
                        shipping_address_name = create_address(order, docCustomer.name, first_name, last_name, "Shipping")
                        if bln_billing_differs:
                            billing_address_name = create_address(order, docCustomer.name, first_name, last_name, "Billing")
                        customer_for_order = docCustomer.name
                else:
                    docCustomer = frappe.new_doc('Customer')
                    docCustomer.customer_name = f"{first_name} {last_name.strip()}"
                    docCustomer.customer_type = "Company"
                    docCustomer.customer_group = "Individual"
                    docCustomer.save()
                    shipping_address_name = create_address(order, docCustomer.name, first_name, last_name, "Shipping")
                    if bln_billing_differs:
                        billing_address_name = create_address(order, docCustomer.name, first_name, last_name, "Billing")
                    customer_for_order = docCustomer.name

        except Exception as e:
            frappe.log_error("Müşteri/Adres oluşturma hatası", frappe.get_traceback())
            dctResult['op_message'] = "Müşteri veya adres oluşturulamadı, destek ile iletişime geçin."
            return dctResult

        # Doc alanları setleme
        try:
            doc.customer = customer_for_order
            doc.customer_name = customer_for_order
            doc.shipping_address_name = shipping_address_name
            doc.customer_address = shipping_address_name
            if billing_address_name:
                doc.billing_address_name = billing_address_name
            doc.po_no = order_id
            doc.custom_ld_sales_person = ikas_settings.custom_ld_sales_person

            str_vehicle = getattr(ikas_settings, 'custom_ld_vehicle', None)
            if not str_vehicle:
                str_vehicle = frappe.db.get_value("Vehicle", {}, "name")
            if str_vehicle:
                doc.custom_ld_vehicle = str_vehicle
            # Tax category setting
            doc.tax_category = ikas_settings.tax_category
            doc.payment_terms_template = ikas_settings.payment_terms_template

            ordered_at = order.get('orderedAt', '')
            date = ''
            if ordered_at:
                try:
                    date = datetime.fromtimestamp(ordered_at / 1000).strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    date = str(ordered_at)

            doc.transaction_date = date
            doc.delivery_date = date
            doc.po_date = date
        except Exception as e:
            frappe.log_error("Doc alanları setleme hatası", frappe.get_traceback())
            dctResult['op_message'] = "Sipariş alanları ayarlanamadı, destek ile iletişime geçin."
            return dctResult

        # Items ekleme
        try:
            doc.items = []
            total_qty = 0
            total_amount = 0

            for line in order.get('orderLineItems', []):
                variant = line.get('variant', {})
                variant_values = variant.get('variantValues', [])
                variant_value_names = ', '.join([v.get('variantValueName', '') for v in variant_values])
                description= variant.get('name', '')
                if variant_value_names:
                    description += ' ' + variant_value_names

                itemnamesrc = variant.get('sku')

                if not itemnamesrc:
                    dctResult['op_result'] = False
                    dctResult['error_type'] = "MISSING_SKU_IN_IKAS"
                    dctResult['op_message'] = "Product has no SKU in IKAS. Add SKU in IKAS admin."
                    return dctResult

                # SKU ile ERPNext Item arama
                erp_item = frappe.db.get_value(
                    "Item",
                    {"item_code": itemnamesrc},
                    ["item_code", "item_name", "stock_uom"],
                    as_dict=True
                )

                if not erp_item:
                    dctResult['op_result'] = False
                    dctResult['error_type'] = "MISSING_SKU_IN_ERP"
                    dctResult['op_message'] = f"Product code {itemnamesrc} not found in ERPNext."
                    return dctResult

                # SKU bulunduysa ERPNext bilgilerini kullanarak satır oluştur
                quantity = line.get('quantity', 0)  # örn. 2
                barcode_list = variant.get('barcodeList', [])

                if barcode_list:
                    try:
                        unit_qty = float(barcode_list[0].replace(',', '.'))  # kg cinsinden
                    except ValueError:
                        unit_qty = 0.0
                else:
                    unit_qty = 0.0

                # 1 kg fiyatı
                kdvharifiyati=line.get('finalPrice', 0) / (1 + line.get('taxValue', 0)/100)
                rate_per_kg = kdvharifiyati / unit_qty if unit_qty > 0 else 0

                # Toplam miktar
                qty = unit_qty * quantity

                # Toplam tutar
                amount = rate_per_kg * qty
                
                doc.append('items', {
                    'item_code': erp_item.item_code,
                    'item_name': erp_item.item_name,
                    'description':description,
                    'qty': qty,            # kg cinsinden toplam
                    'rate': rate_per_kg,   # 1 kg fiyatı
                    'amount': amount,
                    'delivery_date': date,
                    'uom': 'kg'
                })



              

            for ship in order.get('shippingLines', []):
                erp_ship = frappe.db.get_value(
                    "Item",
                    {"item_code": ikas_settings.cargo_company},
                    ["item_code", "item_name", "stock_uom"],
                    as_dict=True
                )

                if not erp_ship:
                    frappe.log_error("Kargo Item bulunamadı!", f"Item Code: {ikas_settings.cargo_company}")
                    continue

                
                kdvharickargofiyati=ship.get('price', 0) / (1 + ship.get('taxValue', 0)/100)
                doc.append('items', {
                    'item_code': erp_ship.item_code,
                    'item_name': erp_ship.item_name,
                    'qty': 1,
                    'rate': kdvharickargofiyati,
                    'amount': kdvharickargofiyati,
                    'delivery_date': date,
                    'uom': erp_ship.stock_uom
                })




            tax_lines = order.get('taxLines', [])

            # Mevcut vergileri temizle
            doc.set("taxes", [])

            for tax in tax_lines:
                rate = float(tax.get("rate", 0))
                price = float(tax.get("price", 0))

                # IKAS Tax Doctype içinden rate'e göre account çek
                tax_row = frappe.db.get_value(
                    "IKAS Tax",
                    {"rate": rate},
                    ["account_name"],
                    as_dict=True
                )

                if not tax_row or not tax_row.get("account_name"):
                    frappe.throw(
                        f"Tax rate {rate} from IKAS is not mapped in IKAS Tax DocType. "
                        f"Please map it before processing order {order_id}."
                    )
                account = tax_row.account_name

                # Actual tipi ile vergi satırı ekle
                doc.append("taxes", {
                    "charge_type": "Actual",
                    "account_head": account,
                    "rate": rate,
                    "tax_amount": price,
                    "description":account
                })

            # Vergileri yeniden hesapla
            doc.calculate_taxes_and_totals()

            totalFinalPrice = float(order.get('totalFinalPrice', 0) or 0)
            totalFinalPrice_rounded = math.ceil(totalFinalPrice)
            erp_grand_total_raw = float(doc.get("grand_total") or 0)
            erp_grand_total = math.ceil(erp_grand_total_raw)
            total_amountkontrol = erp_grand_total

            dDifference = abs(totalFinalPrice_rounded - total_amountkontrol)
            if dDifference > 5:
                ikas_order_number = order.get('orderNumber', 'Bilinmiyor')
                frappe.log_error(
                    f"IKAS-ERP tutar uyumsuzluğu! Sipariş: {ikas_order_number}",
                    f"IKAS: {totalFinalPrice_rounded}, ERP: {total_amountkontrol}, Fark: {dDifference}"
                )
                dctResult['error_type'] = "Totals Mismatch"
                dctResult['op_message'] = "IKAS order total amount and generated sales order's total amount doesn't match"
                return dctResult

        except Exception as e:
            frappe.log_error("İtem veya toplam hesaplama hatası", frappe.get_traceback())
            dctResult['op_message'] = "Sipariş kalemleri işlenemedi, destek ile iletişime geçin."
            return dctResult

        dctResult['doc'] = doc.as_dict()

        try:
            if doc:
                if save_doc:  # sadece save_doc=True ise kaydet
                    frappe.log_error("SO info",f"SO Name: {doc.name}, po_no: {doc.po_no}, Customer: {doc.customer}")
                    doc.save(ignore_permissions=True)
                    dctResult['op_result'] = True
                    dctResult['op_message'] = "Sipariş Başarıyla Kaydedildi."
                else:
                    dctResult['op_result'] = True
                    dctResult['op_message'] = "Sipariş bilgileri dolduruldu (veritabanına kaydedilmedi)."
            try:
                docIKASSettings = frappe.get_single("IKAS Settings")
                if getattr(docIKASSettings, "order_auto_confirm", 1):
                # None veya string sorunlarını önlemek için int'e çeviriyoruz
                    frappe.log_error("SO Debug",f"Sales Order Kaydediliyor - SO Name: {doc.name}, po_no: {doc.po_no}, Customer: {doc.customer}")
                    docIKASSettings.last_order_no = str(order_id)
                    docIKASSettings.save(ignore_permissions=True)

            except Exception:
                frappe.log_error(f"IKAS Settings last_order_no güncelleme hatası ({order_id})", frappe.get_traceback())
        except Exception as e:
            dctResult['op_result'] = False
            dctResult['op_message'] = f"Sales Order kaydetme hatası: {str(e)}"
            frappe.log_error("SO Debug",f"SO Name: {doc.name}, po_no: {doc.po_no}, Customer: {doc.customer} - exception below")
            frappe.log_error(f"Sales Order kaydetme hatası - Order: {order_id}", frappe.get_traceback())


        # Safety: op_message must never be empty when op_result is False
        if not dctResult.get('op_result') and not dctResult.get('op_message'):
            dctResult['op_message'] = "Sipariş işlenemedi ancak detaylı hata mesajı alınamadı."

        return dctResult

    except Exception as e:
        frappe.log_error("Genel process_ikas_order hatası", frappe.get_traceback())
        dctResult['op_message'] = "Sipariş işleme sırasında bir hata oluştu, destek ile iletişime geçin."
    finally:
        # Tüm durumları logla
        log_title = f"GENEL LOG - Order: {order_id}"
        log_message = dctResult['op_message']
        if 'traceback' in dctResult:
            log_message += "\n" + dctResult['traceback'] 
        frappe.log_error(log_title, log_message)
        try:
            if doc:
                frappe.log_error("SO Debug", f"SO Name: {doc.name}, po_no: {doc.po_no}, Customer: {doc.customer}")
        except Exception:
            pass

    return dctResult


def create_address(order, customer_name, first_name, last_name, address_type="Shipping"):
    """Create Address with multi-field dedup and self-describing title."""

    dct_customer = order.get('customer', {})
    str_email = dct_customer.get('email', '').strip()
    str_phone = dct_customer.get('phone', '').strip()

    if address_type == "Billing":
        dct_addr = order.get('billingAddress', {})
    else:
        dct_addr = order.get('shippingAddress', {})

    str_address_line1 = dct_addr.get('addressLine1', '')
    str_city = dct_addr.get('city', {}).get('name', 'Bilinmiyor')
    str_country = dct_addr.get('country', {}).get('name', '')
    if str_country == "Türkiye":
        str_country = "Turkey"
    str_postal_code = dct_addr.get('postalCode', '')

    str_existing = _find_linked_address(
        {
            "email_id": str_email,
            "phone": str_phone,
            "city": str_city,
            "address_line1": str_address_line1
        },
        "Customer",
        customer_name
    )
    if str_existing:
        return str_existing

    docAddress = frappe.new_doc("Address")
    docAddress.email_id = str_email
    docAddress.phone = str_phone
    docAddress.address_title = f"{first_name} {last_name} — {address_type} — {str_city} ({str_phone})"
    docAddress.address_type = address_type
    docAddress.address_line1 = str_address_line1
    docAddress.state = dct_addr.get('district', {}).get('name', '')
    docAddress.city = str_city
    docAddress.country = str_country

    docAddress.append("links", {"link_doctype": "Customer", "link_name": customer_name})
    docAddress.save(ignore_permissions=True)
    return docAddress.name





@frappe.whitelist()
def get_ikas_auth_token_py():
	"""
	IKAS Access Token alır, IKAS Settings içindeki token alanını günceller.
	JS fonksiyonu get_ikas_auth_token()'ın Python eşdeğeridir.
	"""
	dctResult = {
		"op_result": False,
		"op_message": "",
		"auth_token": None
	}

	try:
		frappe.cache().delete_value("ikas_access_token")
		str_token = get_valid_token()

		if not str_token:
			dctResult["op_message"] = "Token alınamadı. Ayarları kontrol edin."
			return dctResult

		dctResult["op_result"] = True
		dctResult["op_message"] = "Access Token alındı ve IKAS Settings kaydedildi."
		dctResult["auth_token"] = str_token
	except Exception as e:
		frappe.log_error(title="IKAS Token Error", message=frappe.get_traceback())
		dctResult["op_message"] = f"Token alınırken hata oluştu: {str(e)}"

	return dctResult


# DEPRECATED: Replaced by fetch_ikas_orders() + process_staged_orders()
# def check_untransferred_orders():
#     import requests
#     from datetime import datetime
#
#     try:
#         settings = frappe.get_single("IKAS Settings")
#         token = settings.token
#         ikas_tag_id = settings.ikas_tag_id
#         automatic_transfer_start_date = settings.automatic_transfer_start_date
#
#         try:
#             start_date = datetime.strptime(str(automatic_transfer_start_date), "%Y-%m-%d")
#         except Exception as e:
#             frappe.log_error(f"automatic_transfer_start_date parse hatası: {e}", "IKAS Order İşleme1")
#             return []
#
#         api_url = "https://api.myikas.com/api/v1/admin/graphql"
#         headers = {
#             'Content-Type': 'application/json',
#             'Authorization': f"Bearer {token}"
#         }
#
#         query = f"""
#             query GetOrdersByTagId {{
#                 listOrder(orderTagIds: {{ in: ["{ikas_tag_id}"] }}) {{
#                     data {{
#                         id
#                         orderNumber
#                         orderedAt
#                     }}
#                 }}
#             }}
#         """
#
#         try:
#             response = requests.post(api_url, json={"query": query}, headers=headers, timeout=30)
#             response.raise_for_status()
#             result = response.json()
#         except Exception as e:
#             frappe.log_error(f"IKAS API request hatası: {e}", "IKAS Order İşlem2")
#             return []
#
#         if "errors" in result:
#             frappe.log_error(f"IKAS GraphQL hatası: {result['errors']}", "IKAS Order İşleme3")
#             return []
#
#         try:
#             orders = result["data"]["listOrder"]["data"]
#         except Exception as e:
#             frappe.log_error(f"GraphQL response veri hatası: {e} - Response: {result}", "IKAS Order İşleme4")
#             return []
#
#         valid_orders = []
#
#         for order in orders:
#             try:
#                 created_raw = order.get("orderedAt")
#
#                 # createdAt -> datetime
#                 if isinstance(created_raw, int):
#                     created_at = datetime.fromtimestamp(created_raw / 1000)
#                 elif isinstance(created_raw, str):
#                     created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
#                 else:
#                     raise ValueError(f"Unknown orderedAt format: {created_raw}")
#
#                 if created_at > start_date:
#                     # datetime → milisaniye timestamp
#                     ordered_at_ms = int(created_at.timestamp() * 1000)
#
#                     valid_orders.append({
#                         "orderNumber": order["orderNumber"],
#                         "orderedAt": ordered_at_ms
#                     })
#
#             except Exception as e:
#                 frappe.log_error(f"Order işleme hatası: {e} - Order: {order}", "IKAS Order İşleme5")
#
#         return valid_orders
#
#     except Exception as e:
#         frappe.log_error(f"check_untransferred_orders hatası: {e}", "IKAS Order İşleme6")
#         return []


# DEPRECATED: Replaced by fetch_ikas_orders() + process_staged_orders()
# def process_new_orders():
#     try:
#         settings = frappe.get_single("IKAS Settings")
#         if getattr(settings, "order_auto_confirm", 0):
#             try:
#                 new_orders = check_untransferred_orders()
#                 """
#                 new_orders = [
#                     {
#                         "orderNumber": "2257",
#                         "orderedAt": 1760945411189
#                     },
#                 ]
#                 """
#
#
#                 frappe.log_error(
#                 message=json.dumps(new_orders, ensure_ascii=False),
#                 title="IKAS Yeni Siparişler"
#                 )
#                 if not new_orders:
#                     frappe.log_error("Yeni sipariş bulunamadı.", "IKAS Order İşleme")
#                     return
#
#             except Exception as e:
#                 frappe.log_error(frappe.get_traceback(), "check_untransferred_orders hatası")
#                 return
#
#             # -------------------------------
#             # 2️⃣ Her siparişi işle
#             # -------------------------------
#             for order in new_orders:
#                 try:
#                     order_id = order["orderNumber"]
#
#                     # Manual test için sahte Sales Order doc oluştur
#                     doc = frappe.new_doc("Sales Order")
#                     doc.customer = settings.customer_name
#                     doc.po_no = order["orderNumber"]
#                     doc.transaction_date = datetime.fromtimestamp(order["orderedAt"] / 1000).strftime('%Y-%m-%d %H:%M:%S')
#                     doc.delivery_date = doc.transaction_date
#
#                     # doc'u JSON olarak serialize et
#                     doc_json = frappe.as_json(doc)
#
#                     # Siparişi işleyen fonksiyon
#                     result = process_ikas_order(order_id, doc_json)
#
#                     if result.get("op_result"):
#                         settings = frappe.get_single("IKAS Settings")
#                         settings.last_order_no = int(order["orderNumber"])
#                         settings.save(ignore_permissions=True)
#
#                 except Exception as e:
#                     frappe.log_error(frappe.get_traceback(), f"process_new_orders hata - Order: {order.get('orderNumber')}")
#
#             frappe.log_error("Aktarım döngüsü tamamlandı.", "IKAS Order İşleme")
#         else:
#                 frappe.log_error("order_auto_confirm işaretli değil, scheduler atlandı.", "IKAS Scheduler")
#     except Exception as e:
#         frappe.log_error(f"scheduled_process_new_orders hatası: {str(e)}", "IKAS Scheduler")
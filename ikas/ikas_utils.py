# -*- coding: utf-8 -*-
# LOGEDOSOFT

import frappe, json
from frappe import msgprint, _

from frappe.model.document import Document
from frappe.utils import cint, flt




def get_ikas_order_info(order_id):
	import requests
	#Get Order info from https://api.myikas.com/api/v1/admin/graphql API

	dctResult = {
		'op_result': False,
		'op_message': '',
		'order_info': ''
	}

	token = frappe.db.get_single_value('IKAS Settings', 'token')

	#print(token)

	if token:
		api_url = "https://api.myikas.com/api/v1/admin/graphql"
		headers = {
			'Content-Type': 'application/json',
			'Authorization': "Bearer " + token
		}

		query = {
		    "query": f'{{ listOrder(orderNumber: {{eq: "{order_id}"}}) {{ data {{ billingAddress {{ addressLine1 addressLine2 city {{ code id name }} company country {{ code id iso2 iso3 name }} district {{ code id name }} firstName id identityNumber isDefault lastName phone postalCode state {{ code id name }} taxNumber taxOffice }} branch {{ id name }} branchSessionId cancelReason cancelledAt clientIp createdAt currencyCode currencyRates {{ code originalRate rate }} customer {{ email firstName id isGuestCheckout lastName phone }} deleted giftPackageLines {{ price taxValue }} giftPackageNote host id invoices {{ appId appName createdAt id invoiceNumber storeAppId type }} isGiftPackage merchantId note orderAdjustments {{ amount amountType appliedOrderLines {{ amount appliedQuantity orderLineId }} campaignId couponId name order type }} orderLineItems {{ createdAt currencyCode deleted discount {{ amount amountType reason }} discountPrice finalPrice id options {{ name productOptionId productOptionsSetId type values {{ name price value }} }} originalOrderLineItemId price quantity status statusUpdatedAt stockLocationId taxValue updatedAt variant {{ barcodeList brand {{ id name }} categories {{ categoryPath {{ id name }} id name }} id mainImageId name prices {{ buyPrice currency discountPrice priceListId sellPrice }} productId sku slug tagIds taxValue type variantValues {{ order variantTypeId variantTypeName variantValueId variantValueName }} }} }} orderNumber orderPackageSequence orderPackageStatus orderPackages {{ createdAt deleted errorMessage id note orderLineItemIds orderPackageFulfillStatus orderPackageNumber stockLocationId trackingInfo {{ barcode cargoCompany isSendNotification trackingLink trackingNumber }} updatedAt }} orderPaymentStatus orderSequence orderTagIds orderedAt paymentMethods {{ price type }} priceList {{ id name }} salesChannel {{ id name type }} shippingAddress {{ addressLine1 addressLine2 city {{ code id name }} company country {{ code id iso2 iso3 name }} district {{ code id name }} firstName id identityNumber isDefault lastName phone postalCode state {{ code id name }} taxNumber taxOffice }} shippingLines {{ isRefunded price shippingSettingsId shippingZoneRateId taxValue title }} shippingMethod staff {{ email firstName lastName }} status storefront {{ id name }} storefrontRouting {{ domain id locale path priceListId }} storefrontTheme {{ id name themeId themeVersionId }} taxLines {{ price rate }} terminalId totalFinalPrice totalPrice updatedAt userAgent }} }} }}'
		}

		response = requests.post(api_url, json=query, headers=headers)

		

		if response.status_code != 200:
			dctResult = {'op_result': False, 'op_message': f"Get Order API failed with status {response.status_code}. Reason: {response.text}"}
		else:
			dctResult = {'op_result': True, 'order_info': response.json()}

		#print(dctResult)

	return dctResult

@frappe.whitelist()
def process_ikas_order(order_id):
	#Get token, call get_ikas_order_info with token. Process Order info.

	dctResult = {
		'op_result': False,
		'op_message': '',
		'order_info': ''
	}

	dctOrderInfo = get_ikas_order_info(order_id)

	if dctOrderInfo['op_result'] == False:
		dctResult['op_result'] = False
		dctResult['op_message'] = dctOrderInfo['op_message']
	else:
		#We Get the order info
		dctResult['op_result'] = True
		
		order = dctOrderInfo['order_info']['data']['listOrder']['data'][0]
		customer = order.get('customer', {})

		first_name = customer.get('firstName', '')
		last_name = customer.get('lastName', '')

		#Create new customer with first and last name
		#docCustomer = frappe.new_doc('Customer')
		#docCustomer.customer_name = f"{first_name} {last_name}"
		#docCustomer.payment_terms = "%50 CASH %50 60 DAYS"
		#docCustomer.customer_type = "Company"
		#docCustomer.customer_group = "Individual"
		#docCustomer.custom_ld_country = "United States"
		#docCustomer.save()
		Defaut_Custumer = frappe.db.get_single_value('IKAS Settings', 'custumer_name')
		print(Defaut_Custumer)
		#Creat address first
		docAddress = frappe.new_doc('Address')
		docAddress.address_title = f"{first_name} {last_name}"
		docAddress.address_type = "Shipping"
		docAddress.address_line1 = "ASD"
		docAddress.address_line2 = "TEST"
		docAddress.city = order.get('shippingAddress', {}).get('city', {}).get('name', '')
		docAddress.country = "Turkey"
		docAddress.append("links", {
			"link_doctype": "Customer", 
			"link_name": Defaut_Custumer})
		docAddress.save()

		print(f"FN = {first_name}, LN = {last_name}")

	return dctResult

@frappe.whitelist()
def process_ikas_auth(store_name=None, client_id=None, client_secret=None):
	import requests

	dctResult = {
		'op_result': False,
		'op_message': '',
		'auth_token': ''
	}

	try:
		# API URL'ini dinamik olarak store_name'den oluştur (örn. kayaoglulokum.myikas.com)
		api_url = f"{store_name}"

		headers = {'Content-Type': 'application/x-www-form-urlencoded'}
		payload = {
			"grant_type": "client_credentials",
			"client_id": client_id,
			"client_secret": client_secret
		}

		response = requests.post(api_url, data=payload, headers=headers)

		if response.status_code != 200:
			dctResult = {
				'op_result': False,
				'op_message': f"API bağlantısı başarısız! Kod: {response.status_code}\n{response.text}"
			}
		else:
			api_data = response.json()
			dctResult = {
				'op_result': True,
				'op_message': "IKAS bağlantısı başarılı ✅",
				'auth_token': api_data.get('access_token')
			}

	except Exception as e:
		dctResult = {
			'op_result': False,
			'op_message': f"Hata oluştu: {str(e)}"
		}

	return dctResult

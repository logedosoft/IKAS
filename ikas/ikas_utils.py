# -*- coding: utf-8 -*-
# LOGEDOSOFT

import frappe, json
from frappe import msgprint, _

from frappe.model.document import Document
from frappe.utils import cint, flt

def get_ikas_auth_token():
	import requests
	#Get Auth Token from https://api.myikas.com/api/v1/admin/graphql API

	dctResult = {
		'op_result': False,
		'op_message': '',
		'auth_token': ''
	}

	api_url = "https://kayaoglulokum.myikas.com/api/admin/oauth/token"
	headers = {
		'Content-Type': 'application/x-www-form-urlencoded'
	}

	payload = {
		"grant_type": "client_credentials",
		"client_id": "0e80d184-d742-49d7-94b3-8585d31ae13a",
		"client_secret": "s_1QoGh4p6O218QxZF1Q5my0jU4780825100754bf2baee5bd8a96ef41a"
	}

	response = requests.post(api_url, data=payload, headers=headers)

	if response.status_code != 200:
		dctResult = {'op_result': False, 'op_message': f"API failed with status {response.status_code}. Reason: {response.text}"}
	else:
		api_data = response.json()
		dctResult = {'op_result': True, 'auth_token': api_data.get('access_token')}

	return dctResult

def get_ikas_order_info(order_id):
	import requests
	#Get Order info from https://api.myikas.com/api/v1/admin/graphql API

	dctResult = {
		'op_result': False,
		'op_message': '',
		'order_info': ''
	}

	token = get_ikas_auth_token()

	if token['op_result'] == False:
		dctResult['op_result'] = False
		dctResult['op_message'] = token['op_message']
	else:
		api_url = "https://api.myikas.com/api/v1/admin/graphql"
		headers = {
			'Content-Type': 'application/json',
			'Authorization': "Bearer " + token['auth_token']
		}

		query = {
		    "query": f'{{ listOrder(orderNumber: {{eq: "{order_id}"}}) {{ data {{ billingAddress {{ addressLine1 addressLine2 city {{ code id name }} company country {{ code id iso2 iso3 name }} district {{ code id name }} firstName id identityNumber isDefault lastName phone postalCode state {{ code id name }} taxNumber taxOffice }} branch {{ id name }} branchSessionId cancelReason cancelledAt clientIp createdAt currencyCode currencyRates {{ code originalRate rate }} customer {{ email firstName id isGuestCheckout lastName phone }} deleted giftPackageLines {{ price taxValue }} giftPackageNote host id invoices {{ appId appName createdAt id invoiceNumber storeAppId type }} isGiftPackage merchantId note orderAdjustments {{ amount amountType appliedOrderLines {{ amount appliedQuantity orderLineId }} campaignId couponId name order type }} orderLineItems {{ createdAt currencyCode deleted discount {{ amount amountType reason }} discountPrice finalPrice id options {{ name productOptionId productOptionsSetId type values {{ name price value }} }} originalOrderLineItemId price quantity status statusUpdatedAt stockLocationId taxValue updatedAt variant {{ barcodeList brand {{ id name }} categories {{ categoryPath {{ id name }} id name }} id mainImageId name prices {{ buyPrice currency discountPrice priceListId sellPrice }} productId sku slug tagIds taxValue type variantValues {{ order variantTypeId variantTypeName variantValueId variantValueName }} }} }} orderNumber orderPackageSequence orderPackageStatus orderPackages {{ createdAt deleted errorMessage id note orderLineItemIds orderPackageFulfillStatus orderPackageNumber stockLocationId trackingInfo {{ barcode cargoCompany isSendNotification trackingLink trackingNumber }} updatedAt }} orderPaymentStatus orderSequence orderTagIds orderedAt paymentMethods {{ price type }} priceList {{ id name }} salesChannel {{ id name type }} shippingAddress {{ addressLine1 addressLine2 city {{ code id name }} company country {{ code id iso2 iso3 name }} district {{ code id name }} firstName id identityNumber isDefault lastName phone postalCode state {{ code id name }} taxNumber taxOffice }} shippingLines {{ isRefunded price shippingSettingsId shippingZoneRateId taxValue title }} shippingMethod staff {{ email firstName lastName }} status storefront {{ id name }} storefrontRouting {{ domain id locale path priceListId }} storefrontTheme {{ id name themeId themeVersionId }} taxLines {{ price rate }} terminalId totalFinalPrice totalPrice updatedAt userAgent }} }} }}'
		}

		response = requests.post(api_url, json=query, headers=headers)

		frappe.log_error("IKAS 4", response.text)
		frappe.log_error("IKAS 5", response.content)
		frappe.log_error("IKAS 6", frappe.as_json(response.json()))

		if response.status_code != 200:
			dctResult = {'op_result': False, 'op_message': f"Get Order API failed with status {response.status_code}. Reason: {response.text}"}
		else:
			dctResult = {'op_result': True, 'order_info': response.json()}

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
		dctResult['op_result'] = True
		dctResult['order_info'] = dctOrderInfo['order_info']

	return dctResult
# -*- coding: utf-8 -*-
# LOGEDOSOFT

import frappe, json
from frappe import msgprint, _

from frappe.model.document import Document
from frappe.utils import cint, flt
from frappe.utils import now_datetime


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
	
    response = requests.post(api_url, data=payload, headers=headers)
    if response.status_code != 200:
        return {"op_result": False, "op_message": f"Token API failed: {response.text}"}
    data = response.json()

	
    return {"op_result": True, "auth_token": data.get("access_token")}
	


def get_ikas_order_info(order_id):
    import requests
    token = frappe.db.get_single_value('IKAS Settings', 'token')

    api_url = "https://api.myikas.com/api/v1/admin/graphql"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': "Bearer " + token
    }
    print(token)
    print(order_id)
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
    print("*******************DENEME***************************")
    response = requests.post(api_url, json={"query": query}, headers=headers,timeout=3)
    print(response.status_code)
    print(response.text)

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

    print(dctResult)
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
		
		
		Defaut_Customer = frappe.db.get_single_value('IKAS Settings', 'custumer_name')
		if	Defaut_Customer:
			print(Defaut_Customer + "******************DENEME*********************")
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
				"link_name": Defaut_Customer})
			docAddress.save()
		else:
			#Create new customer with first and last name
			docCustomer = frappe.new_doc('Customer')
			print( "***************************************")
			docCustomer.customer_name = f"{first_name} {last_name}"
			#docCustomer.payment_terms = "%50 CASH %50 60 DAYS"
			docCustomer.customer_type = "Company"
			docCustomer.customer_group = "Individual"
			docCustomer.custom_ld_country = "United States"
			docCustomer.save()
			docAddress = frappe.new_doc('Address')
			docAddress.address_title = f"{first_name} {last_name}"
			docAddress.address_type = "Shipping"
			docAddress.address_line1 = "ASD"
			docAddress.address_line2 = "TEST"
			docAddress.city = order.get('shippingAddress', {}).get('city', {}).get('name', '')
			docAddress.country = "Turkey"
			docAddress.append("links", {
				"link_doctype": "Customer", 
				"link_name": docCustomer.name})
			docAddress.save()
			


		print(f"FN = {first_name}, LN = {last_name}")

	return dctResult

@frappe.whitelist()
def get_ikas_auth_token_py():
    """
    IKAS Access Token alır, IKAS Settings içindeki token alanını günceller.
    JS fonksiyonu get_ikas_auth_token()'ın Python eşdeğeridir.
    """

    try:
        # IKAS Settings belgesini al
        ikas_settings = frappe.get_single("IKAS Settings")

        # Gerekli parametreleri çek
        store_name = ikas_settings.store_name
        client_id = ikas_settings.client_id
        client_secret = ikas_settings.client_secret
		
		

        
        # process_ikas_auth fonksiyonunu doğrudan çağır
        result = process_ikas_auth(store_name, client_id, client_secret)
		
        # Sonucu kontrol et
        if not result.get("op_result"):
            frappe.throw(result.get("op_message", _("Sunucudan geçerli bir yanıt alınamadı!")))
			
        # Token ve tarih bilgilerini kaydet
        ikas_settings.token = result.get("auth_token")
        ikas_settings.token_valid_upto = now_datetime()
        ikas_settings.save()

        frappe.msgprint("Access Token alındı ve IKAS Settings kaydedildi. ✅")


        return {"op_result": True, "message": _("Token başarıyla alındı.")}

    except Exception as e:
        frappe.log_error(title="IKAS Token Error", message=str(e))
        frappe.throw(_("Token alınırken hata oluştu: {0}").format(str(e)))

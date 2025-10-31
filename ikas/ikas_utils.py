# -*- coding: utf-8 -*-
# LOGEDOSOFT

import frappe, json
from frappe import msgprint, _
from frappe.model.document import Document
from frappe.utils import cint, flt
from frappe.utils import now_datetime
from datetime import datetime


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
    frappe.log_error("as1",payload)
    response = requests.post(api_url, data=payload, headers=headers ,timeout=1)
    frappe.log_error("as2",response)
    if response.status_code != 200:
        return {"op_result": False, "op_message": f"Token API failed: {response.text}"}
    data = response.json()

	
    return {"op_result": True, "auth_token": data.get("access_token")}
	


def get_ikas_order_info(order_id):
    import requests
    from datetime import datetime, timedelta
    settings = frappe.get_single("IKAS Settings")
    token = settings.token
    token_valid_upto = settings.token_valid_upto
    store_name = settings.store_name
    client_id = settings.client_id
    client_secret = settings.client_secret

    now = datetime.now()
    needs_refresh = False
    
    # Token süresi kontrolü
    if not token_valid_upto or str(token_valid_upto) in ["0001-01-01 00:00:00", "0001-01-01"]:
        needs_refresh = True
    else:
        if isinstance(token_valid_upto, str):
            try:
                token_valid_upto = datetime.strptime(token_valid_upto, "%Y-%m-%d %H:%M:%S")
            except Exception:
                token_valid_upto = datetime.now() - timedelta(hours=5)

        if now > token_valid_upto:
            needs_refresh = True

    if needs_refresh:
        result = process_ikas_auth(store_name, client_id, client_secret)
        frappe.log_error("t3",result)
        if result.get("op_result"):
            new_token = result.get("auth_token")

            # Yeni token ve 4 saat sonraki bitiş zamanını kaydet
            settings.token = new_token
            settings.token_valid_upto = now + timedelta(hours=4)
            settings.save(ignore_permissions=True)


            token = new_token
        else:
            frappe.log_error("İkas token Yenileme Hatası",f"Token yenileme başarısız: {result.get('op_message')}")

    api_url = "https://api.myikas.com/api/v1/admin/graphql"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': "Bearer " + token
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


@frappe.whitelist()
def process_ikas_order(order_id, doc):
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
        doc = frappe.get_doc(json.loads(doc))
        ikas_settings = frappe.get_single("IKAS Settings")

        customer_name_setting = ikas_settings.customer_name
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
            dctResult['op_message'] = f"Bu sipariş zaten aktarılmış: {existing_sos[0].name}"
            return dctResult

        # Müşteri ve adres işlemleri
        try:
            customer_data = order.get('customer', {})
            first_name = customer_data.get('firstName', '')
            last_name = customer_data.get('lastName', '')
            email_id = customer_data.get('email', '').strip()

            address_list = frappe.get_all("Address", filters={"email_id": email_id}, fields=["name"])
            existing_address_name = address_list[0].name if address_list else None

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
                else:
                    create_address(order, customer_name_setting, first_name, last_name)
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
                    else:
                        docCustomer = frappe.new_doc('Customer')
                        docCustomer.customer_name = f"{first_name} {last_name.strip()}"
                        docCustomer.customer_type = "Company"
                        docCustomer.customer_group = "Individual"
                        docCustomer.save()
                        create_address(order, docCustomer.name, first_name, last_name)
                        customer_for_order = docCustomer.name
                else:
                    docCustomer = frappe.new_doc('Customer')
                    docCustomer.customer_name = f"{first_name} {last_name.strip()}"
                    docCustomer.customer_type = "Company"
                    docCustomer.customer_group = "Individual"
                    docCustomer.save()
                    create_address(order, docCustomer.name, first_name, last_name)
                    customer_for_order = docCustomer.name

        except Exception as e:
            frappe.log_error(e, "Müşteri/Adres oluşturma hatası")
            dctResult['op_message'] = "Müşteri veya adres oluşturulamadı, destek ile iletişime geçin."
            return dctResult

        # Doc alanları setleme
        try:
            doc.customer = customer_for_order
            doc.customer_name = customer_for_order
            doc.customer_address = f"{first_name} {last_name.strip()}-Shipping"
            doc.po_no = order_id

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
            frappe.log_error(e, "Doc alanları setleme hatası")
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
                variant_uom = variant_values[0].get('variantTypeName', '') if variant_values else ''
                itemname = variant.get('name', 'Item')
                if variant_value_names:
                    itemname += ' ' + variant_value_names
                qty = line.get('quantity', 0)
                rate = line.get('finalPrice', 0)
                amount = qty * rate
                doc.append('items', {
                    'item_code': itemname,
                    'item_name': itemname,
                    'qty': qty,
                    'rate': rate,
                    'amount': amount,
                    'delivery_date': date,
                    'uom': variant_uom
                })
                total_qty += qty
                total_amount += amount

            # Kargo ekle
            for ship in order.get('shippingLines', []):
                title = ship.get('title')
                price = ship.get('price', 0)
                if title:
                    doc.append('items', {
                        'item_code': 'KARGO',
                        'item_name': title,
                        'qty': 1,
                        'rate': price,
                        'amount': price,
                        'delivery_date': date,
                        'uom': 'Adet'
                    })
                    total_qty += 1
                    total_amount += price

            doc.total_qty = total_qty
            doc.total = total_amount
            doc.grand_total = total_amount

            totalFinalPrice = order.get('totalFinalPrice', 0)
            total_amountkontrol = sum(float(item.get('amount') or 0) for item in doc.get('items', []))
            if float(totalFinalPrice) != total_amountkontrol:
                dctResult['op_message'] = "ERP ve IKAS sipariş tutarı tutarsız, kontrol ediniz."
                return dctResult

        except Exception as e:
            frappe.log_error(e, "İtem veya toplam hesaplama hatası")
            dctResult['op_message'] = "Sipariş kalemleri işlenemedi, destek ile iletişime geçin."
            return dctResult

        dctResult['op_result'] = True
        dctResult['doc'] = doc
        return dctResult

    except Exception as e:
        frappe.log_error(e, "Genel process_ikas_order hatası")
        dctResult['op_message'] = "Sipariş işleme sırasında bir hata oluştu, destek ile iletişime geçin."
        return dctResult


def create_address(order, customer_name, first_name, last_name,):
    """Shipping Address oluşturur ve Customer ile ilişkilendirir"""
    
    docAddress = frappe.new_doc('Address')
    docAddress.email_id = order.get('customer', {}).get('email', '')
    docAddress.address_title = f"{first_name} {last_name}"
    docAddress.address_type = "Shipping"
    docAddress.address_line1 = order.get('shippingAddress', {}).get('addressLine1', '')
    docAddress.state = order.get('shippingAddress', {}).get('district', {}).get('name', '')
    docAddress.city = order.get('shippingAddress', {}).get('city', {}).get('name', '')
    country = order.get('shippingAddress', {}).get('country', {}).get('name', '')
    if country == "Türkiye":
        country = "Turkey"
    docAddress.country = country
    
    docAddress.phone = order.get('customer', {}).get('phone', '')

    docAddress.append("links", {
        "link_doctype": "Customer",
        "link_name": customer_name
    })
    docAddress.save()





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
            dctResult["op_message"] = result.get("op_message", "Sunucudan geçerli bir yanıt alınamadı!")
            return dctResult

        # Token ve tarih bilgilerini kaydet
        ikas_settings.token = result.get("auth_token")
        ikas_settings.token_valid_upto = now_datetime()
        ikas_settings.save()

        dctResult["op_result"] = True
        dctResult["op_message"] = "Access Token alındı ve IKAS Settings kaydedildi. ✅"
        dctResult["auth_token"] = result.get("auth_token")
        return dctResult

    except Exception as e:
        frappe.log_error(title="IKAS Token Error", message=str(e))
        dctResult["op_message"] = f"Token alınırken hata oluştu: {str(e)}"
        return dctResult

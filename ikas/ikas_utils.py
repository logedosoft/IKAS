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
	
    response = requests.post(api_url, data=payload, headers=headers)
    if response.status_code != 200:
        return {"op_result": False, "op_message": f"Token API failed: {response.text}"}
    data = response.json()

	
    return {"op_result": True, "auth_token": data.get("access_token")}
	


def get_ikas_order_info(order_id):
    import requests
    from datetime import datetime, timedelta
    token = frappe.db.get_single_value('IKAS Settings', 'token')
    token_valid_upto = frappe.db.get_single_value('IKAS Settings', 'token_valid_upto')

    store_name = frappe.db.get_single_value('IKAS Settings', 'store_name')
    client_id = frappe.db.get_single_value('IKAS Settings', 'client_id')
    client_secret = frappe.db.get_single_value('IKAS Settings', 'client_secret')

    now = datetime.now()
    needs_refresh = False

    # Token süresi kontrolü
    if not token_valid_upto:
        needs_refresh = True
    else:
        if isinstance(token_valid_upto, str):
            try:
                token_valid_upto = datetime.strptime(token_valid_upto, "%Y-%m-%d %H:%M:%S")
            except Exception:
                token_valid_upto = now - timedelta(hours=5)
        if now > token_valid_upto:
            needs_refresh = True

    if needs_refresh:
        frappe.logger().info("🔄 IKAS token süresi geçmiş veya bulunamadı, yenileniyor...")
        result = process_ikas_auth(store_name, client_id, client_secret)

        if result.get("op_result"):
            new_token = result.get("auth_token")

            # Yeni token ve 4 saat sonraki bitiş zamanını kaydet
            frappe.db.set_value('IKAS Settings', None, 'token', new_token)
            frappe.db.set_value('IKAS Settings', None, 'token_valid_upto', now + timedelta(hours=4))
            frappe.db.commit()
            frappe.clear_cache(doctype="IKAS Settings")

            token = new_token
        else:
            frappe.throw(f"Token yenileme başarısız: {result.get('op_message')}")


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
def process_ikas_order(order_id,doc):
    """
    IKAS sipariş bilgilerini alır, gerekli müşteri ve adres dokümanlarını oluşturur
    ve Sales Order formu için kullanılacak bilgileri JSON olarak döner.
    """
    dctResult = {
        'op_result': False,
        'op_message': '',
        'order_info': '',
        'order': {}
    }
    doc = frappe.get_doc(json.loads(doc))

    # IKAS API'den sipariş bilgisini al
    dctOrderInfo = get_ikas_order_info(order_id)

    if not dctOrderInfo['op_result']:
        dctResult['op_result'] = False
        dctResult['op_message'] = dctOrderInfo['op_message']
        return dctResult

    dctResult['op_result'] = True
    order_list = dctOrderInfo.get('order_info', {}).get('data', {}).get('listOrder', {}).get('data', [])
    if not order_list:
        frappe.throw("Sipariş numarası bulunamadı.")
    else:
        order = order_list[0]


    # Daha önce aktarılmış mı kontrol et
    existing_so = frappe.db.exists("Sales Order", {"po_no": order_id})

    if existing_so:
        frappe.throw(f"Bu sipariş ({order_id}) daha önce aktarılmış.")


    customer_data = order.get('customer', {})
    first_name = customer_data.get('firstName', '')
    last_name = customer_data.get('lastName', '')

    default_customer_name = frappe.db.get_single_value('IKAS Settings', 'custumer_name')

    # Adres zaten var mı kontrol et
    existing_address = frappe.db.exists("Address", {"address_title": f"{first_name} {last_name.strip()}"})
    # Müşteri ve adres oluşturma
    if default_customer_name:
         if not existing_address:
        # Default müşteri varsa sadece adres oluştur
            create_address(order, default_customer_name, first_name, last_name)
            customer_for_order = default_customer_name
     # Yeni müşteri oluşturulmadan önce adres var mı kontrol et
    if existing_address:
        # Adres varsa, bağlı müşteri adını al
        existing_customer = frappe.db.get_value("Dynamic Link",
            {"parent": existing_address, "link_doctype": "Customer"}, "link_name"
        )

        if existing_customer:
            customer_for_order = existing_customer
        else:
            # Adres var ama müşterisi yoksa yeni müşteri oluştur
            docCustomer = frappe.new_doc('Customer')
            docCustomer.customer_name = f"{first_name} {last_name.strip()}"
            docCustomer.customer_type = "Company"
            docCustomer.customer_group = "Individual"
            docCustomer.save()

            create_address(order, docCustomer.name, first_name, last_name)
            customer_for_order = docCustomer.name
    else:
        # Adres yoksa tamamen yeni müşteri oluştur
        docCustomer = frappe.new_doc('Customer')
        docCustomer.customer_name = f"{first_name} {last_name.strip()}"
        docCustomer.customer_type = "Company"
        docCustomer.customer_group = "Individual"
        docCustomer.save()


    doc.customer = customer_for_order
    doc.customer_name = customer_for_order
    doc.customer_address = f"{first_name} {last_name.strip()}-Shipping"
    doc.po_no=order_id


    ordered_at = order.get('orderedAt', '')
    date = ''
    if ordered_at:
        # Eğer değer milisaniye cinsindense (örn: 1761204968235)
        try:
            date = datetime.fromtimestamp(ordered_at / 1000).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            date = str(ordered_at)  # Eğer zaten tarih string'iyse, direkt al
    doc.transaction_date=date
    doc.delivery_date=date
    doc.po_date=date

    # Eski satırları temizle
    if len(doc.get("items", [])) > 0:
        doc.items = []

    total_qty = 0
    total_amount = 0

    for line in order.get('orderLineItems', []):
        variant = line.get('variant', {})

        # variantValues listesi alınıyor
        variant_values = variant.get('variantValues', [])
        # Listeyi dolaşarak variantValueName'leri birleştiriyoruz
        variant_value_names = ', '.join([v.get('variantValueName', '') for v in variant_values])
        variant_uom = variant_values[0].get('variantTypeName', '') if variant_values else ''

        # itemname = ürün adı + variant değerleri
        itemname = variant.get('name', '')
        if variant_value_names:
            itemname += ' ' + variant_value_names

        qty = line.get('quantity', 0)
        rate = line.get('finalPrice', 0)
        amount = qty * rate

        # doc.items'e ekleme
        doc.append('items', {
            'item_code': itemname,
            'item_name': itemname,
            'qty': qty,
            'rate': rate,
            'amount': amount,
            'delivery_date': date,
            'uom':variant_uom
        })

        # Toplamları biriktir
        total_qty += qty
        total_amount += amount

    shipping_lines = order.get('shippingLines', [])
    if shipping_lines:
        for ship in shipping_lines:
            title = ship.get('title')
            price = ship.get('price', 0)
            if title:  # Boş veya None değilse
                doc.append('items', {
                    'item_code': 'KARGO',
                    'item_name': title,
                    'qty': 1,
                    'rate': price,
                    'amount': price,
                    'delivery_date': date,
                    'uom':'Adet'
                })
                total_qty += 1
                total_amount += price

    # Doc genel alanlarına toplamları yaz
    doc.total_qty = total_qty
    doc.total = total_amount
    doc.grand_total=total_amount
    totalFinalPrice=order.get('totalFinalPrice','')
    total_amountkontrol = sum(float(item.get('amount') or 0) for item in doc.get('items', []))

    if totalFinalPrice != total_amountkontrol:
        frappe.throw("ERP Sipariş tutarı ile IKAS tutarı tutarsız. Kontrol ediniz.")


    dctResult['doc'] = doc


    return dctResult

def create_address(order, customer_name, first_name, last_name):
    """Shipping Address oluşturur ve Customer ile ilişkilendirir"""
    docAddress = frappe.new_doc('Address')
    docAddress.address_title = f"{first_name} {last_name}"
    docAddress.address_type = "Shipping"
    docAddress.address_line1 = order.get('shippingAddress', {}).get('addressLine1', '')
    docAddress.state = order.get('shippingAddress', {}).get('district', {}).get('name', '')
    docAddress.city = order.get('shippingAddress', {}).get('city', {}).get('name', '')
    country = order.get('shippingAddress', {}).get('country', {}).get('name', '')
    if country == "Türkiye":
        country = "Turkey"
    docAddress.country = country
    docAddress.email_id = order.get('customer', {}).get('email', '')
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

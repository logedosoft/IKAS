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

@frappe.whitelist()
def get_ikas_order_info(order_id):
	#Get Order info from https://api.myikas.com/api/v1/admin/graphql API

	dctResult = {
		'op_result': False,
		'op_message': '',
		'order_info': ''
	}

	token = get_ikas_auth_token()

	dctResult['order_info'] = token
	dctResult['op_result'] = True

	return dctResult
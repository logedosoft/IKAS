# IKAS Integration — Setup & Testing Guide

## Architecture Overview

The integration uses a two-stage pipeline:

```
IKAS API ──(every 10 min)──> IKAS Order ──(every 3 min)──> Sales Order
                   │              │
                   v              v
            IKAS Order Payload   (staging docs)
```

1. **Fetcher** (`fetch_ikas_orders`) polls IKAS GraphQL with your tag ID, stores raw orders in staging.
2. **Processor** (`process_staged_orders`) picks up staged orders, calls `process_ikas_order` to create Sales Orders.

---

## Step 1: Prerequisites

Before configuring the app, ensure these exist in your ERPNext site:

| What | How to check | Example |
|------|-------------|---------|
| At least one **Customer** | Desk > Customer list | `IKAS Default Customer` |
| A **Sales Person** | Desk > Sales Person list | `IKAS Sales Person` |
| A **Tax Category** | Desk > Tax Category list | `Standard` |
| A **Payment Terms Template** | Desk > Payment Terms Template list | `Net 30` |
| A **Cargo/shipping Item** | Desk > Item list (type=Service) | `Kargo` (item_code must match) |
| **IKAS Tax** rows | Desk > IKAS Tax list | Rate `20` -> Account `KDV - 191000` |

---

## Step 2: IKAS Settings Configuration

Navigate to **Desk > IKAS Settings** and fill in:

### Integration Information

| Field | Value |
|-------|-------|
| Store Name | `https://auth.myikas.com/oauth/token` (the OAuth endpoint) |
| Client Id | Your IKAS API client ID |
| Client Secret | Your IKAS API client secret |
| Connection Check | Click to verify -- token will appear in Token field |

### Settings

| Field | Value |
|-------|-------|
| Customer Name | Select the default Customer for all IKAS orders |
| Cargo Company | Select the shipping/cargo Item (by item_code) |
| Sales Person | Select the Sales Person |
| Payment Terms Template | Select the payment terms |
| Order Auto Confirm | Checked (enables automatic processing) |
| Automatic Transfer Start Date | Only orders **after** this date will be fetched |
| Ikas Tag Id | The tag ID you use in IKAS to mark orders for ERP transfer |
| Notification Mail | Email for amount-mismatch alerts |

### Tax

| Field | Value |
|-------|-------|
| Tax Category | Select the tax category |
| Taxes (table) | Add rows: Account Name + Rate (e.g., `KDV - 191000` at rate `20`) |

---

## Step 3: Verify the Scheduler is Running

Check via bench console:

```bash
bench --site YOUR_SITE_NAME console
```

```python
from frappe.utils.scheduler import get_scheduler_info
info = get_scheduler_info()
for event in info.get("events", []):
    if "ikas" in str(event):
        print(event)
```

You should see two entries:
- `*/10 * * * *` -> `ikas.ikas_utils.fetch_ikas_orders`
- `*/3 * * * *` -> `ikas.ikas_utils.process_staged_orders`

---

## Step 4: Manual Test -- Run the Fetcher

Instead of waiting for the scheduler, trigger the fetcher manually:

```bash
bench --site YOUR_SITE_NAME execute ikas.ikas_utils.fetch_ikas_orders
```

**Expected results:**
- Returns `0` if no new orders match the tag or all are already fetched.
- Returns a positive integer if new `IKAS Order` docs were created.

**Verify in Desk:**
1. Go to **IKAS Order** list -- you should see new rows with `status = New`.
2. Go to **IKAS Order Payload** list -- each IKAS Order should have a linked payload with `raw_payload` containing JSON.

---

## Step 5: Manual Test -- Run the Processor

After orders are staged:

```bash
bench --site YOUR_SITE_NAME execute ikas.ikas_utils.process_staged_orders
```

**Expected results:**
- `IKAS Order` records transition: `New` -> `Processing` -> `Completed` (or `Failed`).
- On success, the `sales_order` field is populated with the created SO name.

**Verify in Desk:**
1. Open the **IKAS Order** -- check `status = Completed` and `sales_order` links to a valid Sales Order.
2. Open the **Sales Order** -- verify items, taxes, customer, and addresses are populated correctly.

---

## Step 6: Check for Errors

### Error Log (Desk)

Go to **Desk > Error Log** and filter by title prefix:

| Error Title | Meaning | Fix |
|-------------|---------|-----|
| `IKAS Token Refresh Failed` | OAuth token could not be obtained | Check Client ID / Client Secret / Store Name in IKAS Settings |
| `IKAS Fetcher` | `automatic_transfer_start_date` is not set | Fill in the date field in IKAS Settings |
| `IKAS Fetcher API Error` | HTTP error calling IKAS GraphQL | Check network connectivity, IKAS API status |
| `IKAS Fetcher GraphQL Error` | IKAS returned GraphQL errors | Check `ikas_tag_id` -- may be wrong or no orders have this tag |
| `IKAS Fetcher Safety Cap` | Hit 50 pages of pagination | Investigate -- too many orders per fetch window |
| `IKAS Fetcher Order Error` | Failed to create staging doc for a specific order | Check IKAS Order DocType fields, review traceback |
| `IKAS Processor Record Error` | Failed to process a specific staged order | Open the IKAS Order in Desk, check `error_message` field |
| `IKAS-ERP tutar uyumsuzlugu` | IKAS total != ERP total (email also sent) | Review the order manually -- pricing/tax mismatch |

### IKAS Order Error Details

For any `IKAS Order` with `status = Failed`:
1. Open the IKAS Order document in Desk.
2. Check the **Error Message** field -- it contains the last exception text.
3. Check the **Retry Count** field -- processing retries 3 times before marking as `Failed`.

### Terminal: Direct Error Log Query

```bash
bench --site YOUR_SITE_NAME mariadb -e "
SELECT method, LEFT(error, 300) AS error_preview, creation
FROM \`tabError Log\`
WHERE method LIKE 'IKAS%'
ORDER BY creation DESC
LIMIT 20;
"
```

---

## Step 7: Re-Process Failed Orders

If an order failed due to a transient error (e.g., SKU not found, network timeout):

1. Open the **IKAS Order** in Desk.
2. Set `status` back to `New` and `retry_count` to `0`.
3. Clear the `error_message`.
4. The processor will pick it up on the next `*/3 * * * *` cycle, or run manually:

```bash
bench --site YOUR_SITE_NAME execute ikas.ikas_utils.process_staged_orders
```

---

## Step 8: Verify No Duplicates

Re-run the fetcher -- it should NOT create duplicate records:

```bash
bench --site YOUR_SITE_NAME execute ikas.ikas_utils.fetch_ikas_orders
```

Should return `0` if all orders are already staged. The dedup check uses:
`source1 = "IKAS"` + `source2 = <tag_id>` + `order_number = <order_number>`

---

## Quick Reference: Manual Execution Commands

```bash
# Test token connection
bench --site YOUR_SITE_NAME execute ikas.ikas_utils.get_ikas_auth_token_py

# Fetch orders from IKAS into staging
bench --site YOUR_SITE_NAME execute ikas.ikas_utils.fetch_ikas_orders

# Process staged orders into Sales Orders
bench --site YOUR_SITE_NAME execute ikas.ikas_utils.process_staged_orders
```

---

## Troubleshooting Checklist

| Symptom | Check |
|---------|-------|
| Fetcher returns 0 every time | Is `ikas_tag_id` correct? Are there orders in IKAS with that tag after `automatic_transfer_start_date`? |
| Token refresh fails | Verify Store Name is the OAuth URL (`https://auth.myikas.com/oauth/token`), not the storefront URL |
| Orders staged but not processed | Check if `order_auto_confirm` is checked in IKAS Settings |
| Sales Order created but missing items | Check IKAS Tax table -- every IKAS tax rate must have a matching row in IKAS Tax |
| Amount mismatch emails | Compare `totalFinalPrice` in IKAS Order Payload raw_payload with `grand_total` on the Sales Order |
| `IKAS Order` stuck in `Processing` | The processor crashed mid-processing. Set status back to `New` and re-run |
| No IKAS Order docs appearing at all | Run `bench --site YOUR_SITE_NAME execute ikas.ikas_utils.fetch_ikas_orders` and check the return value and Error Log |

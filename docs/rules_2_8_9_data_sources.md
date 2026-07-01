# Data Sources — Rules 2, 8, 9

Tables/columns each rule actually queries (from `app/rules/queries.py`), DB: `b2c-v1`.
All rules join `item_master (id, name, item_no)` for product display.

---

## Rule 2 — Inventory Clearance Candidate  (`rule_clearance`)
**Trigger:** inventory > 100 units **AND** 30-day sales < 5.

| Data | Table | Column(s) | Notes |
|------|-------|-----------|-------|
| Inventory on hand | `stock_inventroy` | `item_id`, `quantity`, `company_id` | `SUM(quantity)` per item → must be > 100 |
| 30-day sales qty | `sales_order_details` | `item_id`, `quantity`, `sales_id`, `company_id` | `SUM(quantity)` in last 30d → must be < 5 |
| Order date filter | `sales_order` | `id`, `created_at` (epoch) | joined `o.id = d.sales_id`; `created_at >= now - 30d` |
| Product info | `item_master` | `id`, `name`, `item_no` | |

**Owner / dependency (Abdul):** confirm **`stock_inventroy`** is populated (table exists but is often empty → rule returns 0). If inventory comes from an API instead, that source must feed `stock_inventroy`. Note the table name is spelled `stock_inventroy`.

---

## Rule 8 — Profit Protection Product  (`rule_profit`)
**Trigger:** gross margin = (price − cost) / price > 50%, over last 90 days, cost > 0.

| Data | Table | Column(s) | Notes |
|------|-------|-----------|-------|
| Selling price | `sales_order_details` | `price`, `item_id`, `quantity`, `sales_id`, `company_id` | margin numerator/denominator |
| **Cost (PRIMARY)** | `stock_inventroy` | `cost`, `item_id`, `company_id` | `AVG(cost)` where `cost > 0` — authoritative unit cost (`单价成本`) held in inventory; used first |
| Cost (fallback 1) | `sales_order_details` | `cost` | used when `stock_inventroy.cost` is 0/missing |
| Cost (fallback 2) | `item_master_purchase` | `item_id`, `unit_price`, `company_id` | `AVG(unit_price)` where `unit_price > 0`; last resort |
| Order date filter | `sales_order` | `id`, `created_at` (epoch) | last 90d |
| Product info | `item_master` | `id`, `name`, `item_no` | |

**Cost flow (first non-zero wins, 100% coverage):**
`stock_inventroy.cost` → `sales_order_details.cost` → `item_master_purchase.unit_price` → 0.

**Owner / dependency (Santhosh):** the primary cost is now **`stock_inventroy.cost`** (the per-item unit cost the warehouse holds). Only if inventory carries no cost does it fall back to the sales-line cost, then the purchase price. If all three are 0/missing, margin can't be computed and the rule returns 0.

---

## Rule 9 — User Engagement Leader  (`rule_engagement`)
**Trigger:** average product-page dwell time > 90 seconds.

| Data | Table | Column(s) | Notes |
|------|-------|-----------|-------|
| View-start events | `shopify_web_pixel_log` | `id`, `event_name`, `user_id`, `created_at`, `event_data` (jsonb), `company_id` | filter `event_name = 'product_viewed'` |
| View-end events | `shopify_web_pixel_log` | `id`, `event_name`, `user_id`, `created_at`, `event_data` (jsonb), `company_id` | filter `event_name = 'product_view_end'` |
| Variant → item map | `item_master_attribute` | `shopify_variant_id`, `item_id`, `company_id` | join on `event_data->>'variantId'` |
| Product info | `item_master` | `id`, `name`, `item_no` | |

**Dwell time is NOT a stored column.** It is *derived* per viewing session as
`product_view_end.created_at − product_viewed.created_at`. Each `product_viewed` (start) is paired
with the **first `product_view_end` (end) that arrives after it** for the same `user_id` + `item_id`
(`CROSS JOIN LATERAL ... ORDER BY end_at ASC LIMIT 1`). The per-item metric is `AVG(dwell)` across all
such sessions, and qualifies when `avg_dwell > 90` seconds.

**Owner / dependency (Santhosh):** this rule now requires an explicit **`product_view_end`** event
in `shopify_web_pixel_log`. The web-pixel (`shopify-app/extensions/web-pixel/src/index.js`) must emit
`product_view_end` (e.g. on `page_hidden` / unload / navigation away) carrying the same
`event_data.variantId` as the matching `product_viewed`. Until that event is emitted, no session pairs
and the rule returns 0.

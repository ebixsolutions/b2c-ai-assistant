# Rule 7 — Customer Loyalty Favorite

**KPI Target:** LTV (Lifetime Value) +22%
**Tag:** `loyalty`
**Source:** [`rule_loyalty` in queries.py](../rules/queries.py)

---

## What this rule detects

A product that customers **buy more than once**. A high repeat-buyer rate means people came back specifically for this item — these are LTV anchors, perfect for subscription, replenishment, or VIP campaigns.

---

## Rule definition

```
repeat_buyers / total_buyers  >  0.20
```

i.e. more than 20% of buyers placed at least 2 orders containing this item.

---

## Step-by-step calculation

### Step 1 — Per-(item, buyer) order counts (`item_buyers` CTE)
Join `sales_order_details` → `sales_order` → `user` on `create_user_id`.
Filter to real B2C shoppers: `user.relation_type = 'b2c'` AND `user.relation_company_id = tenant`.

```
orders_by_buyer = COUNT(DISTINCT sales_id)   GROUP BY item_id, user_id
```

### Step 2 — Per-item buyer aggregates (`per_item` CTE)
```
total_buyers  = COUNT(*)                                 (distinct buyers of this item)
repeat_buyers = COUNT(*)  WHERE  orders_by_buyer >= 2    (buyers who came back ≥ 2 orders)
```

### Step 3 — Repeat rate (key division)
```
repeat_rate = repeat_buyers / total_buyers
```

### Step 4 — Filter (the rule condition)
```
total_buyers >  0
AND
repeat_rate  >  0.20
```

### Step 5 — Rank
Order by `repeat_rate DESC`, then `total_buyers DESC` (tiebreaker). Return top `PRODUCT_LIMIT`.

---

## Why an item appears (worked example)

| item | total_buyers | repeat_buyers | repeat_rate = repeat/total | > 0.20? | passes? |
|------|--------------|---------------|----------------------------|---------|---------|
| A    | 100          | 35            | 35 / 100 = **0.35**        | ✓       | ✅      |
| B    | 200          | 30            | 30 / 200 = **0.15**        | ✗       | ❌      |
| C    | 4            | 3             | 3 / 4 = **0.75**           | ✓       | ✅ (tiny sample — low confidence but ranks first by ratio) |

Item A wins on volume + retention: 35 of 100 buyers came back for more.

---

## Output fields (per product)

| Field | Meaning |
|-------|---------|
| `total_customers` | distinct buyers ever |
| `repeat_customers` | of those, how many ordered ≥2 times |
| `repeat_rate` | `repeat_customers / total_customers` |
| `score` | the `repeat_rate` value (used for ranking) |

---

## Notes

- No time window — uses **all-time** purchase history.
- The `0.20` threshold is hard-coded at [queries.py:484](../rules/queries.py#L484).
- Customer identity comes directly from `sales_order.create_user_id` → `user.id` (no `system_client_shadow` hop).
- Result count via `PRODUCT_LIMIT` env var.

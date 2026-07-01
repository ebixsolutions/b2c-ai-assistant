# Rule 5 — Shopping Basket Magnet

**KPI Target:** Average Order Value (AOV) +18%
**Tag:** `basket_magnet`
**Source:** [`rule_basket_magnet` in queries.py](../rules/queries.py)

---

## What this rule detects

A product that is **rarely bought alone** — when shoppers buy it, they tend to add other items to the same order. These are natural anchors for bundles, "frequently bought together" widgets, and cross-sell campaigns.

---

## Rule definition

```
multi_product_orders / total_orders  >  0.40
```

i.e. more than 40% of this item's orders contained at least one other distinct item.

---

## Step-by-step calculation

### Step 1 — Order sizes (`order_sizes` CTE)
For each order, count how many *distinct* products it contained.
```
n_items_per_order = COUNT(DISTINCT item_id)  GROUP BY sales_id
```

### Step 2 — Per-item order counts (`per_item` CTE)
```
total_orders = COUNT(DISTINCT sales_id)                                  (all orders with this item)
multi_orders = COUNT(DISTINCT sales_id)  WHERE  n_items_per_order > 1    (orders that also had other items)
```

### Step 3 — Multi-product ratio (key division)
```
multi_ratio = multi_orders / total_orders
```

### Step 4 — Filter (the rule condition)
```
total_orders >  0
AND
multi_ratio  >  0.40
```

### Step 5 — Rank
Order by `multi_ratio DESC`, then `total_orders DESC` (tiebreaker). Return top `PRODUCT_LIMIT`.

---

## Why an item appears (worked example)

| item | total_orders | multi_orders | multi_ratio = multi/total | > 0.40? | passes? |
|------|--------------|--------------|---------------------------|---------|---------|
| A    | 50           | 40           | 40 / 50 = **0.80**        | ✓       | ✅      |
| B    | 100          | 35           | 35 / 100 = **0.35**       | ✗       | ❌      |
| C    | 5            | 5            | 5 / 5 = **1.00**          | ✓       | ✅ (lower volume → ranks below A by tie-break) |

Item A wins: high volume *and* shows up in baskets with other products 80% of the time.

---

## Output fields (per product)

| Field | Meaning |
|-------|---------|
| `total_orders` | distinct orders containing the item |
| `multi_product_orders` | of those, how many had ≥2 distinct items |
| `multi_order_ratio` | `multi_orders / total_orders` |
| `score` | the `multi_ratio` value (used for ranking) |

---

## Notes

- No time window — uses **all-time** order history. Add a 90-day filter if you need recency.
- The `0.4` threshold is hard-coded at [queries.py:425](../rules/queries.py#L425).
- Result count via `PRODUCT_LIMIT` env var.

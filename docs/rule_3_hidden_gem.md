# Rule 3 — Hidden Gem Product

**KPI Target:** ROAS +30%
**Tag:** `hidden_gem`
**Source:** [`rule_hidden_gem` in queries.py](../rules/queries.py)

---

## What this rule detects

A product that **converts at an extremely high rate** (much better than average) but **almost nobody sees it**. These products are under-exposed wins — give them more impressions/spend and ROAS jumps.

---

## Rule definition

```
CR             >  Store Avg CR × 2.0
AND
impressions    in bottom 20% by traffic
```

---

## Step-by-step calculation

### Step 1 — Impressions per item
Count `product_viewed` events in `shopify_web_pixel_log`, joined to local `item_id`.
```
impressions = COUNT(event = product_viewed)
```

### Step 2 — Orders per item
Count distinct `sales_order` rows containing the item.
```
orders_30d = COUNT(DISTINCT sales_id)
```

### Step 3 — Conversion rate (the key division)
```
cr = orders_30d / impressions
```

### Step 4 — Impression percentile (low-traffic detector)
```
impressions_pct = PERCENT_RANK() OVER (ORDER BY impressions ASC)
```
A value of `0.20` means the item has fewer impressions than 80% of items.

### Step 5 — Store-wide average CR
```
avg_cr = AVG(cr) OVER ()
```

### Step 6 — Filter (the two rule conditions)
```
cr               >  2.0 × avg_cr     (converts at 2× store average)
AND
impressions_pct  <= 0.20             (bottom 20% of traffic)
```

### Step 7 — Rank
Order by `cr DESC`, return top `PRODUCT_LIMIT`.

---

## Why an item appears (worked example)

Suppose store `avg_cr = 0.04` (4%) and there are 10 items. Threshold A = `2.0 × 0.04 = 0.08`. Threshold B = `impressions_pct ≤ 0.20`.

| item | impressions | orders_30d | cr = orders/impr      | impressions_pct | cr > 0.08? | pct ≤ 0.20? | passes? |
|------|-------------|------------|-----------------------|-----------------|------------|-------------|---------|
| A    | 12          | 2          | 2 / 12  = **0.167**   | 0.00            | ✓          | ✓           | ✅      |
| B    | 18          | 1          | 1 / 18  = **0.056**   | 0.11            | ✗          | ✓           | ❌      |
| C    | 200         | 30         | 30 / 200 = **0.150**  | 0.78            | ✓          | ✗           | ❌      |

Item A: 1 buyer in every 6 viewers (`0.167 / 0.04 = 4.2×` store average), only 12 impressions. Classic hidden gem.

---

## Output fields (per product)

| Field | Meaning |
|-------|---------|
| `impressions` | `product_viewed` count (30d) |
| `orders_30d` | distinct orders containing the item (30d) |
| `conversion_rate` | `orders_30d / impressions` |
| `store_avg_cr` | mean CR across candidate items |
| `score` | the `cr` value (used for ranking) |

---

## Tuning knobs

- Hard-coded `2.0 × avg_cr` and `0.20` percentile cutoff at [queries.py:337-338](../rules/queries.py#L337-L338).
- Result count via `PRODUCT_LIMIT` env var.

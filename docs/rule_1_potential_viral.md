# Rule 1 — Potential Viral Product

**KPI Target:** Conversion Rate (CR) +15%
**Tag:** `viral`
**Source:** [`rule_viral` in queries.py](../rules/queries.py)

---

## What this rule detects

A product that is being **discovered through external traffic** (ads, social, referrals) and shows **unusually strong engagement** (high cart-add rate) despite **low page-view traffic**. These are early-signal viral candidates worth amplifying.

---

## Rule definition

```
CTR Proxy  >  Store Avg CTR × 1.5
AND
PV         <  Store Avg PV  × 0.5
AND
type       =  16            (external click in user_tag_define)
```

---

## Step-by-step calculation

### Step 1 — Find externally clicked products
```
external_products = user_tag_define
                    WHERE type = 16
                      AND created_at >= NOW - window_days
```

### Step 2 — Map pixel events to local items
Join `shopify_web_pixel_log` to `item_master_attribute` via `variantId` → resolves each pixel row to a local `item_id`.

### Step 3 — Keep only externally discovered items
Intersect Step 1 + Step 2 — only items that were *both* externally clicked *and* saw pixel activity.

### Step 4 — Per-item counts
```
pv  = COUNT(event = product_viewed)
atc = COUNT(event = product_added_to_cart)
```

### Step 5 — CTR Proxy (per item)
```
ctr_proxy = atc / pv          (0 when pv = 0)
```

### Step 6 — Store averages (across all candidates)
```
avg_ctr = AVG(ctr_proxy) OVER ()
avg_pv  = AVG(pv)        OVER ()
```

### Step 7 — Filter (the two rule conditions)
```
ctr_proxy >  1.5 × avg_ctr         (high engagement)
AND
pv        <  0.5 × avg_pv          (low traffic)
```

### Step 8 — Rank
```
ctr_ratio = ctr_proxy / avg_ctr    (how many × above average CTR)
```
Order by `ctr_ratio DESC`, return top `PRODUCT_LIMIT`.

---

## Why an item appears (worked example)

Suppose `avg_ctr = 0.20` and `avg_pv = 40`. Threshold A = `1.5 × 0.20 = 0.30`. Threshold B = `0.5 × 40 = 20`.

| item | pv | atc | ctr_proxy = atc/pv | ctr_proxy > 0.30? | pv < 20? | passes? |
|------|----|-----|--------------------|--------------------|----------|---------|
| A    | 10 | 5   | 5 / 10  = **0.500** | ✓                  | ✓        | ✅      |
| B    | 80 | 30  | 30 / 80 = **0.375** | ✓                  | ✗        | ❌      |
| C    | 5  | 0   | 0 / 5   = **0.000** | ✗                  | ✓        | ❌      |

Item A wins: low traffic but converts at `0.50 / 0.20 = 2.5×` the store average.

---

## Output fields (per product)

| Field | Meaning |
|-------|---------|
| `page_views` | `pv` count in window |
| `add_to_carts` | `atc` count in window |
| `ctr_proxy` | `atc / pv` |
| `store_avg_ctr` | mean `ctr_proxy` across candidates |
| `score` | `ctr_proxy / avg_ctr` (how many × above average) |
| `traffic_window_days` | rolling window used (default 30) |

---

## Tuning knobs

- **Window** — `window_days` parameter (default 30) controls how recent the external-click and pixel data must be.
- **Result count** — controlled by the `PRODUCT_LIMIT` env var via [`get_product_limit()`](../db.py).

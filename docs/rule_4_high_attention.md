# Rule 4 — High Attention, Low Purchase

**KPI Target:** Add-to-Cart Rate (ATC) +20%
**Tag:** `high_attention`
**Source:** [`rule_high_attention` in queries.py](../rules/queries.py)

---

## What this rule detects

A product that **many shoppers view but few add to cart** — the page is pulling traffic but something is killing conversion (price, photos, description, reviews, stock). Classic candidate for a discount, page refresh, or A/B test.

---

## Rule definition

```
PV in Top 5% by traffic
AND
ATC rate < Store Avg ATC rate × 0.6
```

The "Top 5%" floor is widened to at least `:limit` ranks so the result set is never starved when the catalogue is small.

---

## Step-by-step calculation

### Step 1 — Pixel → item join
Pull all `shopify_web_pixel_log` rows, resolve `variantId` → local `item_id` via `item_master_attribute`.

### Step 2 — Per-item counts
```
pv  = COUNT(event = product_viewed)
atc = COUNT(event = product_added_to_cart)
```

### Step 3 — Per-item ATC rate (key division)
```
atc_rate = atc / pv          (0 when pv = 0)
```

### Step 4 — Store-wide stats (`stats` CTE)
```
n_items      = COUNT(*)             (number of items with pixel activity)
avg_atc_rate = AVG(atc_rate)
```

### Step 5 — PV ranking with ties
```
pv_rank = RANK() OVER (ORDER BY pv DESC)
```
Items tied on `pv` share the same rank — critical for small datasets.

### Step 6 — Top-5% cutoff (with safety floor)
```
top_n_cutoff = GREATEST( PRODUCT_LIMIT, CEIL(n_items × 0.05) )
```
Take the larger of "top 5% by count" or `PRODUCT_LIMIT`, so small catalogues still return rows.

### Step 7 — Filter (the two rule conditions)
```
pv_rank  <=  top_n_cutoff               (high traffic — top 5%)
AND
atc_rate <   0.6 × avg_atc_rate         (clearly below-average cart-add)
```

### Step 8 — Order and limit
Order by `pv DESC`, then `LIMIT PRODUCT_LIMIT`.

---

## Why an item appears (worked example)

Real data captured during this build. `n_items = 4`, `avg_atc_rate = 0.250`. Threshold = `0.6 × 0.250 = 0.150`. Cutoff = `GREATEST(PRODUCT_LIMIT=2, CEIL(4×0.05)=1) = 2`.

| item_id  | pv | atc | atc_rate = atc/pv    | atc_rate < 0.150? | pv_rank | pv_rank ≤ 2? | passes? |
|----------|----|-----|----------------------|--------------------|---------|---------------|---------|
| 1033458  | 4  | 4   | 4 / 4  = **1.000**   | ✗                  | 4       | ✗             | ❌      |
| 1033468  | 25 | 0   | 0 / 25 = **0.000**   | ✓                  | 1       | ✓             | ✅      |
| 1033460  | 21 | 0   | 0 / 21 = **0.000**   | ✓                  | 2       | ✓             | ✅      |
| 1033471  | 21 | 0   | 0 / 21 = **0.000**   | ✓                  | 2       | ✓             | ✅      |

Note: both pv=21 rows tie at `pv_rank = 2` (that's the point of `RANK()`). 3 rows pass the WHERE clause; final `LIMIT 2` trims to 2 displayed.

---

## Why `RANK()` instead of `NTILE`/`PERCENTILE_CONT`

- `NTILE(20)` produced wrong results when there were fewer than 20 candidates — buckets stopped meaning "top 5%".
- `PERCENTILE_CONT(0.95)` interpolates a synthetic cutoff (e.g. 24.4 between 21 and 25) and silently drops tied rows just below it.
- `RANK()` gives integer ranks and **shares the rank on ties**, which matches what humans expect from "top N".

---

## Output fields (per product)

| Field | Meaning |
|-------|---------|
| `page_views` | `pv` (30d) |
| `add_to_carts` | `atc` (30d) |
| `atc_rate` | `atc / pv` |
| `store_avg_atc` | `avg_atc_rate` across candidate items |
| `score` | the `pv` value (used for ordering) |

---

## Tuning knobs

- 5% cutoff and 0.6 ATC multiplier hard-coded at [queries.py:383-384](../rules/queries.py#L383-L384).
- Result count via `PRODUCT_LIMIT` env var → [`get_product_limit()`](../db.py).

# Rule 10 — New Product Momentum

**KPI Target:** New Customer Acquisition +20%
**Tag:** `momentum`
**Source:** [`rule_momentum` in queries.py](../rules/queries.py)

---

## What this rule detects

A **newly launched product** (created in the last 7 days) whose **today's sales pace is more than 2× its 7-day average**. Signal: this product is accelerating — promote it before momentum dies.

---

## Rule definition

```
item created within last 7 days
AND
qty_7d > 0
AND
today_qty  >  2 × (qty_7d / 7)
```

The right-hand side is the item's average daily volume across the last 7 days. Today must be more than double that.

---

## Step-by-step calculation

1. **New items (`new_items` CTE):**
   - `item_master.created_at >= now - 7 days`
   - Captures id, name, item_no, created_at.
2. **Sales aggregates (`sales` CTE):**
   - `today_qty` = `SUM(quantity)` from `sales_order_details` joined to `sales_order` where order `created_at >= now - 1 day`.
   - `qty_7d` = same SUM but `created_at >= now - 7 days`.
3. **Velocity ratio per item:**
   ```
   velocity_ratio = today_qty / (qty_7d / 7)
   ```
   "How many times the recent daily average is today selling at?"
4. **Filter** items where `qty_7d > 0` AND `velocity_ratio > 2.0`.
5. **Age** — `(NOW - created_at) / 86400` → fractional days since launch.
6. **Order by** `velocity_ratio DESC`. Return top `:limit`.
7. **Humanize launch age** in Python via `_humanize_age_days(...)` → e.g. `"3 days old"`, `"5 hr old"`, `"just now"`.

---

## Why an item appears (worked example)

Today = Day 7. Item launched on Day 1.

| item | created (days ago) | qty_7d | today_qty | daily_avg (qty_7d/7) | velocity_ratio | passes >2.0? |
|------|--------------------|--------|-----------|----------------------|----------------|--------------|
| A    | 3                  | 14     | 10        | 2.0                  | 5.0            | ✓ — **selected** |
| B    | 5                  | 21     | 3         | 3.0                  | 1.0            | ✗ (today < average) |
| C    | 2                  | 0      | 4         | n/a                  | filtered out   | ✗ (qty_7d = 0) |

Item A is launching with momentum: lifetime daily pace ~2/day, but today did 10 → 5× pace. Surface it.

---

## Output fields (per product)

| Field | Meaning |
|-------|---------|
| `today_sales` | quantity sold in the last 24h |
| `sales_7d` | quantity sold in the last 7 days |
| `velocity_ratio` | `today_qty / (qty_7d / 7)` |
| `launched` | humanised age, e.g. `"3 days old"` |
| `score` | the `velocity_ratio` value (used for ranking) |

---

## Notes

- The `2.0` velocity threshold and the 7-day age window are hard-coded at [queries.py:601 and 623](../rules/queries.py#L601).
- "Today" / "7d" / "90d" windows are scaled by the `WINDOW_MULT` env var (default 1). Raise it only against a stale demo snapshot.
- Result count via `PRODUCT_LIMIT` env var.

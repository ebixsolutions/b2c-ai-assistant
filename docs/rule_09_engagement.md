# Rule 9 — User Engagement Leader (`engagement`)

| | |
|---|---|
| **Tag** | `engagement` |
| **Label** | User Engagement Leader |
| **KPI Target** | Dwell Time +35% |
| **Intent** | Customers deeply engage with the page — strong content attraction. |
| **Implementation** | [`rule_engagement` in queries.py](../rules/queries.py#L554) |
| **Diagnostics** | [`_diag_sql_engagement` / `_diagnose_engagement` in calc_log.py](../rules/calc_log.py#L641) |
| **Explainer** | [`_explain_engagement` in calc_log.py](../rules/calc_log.py#L126) |
| **Aliases** | `user_engagement_leader`; keywords: `engagement`, `dwell`, `time on page`, `engaged` |

---

## What it finds

Products whose visitors **spend a long time on the product page** — average dwell time
greater than **90 seconds** per visitor. A high dwell time signals strong content
attraction and genuine interest, independent of how many people viewed the page.

## Qualifying condition

```
qualifies if  avg_dwell_seconds > 90
```

`avg_dwell_seconds` is the average, **across distinct visitors**, of how long each
visitor spent on the product page. Products are ranked by `avg_dwell` descending and
limited to the top `limit` (default 2).

## How dwell time is measured

Dwell time is derived from `product_view_end` pixel events. **How** it is computed
depends on the `reason` field inside each event's `event_data` — there are two branches,
and both feed a single pool of sessions.

### Branch A — `reason = 'page_exit'` (row timestamps, epoch seconds)

The `product_view_end` row is paired **by `id`** with the immediately-preceding
`product_viewed` row (largest `id` below it, same `user_id` + `item_id`):

```
dwell = view_end.created_at − viewed.created_at
```

Both `created_at` values are epoch **seconds**, so the result is already in seconds.

### Branch B — `reason = 'tab_closed'` (JS timestamps inside event_data, ms)

No row pairing. The start/end timestamps are read straight out of `event_data`
(JavaScript millisecond timestamps):

```
dwell = (endedAt − startedAt) / 1000
```

Rows missing `startedAt` or `endedAt` are dropped.

### Aggregation

1. **Per visitor** — each visitor's sessions are collapsed to one average dwell first,
   so a repeat viewer counts as a **single** visitor (not once per page view).
2. **Per item** — `avg_dwell = AVG(per-visitor dwell)` and `customers = COUNT(distinct visitors)`.

```
Per-visitor:  user_dwell = AVG(dwell)            grouped by (item_id, user_id)
Per-item:     avg_dwell  = AVG(user_dwell)       grouped by item_id
              customers  = COUNT(*)              one row per distinct visitor
```

> **Note:** the shared `PIXEL_TO_ITEM_CTE` does **not** expose `event_data`, so Rule 9
> uses its own `pixel` CTE that carries `event_data` through for the JSON reads
> (`reason`, `startedAt`, `endedAt`, `variantId`).

## Output metric fields

Each qualifying product carries a `metric` dict with:

| Field | Meaning |
|---|---|
| `avg_dwell_seconds` | Average dwell time across distinct visitors (rounded to 1 dp) |
| `customers` | Number of distinct engaged visitors |

The product `score` equals `avg_dwell`.

---

## Calculation log (per qualifying product)

When a product qualifies, `_explain_engagement()` narrates:

```
Formula: dwell from product_view_end — reason='page_exit': view_end.created_at - viewed.created_at
         (id-paired, e.g. id=2 <- id=1); reason='tab_closed': (endedAt-startedAt)/1000 from event_data;
         qualifies if avg_dwell_seconds > 90
Step 1  avg dwell time = {dwell} s   (across {customers} engaged customers)
Step 2  avg_dwell {dwell} > 90 ? -> QUALIFIES
```

## Diagnostics — why 0 products qualified

When no product qualifies, `_diagnose_engagement()` reports the funnel and pinpoints the
binding constraint:

```
Step 1  product_view_end events: page_exit = {pe}, tab_closed = {tc}
Step 2  products with at least one dwell session  = {sess}
Step 3  products with avg dwell > 90s             = {pass_dwell}   (max avg dwell = {max_dwell}s)
```

| Condition | REASON reported |
|---|---|
| `page_exit = 0` **and** `tab_closed = 0` | No `product_view_end` events at all — no sessions to measure (check the web-pixel emits `product_view_end`). |
| sessions = 0 | Events exist, but `page_exit` rows had no preceding `product_viewed` (same user+item) to pair with, and `tab_closed` rows lacked `startedAt`/`endedAt` — no dwell could be computed. |
| `pass_dwell = 0` | No product's avg dwell exceeds 90s (longest is `{max_dwell}`s). |
| otherwise | Conditions met in diagnostics but filtered at selection — check window/limit. |

---

## Data dependencies

| Source | Used for |
|---|---|
| `shopify_web_pixel_log` | `product_view_end` + `product_viewed` events, `event_data` JSON (`reason`, `startedAt`, `endedAt`, `variantId`) |
| `item_master_attribute` | Maps `event_data.variantId` → local `item_id` (via `shopify_variant_id`) |
| `item_master` | Product `name` and `item_no` for display |

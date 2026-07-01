"""Step-by-step calculation explanation for the 10 rules.

Builds a human-readable explanation of WHY each product satisfied a rule —
the formula, the actual numbers plugged in, the thresholds, and the pass result.

Called from queries._bundle() after each rule runs; the returned text is
persisted into ai_rule_responses.calculation_log.

Nothing here changes rule behaviour; it only reads the products a rule already
produced (each product carries its `metric` dict) and narrates the math.
"""
from __future__ import annotations

from datetime import datetime


def _g(metric: dict, *keys, default=None):
    """Get the first present key from a product's metric dict."""
    for k in keys:
        if k in metric and metric[k] is not None:
            return metric[k]
    return default


# ---------------------------------------------------------------------------
# Per-rule explanation builders. Each returns a list of step lines for ONE
# product, using the metric values the rule already computed.
# ---------------------------------------------------------------------------
def _explain_viral(m: dict) -> list[str]:
    pv = _g(m, "page_views", default=0)
    atc = _g(m, "add_to_carts", default=0)
    ctr = _g(m, "ctr_proxy", default=0)
    avg = _g(m, "store_avg_ctr", default=0)
    win = _g(m, "traffic_window_days", default=30)
    return [
        f"      Formula: CTR_proxy = ATC / PV ;  qualifies if CTR_proxy > 1.5 x StoreAvgCTR  AND  PV < 0.5 x StoreAvgPV",
        f"      Step 1  PV (product_viewed, last {win}d) = {pv}",
        f"      Step 2  ATC (product_added_to_cart)      = {atc}",
        f"      Step 3  CTR_proxy = ATC / PV = {atc} / {pv} = {ctr}",
        f"      Step 4  Store avg CTR = {avg}  ->  threshold = 1.5 x {avg} = {round(1.5*avg,4)}",
        f"      Step 5  CTR_proxy {ctr} > {round(1.5*avg,4)} ? AND low-traffic condition met  -> QUALIFIES",
    ]


def _explain_clearance(m: dict) -> list[str]:
    inv = _g(m, "inventory", default=0)
    s30 = _g(m, "sales_30d", default=0)
    doi = _g(m, "days_of_inventory", default=None)
    doi_str = f"{doi:.1f}" if doi is not None else "N/A (no sales)"
    doi_flag = doi is None or doi > 90
    slow_sales = s30 < 5
    return [
        f"      Formula: inventory > 100  AND  (sales_30d < 5  OR  DOI > 90 days)",
        f"      Step 1  inventory (stock_inventroy)  = {inv}   (> 100 ? {inv > 100})",
        f"      Step 2  sales_30d                    = {s30}   (< 5 ? {slow_sales})",
        f"      Step 3  DOI = inventory / (sales_30d / 30)  = {doi_str}   (> 90 ? {doi_flag})",
        f"      Step 4  condition met (slow sales OR high DOI) -> QUALIFIES",
    ]


def _explain_hidden_gem(m: dict) -> list[str]:
    imp = _g(m, "impressions", default=0)
    o30 = _g(m, "orders_30d", default=0)
    cr = _g(m, "conversion_rate", default=0)
    avg = _g(m, "store_avg_cr", default=0)
    return [
        f"      Formula: CR = orders_30d / impressions ;  qualifies if CR > 2.0 x StoreAvgCR  AND  impressions in bottom 20%",
        f"      Step 1  impressions (product_viewed) = {imp}",
        f"      Step 2  orders_30d                   = {o30}",
        f"      Step 3  CR = {o30} / {imp} = {cr}",
        f"      Step 4  Store avg CR = {avg}  ->  threshold = 2.0 x {avg} = {round(2*avg,4)}",
        f"      Step 5  CR {cr} > {round(2*avg,4)} ? AND low-visibility (bottom 20%) -> QUALIFIES",
    ]


def _explain_high_attention(m: dict) -> list[str]:
    pv = _g(m, "page_views", default=0)
    atc = _g(m, "add_to_carts", default=0)
    rate = _g(m, "atc_rate", default=0)
    avg = _g(m, "store_avg_atc", default=0)
    threshold = round(avg * 0.6, 4)
    return [
        f"      Formula: qualifies if PV in store Top 5%  AND  ATC_rate < StoreAvgATC x 0.6 ; ranked by PV",
        f"      Step 1  PV (product_viewed)            = {pv}   (in Top 5% of store PV)",
        f"      Step 2  ATC (product_added_to_cart)    = {atc}",
        f"      Step 3  ATC_rate = {atc} / {pv} = {rate}",
        f"      Step 4  Store avg ATC = {avg}  ->  threshold = 0.6 x {avg} = {threshold}",
        f"      Step 5  High Attention (Top 5% PV) AND ATC_rate {rate} < {threshold} -> QUALIFIES",
    ]


def _explain_basket_magnet(m: dict) -> list[str]:
    tot = _g(m, "total_orders", default=0)
    multi = _g(m, "multi_product_orders", default=0)
    ratio = _g(m, "multi_order_ratio", default=0)
    return [
        f"      Formula: multi_ratio = multi_product_orders / total_orders ;  qualifies if multi_ratio > 0.4",
        f"      Step 1  total_orders containing item        = {tot}",
        f"      Step 2  of those, orders with >1 product     = {multi}",
        f"      Step 3  multi_ratio = {multi} / {tot} = {ratio}  (> 0.4 ? {ratio > 0.4})",
        f"      Step 4  -> QUALIFIES (often bought alongside other products)",
    ]


def _explain_loyalty(m: dict) -> list[str]:
    tot = _g(m, "total_customers", default=0)
    rep = _g(m, "repeat_customers", default=0)
    rate = _g(m, "repeat_rate", default=0)
    return [
        f"      Formula: repeat_rate = repeat_customers / total_customers ;  qualifies if repeat_rate > 0.20",
        f"      Step 1  total distinct buyers   = {tot}",
        f"      Step 2  buyers who bought >= 2x = {rep}",
        f"      Step 3  repeat_rate = {rep} / {tot} = {rate}  (> 0.20 ? {rate > 0.20})",
        f"      Step 4  -> QUALIFIES (strong repeat-purchase loyalty)",
    ]


def _explain_profit(m: dict) -> list[str]:
    margin = _g(m, "gross_margin", default=0)
    pct = _g(m, "gross_margin_pct", default=0)
    price = _g(m, "avg_selling_price", default=0)
    cost = _g(m, "avg_cost", default=0)
    qty = _g(m, "qty_sold_90d", default=0)
    return [
        f"      Formula: margin = (price - cost) / price ;  qualifies if margin > 0.50  AND  cost > 0",
        f"      Step 1  avg selling price = {price}",
        f"      Step 2  avg cost          = {cost}",
        f"      Step 3  margin = ({price} - {cost}) / {price} = {margin}  ({pct}% )",
        f"      Step 4  margin {margin} > 0.50 ? AND cost > 0  -> QUALIFIES   (qty sold 90d = {qty})",
    ]


def _explain_engagement(m: dict) -> list[str]:
    dwell = _g(m, "avg_dwell_seconds", default=0)
    cust = _g(m, "customers", default=0)
    return [
        f"      Formula: dwell from product_view_end — reason='page_exit': view_end.created_at - viewed.created_at (id-paired, e.g. id=2 <- id=1); reason='tab_closed': (endedAt-startedAt)/1000 from event_data; qualifies if avg_dwell_seconds > 90",
        f"      Step 1  avg dwell time = {dwell} s   (across {cust} engaged customers)",
        f"      Step 2  avg_dwell {dwell} > 90 ? -> QUALIFIES",
    ]


def _explain_momentum(m: dict) -> list[str]:
    today = _g(m, "today_sales", default=0)
    s7 = _g(m, "sales_7d", default=0)
    vel = _g(m, "velocity_ratio", default=0)
    launched = _g(m, "launched", default="?")
    return [
        f"      Formula: velocity = today_sales / (sales_7d / 7) ;  qualifies if new product (<=7d) AND velocity > 2.0",
        f"      Step 1  launched: {launched}  (new product, within 7 days)",
        f"      Step 2  today_sales = {today} ; sales_7d = {s7} ; 7d daily avg = {round(s7/7, 3) if s7 else 0}",
        f"      Step 3  velocity = {today} / ({s7}/7) = {vel}  (> 2.0 ? {vel > 2.0})",
        f"      Step 4  -> QUALIFIES (rapid early traction)",
    ]


_EXPLAINERS = {
    "viral": _explain_viral,
    "clearance": _explain_clearance,
    "hidden_gem": _explain_hidden_gem,
    "high_attention": _explain_high_attention,
    "basket_magnet": _explain_basket_magnet,
    "loyalty": _explain_loyalty,
    "profit": _explain_profit,
    "engagement": _explain_engagement,
    "momentum": _explain_momentum,
}


# ===========================================================================
# DIAGNOSTICS — explain WHY zero products qualified.
#
# Each rule has two parts:
#   1. a COLLECTOR (_diag_sql_*) — runs the rule's funnel WITHOUT the qualifying
#      WHERE filter and returns a single row of counts (how many products
#      survived each stage, the store averages, the best value seen, etc.).
#   2. a RENDERER (_diagnose_*) — turns that counts dict into a readable
#      funnel breakdown and pinpoints the binding constraint.
#
# diagnose(tag, session, company_id) runs the collector then returns the dict;
# build_calculation_log() later passes that dict to the renderer.
#
# The collectors need DB helpers (_exec, PIXEL_TO_ITEM_CTE) that live in
# queries.py — imported lazily inside diagnose() to avoid a circular import.
# ===========================================================================
def diagnose(tag: str, session, company_id) -> dict | None:
    """Run the diagnostic collector for `tag` and return a counts dict
    (or None if the rule has no collector / the query fails)."""
    collector = _COLLECTORS.get(tag)
    if collector is None or session is None:
        return None
    try:
        from .queries import _exec, PIXEL_TO_ITEM_CTE
        return collector(session, company_id, _exec, PIXEL_TO_ITEM_CTE)
    except Exception:
        return None


def _first(rows):
    return rows[0] if rows else {}


def _i(r, k):
    try:
        return int(r.get(k) or 0)
    except Exception:
        return 0


def _f(r, k, nd=4):
    try:
        return round(float(r.get(k) or 0), nd)
    except Exception:
        return 0


# ----- Rule 1: viral -------------------------------------------------------
def _diag_sql_viral(session, company_id, _exec, PIXEL_CTE) -> dict:
    win_seconds = 30 * 24 * 60 * 60
    sql = """
    WITH external_products AS (
        SELECT DISTINCT utd.ref_id AS item_id, utd.company_id
        FROM user_tag_define utd
        WHERE utd.company_id = :company_id AND utd.type = 16 AND utd.ref_id IS NOT NULL
          AND utd.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_seconds
    ),
    pixel AS (
        SELECT p.event_name, a.item_id
        FROM shopify_web_pixel_log p
        JOIN item_master_attribute a
          ON a.shopify_variant_id::text = (p.event_data::jsonb ->> 'variantId')
         AND a.company_id = p.company_id
        WHERE p.company_id = :company_id
          AND p.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_seconds
    ),
    filtered AS (
        SELECT p.* FROM pixel p JOIN external_products ep ON ep.item_id = p.item_id
    ),
    per_item AS (
        SELECT item_id,
               COUNT(*) FILTER (WHERE event_name='product_viewed')        AS pv,
               COUNT(*) FILTER (WHERE event_name='product_added_to_cart') AS atc
        FROM filtered GROUP BY item_id
    ),
    scored AS (
        SELECT p.pv, p.atc,
               CASE WHEN p.pv>0 THEN p.atc::float/p.pv ELSE 0 END AS ctr,
               AVG(CASE WHEN p.pv>0 THEN p.atc::float/p.pv ELSE 0 END) OVER () AS avg_ctr,
               AVG(p.pv) OVER () AS avg_pv
        FROM per_item p
    )
    SELECT
      COUNT(*)                                              AS external_products,
      COUNT(*) FILTER (WHERE pv > 0)                        AS products_with_views,
      MAX(avg_ctr)                                          AS avg_ctr,
      MAX(avg_pv)                                           AS avg_pv,
      MAX(ctr)                                              AS best_ctr,
      COUNT(*) FILTER (WHERE pv > 0 AND ctr > 1.5*avg_ctr)  AS pass_ctr,
      COUNT(*) FILTER (WHERE pv > 0 AND pv < 0.5*avg_pv)    AS pass_low_traffic,
      COUNT(*) FILTER (WHERE pv > 0 AND ctr > 1.5*avg_ctr
                         AND pv < 0.5*avg_pv)               AS pass_both
    FROM scored
    """
    r = _first(_exec(session, sql, company_id=company_id, win_seconds=win_seconds))
    avg_ctr = _f(r, "avg_ctr")
    return {
        "external_products": _i(r, "external_products"),
        "products_with_views": _i(r, "products_with_views"),
        "avg_ctr": avg_ctr, "ctr_threshold": round(1.5 * avg_ctr, 4),
        "avg_pv": _f(r, "avg_pv", 2), "best_ctr": _f(r, "best_ctr"),
        "pass_ctr": _i(r, "pass_ctr"),
        "pass_low_traffic": _i(r, "pass_low_traffic"),
        "pass_both": _i(r, "pass_both"),
    }


def _diagnose_viral(d: dict) -> list[str]:
    ext, views = d["external_products"], d["products_with_views"]
    thr, best, pass_ctr, pass_lt, both = (d["ctr_threshold"], d["best_ctr"],
                                          d["pass_ctr"], d["pass_low_traffic"], d["pass_both"])
    lines = [
        f"      Rule: CTR_proxy = ATC / PV ;  qualifies if CTR_proxy > 1.5 x StoreAvgCTR  AND  PV < 0.5 x StoreAvgPV",
        f"      Step 1  externally-clicked products (type=16, 30d) = {ext}",
        f"      Step 2  of those, products with >=1 view (PV>0)    = {views}",
        f"      Step 3  store avg CTR = {d['avg_ctr']}  -> threshold = 1.5 x = {thr}   (best CTR = {best})",
        f"      Step 4  products passing high-CTR (CTR > {thr})    = {pass_ctr}",
        f"      Step 5  products passing low-traffic (PV < 0.5xavgPV={round(0.5*d['avg_pv'],2)}) = {pass_lt}",
        f"      Step 6  products passing BOTH                      = {both}",
    ]
    if ext == 0:
        lines.append("      REASON: no products were clicked from external sources (user_tag_define type=16) in the last 30 days.")
    elif views == 0:
        lines.append("      REASON: externally-clicked products have no pixel 'product_viewed' events to score.")
    elif pass_ctr == 0:
        lines.append(f"      REASON: no product's CTR beats the {thr} threshold (best is only {best}).")
    elif both == 0:
        lines.append("      REASON: high-CTR products don't also have low traffic — they aren't 'under-exposed', so none qualify.")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered at selection — check window/limit.")
    return lines


# ----- Rule 2: clearance ---------------------------------------------------
def _diag_sql_clearance(session, company_id, _exec, PIXEL_CTE) -> dict:
    sql = """
    WITH stock AS (
      SELECT item_id, SUM(quantity) AS total_qty
      FROM stock_inventroy
      WHERE company_id = :company_id AND item_id IS NOT NULL
      GROUP BY item_id
    ),
    sales30 AS (
      SELECT d.item_id, COALESCE(SUM(d.quantity),0) AS qty_30d
      FROM sales_order_details d
      JOIN sales_order o ON o.id = d.sales_id
      WHERE d.company_id = :company_id
        AND o.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_30
      GROUP BY d.item_id
    ),
    combined AS (
      SELECT
        s.item_id,
        s.total_qty,
        COALESCE(ss.qty_30d, 0) AS qty_30d,
        CASE
          WHEN COALESCE(ss.qty_30d, 0) > 0
          THEN s.total_qty / (COALESCE(ss.qty_30d, 0)::float / 30.0)
          ELSE NULL
        END AS doi_days
      FROM stock s
      LEFT JOIN sales30 ss ON ss.item_id = s.item_id
    )
    SELECT
      COUNT(*)                                                                      AS products_in_stock,
      COUNT(*) FILTER (WHERE total_qty > 100)                                       AS pass_overstock,
      COUNT(*) FILTER (WHERE qty_30d < 5)                                           AS pass_slow_sales,
      COUNT(*) FILTER (WHERE COALESCE(doi_days, 9999) > 90)                         AS pass_high_doi,
      COUNT(*) FILTER (WHERE total_qty > 100
                         AND (qty_30d < 5 OR COALESCE(doi_days, 9999) > 90))        AS pass_all,
      MAX(total_qty)                                                                AS max_stock
    FROM combined
    """
    r = _first(_exec(session, sql, company_id=company_id))
    return {
        "products_in_stock": _i(r, "products_in_stock"),
        "pass_overstock": _i(r, "pass_overstock"),
        "pass_slow_sales": _i(r, "pass_slow_sales"),
        "pass_high_doi": _i(r, "pass_high_doi"),
        "pass_all": _i(r, "pass_all"),
        "max_stock": _i(r, "max_stock"),
    }


def _diagnose_clearance(d: dict) -> list[str]:
    instock = d["products_in_stock"]
    lines = [
        f"      Rule: qualifies if inventory > 100  AND  (sales_30d < 5  OR  DOI > 90 days)",
        f"      Step 1  products with inventory rows                    = {instock}",
        f"      Step 2  products passing overstock (qty > 100)          = {d['pass_overstock']}   (max stock = {d['max_stock']})",
        f"      Step 3  products passing slow-sales (sales_30d < 5)     = {d['pass_slow_sales']}",
        f"      Step 4  products passing high-DOI (DOI > 90 days)       = {d['pass_high_doi']}",
        f"      Step 5  products passing ALL conditions                  = {d['pass_all']}",
    ]
    if instock == 0:
        lines.append("      REASON: stock_inventroy has no rows for this company — load inventory data to populate Rule 2.")
    elif d["pass_overstock"] == 0:
        lines.append(f"      REASON: no product has inventory > 100 (max stock is only {d['max_stock']}).")
    elif d["pass_all"] == 0:
        lines.append("      REASON: overstocked products have sales_30d >= 5 AND DOI <= 90 days, so none qualify as clearance candidates.")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered at selection — check window/limit.")
    return lines


# ----- Rule 3: hidden_gem --------------------------------------------------
def _diag_sql_hidden_gem(session, company_id, _exec, PIXEL_CTE) -> dict:
    sql = PIXEL_CTE + """
    , views AS (
      SELECT item_id, COUNT(*) AS impressions
      FROM pixel WHERE event_name='product_viewed' GROUP BY item_id
    ),
    orders30 AS (
      SELECT d.item_id, COUNT(DISTINCT d.sales_id) AS orders_30d
      FROM sales_order_details d JOIN sales_order o ON o.id=d.sales_id
      WHERE d.company_id = :company_id GROUP BY d.item_id
    ),
    joined AS (
      SELECT v.item_id, v.impressions,
        COALESCE(o.orders_30d,0) AS orders_30d,
        CASE WHEN v.impressions>0 THEN COALESCE(o.orders_30d,0)::float/v.impressions ELSE 0 END AS cr,
        PERCENT_RANK() OVER (ORDER BY v.impressions ASC) AS impressions_pct
      FROM views v LEFT JOIN orders30 o USING (item_id)
    ),
    scored AS ( SELECT j.*, AVG(j.cr) OVER () AS avg_cr FROM joined j )
    SELECT
      COUNT(*)                                            AS products_with_views,
      COUNT(*) FILTER (WHERE orders_30d > 0)              AS products_with_orders,
      MAX(avg_cr)                                         AS store_avg_cr,
      COUNT(*) FILTER (WHERE cr > 2.0*avg_cr)             AS pass_cr,
      COUNT(*) FILTER (WHERE impressions_pct <= 0.20)     AS pass_low_visibility,
      COUNT(*) FILTER (WHERE cr > 2.0*avg_cr
                         AND impressions_pct <= 0.20)     AS pass_both,
      MAX(cr)                                             AS best_cr
    FROM scored
    """
    r = _first(_exec(session, sql, company_id=company_id))
    avg_cr = _f(r, "store_avg_cr")
    return {
        "products_with_views": _i(r, "products_with_views"),
        "products_with_orders": _i(r, "products_with_orders"),
        "store_avg_cr": avg_cr, "cr_threshold": round(2.0 * avg_cr, 4),
        "best_cr": _f(r, "best_cr"),
        "pass_cr": _i(r, "pass_cr"),
        "pass_low_visibility": _i(r, "pass_low_visibility"),
        "pass_both": _i(r, "pass_both"),
    }


def _diagnose_hidden_gem(d: dict) -> list[str]:
    """Explain WHY zero products qualified for Hidden Gem, using the funnel
    counts computed without the qualifying filter."""
    views = d.get("products_with_views", 0)
    orders = d.get("products_with_orders", 0)
    avg = d.get("store_avg_cr", 0)
    thr = d.get("cr_threshold", 0)
    best = d.get("best_cr", 0)
    pass_cr = d.get("pass_cr", 0)
    pass_vis = d.get("pass_low_visibility", 0)
    pass_both = d.get("pass_both", 0)
    lines = [
        f"      Rule: CR = orders_30d / impressions ;  qualifies if CR > 2.0 x StoreAvgCR  AND  impressions in bottom 20%",
        f"      Step 1  products with pixel views (impressions)   = {views}",
        f"      Step 2  of those, products with >=1 order (30d)    = {orders}",
        f"      Step 3  store avg CR = {avg}  ->  threshold = 2.0 x {avg} = {thr}   (best product CR = {best})",
        f"      Step 4  products passing CR > {thr}                = {pass_cr}",
        f"      Step 5  products in bottom-20% visibility          = {pass_vis}",
        f"      Step 6  products passing BOTH conditions           = {pass_both}",
    ]
    # pinpoint the binding constraint
    if views == 0:
        lines.append("      REASON: no products have pixel 'product_viewed' events — no impressions to score.")
    elif orders == 0:
        lines.append("      REASON: no viewed product has any order in the window, so every CR = 0 (none beat the threshold).")
    elif pass_cr == 0:
        lines.append(f"      REASON: no product's CR exceeds the {thr} threshold (best CR is only {best}).")
    elif pass_both == 0:
        lines.append("      REASON: products that beat the CR threshold are NOT in the bottom-20% visibility band "
                     "(they already have high impressions, so they aren't 'hidden').")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered out at selection — check window/limit.")
    return lines


# ----- Rule 4: high_attention ----------------------------------------------
def _diag_sql_high_attention(session, company_id, _exec, PIXEL_CTE) -> dict:
    sql = PIXEL_CTE + """
    , per_item AS (
      SELECT item_id,
        COUNT(*) FILTER (WHERE event_name='product_viewed')        AS pv,
        COUNT(*) FILTER (WHERE event_name='product_added_to_cart') AS atc
      FROM pixel GROUP BY item_id
    ),
    stats AS (
      SELECT
        AVG(CASE WHEN pv > 0 THEN atc::float / pv ELSE 0 END)        AS avg_atc_rate,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY pv)             AS pv_top5_cutoff
      FROM per_item WHERE pv >= 1
    ),
    scored AS (
      SELECT p.pv, p.atc,
        CASE WHEN p.pv > 0 THEN p.atc::float / p.pv ELSE 0 END AS atc_rate
      FROM per_item p
    )
    SELECT
      (SELECT COUNT(*) FROM per_item)                              AS products_with_pixel,
      (SELECT COUNT(*) FROM per_item WHERE pv >= 1)                AS pass_viewed,
      COUNT(*) FILTER (WHERE s.pv >= st.pv_top5_cutoff)            AS pass_top5,
      COUNT(*) FILTER (WHERE s.atc_rate < st.avg_atc_rate * 0.6)   AS pass_low_atc,
      COUNT(*) FILTER (WHERE s.pv >= st.pv_top5_cutoff
                         AND s.atc_rate < st.avg_atc_rate * 0.6)   AS pass_both,
      MAX(st.avg_atc_rate)                                         AS avg_atc_rate,
      MAX(st.pv_top5_cutoff)                                       AS pv_top5_cutoff,
      MAX(s.pv)                                                    AS max_pv
    FROM scored s CROSS JOIN stats st
    """
    r = _first(_exec(session, sql, company_id=company_id))
    return {
        "products_with_pixel": _i(r, "products_with_pixel"),
        "pass_viewed": _i(r, "pass_viewed"),
        "pass_top5": _i(r, "pass_top5"),
        "pass_low_atc": _i(r, "pass_low_atc"),
        "pass_both": _i(r, "pass_both"),
        "avg_atc_rate": _f(r, "avg_atc_rate"),
        "pv_top5_cutoff": _f(r, "pv_top5_cutoff"),
        "max_pv": _i(r, "max_pv"),
    }


def _diagnose_high_attention(d: dict) -> list[str]:
    px = d["products_with_pixel"]
    thr = round(d["avg_atc_rate"] * 0.6, 4)
    lines = [
        f"      Rule: qualifies if PV in Top 5%  AND  ATC_rate < StoreAvgATC x 0.6",
        f"      Step 1  products with any pixel event             = {px}",
        f"      Step 2  products viewed at least once (PV >= 1)   = {d['pass_viewed']}   (max PV = {d['max_pv']})",
        f"      Step 3  Top 5% PV cutoff = {round(d['pv_top5_cutoff'], 4)}  ->  products in Top 5% = {d['pass_top5']}",
        f"      Step 4  Store avg ATC = {round(d['avg_atc_rate'], 4)}  ->  threshold = 0.6 x = {thr}  ->  products below = {d['pass_low_atc']}",
        f"      Step 5  products passing BOTH                     = {d['pass_both']}",
    ]
    if px == 0:
        lines.append("      REASON: no pixel events mapped to local items — nothing to evaluate.")
    elif d["pass_viewed"] == 0:
        lines.append("      REASON: no product has a 'product_viewed' pixel event.")
    elif d["pass_top5"] == 0:
        lines.append("      REASON: no product reaches the Top 5% page-view cutoff.")
    elif d["pass_low_atc"] == 0:
        lines.append("      REASON: no high-traffic product has an ATC rate below 0.6x the store average (none are 'low purchase').")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered at selection — check window/limit.")
    return lines


# ----- Rule 5: basket_magnet -----------------------------------------------
def _diag_sql_basket_magnet(session, company_id, _exec, PIXEL_CTE) -> dict:
    sql = """
    WITH order_sizes AS (
      SELECT sales_id, COUNT(DISTINCT item_id) AS n_items
      FROM sales_order_details WHERE company_id = :company_id GROUP BY sales_id
    ),
    per_item AS (
      SELECT d.item_id,
        COUNT(DISTINCT d.sales_id) AS total_orders,
        COUNT(DISTINCT d.sales_id) FILTER (WHERE os.n_items > 1) AS multi_orders
      FROM sales_order_details d JOIN order_sizes os ON os.sales_id = d.sales_id
      WHERE d.company_id = :company_id GROUP BY d.item_id
    )
    SELECT
      COUNT(*)                                                            AS products_ordered,
      COUNT(*) FILTER (WHERE total_orders > 0)                            AS products_with_orders,
      COUNT(*) FILTER (WHERE total_orders > 0
                         AND multi_orders::float/total_orders > 0.4)      AS pass_ratio,
      MAX(CASE WHEN total_orders>0 THEN multi_orders::float/total_orders ELSE 0 END) AS best_ratio
    FROM per_item
    """
    r = _first(_exec(session, sql, company_id=company_id))
    return {
        "products_ordered": _i(r, "products_ordered"),
        "products_with_orders": _i(r, "products_with_orders"),
        "pass_ratio": _i(r, "pass_ratio"),
        "best_ratio": _f(r, "best_ratio"),
    }


def _diagnose_basket_magnet(d: dict) -> list[str]:
    ord_ = d["products_with_orders"]
    lines = [
        f"      Rule: multi_ratio = multi_product_orders / total_orders ;  qualifies if multi_ratio > 0.4",
        f"      Step 1  products with at least one order           = {ord_}",
        f"      Step 2  products with multi_ratio > 0.4            = {d['pass_ratio']}   (best ratio = {d['best_ratio']})",
    ]
    if ord_ == 0:
        lines.append("      REASON: no orders contain these products — no baskets to analyze.")
    elif d["pass_ratio"] == 0:
        lines.append(f"      REASON: no product is bought in multi-item orders >40% of the time (best is {d['best_ratio']}).")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered at selection — check window/limit.")
    return lines


# ----- Rule 7: loyalty -----------------------------------------------------
def _diag_sql_loyalty(session, company_id, _exec, PIXEL_CTE) -> dict:
    sql = """
    WITH item_buyers AS (
      SELECT d.item_id, u.id AS user_id, COUNT(DISTINCT o.id) AS orders_by_buyer
      FROM sales_order_details d
      JOIN sales_order o ON o.id = d.sales_id
      JOIN "user" u ON u.id = o.create_user_id
                   AND u.relation_type = 'b2c'
                   AND u.relation_company_id = d.company_id
      WHERE d.company_id = :company_id GROUP BY d.item_id, u.id
    ),
    per_item AS (
      SELECT item_id, COUNT(*) AS total_buyers,
             COUNT(*) FILTER (WHERE orders_by_buyer >= 2) AS repeat_buyers
      FROM item_buyers GROUP BY item_id
    )
    SELECT
      COUNT(*)                                                          AS products_with_buyers,
      COUNT(*) FILTER (WHERE repeat_buyers > 0)                         AS products_with_repeat,
      COUNT(*) FILTER (WHERE total_buyers > 0
                         AND repeat_buyers::float/total_buyers > 0.20)  AS pass_rate,
      MAX(CASE WHEN total_buyers>0 THEN repeat_buyers::float/total_buyers ELSE 0 END) AS best_rate
    FROM per_item
    """
    r = _first(_exec(session, sql, company_id=company_id))
    return {
        "products_with_buyers": _i(r, "products_with_buyers"),
        "products_with_repeat": _i(r, "products_with_repeat"),
        "pass_rate": _i(r, "pass_rate"),
        "best_rate": _f(r, "best_rate"),
    }


def _diagnose_loyalty(d: dict) -> list[str]:
    buyers = d["products_with_buyers"]
    lines = [
        f"      Rule: repeat_rate = repeat_customers / total_customers ;  qualifies if repeat_rate > 0.20",
        f"      Step 1  products with at least one buyer           = {buyers}",
        f"      Step 2  products with any repeat buyer (>=2 orders)= {d['products_with_repeat']}",
        f"      Step 3  products with repeat_rate > 0.20           = {d['pass_rate']}   (best rate = {d['best_rate']})",
    ]
    if buyers == 0:
        lines.append("      REASON: no identified b2c buyers for these products — no loyalty signal.")
    elif d["products_with_repeat"] == 0:
        lines.append("      REASON: every buyer purchased only once — no repeat customers at all.")
    elif d["pass_rate"] == 0:
        lines.append(f"      REASON: repeat rate never exceeds 20% (best is {d['best_rate']}).")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered at selection — check window/limit.")
    return lines


# ----- Rule 8: profit ------------------------------------------------------
def _diag_sql_profit(session, company_id, _exec, PIXEL_CTE) -> dict:
    sql = """
    WITH inv_cost AS (
      SELECT item_id, AVG(cost) AS avg_inv_cost
      FROM stock_inventroy WHERE company_id = :company_id AND item_id IS NOT NULL AND cost > 0
      GROUP BY item_id
    ),
    purchase_cost AS (
      SELECT item_id, AVG(unit_price) AS avg_purchase_cost
      FROM item_master_purchase WHERE company_id = :company_id AND unit_price > 0
      GROUP BY item_id
    ),
    per_item AS (
      SELECT d.item_id,
        AVG((d.price - COALESCE(ic.avg_inv_cost, NULLIF(d.cost,0), pc.avg_purchase_cost, 0)) / NULLIF(d.price,0)) AS avg_margin,
        AVG(COALESCE(ic.avg_inv_cost, NULLIF(d.cost,0), pc.avg_purchase_cost, 0)) AS avg_cost
      FROM sales_order_details d
      JOIN sales_order o ON o.id = d.sales_id
      LEFT JOIN inv_cost      ic ON ic.item_id = d.item_id
      LEFT JOIN purchase_cost pc ON pc.item_id = d.item_id
      WHERE d.company_id = :company_id
        AND o.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_90
        AND d.price > 0
      GROUP BY d.item_id
    )
    SELECT
      COUNT(*)                                              AS products_sold_90d,
      COUNT(*) FILTER (WHERE avg_cost > 0)                  AS products_with_cost,
      COUNT(*) FILTER (WHERE avg_margin > 0.5)              AS pass_margin,
      COUNT(*) FILTER (WHERE avg_margin > 0.5 AND avg_cost > 0) AS pass_both,
      MAX(avg_margin)                                       AS best_margin
    FROM per_item
    """
    r = _first(_exec(session, sql, company_id=company_id))
    return {
        "products_sold_90d": _i(r, "products_sold_90d"),
        "products_with_cost": _i(r, "products_with_cost"),
        "pass_margin": _i(r, "pass_margin"),
        "pass_both": _i(r, "pass_both"),
        "best_margin": _f(r, "best_margin"),
    }


def _diagnose_profit(d: dict) -> list[str]:
    sold = d["products_sold_90d"]
    best_pct = round(d["best_margin"] * 100, 1)
    lines = [
        f"      Rule: margin = (price - cost) / price ;  qualifies if margin > 0.50  AND  cost > 0",
        f"      Step 1  products sold in last 90d                  = {sold}",
        f"      Step 2  products with a known cost (cost > 0)      = {d['products_with_cost']}",
        f"      Step 3  products with margin > 50%                 = {d['pass_margin']}   (best margin = {best_pct}%)",
        f"      Step 4  products passing BOTH                      = {d['pass_both']}",
    ]
    if sold == 0:
        lines.append("      REASON: no sales in the last 90 days — no margins to compute.")
    elif d["products_with_cost"] == 0:
        lines.append("      REASON: no cost data (stock_inventroy.cost / d.cost / item_master_purchase.unit_price all 0) — margin can't be trusted.")
    elif d["pass_margin"] == 0:
        lines.append(f"      REASON: no product's margin exceeds 50% (best is {best_pct}%).")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered at selection — check window/limit.")
    return lines


# ----- Rule 9: engagement --------------------------------------------------
def _diag_sql_engagement(session, company_id, _exec, PIXEL_CTE) -> dict:
    # Mirror rule_engagement's two branches:
    #   page_exit  -> dwell = view_end.created_at - viewed.created_at (id-paired)
    #   tab_closed -> dwell = (endedAt - startedAt)/1000 from event_data
    # Rule 9 needs event_data, which PIXEL_CTE strips — use a local pixel CTE.
    sql = """
    WITH pixel AS (
      SELECT
        p.id, p.event_name, p.user_id, p.created_at, p.event_data, a.item_id
      FROM shopify_web_pixel_log p
      JOIN item_master_attribute a
        ON a.shopify_variant_id::text = (p.event_data::jsonb ->> 'variantId')
       AND a.company_id = p.company_id
      WHERE p.company_id = :company_id
    )
    , view_ends AS (
      SELECT
        p.id, p.item_id, p.user_id, p.created_at AS end_created_at,
        (p.event_data::jsonb ->> 'reason')            AS reason,
        (p.event_data::jsonb ->> 'startedAt')::bigint AS started_ms,
        (p.event_data::jsonb ->> 'endedAt')::bigint   AS ended_ms
      FROM pixel p
      WHERE p.event_name = 'product_view_end'
    ),
    page_exit_sessions AS (
      SELECT ve.item_id, ve.user_id, ve.end_created_at - v.start_created_at AS dwell
      FROM view_ends ve
      CROSS JOIN LATERAL (
        SELECT vp.created_at AS start_created_at
        FROM pixel vp
        WHERE vp.event_name = 'product_viewed'
          AND vp.item_id = ve.item_id AND vp.user_id = ve.user_id
          AND vp.id < ve.id
        ORDER BY vp.id DESC LIMIT 1
      ) v
      WHERE ve.reason = 'page_exit'
    ),
    tab_closed_sessions AS (
      SELECT ve.item_id, ve.user_id, (ve.ended_ms - ve.started_ms) / 1000.0 AS dwell
      FROM view_ends ve
      WHERE ve.reason = 'tab_closed'
        AND ve.started_ms IS NOT NULL AND ve.ended_ms IS NOT NULL
    ),
    sessions AS (
      SELECT item_id, user_id, dwell FROM page_exit_sessions
      UNION ALL
      SELECT item_id, user_id, dwell FROM tab_closed_sessions
    ),
    counts AS (
      SELECT
        COUNT(*) FILTER (WHERE reason = 'page_exit')  AS page_exit_events,
        COUNT(*) FILTER (WHERE reason = 'tab_closed') AS tab_closed_events
      FROM view_ends
    ),
    -- per-visitor first, then per-item (matches rule_engagement's avg-per-visitor)
    per_user AS ( SELECT item_id, user_id, AVG(dwell) AS user_dwell FROM sessions GROUP BY item_id, user_id ),
    per_item AS ( SELECT item_id, AVG(user_dwell) AS avg_dwell FROM per_user GROUP BY item_id )
    SELECT
      (SELECT page_exit_events  FROM counts)  AS page_exit_events,
      (SELECT tab_closed_events FROM counts)  AS tab_closed_events,
      COUNT(*)                               AS products_with_sessions,
      COUNT(*) FILTER (WHERE avg_dwell > 90) AS pass_dwell,
      MAX(avg_dwell)                         AS max_dwell
    FROM per_item
    """
    r = _first(_exec(session, sql, company_id=company_id))
    return {
        "page_exit_events": _i(r, "page_exit_events"),
        "tab_closed_events": _i(r, "tab_closed_events"),
        "products_with_sessions": _i(r, "products_with_sessions"),
        "pass_dwell": _i(r, "pass_dwell"),
        "max_dwell": _f(r, "max_dwell", 1),
    }


def _diagnose_engagement(d: dict) -> list[str]:
    pe = d.get("page_exit_events", 0)
    tc = d.get("tab_closed_events", 0)
    sess = d["products_with_sessions"]
    lines = [
        f"      Rule: dwell from product_view_end — reason='page_exit' uses view_end.created_at - viewed.created_at (id-paired); reason='tab_closed' uses (endedAt-startedAt)/1000 from event_data; qualifies if avg_dwell_seconds > 90",
        f"      Step 1  product_view_end events: page_exit = {pe}, tab_closed = {tc}",
        f"      Step 2  products with at least one dwell session  = {sess}",
        f"      Step 3  products with avg dwell > 90s              = {d['pass_dwell']}   (max avg dwell = {d['max_dwell']}s)",
    ]
    if pe == 0 and tc == 0:
        lines.append("      REASON: no product_view_end events at all (no page_exit, no tab_closed) — no sessions to measure (check the web-pixel emits product_view_end).")
    elif sess == 0:
        lines.append("      REASON: product_view_end events exist, but page_exit rows had no preceding product_viewed (same user+item) to pair with, and tab_closed rows lacked startedAt/endedAt — no dwell could be computed.")
    elif d["pass_dwell"] == 0:
        lines.append(f"      REASON: no product's avg dwell exceeds 90s (longest is {d['max_dwell']}s).")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered at selection — check window/limit.")
    return lines


# ----- Rule 10: momentum ---------------------------------------------------
def _diag_sql_momentum(session, company_id, _exec, PIXEL_CTE) -> dict:
    sql = """
    WITH new_items AS (
      SELECT id AS item_id FROM item_master
      WHERE company_id = :company_id
        AND created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_7
    ),
    sales AS (
      SELECT d.item_id,
        SUM(CASE WHEN o.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_today THEN d.quantity ELSE 0 END) AS today_qty,
        SUM(CASE WHEN o.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_7 THEN d.quantity ELSE 0 END) AS qty_7d
      FROM sales_order_details d JOIN sales_order o ON o.id = d.sales_id
      WHERE d.company_id = :company_id GROUP BY d.item_id
    ),
    joined AS (
      SELECT n.item_id, COALESCE(s.today_qty,0) AS today_qty, COALESCE(s.qty_7d,0) AS qty_7d,
        (COALESCE(s.today_qty,0)::float / NULLIF(COALESCE(s.qty_7d,0)/7.0,0)) AS velocity
      FROM new_items n LEFT JOIN sales s ON s.item_id = n.item_id
    )
    SELECT
      (SELECT COUNT(*) FROM new_items)                       AS new_products_7d,
      COUNT(*) FILTER (WHERE qty_7d > 0)                     AS products_with_sales,
      COUNT(*) FILTER (WHERE qty_7d > 0 AND velocity > 2.0)  AS pass_velocity,
      MAX(velocity)                                          AS best_velocity
    FROM joined
    """
    r = _first(_exec(session, sql, company_id=company_id))
    return {
        "new_products_7d": _i(r, "new_products_7d"),
        "products_with_sales": _i(r, "products_with_sales"),
        "pass_velocity": _i(r, "pass_velocity"),
        "best_velocity": _f(r, "best_velocity", 2),
    }


def _diagnose_momentum(d: dict) -> list[str]:
    new_ = d["new_products_7d"]
    lines = [
        f"      Rule: velocity = today_sales / (sales_7d / 7) ;  qualifies if new product (<=7d) AND velocity > 2.0",
        f"      Step 1  products launched in the last 7 days       = {new_}",
        f"      Step 2  of those, products with any 7d sales       = {d['products_with_sales']}",
        f"      Step 3  products with velocity > 2.0               = {d['pass_velocity']}   (best velocity = {d['best_velocity']})",
    ]
    if new_ == 0:
        lines.append("      REASON: no products were created in the last 7 days — no new launches to track.")
    elif d["products_with_sales"] == 0:
        lines.append("      REASON: newly launched products have no sales yet — velocity is undefined.")
    elif d["pass_velocity"] == 0:
        lines.append(f"      REASON: no new product's velocity exceeds 2.0 (best is {d['best_velocity']}).")
    else:
        lines.append("      REASON: conditions met in diagnostics but filtered at selection — check window/limit.")
    return lines


# collector (SQL) + renderer (text) per rule.
_COLLECTORS = {
    "viral": _diag_sql_viral,
    "clearance": _diag_sql_clearance,
    "hidden_gem": _diag_sql_hidden_gem,
    "high_attention": _diag_sql_high_attention,
    "basket_magnet": _diag_sql_basket_magnet,
    "loyalty": _diag_sql_loyalty,
    "profit": _diag_sql_profit,
    "engagement": _diag_sql_engagement,
    "momentum": _diag_sql_momentum,
}

_DIAGNOSERS = {
    "viral": _diagnose_viral,
    "clearance": _diagnose_clearance,
    "hidden_gem": _diagnose_hidden_gem,
    "high_attention": _diagnose_high_attention,
    "basket_magnet": _diagnose_basket_magnet,
    "loyalty": _diagnose_loyalty,
    "profit": _diagnose_profit,
    "engagement": _diagnose_engagement,
    "momentum": _diagnose_momentum,
}


def build_calculation_log(tag: str, label: str, kpi: str, products: list, notes: list,
                          company_id=None, diagnostics: dict | None = None) -> str:
    """Build the full step-by-step calculation block for one rule run and
    return it as text (does NOT write to file)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 78,
        f"[{ts}]  RULE: {label}  (tag={tag})  company_id={company_id}",
        f"  KPI Target: {kpi}",
    ]

    if notes:
        for n in notes:
            lines.append(f"  NOTE: {n}")

    if not products:
        lines.append("  RESULT: 0 products satisfied this rule's trigger conditions.")
        diagnoser = _DIAGNOSERS.get(tag)
        if diagnostics and diagnoser:
            lines.append("")
            lines.append("  WHY 0 PRODUCTS QUALIFIED — funnel breakdown:")
            lines.extend(diagnoser(diagnostics))
        lines.append("=" * 78)
        return "\n".join(lines)

    lines.append(f"  RESULT: {len(products)} product(s) satisfied the trigger conditions:")
    explainer = _EXPLAINERS.get(tag)
    for p in products:
        m = p.get("metric", {}) or {}
        lines.append("")
        lines.append(f"  #{p.get('rank')}  {p.get('name')}  (item_id={p.get('item_id')}, "
                     f"item_no={p.get('item_no')})   score={p.get('score')}")
        if explainer:
            lines.extend(explainer(m))
        else:
            # fallback: just dump the metrics
            for k, v in m.items():
                lines.append(f"      {k} = {v}")
    lines.append("=" * 78)
    return "\n".join(lines)

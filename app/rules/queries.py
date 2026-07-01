"""All 10 rule queries — parameterized by company_id, return top-N items.

Verified against live `b2c-v1` PostgreSQL DB.
Key facts encoded here:
  - created_at columns are integer epoch seconds, not timestamps.
  - shopify_web_pixel_log.event_data is text holding JSON like
    {"variantId":"…","productPrice":…} or {"variantId":"…","quantity":…}.
  - Pixel events join to local items via:
        item_master_attribute.shopify_variant_id (bigint)
        item_master_attribute.item_id -> item_master.id
  - Every query is multi-tenant filtered by company_id.
"""
from __future__ import annotations
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import WINDOW_MULT as W


# ---------------------------------------------------------------- helpers

_SCORE_BANDS = {
    # CTR ratio vs store avg; rule requires ratio > 1.5
    "viral":          (1.5,  6.0,  6.0),
    # total inventory units; rule requires > 100
    "clearance":      (100.0, 1000.0, 6.0),
    # raw conversion rate fraction (orders/impressions); rule requires cr > 2x
    # store avg. A 1% CR qualifies as a hidden gem in most stores; >=10% is
    # exceptional. Anchored on the absolute CR rather than the ratio.
    "hidden_gem":     (0.01, 0.10, 6.0),
    # page views (top 5%); scaled by absolute attention volume
    "high_attention": (1.0,  500.0, 6.0),
    # multi-product order ratio; rule requires > 0.4 (max 1.0)
    "basket_magnet":  (0.4,  1.0,  6.0),
    # repeat-customer rate; rule requires > 0.2 (max 1.0)
    "loyalty":        (0.2,  0.8,  6.0),
    # gross margin fraction; rule requires > 0.5 (max 1.0)
    "profit":         (0.5,  0.9,  6.0),
    # avg dwell seconds; rule requires > 90s
    "engagement":     (90.0, 600.0, 6.0),
    # sales velocity ratio (today vs 7d avg); rule requires > 2.0
    "momentum":       (2.0,  10.0, 6.0),
}


def _score10(tag: str, raw: float | None) -> float | None:
    """Map a rule's raw score to a 0-10 display value (rounded to 1 decimal)."""
    if raw is None:
        return None
    band = _SCORE_BANDS.get(tag)
    if not band:
        return None
    threshold, strong, base = band
    raw = float(raw)
    if raw <= 0:
        return 0.0
    if raw <= threshold:
        # below the qualifying line: scale 0..threshold -> 0..base
        val = base * (raw / threshold) if threshold > 0 else base
    else:
        # at/above the line: scale threshold..strong -> base..10
        span = strong - threshold
        frac = (raw - threshold) / span if span > 0 else 1.0
        val = base + (10.0 - base) * min(frac, 1.0)
    return round(max(0.0, min(val, 10.0)), 1)


def _row(rank: int, item_id: int, name, item_no, score: float, _tag: str | None = None, **metric) -> dict:
    return {
        "rank": rank,
        "item_id": int(item_id),
        "item_no": item_no,
        "name": name,
        "score": float(score) if score is not None else None,
        "score_10": _score10(_tag, score) if _tag else None,
        "metric": {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in metric.items() if v is not None},
    }


def _exec(session: Session, sql: str, **params) -> list:
    # Inject window constants (seconds) so the same SQL works against fresh
    # production data (W=1) or a stale demo snapshot (W>1).
    params.setdefault("win_7",  7  * 86400 * W)
    params.setdefault("win_30", 30 * 86400 * W)
    params.setdefault("win_90", 90 * 86400 * W)
    params.setdefault("win_today", 1 * 86400 * W)
    return session.execute(text(sql), params).mappings().all()


# Common CTE: pixel event -> local item_id (variant-level join)
PIXEL_TO_ITEM_CTE = """
WITH pixel AS (
  SELECT
    p.id,
    p.event_name,
    p.user_id,
    p.created_at,
    a.item_id
  FROM shopify_web_pixel_log p
  JOIN item_master_attribute a
    ON a.shopify_variant_id::text = (p.event_data::jsonb ->> 'variantId')
   AND a.company_id = p.company_id
  WHERE p.company_id = :company_id
)
"""


# ================================================================ Rule 1
# ================================================================ Rule 1
# Potential Viral Product
#
# Logic:
# - Consider only externally clicked products (type = 16)
# - Calculate:
#       PV  = product_viewed count
#       ATC = product_added_to_cart count
#       CTR Proxy = ATC / PV
#
# Rule:
#   CTR Proxy > Store Avg CTR * 1.5
#   AND
#   PV < Store Avg PV * 0.5
#
# Meaning:
# Product receives recent external attention and
# shows unusually high engagement despite low traffic.
 
 
def rule_viral(
    session: Session,
    company_id: int,
    limit: int = 2,
    window_days: int = 30
) -> dict:
 
    print(" *** rule_viral: company_id=%s, limit=%s, window_days=%s" % (company_id, limit, window_days))
    # configurable rolling window
    win_seconds = window_days * 24 * 60 * 60
 
    sql = """
    WITH external_products AS (

        -- Products clicked from external sources
        SELECT DISTINCT
            utd.ref_id AS item_id,
            utd.company_id

        FROM user_tag_define utd

        WHERE utd.company_id = :company_id
          AND utd.type = 16
          AND utd.ref_id IS NOT NULL

          -- rolling window filter
          AND utd.created_at >=
              EXTRACT(EPOCH FROM NOW())::bigint - :win_seconds
    ),

    pixel AS (

        -- Pixel events mapped to internal item_id
        SELECT
            p.id,
            p.event_name,
            p.user_id,
            p.created_at,
            p.company_id,
            a.item_id

        FROM shopify_web_pixel_log p

        JOIN item_master_attribute a
          ON a.shopify_variant_id::text =
             (p.event_data::jsonb ->> 'variantId')
         AND a.company_id = p.company_id

        WHERE p.company_id = :company_id

          -- rolling window filter
          AND p.created_at >=
              EXTRACT(EPOCH FROM NOW())::bigint - :win_seconds
    ),

    filtered AS (

        -- Only externally discovered products
        SELECT p.*

        FROM pixel p

        JOIN external_products ep
          ON ep.item_id = p.item_id
         AND ep.company_id = p.company_id
    ),

    per_item AS (

        -- Per product metrics
        SELECT
            item_id,

            COUNT(*) FILTER (
                WHERE event_name = 'fastbuy_product_view'
            ) AS pv,

            COUNT(*) FILTER (
                WHERE event_name = 'fastbuy_product_added_to_cart'
            ) AS atc

        FROM filtered

        GROUP BY item_id
    ),

    scored AS (

        -- Viral scoring metrics
        SELECT
            p.item_id,
            p.pv,
            p.atc,

            CASE
                WHEN p.pv > 0
                THEN p.atc::float / p.pv
                ELSE 0
            END AS ctr_proxy,

            AVG(
                CASE
                    WHEN p.pv > 0
                    THEN p.atc::float / p.pv
                    ELSE 0
                END
            ) OVER () AS avg_ctr,

            AVG(p.pv) OVER () AS avg_pv

        FROM per_item p
    )

    SELECT
        s.item_id,
        s.pv,
        s.atc,
        s.ctr_proxy,
        s.avg_ctr,
        s.avg_pv,

        im.name,
        im.item_no,

        (
            s.ctr_proxy / NULLIF(s.avg_ctr, 0)
        ) AS ctr_ratio

    FROM scored s

    JOIN item_master im
      ON im.id = s.item_id

    WHERE
        s.pv > 0

        -- high engagement
        AND s.ctr_proxy > 1.5 * s.avg_ctr

        -- low traffic
        AND s.pv < 0.5 * s.avg_pv

    ORDER BY ctr_ratio DESC NULLS LAST

    LIMIT :limit
    """
 
    rows = _exec(
        session,
        sql,
        company_id=company_id,
        limit=limit,
        win_seconds=win_seconds
    )
 
    products = [
        _row(
            i + 1,
            r["item_id"],
            r["name"],
            r["item_no"],
 
            score=r["ctr_ratio"] or 0,
            _tag="viral",

            page_views=r["pv"],
            add_to_carts=r["atc"],

            ctr_proxy=round(r["ctr_proxy"] or 0, 4),
            store_avg_ctr=round(r["avg_ctr"] or 0, 4),

            traffic_window_days=window_days
        )
        for i, r in enumerate(rows)
    ]
 
    return _bundle("viral", products, company_id=company_id, session=session)


# ================================================================ Rule 2
def rule_clearance(session: Session, company_id: int, limit: int = 2) -> dict:
    sql = """
    WITH stock AS (
      SELECT item_id, SUM(quantity) AS total_qty
      FROM stock_inventroy
      WHERE company_id = :company_id AND item_id IS NOT NULL
      GROUP BY item_id
    ),
    sales30 AS (
      SELECT d.item_id, COALESCE(SUM(d.quantity), 0) AS qty_30d
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
    SELECT c.item_id, c.total_qty, c.qty_30d, c.doi_days,
           im.name, im.item_no
    FROM combined c
    JOIN item_master im ON im.id = c.item_id
    WHERE c.total_qty > 100
      AND (
        c.qty_30d < 5
        OR COALESCE(c.doi_days, 9999) > 90
      )
    ORDER BY c.total_qty DESC
    LIMIT :limit
    """
    rows = _exec(session, sql, company_id=company_id, limit=limit)
    products = [
        _row(i + 1, r["item_id"], r["name"], r["item_no"],
             score=r["total_qty"], _tag="clearance",
             inventory=r["total_qty"],
             sales_30d=r["qty_30d"],
             days_of_inventory=round(r["doi_days"], 1) if r["doi_days"] is not None else None)
        for i, r in enumerate(rows)
    ]
    notes = []
    if not products:
        notes.append("stock_inventroy is empty in this DB — load inventory data to populate Rule 2.")
    return _bundle("clearance", products, notes=notes, company_id=company_id, session=session)


# ================================================================ Rule 3
def rule_hidden_gem(session: Session, company_id: int, limit: int = 2) -> dict:
    sql = PIXEL_TO_ITEM_CTE + """
    , views AS (
      SELECT item_id, COUNT(*) AS impressions
      FROM pixel
      WHERE event_name IN ('product_viewed', 'fastbuy_product_view')
      GROUP BY item_id
    ),
    orders30 AS (
      SELECT d.item_id, COUNT(DISTINCT d.sales_id) AS orders_30d
      FROM sales_order_details d
      JOIN sales_order o ON o.id = d.sales_id
      WHERE d.company_id = :company_id
      GROUP BY d.item_id
    ),
    joined AS (
      SELECT
        v.item_id, v.impressions,
        COALESCE(o.orders_30d, 0) AS orders_30d,
        CASE WHEN v.impressions > 0
             THEN COALESCE(o.orders_30d, 0)::float / v.impressions ELSE 0 END AS cr,
        PERCENT_RANK() OVER (ORDER BY v.impressions ASC) AS impressions_pct
      FROM views v
      LEFT JOIN orders30 o USING (item_id)
    ),
    scored AS (
      SELECT j.*, AVG(j.cr) OVER () AS avg_cr
      FROM joined j
    )
    SELECT s.item_id, s.impressions, s.orders_30d, s.cr, s.avg_cr,
           im.name, im.item_no
    FROM scored s
    JOIN item_master im ON im.id = s.item_id
    WHERE s.cr > 2.0 * s.avg_cr
      AND s.impressions_pct <= 0.20
    ORDER BY s.cr DESC NULLS LAST
    LIMIT :limit
    """
    rows = _exec(session, sql, company_id=company_id, limit=limit)
    products = [
        _row(i + 1, r["item_id"], r["name"], r["item_no"],
             score=r["cr"] or 0, _tag="hidden_gem",
             impressions=r["impressions"], orders_30d=r["orders_30d"],
             conversion_rate=round(r["cr"] or 0, 4),
             store_avg_cr=round(r["avg_cr"] or 0, 4))
        for i, r in enumerate(rows)
    ]
    return _bundle("hidden_gem", products, company_id=company_id, session=session)


# ================================================================ Rule 4
def rule_high_attention(session: Session, company_id: int, limit: int = 2) -> dict:
    sql = PIXEL_TO_ITEM_CTE + """
    , per_item AS (
      SELECT
        item_id,
        COUNT(*) FILTER (
          WHERE event_name IN ('product_viewed', 'fastbuy_product_view')
        ) AS pv,
        COUNT(*) FILTER (
          WHERE event_name IN ('product_added_to_cart', 'fastbuy_product_added_to_cart')
        ) AS atc
      FROM pixel
      GROUP BY item_id
    ),
    stats AS (
      -- store-wide benchmarks, computed once over every viewed product
      SELECT
        COUNT(*) AS n_items,
        AVG(CASE WHEN p.pv > 0 THEN p.atc::float / p.pv ELSE 0 END) AS avg_atc_rate,
        -- 95th percentile of page views -> the "Top 5% PV" cutoff
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY p.pv) AS pv_top5_cutoff
      FROM per_item p
      WHERE p.pv >= 1
    ),
    scored AS (
      SELECT
        p.*,
        CASE WHEN p.pv > 0 THEN p.atc::float / p.pv ELSE 0 END AS atc_rate
      FROM per_item p
    )
    SELECT s.item_id, s.pv, s.atc, s.atc_rate, st.avg_atc_rate,
           im.name, im.item_no
    FROM scored s
    CROSS JOIN stats st
    JOIN item_master im ON im.id = s.item_id
    WHERE s.pv >= 1                                   -- must have been viewed
      AND s.pv >= st.pv_top5_cutoff                   -- High Attention: PV in store Top 5%
      AND s.atc_rate < st.avg_atc_rate * 0.6          -- Low Purchase: ATC rate < Store Avg x 0.6
    ORDER BY s.pv DESC, s.atc_rate ASC
    LIMIT :limit
    """
    rows = _exec(session, sql, company_id=company_id, limit=limit)
    products = [
        _row(i + 1, r["item_id"], r["name"], r["item_no"],
             score=r["pv"], _tag="high_attention",
             page_views=r["pv"], add_to_carts=r["atc"],
             atc_rate=round(r["atc_rate"] or 0, 4),
             store_avg_atc=round(r["avg_atc_rate"] or 0, 4))
        for i, r in enumerate(rows)
    ]
    return _bundle("high_attention", products, company_id=company_id, session=session)


# ================================================================ Rule 5
def rule_basket_magnet(session: Session, company_id: int, limit: int = 2) -> dict:
    sql = """
    WITH order_sizes AS (
      SELECT sales_id, COUNT(DISTINCT item_id) AS n_items
      FROM sales_order_details
      WHERE company_id = :company_id
      GROUP BY sales_id
    ),
    per_item AS (
      SELECT
        d.item_id,
        COUNT(DISTINCT d.sales_id) AS total_orders,
        COUNT(DISTINCT d.sales_id) FILTER (WHERE os.n_items > 1) AS multi_orders
      FROM sales_order_details d
      JOIN order_sizes os ON os.sales_id = d.sales_id
      WHERE d.company_id = :company_id
      GROUP BY d.item_id
    )
    SELECT p.item_id, p.total_orders, p.multi_orders,
           (p.multi_orders::float / NULLIF(p.total_orders, 0)) AS multi_ratio,
           im.name, im.item_no
    FROM per_item p
    JOIN item_master im ON im.id = p.item_id
    WHERE p.total_orders > 0
      AND (p.multi_orders::float / p.total_orders) > 0.4
    ORDER BY multi_ratio DESC, p.total_orders DESC
    LIMIT :limit
    """
    rows = _exec(session, sql, company_id=company_id, limit=limit)
    products = [
        _row(i + 1, r["item_id"], r["name"], r["item_no"],
             score=r["multi_ratio"] or 0, _tag="basket_magnet",
             total_orders=r["total_orders"],
             multi_product_orders=r["multi_orders"],
             multi_order_ratio=round(r["multi_ratio"] or 0, 4))
        for i, r in enumerate(rows)
    ]
    return _bundle("basket_magnet", products, company_id=company_id, session=session)


# ================================================================ Rule 7
def rule_loyalty(session: Session, company_id: int, limit: int = 2) -> dict:
    # Customer identity = the `user` row that placed the order.
    # `sales_order.create_user_id` points directly at `user.id` of the
    # shopper (relation_type='b2c', relation_company_id = this tenant).
    # No need for the system_client_shadow hop.
    sql = """
    WITH item_buyers AS (
      SELECT
        d.item_id,
        u.id AS user_id,
        COUNT(DISTINCT o.id) AS orders_by_buyer
      FROM sales_order_details d
      JOIN sales_order o ON o.id = d.sales_id
      JOIN "user"      u ON u.id = o.create_user_id
                        AND u.relation_type        = 'b2c'
                        AND u.relation_company_id  = d.company_id
      WHERE d.company_id = :company_id
      GROUP BY d.item_id, u.id
    ),
    per_item AS (
      SELECT
        item_id,
        COUNT(*) AS total_buyers,
        COUNT(*) FILTER (WHERE orders_by_buyer >= 2) AS repeat_buyers
      FROM item_buyers
      GROUP BY item_id
    )
    SELECT p.item_id, p.total_buyers, p.repeat_buyers,
           (p.repeat_buyers::float / NULLIF(p.total_buyers, 0)) AS repeat_rate,
           im.name, im.item_no
    FROM per_item p
    JOIN item_master im ON im.id = p.item_id
    WHERE p.total_buyers > 0
      AND (p.repeat_buyers::float / p.total_buyers) > 0.20
    ORDER BY repeat_rate DESC, p.total_buyers DESC
    LIMIT :limit
    """
    rows = _exec(session, sql, company_id=company_id, limit=limit)
    products = [
        _row(i + 1, r["item_id"], r["name"], r["item_no"],
             score=r["repeat_rate"] or 0, _tag="loyalty",
             total_customers=r["total_buyers"],
             repeat_customers=r["repeat_buyers"],
             repeat_rate=round(r["repeat_rate"] or 0, 4))
        for i, r in enumerate(rows)
    ]
    return _bundle("loyalty", products, company_id=company_id, session=session)


# ================================================================ Rule 8
def rule_profit(session: Session, company_id: int, limit: int = 2) -> dict:
    # CSV Rule 8: (Selling Price - Cost) / Selling Price > 50%
    #   d.price = selling price.
    #
    # COST FLOW (priority order, first non-zero wins) — gives 100% coverage:
    #   1. stock_inventroy.cost          = authoritative unit cost in inventory  (PRIMARY)
    #   2. sales_order_details.cost      = cost carried on the sales line        (fallback)
    #   3. item_master_purchase.unit_price = supplier purchase cost             (last resort)
    # stock_inventroy.cost is decimal(16,5) "单价成本" (unit cost) — the per-item
    # cost the warehouse holds, so it is the most reliable margin denominator.
    sql = """
    WITH inv_cost AS (
      -- PRIMARY cost: average unit cost held in inventory (cost > 0 only)
      SELECT item_id, AVG(cost) AS avg_inv_cost
      FROM stock_inventroy
      WHERE company_id = :company_id AND item_id IS NOT NULL AND cost > 0
      GROUP BY item_id
    ),
    purchase_cost AS (
      -- last-resort cost: average supplier purchase price
      SELECT item_id, AVG(unit_price) AS avg_purchase_cost
      FROM item_master_purchase
      WHERE company_id = :company_id AND unit_price > 0
      GROUP BY item_id
    ),
    per_item AS (
      SELECT
        d.item_id,
        AVG(
          (d.price - COALESCE(ic.avg_inv_cost, NULLIF(d.cost, 0), pc.avg_purchase_cost, 0))
          / NULLIF(d.price, 0)
        ) AS avg_margin,
        AVG(d.price) AS avg_price,
        AVG(COALESCE(ic.avg_inv_cost, NULLIF(d.cost, 0), pc.avg_purchase_cost, 0)) AS avg_cost,
        SUM(d.quantity) AS qty
      FROM sales_order_details d
      JOIN sales_order o ON o.id = d.sales_id
      LEFT JOIN inv_cost      ic ON ic.item_id = d.item_id
      LEFT JOIN purchase_cost pc ON pc.item_id = d.item_id
      WHERE d.company_id = :company_id
        AND o.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_90
        AND d.price > 0
      GROUP BY d.item_id
    )
    SELECT p.item_id, p.avg_margin, p.avg_price, p.avg_cost, p.qty,
           im.name, im.item_no
    FROM per_item p
    JOIN item_master im ON im.id = p.item_id
    WHERE p.avg_margin > 0.5
      AND p.avg_cost   > 0
    ORDER BY p.avg_margin DESC
    LIMIT :limit
    """
    rows = _exec(session, sql, company_id=company_id, limit=limit)
    products = [
        _row(i + 1, r["item_id"], r["name"], r["item_no"],
             score=r["avg_margin"] or 0, _tag="profit",
             gross_margin=round(r["avg_margin"] or 0, 4),
             gross_margin_pct=round((r["avg_margin"] or 0) * 100, 2),
             avg_selling_price=round(r["avg_price"] or 0, 2),
             avg_cost=round(r["avg_cost"] or 0, 2),
             qty_sold_90d=r["qty"])
        for i, r in enumerate(rows)
    ]
    return _bundle("profit", products, company_id=company_id, session=session)


# ================================================================ Rule 9
def rule_engagement(session: Session, company_id: int, limit: int = 2) -> dict:
    # Dwell time is derived from product_view_end events, and HOW depends on the
    # event_data.reason:
    #
    #  reason = 'page_exit'  -> dwell from ROW created_at (epoch SECONDS):
    #       pair the product_view_end with the immediately-preceding product_viewed
    #       row BY id (largest id below it, same user+item) and take
    #       dwell = view_end.created_at - viewed.created_at.
    #
    #  reason = 'tab_closed' -> dwell from INSIDE event_data (JS ms timestamps):
    #       dwell = (endedAt - startedAt) / 1000 ; no pairing / created_at used.
    #
    # Both branches feed one pool of sessions; per-item AVG(dwell) must exceed 90s.
    # NB: the shared PIXEL_TO_ITEM_CTE does NOT expose event_data, so Rule 9
    # uses its own pixel CTE that carries event_data through for the JSON reads.
    sql = """
    WITH pixel AS (
      SELECT
        p.id,
        p.event_name,
        p.user_id,
        p.created_at,
        p.event_data,
        a.item_id
      FROM shopify_web_pixel_log p
      JOIN item_master_attribute a
        ON a.shopify_variant_id::text = (p.event_data::jsonb ->> 'variantId')
       AND a.company_id = p.company_id
      WHERE p.company_id = :company_id
    )
    -- All product_view_end rows, with their reason + (for tab_closed) the
    -- startedAt/endedAt JS-ms timestamps pulled out of event_data.
    , view_ends AS (
      SELECT
        p.id,
        p.item_id,
        p.user_id,
        p.created_at AS end_created_at,
        (p.event_data::jsonb ->> 'reason')            AS reason,
        (p.event_data::jsonb ->> 'startedAt')::bigint AS started_ms,
        (p.event_data::jsonb ->> 'endedAt')::bigint   AS ended_ms
      FROM pixel p
      WHERE p.event_name = 'product_view_end'
    ),
    -- Branch A: page_exit / next_product -> dwell from row created_at, paired BY
    -- id with the immediately-preceding product_viewed (largest id below, same
    -- user+item). next_product (user moved to the next product) is the same
    -- concept as page_exit: the dwell is view_end.created_at - viewed.created_at,
    -- and this matches the durationSeconds carried in event_data exactly.
    page_exit_sessions AS (
      SELECT
        ve.item_id,
        ve.user_id,
        ve.end_created_at - v.start_created_at AS dwell
      FROM view_ends ve
      CROSS JOIN LATERAL (
        SELECT vp.created_at AS start_created_at
        FROM pixel vp
        WHERE vp.event_name IN ('product_viewed', 'fastbuy_product_view')
          AND vp.item_id = ve.item_id
          AND vp.user_id = ve.user_id
          AND vp.id < ve.id                  -- viewed row comes before view_end by id
        ORDER BY vp.id DESC                   -- the immediately-preceding view (id just below)
        LIMIT 1
      ) v
      WHERE ve.reason IN ('page_exit', 'next_product')
    ),
    -- Branch B: tab_closed -> dwell straight from event_data, (endedAt-startedAt)/1000.
    tab_closed_sessions AS (
      SELECT
        ve.item_id,
        ve.user_id,
        (ve.ended_ms - ve.started_ms) / 1000.0 AS dwell
      FROM view_ends ve
      WHERE ve.reason = 'tab_closed'
        AND ve.started_ms IS NOT NULL
        AND ve.ended_ms   IS NOT NULL
    ),
    sessions AS (
      SELECT item_id, user_id, dwell FROM page_exit_sessions
      UNION ALL
      SELECT item_id, user_id, dwell FROM tab_closed_sessions
    ),
    -- Avg Dwell = SUM(time spent by all visitors) / COUNT(visitors).
    -- Collapse each visitor's sessions to one per-visitor dwell FIRST so a
    -- repeat viewer counts as a single visitor (not once per page-view).
    per_user AS (
      SELECT item_id, user_id, AVG(dwell) AS user_dwell
      FROM sessions
      GROUP BY item_id, user_id
    ),
    per_item AS (
      SELECT
        item_id,
        AVG(user_dwell) AS avg_dwell,        -- average across distinct visitors
        COUNT(*)        AS customers          -- one row per distinct visitor
      FROM per_user
      GROUP BY item_id
    )
    SELECT p.item_id, p.avg_dwell, p.customers, im.name, im.item_no
    FROM per_item p
    JOIN item_master im ON im.id = p.item_id
    WHERE p.avg_dwell > 90
    ORDER BY p.avg_dwell DESC
    LIMIT :limit
    """
    rows = _exec(session, sql, company_id=company_id, limit=limit)
    products = [
        _row(i + 1, r["item_id"], r["name"], r["item_no"],
             score=r["avg_dwell"] or 0, _tag="engagement",
             avg_dwell_seconds=round(r["avg_dwell"] or 0, 1),
             customers=r["customers"])
        for i, r in enumerate(rows)
    ]
    return _bundle("engagement", products, company_id=company_id, session=session)


# ================================================================ Rule 10
def rule_momentum(session: Session, company_id: int, limit: int = 2) -> dict:
    sql = """
    WITH new_items AS (
      SELECT id AS item_id, name, item_no, created_at
      FROM item_master
      WHERE company_id = :company_id
        AND created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_7
    ),
    sales AS (
      SELECT
        d.item_id,
        SUM(CASE WHEN o.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_today
                 THEN d.quantity ELSE 0 END) AS today_qty,
        SUM(CASE WHEN o.created_at >= EXTRACT(EPOCH FROM NOW())::bigint - :win_7
                 THEN d.quantity ELSE 0 END) AS qty_7d
      FROM sales_order_details d
      JOIN sales_order o ON o.id = d.sales_id
      WHERE d.company_id = :company_id
      GROUP BY d.item_id
    )
    SELECT n.item_id, n.name, n.item_no,
           COALESCE(s.today_qty, 0) AS today_qty,
           COALESCE(s.qty_7d, 0)    AS qty_7d,
           (COALESCE(s.today_qty,0)::float / NULLIF(COALESCE(s.qty_7d,0)/7.0, 0)) AS velocity_ratio,
           (EXTRACT(EPOCH FROM NOW()) - n.created_at) / 86400.0 AS age_days
    FROM new_items n
    LEFT JOIN sales s ON s.item_id = n.item_id
    WHERE COALESCE(s.qty_7d, 0) > 0
      AND (COALESCE(s.today_qty,0)::float / NULLIF(COALESCE(s.qty_7d,0)/7.0, 0)) > 2.0
    ORDER BY velocity_ratio DESC
    LIMIT :limit
    """
    rows = _exec(session, sql, company_id=company_id, limit=limit)
    products = [
        _row(i + 1, r["item_id"], r["name"], r["item_no"],
             score=r["velocity_ratio"] or 0, _tag="momentum",
             today_sales=r["today_qty"], sales_7d=r["qty_7d"],
             launched=_humanize_age_days(r["age_days"] or 0),
             velocity_ratio=round(r["velocity_ratio"] or 0, 2))
        for i, r in enumerate(rows)
    ]
    return _bundle("momentum", products, company_id=company_id, session=session)


def _humanize_age_days(d: float) -> str:
    """Turn a fractional-day age into 'just now' / '29 min old' / '5 hr old' /
    '3 days old' / '2 months old' / '1 year old'. Computed fresh on each rule run."""
    d = float(d)
    if d < 0:
        return "just now"
    mins  = d * 24 * 60
    hours = d * 24
    if mins  <  1: return "just now"
    if mins  < 60: return f"{round(mins)} min old"
    if hours < 24: return f"{round(hours)} hr old"
    if d     < 30:
        n = round(d); return f"{n} day{'' if n == 1 else 's'} old"
    if d < 365:
        m = round(d / 30); return f"{m} month{'' if m == 1 else 's'} old"
    y = round(d / 365);  return f"{y} year{'' if y == 1 else 's'} old"


# ---------------------------------------------------------- bundle helper
def _bundle(tag: str, products: list, notes: list[str] | None = None,
            company_id: int | None = None, session: Session | None = None) -> dict:
    from .registry import RULE_META
    label, kpi, reason = RULE_META[tag]

    # When nothing qualified, run a diagnostic pass (same funnel, no qualifying
    # filter) so the log can explain WHY zero products matched. All diagnostic
    # logic lives in calc_log.diagnose().
    diagnostics = None
    if not products and session is not None:
        try:
            from .calc_log import diagnose
            diagnostics = diagnose(tag, session, company_id)
        except Exception:
            diagnostics = None

    # build a step-by-step calculation explanation of WHY each product qualified
    # (or, when none did, WHY zero qualified) to be persisted into
    # ai_rule_responses.calculation_log.
    calculation_log = ""
    try:
        from .calc_log import build_calculation_log
        calculation_log = build_calculation_log(tag, label, kpi, products, notes or [],
                                                company_id, diagnostics)
    except Exception:
        pass

    return {
        "tag": tag,
        "tag_label": label,
        "kpi_target": kpi,
        "reason": reason,
        "top_products": products,
        "notes": notes or [],
        "calculation_log": calculation_log,
    }

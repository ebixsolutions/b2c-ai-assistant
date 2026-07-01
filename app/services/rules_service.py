"""Rules service — business logic for all chatbot endpoints.

  * list_rules_tags()  -> rule rows + display metadata from the rules_tags table
  * check_health()     -> DB liveness probe
  * list_companies()   -> companies with pixel/sales activity (chatbot targets)
  * run_chat()         -> classify a message, run the rule, enrich, and log

run_chat runs the matched rule, attaches product images, applies optional AI
enrichment, and persists each run into ai_rule_responses. No HTTP concerns here;
the controller maps these results/errors to HTTP responses.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_product_limit, is_ai_enabled
from ..rules import RULES, RULE_LABELS, classify
from ..rules.registry import TAG_TO_SLUG
from ..rules.ai import enrich_reason, enrich_product_reason

logger = logging.getLogger("b2c")


def list_rules_tags(db: Session) -> list[dict]:
    """Rule rows from the rules_tags master table: the stable key (rule_name),
    the pretty label (display_name) and the KPI. Visual styling (icon, gradient)
    is NOT stored here — the CMS holds it statically, keyed by rule_name."""
    rows = db.execute(text(
        "SELECT id, rule_name, display_name, kpi FROM rules_tags ORDER BY id"
    )).mappings().all()
    return [
        {
            "id": r["id"],
            "rule_name": r["rule_name"],
            "display_name": r["display_name"],
            "kpi": r["kpi"],
        }
        for r in rows
    ]


def check_health(db: Session) -> dict:
    """Lightweight DB liveness probe (raises if the connection is down)."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


def list_companies(db: Session) -> list[dict]:
    """Companies that have either pixel activity or sales — the best targets
    for the chatbot — ordered by total activity."""
    sql = """
    WITH pix AS (
      SELECT company_id, COUNT(*) AS n FROM shopify_web_pixel_log GROUP BY company_id
    ),
    so AS (
      SELECT company_id, COUNT(*) AS n FROM sales_order GROUP BY company_id
    ),
    ids AS (
      SELECT company_id FROM pix
      UNION
      SELECT company_id FROM so
    )
    SELECT
      c.id,
      COALESCE(NULLIF(c.name, ''), NULLIF(c.short_name, ''), 'Company #' || c.id) AS name,
      COALESCE(pix.n, 0) AS pixel_events,
      COALESCE(so.n, 0)  AS sales_orders
    FROM ids
    JOIN company c ON c.id = ids.company_id
    LEFT JOIN pix ON pix.company_id = c.id
    LEFT JOIN so  ON so.company_id  = c.id
    ORDER BY (COALESCE(pix.n,0) + COALESCE(so.n,0)) DESC
    LIMIT 50
    """
    rows = db.execute(text(sql)).mappings().all()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "pixel_events": r["pixel_events"],
            "sales_orders": r["sales_orders"],
        }
        for r in rows
    ]


class RuleNotMatched(Exception):
    """Raised when the user message matches none of the 10 rules."""

    def __init__(self) -> None:
        labels = ", ".join(RULE_LABELS.values())
        super().__init__(
            "I couldn't match your question to one of the 10 rules. "
            f"Try one of: {labels}."
        )


class RuleExecutionError(Exception):
    """Raised when the matched rule's query fails."""

    def __init__(self, tag: str, cause: Exception) -> None:
        self.tag = tag
        super().__init__(f"Rule '{tag}' failed: {cause}")


def run_chat(db: Session, message: str, company_id: int) -> dict:
    """Classify the message, run the rule, enrich + log, and return a dict
    ready for the ChatResponse model.

    Raises RuleNotMatched / RuleExecutionError for the controller to translate.
    """
    tag = classify(message)
    if tag is None:
        raise RuleNotMatched()

    try:
        result = RULES[tag](db, company_id, limit=get_product_limit())
    except Exception as exc:
        raise RuleExecutionError(tag, exc) from exc

    reason = result["reason"]
    products = result["top_products"]

    if products:
        _attach_images(db, company_id, products)

    # Track the AI tokens spent on this rule run: each AI call's usage plus a
    # rolled-up total. Stays None when AI is disabled / no call was made.
    token_usage = None

    ai_enabled = is_ai_enabled() and bool(products)
    if ai_enabled:
        calls = []
        reason, store_usage = enrich_reason(tag, products, result["reason"])
        if store_usage:
            calls.append({"call": "store_reason", **store_usage})
        for p in products:
            ai_line, prod_usage = enrich_product_reason(tag, p, result["reason"])
            if ai_line:
                p["ai_reason"] = ai_line
            if prod_usage:
                calls.append({
                    "call": "product_reason",
                    "item_id": p.get("item_id"),
                    **prod_usage,
                })
        token_usage = _summarize_token_usage(tag, calls)

    # Persist the run (best-effort; never blocks the reply). Store the stable
    # slug (rules_tags.rule_name) so the rule_id FK lookup resolves — NOT the
    # display label, which would never match and leaves rule_id NULL.
    _log_ai_response(
        db,
        rule_name=TAG_TO_SLUG.get(result["tag"], result["tag"]),
        company_id=company_id,
        calculation_log=result.get("calculation_log", ""),
        ai_reason=reason,
        kpi_target=result["kpi_target"],
        products=products,
        token_usage=token_usage,
    )

    return {
        "tag": result["tag"],
        "tag_label": result["tag_label"],
        "kpi_target": result["kpi_target"],
        "reason": reason,
        "matched_count": len(products),
        "top_products": products,
    }


def _attach_images(db: Session, company_id: int, products: list[dict]) -> None:
    """Set product['image_url'] from system_photo (table_id = item_master.id).
    One query for all items; prefers the default photo, then lowest sort order."""
    item_ids = [p["item_id"] for p in products if p.get("item_id") is not None]
    if not item_ids:
        return
    sql = """
    SELECT DISTINCT ON (table_id) table_id, wan_url
    FROM system_photo
    WHERE company_id = :company_id
      AND table_id = ANY(:item_ids)
      AND wan_url IS NOT NULL AND wan_url <> ''
    ORDER BY table_id, is_default DESC, sort ASC, id ASC
    """
    rows = db.execute(
        text(sql), {"company_id": company_id, "item_ids": item_ids}
    ).mappings().all()
    by_item = {r["table_id"]: r["wan_url"] for r in rows}
    for p in products:
        p["image_url"] = by_item.get(p["item_id"])


def _summarize_token_usage(tag: str, calls: list[dict]) -> dict:
    """Roll up per-call token usage for one rule run into a single JSON payload:
    the rule, each individual AI call, and the summed totals."""
    return {
        "rule": tag,
        "ai_calls": len(calls),
        "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
        "total_tokens": sum(c["total_tokens"] for c in calls),
        "calls": calls,
    }


def _log_ai_response(db: Session, *, rule_name, company_id, calculation_log,
                     ai_reason, kpi_target, products, token_usage) -> None:
    """Insert one row into ai_rule_responses for this /chat run.
    Best-effort: any failure is logged and swallowed so the reply is unaffected."""
    try:
        row_id = db.execute(
            text("""
                INSERT INTO ai_rule_responses
                    (rule_id, rule_name, company_id, calculation_log,
                     ai_reason, kpi_target, matched_count, top_products, token_usage)
                VALUES
                    ((SELECT id FROM rules_tags WHERE rule_name = :rule_name),
                     :rule_name, :company_id, :calculation_log,
                     :ai_reason, :kpi_target, :matched_count,
                     CAST(:top_products AS JSONB), CAST(:token_usage AS JSONB))
                RETURNING id
            """),
            {
                "rule_name": rule_name,
                "company_id": company_id,
                "calculation_log": calculation_log,
                "ai_reason": ai_reason,
                "kpi_target": kpi_target,
                "matched_count": len(products),
                "top_products": json.dumps(products, default=str),
                "token_usage": json.dumps(token_usage, default=str) if token_usage else None,
            },
        ).scalar()
        db.commit()
        logger.info("ai_rule_responses: logged run id=%s rule=%s company=%s matched=%s",
                    row_id, rule_name, company_id, len(products))
    except Exception as exc:
        db.rollback()
        logger.warning("ai_rule_responses insert failed: %s", exc)

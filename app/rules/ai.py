"""LLM-driven explanation layer for rule results.

Toggle with IS_AI_ENABLE in .env. When False, callers should fall back to
the static text in RULE_META. Never raises — any failure returns None so the
caller can fall back to the static reason.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger("b2c.ai")

# Project root (…/b2c-ai-assistant), used to resolve relative credential paths.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Per-rule static context lifted from the rules spec sheet. Sent to the LLM as
# grounding so the explanation matches the documented detection/reason logic.
RULE_AI_CONTEXT: dict[str, dict[str, str]] = {
    "viral": {
        "trigger": "CTR > (Store Avg × 1.5) AND PV < (Store Avg × 0.5)",
        "detection": "Click-through rate is above average by 50%, but total traffic is low.",
        "reason": "High CTR proves strong appeal; the product only needs more traffic exposure to become a bestseller.",
        "kpi": "Conversion Rate (CR) +15%",
    },
    "clearance": {
        "trigger": "Current Inventory > 100 units AND 30-day Sales < 5 (or DOI > 90 days)",
        "detection": "Inventory exceeds 100 units while 30-day sales are below 5.",
        "reason": "Inventory accumulation is severe; promotional campaigns are recommended for faster liquidation.",
        "kpi": "Inventory Turnover +25%",
    },
    "hidden_gem": {
        "trigger": "CR > (Store Avg × 2.0) AND Impressions < Bottom 20%",
        "detection": "Impressions are low, but conversions occur whenever visitors arrive.",
        "reason": "Extremely strong conversion ability but low visibility; this is an undiscovered opportunity product.",
        "kpi": "ROAS +30%",
    },
    "high_attention": {
        "trigger": "PV in Top 5% AND ATC < (Store Avg × 0.6)",
        "detection": "Product page traffic ranks in the store's top 5%, but add-to-cart rate is below average.",
        "reason": "Many users view but do not buy, usually due to pricing or decision barriers; discounts or incentives may help conversion.",
        "kpi": "Add-to-Cart Rate (ATC) +20%",
    },
    "basket_magnet": {
        "trigger": "(Orders with Multiple Products / Total Orders) > 40%",
        "detection": "Frequently appears together with other products in the same order.",
        "reason": "This product naturally drives bundle purchases and is ideal for increasing average order value.",
        "kpi": "Average Order Value (AOV) +18%",
    },
    "loyalty": {
        "trigger": "(Repeat Customers / Total Customers) > 20%",
        "detection": "Products with the highest repeat purchase counts among existing customers.",
        "reason": "Product quality and customer satisfaction are excellent, reducing customer acquisition costs through word-of-mouth.",
        "kpi": "LTV (Lifetime Value) +22%",
    },
    "profit": {
        "trigger": "(Selling Price - Cost) / Selling Price > 50%",
        "detection": "Gross margin exceeds 50%.",
        "reason": "Products with the highest profit potential are suitable for higher advertising budgets.",
        "kpi": "Net Profit +12%",
    },
    "engagement": {
        "trigger": "Average Product Page Dwell Time > 90 seconds",
        "detection": "Average user browsing time on the product page exceeds 90 seconds.",
        "reason": "Customers deeply engage with the page, indicating strong content attraction and exploration intent.",
        "kpi": "Dwell Time +35%",
    },
    "momentum": {
        "trigger": "(Today's Sales / 7-Day Average Sales) > 2.0 AND Product Age < 7 days",
        "detection": "Sales growth curve is steepest within the first 7 days after launch.",
        "reason": "Newly launched product is rapidly gaining traction and market attention.",
        "kpi": "New Customer Acquisition +20%",
    },
}


def _get_client():
    """Lazy import + per-call env reload so .env edits take effect without restart.

    Uses Vertex AI (Gemini) through the google-genai SDK. Authentication is via
    Google Cloud Application Default Credentials (run `gcloud auth application-default
    login` or set GOOGLE_APPLICATION_CREDENTIALS to a service-account key file).
    """
    load_dotenv(override=True)
    if os.getenv("IS_AI_ENABLE", "").strip().lower() not in ("true", "1", "yes"):
        return None, None
    project_id = os.getenv("PROJECT_ID", "").strip()
    location = os.getenv("LOCATION", "").strip()
    model = os.getenv("MODEL", "").strip()
    if not (project_id and location and model):
        logger.warning(
            "Vertex AI not configured — set PROJECT_ID, LOCATION and MODEL in .env"
        )
        return None, None
    try:
        from google import genai
    except ImportError:
        logger.warning("google-genai package not installed — AI layer disabled")
        return None, None

    # Resolve the service-account key path (relative paths are taken against the
    # project root) and expose it so the google-auth library can find it.
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds:
        if not os.path.isabs(creds):
            creds = os.path.join(_PROJECT_ROOT, creds)
        if os.path.isfile(creds):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds
        else:
            logger.warning("GOOGLE_APPLICATION_CREDENTIALS file not found: %s", creds)

    try:
        client = genai.Client(vertexai=True, project=project_id, location=location)
    except Exception as exc:
        logger.warning("Vertex AI client init failed: %s", exc)
        return None, None
    return client, model


def _usage_from_response(resp: Any) -> dict:
    """Extract token counts from a Gemini response's usage_metadata.
    Returns zeros if the field is missing so callers can always sum safely."""
    um = getattr(resp, "usage_metadata", None)
    return {
        "prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(um, "candidates_token_count", 0) or 0,
        "total_tokens": getattr(um, "total_token_count", 0) or 0,
    }


def _summarize_products(products: list[dict]) -> str:
    """Compact product summary for the prompt — name + key metrics only."""
    if not products:
        return "(no products matched the rule)"
    lines = []
    for p in products[:5]:
        name = p.get("name") or f"item {p.get('item_id')}"
        metrics = p.get("metric") or {}
        metric_str = ", ".join(f"{k}={v}" for k, v in metrics.items() if v is not None)
        lines.append(f"- {name}: {metric_str}")
    return "\n".join(lines)


def enrich_reason(tag: str, products: list[dict], static_reason: str) -> tuple[str, dict | None]:
    """Return (reason_string, token_usage). Falls back to static_reason on any
    failure; token_usage is None when no AI call was made."""
    client, model = _get_client()
    if client is None:
        return static_reason, None

    ctx = RULE_AI_CONTEXT.get(tag)
    if ctx is None:
        return static_reason, None

    prompt = f"""You are a retail analytics assistant. A rule has just selected products from a store.

Rule: {tag}
Trigger formula: {ctx['trigger']}
Detection logic: {ctx['detection']}
Generic recommendation: {ctx['reason']}
KPI target: {ctx['kpi']}

Selected products (actual metrics from the database):
{_summarize_products(products)}

Write ONE short, actionable explanation (2 sentences max, under 50 words) that:
1. References the actual numbers above so the merchant sees why these specific products matched.
2. Suggests the next action aligned with the KPI target.

IMPORTANT — write for a non-technical merchant: ALWAYS spell out acronyms in full on first use.
Use these full forms:
- CTR → Click-Through Rate
- CR  → Conversion Rate
- ATC → Add-to-Cart Rate
- AOV → Average Order Value
- LTV → Lifetime Value
- ROAS → Return on Ad Spend
- PV  → Page Views
- DOI → Days of Inventory
- KPI → Key Performance Indicator

You may include the acronym in parentheses after the full form, e.g. "Add-to-Cart Rate (ATC)".

Plain text only. No markdown, no headers, no bullet points."""

    try:
        from google.genai import types

        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=256,
                temperature=0.4,
                # gemini-2.5-flash is a thinking model; disable thinking so the
                # whole token budget goes to the visible answer (no truncation).
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        text = (resp.text or "").strip()
        usage = _usage_from_response(resp)
        logger.info("Gemini OK -> rule '%s' (store-level) tokens=%s", tag, usage["total_tokens"])
        return (text or static_reason), usage
    except Exception as exc:
        logger.warning("AI enrichment failed for rule '%s': %s", tag, exc)
        return static_reason, None


def enrich_product_reason(tag: str, product: dict, static_reason: str) -> tuple[str | None, dict | None]:
    """Return (one_liner_or_None, token_usage). None text on failure so caller
    can drop the field; token_usage is None when no AI call was made."""
    client, model = _get_client()
    if client is None:
        return None, None

    ctx = RULE_AI_CONTEXT.get(tag)
    if ctx is None:
        return None, None

    name = product.get("name") or f"item {product.get('item_id')}"
    metrics = product.get("metric") or {}
    metric_str = ", ".join(f"{k}={v}" for k, v in metrics.items() if v is not None) or "no metrics"

    prompt = f"""Rule '{tag}' selected this product. KPI: {ctx['kpi']}.
Detection: {ctx['detection']}

Product: {name}
Metrics: {metric_str}

Write ONE sentence (under 30 words, plain text) explaining what makes THIS product fit the rule, citing its numbers.

Write for a non-technical merchant: ALWAYS spell out acronyms in full (CTR → Click-Through Rate, CR → Conversion Rate, ATC → Add-to-Cart Rate, AOV → Average Order Value, LTV → Lifetime Value, ROAS → Return on Ad Spend, PV → Page Views). You may add the acronym in parentheses.

No markdown."""

    try:
        from google.genai import types

        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=128,
                temperature=0.4,
                # Disable thinking so the short answer isn't truncated (see above).
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        text = (resp.text or "").strip()
        usage = _usage_from_response(resp)
        logger.info("Gemini OK -> rule '%s' (per-product) tokens=%s", tag, usage["total_tokens"])
        return (text or None), usage
    except Exception as exc:
        logger.warning("AI per-product enrichment failed for rule '%s': %s", tag, exc)
        return None, None

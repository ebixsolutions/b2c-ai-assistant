"""Intent classification (keyword router) + rule registry.

Each rule is a callable `(session, company_id, limit) -> dict` returning:
    {
        "tag": str,
        "tag_label": str,
        "kpi_target": str,
        "reason": str,
        "top_products": [ {rank, item_id, item_no, name, score, metric}, ... ],
        "notes": [str, ...],
    }
"""
from __future__ import annotations
import re
from . import queries

# ----- rule metadata (from B2C v1.csv) -----------------------------------
RULE_META = {
    "viral":        ("Potential Viral Product",      "Conversion Rate (CR) +15%",
                     "High CTR proves strong appeal; the product only needs more traffic exposure."),
    "clearance":    ("Inventory Clearance Candidate","Inventory Turnover +25%",
                     "Inventory accumulation is severe; run promotional campaigns to liquidate."),
    "hidden_gem":   ("Hidden Gem Product",           "ROAS +30%",
                     "Extremely strong conversion ability but low visibility — undiscovered opportunity."),
    "high_attention":("High Attention, Low Purchase","Add-to-Cart Rate (ATC) +20%",
                     "Many users view but do not buy — pricing or decision barriers; try discounts."),
    "basket_magnet":("Shopping Basket Magnet",       "Average Order Value (AOV) +18%",
                     "Naturally drives bundle purchases; ideal for raising AOV."),
    "loyalty":      ("Customer Loyalty Favorite",    "LTV +22%",
                     "Excellent satisfaction reduces acquisition cost through word-of-mouth."),
    "profit":       ("Profit Protection Product",    "Net Profit +12%",
                     "Highest profit potential — suitable for higher advertising budgets."),
    "engagement":   ("User Engagement Leader",       "Dwell Time +35%",
                     "Customers deeply engage with the page — strong content attraction."),
    "momentum":     ("New Product Momentum",         "New Customer Acquisition +20%",
                     "Newly launched product is rapidly gaining market traction."),
}

RULE_LABELS = {k: v[0] for k, v in RULE_META.items()}

# ----- rule_name slugs (the stable keys stored in rules_tags.rule_name) ---
# The CMS sends rules_tags.rule_name straight to /chat, so classify() must map
# each slug to its internal tag. Keep these in sync with the SQL seed.
SLUG_TO_TAG = {
    "potential_viral_product":       "viral",
    "inventory_clearance_candidate": "clearance",
    "hidden_gem_product":            "hidden_gem",
    "high_attention_low_purchase":   "high_attention",
    "shopping_basket_magnet":        "basket_magnet",
    "customer_loyalty_favorite":     "loyalty",
    "profit_protection_product":     "profit",
    "user_engagement_leader":        "engagement",
    "new_product_momentum":          "momentum",
}

# Reverse map: internal tag -> stable slug (the rules_tags.rule_name key).
# Used when persisting a run so ai_rule_responses.rule_name / rule_id resolve.
TAG_TO_SLUG = {tag: slug for slug, tag in SLUG_TO_TAG.items()}

# ----- keyword router ----------------------------------------------------
KEYWORDS: list[tuple[str, list[str]]] = [
    ("viral",        ["viral", "trending up", "could go viral", "potential viral"]),
    ("clearance",    ["clearance", "clear stock", "overstock", "dead stock", "slow moving", "liquidate", "excess inventory"]),
    ("hidden_gem",   ["hidden gem", "hidden", "undiscovered", "underexposed", "low visibility"]),
    ("high_attention",["high attention", "not buying", "many views", "view but", "abandoned", "low conversion"]),
    ("basket_magnet",["basket", "bundle", "cross sell", "cross-sell", "combo", "bought together", "aov"]),
    ("loyalty",      ["loyalty", "repeat", "loyal", "returning customer", "favourite", "favorite"]),
    ("profit",       ["profit", "margin", "high margin", "profitable", "best margin"]),
    ("engagement",   ["engagement", "dwell", "time on page", "engaged"]),
    ("momentum",     ["momentum", "new product", "newly launched", "just launched", "new arrival", "trending now"]),
]


def classify(message: str) -> str | None:
    msg = message.lower().strip()
    # 1) Exact rule_name slug from the CMS picker (e.g. 'potential_viral_product').
    if msg in SLUG_TO_TAG:
        return SLUG_TO_TAG[msg]
    # 2) Free-text keyword router (typed questions).
    for tag, kws in KEYWORDS:
        for kw in kws:
            if re.search(rf"\b{re.escape(kw)}\b", msg):
                return tag
    return None


# ----- registry ----------------------------------------------------------
RULES = {
    "viral":         queries.rule_viral,
    "clearance":     queries.rule_clearance,
    "hidden_gem":    queries.rule_hidden_gem,
    "high_attention":queries.rule_high_attention,
    "basket_magnet": queries.rule_basket_magnet,
    "loyalty":       queries.rule_loyalty,
    "profit":        queries.rule_profit,
    "engagement":    queries.rule_engagement,
    "momentum":      queries.rule_momentum,
}

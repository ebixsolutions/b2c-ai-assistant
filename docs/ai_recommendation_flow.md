# AI Recommendation Flow

**Purpose:** Document how a user message becomes a rule-based product selection, and exactly where GPT produces the **AI Detection Logic** and **AI Recommendation Reason**.

**Sources:**
- [`classify` / `RULES` in registry.py](../rules/registry.py)
- [`rule_*` queries in queries.py](../rules/queries.py)
- [`enrich_reason` / `enrich_product_reason` in ai.py](../rules/ai.py)
- [`run_chat` in rules_service.py](../services/rules_service.py)

---

## Key fact

> **SQL selects the products. GPT does NOT pick, rank, or drop anything.**
> GPT only rewrites the static **Detection Logic** and **Recommendation Reason** using the store's real numbers. If GPT is disabled or fails, the static spec text is returned verbatim.

---

## End-to-end flow

```
User message
     ↓
Classify → 1 rule  (keyword router, 1 of 10)          →  tag = "viral"
     ↓
┌─ WHERE   (rule formula: CTR > 1.5×avg AND PV < 0.5×avg) ─┐
│  ORDER BY (rank by score)                               │  one SQL query
└─ LIMIT 2 (top-N, PRODUCT_LIMIT default = 2)            ─┘
     ↓
Top 2 Products  (with real metrics: pv, atc, ctr_proxy, avg…)
     ↓
┌──────────────────────────────────────────────────────────────┐
│  GPT INPUT  (the spec row is fed in as grounding)            │
│  RULE_AI_CONTEXT["viral"]:                                  │
│    trigger   = "CTR > (Store Avg × 1.5) AND PV < (Avg × 0.5)"│
│    detection = "Click-through rate is above average by 50%…" │  ← AI Detection Logic
│    reason    = "High CTR proves strong appeal…"             │  ← AI Recommendation Reason
│    kpi       = "Conversion Rate (CR) +15%"                  │
│  + the 2 products' actual metrics                           │
└──────────────────────────────────────────────────────────────┘
     ↓
Gemini (gemini-2.5-flash on Vertex AI)  — rewrites the generic detection/reason
     using THIS store's real numbers
     ↓
┌──────────────────────────────────────────────────────────────┐
│  GPT OUTPUT                                                  │
│  • enrich_reason()         → one store-level reason string   │
│  • enrich_product_reason() → per-product "ai_reason" line    │
│  (on failure → falls back to the static spec reason)         │
└──────────────────────────────────────────────────────────────┘
     ↓
2 Products returned, each with a personalized reason
```

---

## How the spec columns map to the code

Using **Rule 1 — Potential Viral Product** as the example:

| Spec column | Where it lives in code | Role |
|---|---|---|
| **Trigger Conditions & Formula** | SQL `WHERE` in [queries.py](../rules/queries.py) **and** `RULE_AI_CONTEXT["viral"]["trigger"]` in [ai.py](../rules/ai.py) | SQL enforces it; the text version is fed to GPT as context |
| **Key Metrics** | SQL computes `pv, atc, ctr_proxy, avg_ctr` in [queries.py](../rules/queries.py) | Real numbers passed into the prompt |
| **AI Detection Logic** | `RULE_AI_CONTEXT["viral"]["detection"]` in [ai.py](../rules/ai.py) | Static grounding → GPT personalizes it |
| **AI Recommendation Reason** | `RULE_AI_CONTEXT["viral"]["reason"]` in [ai.py](../rules/ai.py) | Static fallback → GPT rewrites with real data |
| **KPI Target** | `RULE_AI_CONTEXT["viral"]["kpi"]` in [ai.py](../rules/ai.py) | GPT aligns the suggested next action to it |

---

## Reference spec row (Rule 1)

| Field | Value |
|---|---|
| **Rule ID** | 1 |
| **Key Metrics** | CTR (Click-Through Rate) + Traffic |
| **AI Recommendation Tag** | 🔥 Potential Viral Product |
| **Trigger Conditions & Formula** | CTR > (Store Average × 1.5) and PV < (Store Average × 0.5) |
| **AI Detection Logic** | Click-through rate is above average by 50%, but total traffic is low. |
| **AI Recommendation Reason** | High CTR proves strong appeal; the product only needs more traffic exposure to become a bestseller. |
| **KPI Target** | Conversion Rate (CR) +15% |

---

## Important behaviour notes

- **GPT is optional.** It runs only when `IS_AI_ENABLE=true` in `.env`. When off, the static **Detection Logic** / **Recommendation Reason** from `RULE_AI_CONTEXT` are returned as-is.
- **GPT never changes the product set.** The list returned to the user is exactly what SQL selected (default top **2**, set by `PRODUCT_LIMIT`).
- **Fail-safe.** Any GPT/API error is swallowed and the static spec text is returned — the user always gets a reply.
- **Two GPT calls per run:**
  - `enrich_reason()` → one overall reason for the whole match.
  - `enrich_product_reason()` → one `ai_reason` line per product.

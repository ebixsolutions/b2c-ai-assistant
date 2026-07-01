
-- ----------------------------------------------------------------------------
-- 1) Rules master table: the product-tagging rules.
--    Holds ONLY the data the rule owns: a stable key (rule_name), the pretty
--    label (display_name) and the KPI. Visual styling (icon / gradient color)
--    lives statically in the CMS, keyed by rule_name — NOT in the DB.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rules_tags (
    id            SERIAL PRIMARY KEY,
    rule_name     TEXT NOT NULL,                        -- stable key/slug, e.g. 'potential_viral_product'
    display_name  TEXT NOT NULL,                        -- pretty label, e.g. 'Potential Viral Product'
    kpi           TEXT,                                 -- KPI label, e.g. 'Conversion Rate +15%'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One rule per key (lets us upsert metadata safely).
CREATE UNIQUE INDEX IF NOT EXISTS rules_tags_rule_name_uniq ON rules_tags (rule_name);

-- Seed / upsert the rules. rule_name is the stable snake_case key the CMS uses
-- to look up its static icon/gradient; display_name is what users see.
INSERT INTO rules_tags (rule_name, display_name, kpi) VALUES
    ('potential_viral_product',      'Potential Viral Product',              'Conversion Rate +15%'),
    ('inventory_clearance_candidate','Inventory Clearance Candidate',        'Inventory Turnover +25%'),
    ('hidden_gem_product',           'Hidden Gem Product',                   'ROAS +30%'),
    ('high_attention_low_purchase',  'High Attention, Low Purchase Product', 'Add-to-Cart Rate +20%'),
    ('shopping_basket_magnet',       'Shopping Basket Magnet',               'Basket Size +18%'),
    ('customer_loyalty_favorite',    'Customer Loyalty Favorite',            'Repeat Rate +20%'),
    ('profit_protection_product',    'Profit Protection Product',            'Gross Margin >50%'),
    ('user_engagement_leader',       'User Engagement Leader',               'Dwell Time'),
    ('new_product_momentum',         'New Product Momentum',                 'New Customer +20%')
ON CONFLICT (rule_name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    kpi          = EXCLUDED.kpi,
    updated_at   = NOW();

-- Retire the seasonal/trending rule (removed from the product).
DELETE FROM rules_tags WHERE rule_name = 'seasonal_trending_product';

-- ----------------------------------------------------------------------------
-- 2) AI response log: one row per /chat run.
--    Captures which rule ran, for which company, the step-by-step calculation
--    log, the AI response (reason + KPI + matched products), and the AI token
--    spend for the run.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_rule_responses (
    id               SERIAL PRIMARY KEY,
    rule_id          INTEGER REFERENCES rules_tags(id) ON DELETE SET NULL,
    rule_name        TEXT,                              -- denormalized for easy reading
    company_id       INTEGER,                           -- store the run was scoped to
    calculation_log  TEXT,                              -- step-by-step calc (from calc_log.py)
    ai_reason        TEXT,                              -- AI / rule reason text
    kpi_target       TEXT,                              -- KPI target for this run
    matched_count    INTEGER NOT NULL DEFAULT 0,        -- how many products qualified
    top_products     JSONB,                             -- full top_products payload
    token_usage      JSONB,                             -- AI tokens spent on this run (per-call + totals)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ai_rule_responses_rule_id_idx    ON ai_rule_responses (rule_id);
CREATE INDEX IF NOT EXISTS ai_rule_responses_company_id_idx ON ai_rule_responses (company_id);
CREATE INDEX IF NOT EXISTS ai_rule_responses_created_at_idx ON ai_rule_responses (created_at);

-- ----------------------------------------------------------------------------
-- 3) Keep updated_at fresh on UPDATE for both tables.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_rules_tags_updated_at ON rules_tags;
CREATE TRIGGER trg_rules_tags_updated_at
    BEFORE UPDATE ON rules_tags
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_ai_rule_responses_updated_at ON ai_rule_responses;
CREATE TRIGGER trg_ai_rule_responses_updated_at
    BEFORE UPDATE ON ai_rule_responses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

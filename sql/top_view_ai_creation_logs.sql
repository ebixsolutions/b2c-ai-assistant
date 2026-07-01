-- ─────────────────────────────────────────────────────────────────────────────
-- top_view_ai_creation_logs  (v3 — one row per video creation session)
--
-- Each video ad creation = ONE row, updated as each step completes.
-- Steps in order: generate_prompt → generate (video) → identify_segments → banner
--
-- v3 changes vs v2:
--   • Gemini token logging slimmed to a single total per step
--     (dropped prompt_completion_tokens / prompt_thinking_tokens).
--   • Added per-stage status for the segment step (segment_status).
--   • Columns regrouped in logical stage order; credit columns sit with their stage.
--
-- Runnable as-is (local or server). Drops any existing table first — there is no
-- production data to preserve, the logger lives only in this table.
-- ─────────────────────────────────────────────────────────────────────────────

-- gen_random_uuid() is built into Postgres 13+, but on older servers it lives in
-- the pgcrypto extension. Enable it first so the log_id DEFAULT works everywhere.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP TABLE IF EXISTS top_view_ai_creation_logs;

CREATE TABLE top_view_ai_creation_logs (
    id                          BIGSERIAL PRIMARY KEY,

    -- Session key — returned to frontend on generate_prompt, passed back in all subsequent calls
    log_id                      UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,

    company_id                  INT,
    gemini_model                VARCHAR(100),
    market_category             VARCHAR(100),
    ad_style                    VARCHAR(100),

    -- ── Step 1: Gemini prompt generation ─────────────────────────────────────
    prompt_total_tokens         INT,           -- totalTokenCount (billable total)
    prompt_status               VARCHAR(20),   -- 'success' | 'error' | 'skipped'

    -- ── Step 2: TopView video generation ──────────────────────────────────────
    video_task_id               VARCHAR(150),
    video_duration_seconds      INT,
    video_status                VARCHAR(20),   -- 'submitted' | 'success' | 'fail'
    video_topview_credits       NUMERIC(10,3), -- costCredit from omni_reference/task/query on success

    -- ── Step 3: Gemini segment identification (optional) ──────────────────────
    segment_total_tokens        INT,           -- totalTokenCount from identify_segments call
    segment_status              VARCHAR(20),   -- 'success' | 'error'

    -- ── Step 4a: Gemini banner frame picker ────────────────────────────────────
    banner_picker_total_tokens  INT,           -- sum of totalTokenCount across all batch Gemini calls
    banner_picker_status        VARCHAR(20),   -- 'success' | 'error'

    -- ── Step 4b: TopView banner (GPT Image 2 image_edit) ──────────────────────
    banner_task_id              VARCHAR(150),
    banner_status               VARCHAR(20),   -- 'submitted' | 'success' | 'error'
    banner_topview_credits      NUMERIC(10,3), -- costCredit from image_edit/task/query on success

    -- ── Overall ───────────────────────────────────────────────────────────────
    overall_status              VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    error_message               TEXT,          -- exact reason of the failing stage

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS tvaicl_log_id_idx    ON top_view_ai_creation_logs (log_id);
CREATE INDEX IF NOT EXISTS tvaicl_company_idx   ON top_view_ai_creation_logs (company_id);
CREATE INDEX IF NOT EXISTS tvaicl_task_id_idx   ON top_view_ai_creation_logs (video_task_id);
CREATE INDEX IF NOT EXISTS tvaicl_created_idx   ON top_view_ai_creation_logs (created_at DESC);

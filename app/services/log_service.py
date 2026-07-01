"""AI usage logging service — one row per video creation session.

Flow:
  1. generate_prompt   → create_log()               → INSERT row, return log_id
  2. generate (video)  → update_log_video()         → UPDATE: video task submitted
  3. task_status       → update_log_video_result()  → UPDATE: video success/fail (+credit, +error)
  4. identify_segments → update_log_segments()      → UPDATE: segment tokens (+status/error)
  5. banner (preview)  → update_log_banner_picker() → UPDATE: banner_picker tokens += N (+status/error)
  6. banner (final)    → update_log_banner_topview()→ UPDATE: banner task success/fail (+credit, +error)

Any stage failure → mark_stage_error() (or the stage's own update fn) records the stage
status = 'error', overall_status = 'error', and the exact reason in error_message.

All errors are swallowed — logging must never break the main flow.
"""
import logging

from sqlalchemy import text

from ..db import SessionLocal

logger = logging.getLogger("b2c.log_service")

# stage name → its status column in the table
_STAGE_STATUS_COL = {
    "prompt":        "prompt_status",
    "video":         "video_status",
    "segment":       "segment_status",
    "banner_picker": "banner_picker_status",
    "banner":        "banner_status",
}


def _exec(sql: str, params: dict) -> None:
    try:
        db = SessionLocal()
        try:
            db.execute(text(sql), params)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("log_service DB error (non-fatal): %s", exc)


def create_log(
    *,
    company_id: int | None,
    gemini_model: str | None,
    market_category: str | None,
    ad_style: str | None,
    prompt_total_tokens: int | None,
    prompt_status: str,
    error_message: str | None = None,
) -> str | None:
    """INSERT a new session row. Returns the log_id UUID string, or None on error."""
    try:
        db = SessionLocal()
        try:
            row = db.execute(
                text("""
                    INSERT INTO top_view_ai_creation_logs (
                        company_id, gemini_model, market_category, ad_style,
                        prompt_total_tokens, prompt_status,
                        overall_status, error_message
                    ) VALUES (
                        :company_id, :gemini_model, :market_category, :ad_style,
                        :prompt_total_tokens, :prompt_status,
                        :overall_status, :error_message
                    )
                    RETURNING log_id
                """),
                {
                    "company_id":           company_id,
                    "gemini_model":          gemini_model,
                    "market_category":       market_category,
                    "ad_style":              ad_style,
                    "prompt_total_tokens":   prompt_total_tokens,
                    "prompt_status":         prompt_status,
                    "overall_status":        "error" if prompt_status == "error" else "in_progress",
                    "error_message":         error_message,
                },
            )
            db.commit()
            result = row.fetchone()
            return str(result[0]) if result else None
        finally:
            db.close()
    except Exception as exc:
        logger.warning("create_log failed (non-fatal): %s", exc)
        return None


def mark_stage_error(log_id: str | None, *, stage: str, message: str | None) -> None:
    """Record a failure for `stage`: set its status='error', overall_status='error',
    and store the reason. Used for failures that don't have a dedicated update fn
    (e.g. video-submit, banner upload/submit, crashes)."""
    if not log_id:
        return
    col = _STAGE_STATUS_COL.get(stage)
    if not col:
        return
    _exec(
        f"""
        UPDATE top_view_ai_creation_logs
        SET {col} = 'error',
            overall_status = 'error',
            error_message = COALESCE(:message, error_message),
            updated_at = NOW()
        WHERE log_id = CAST(:log_id AS uuid)
        """,
        {"log_id": log_id, "message": message},
    )


def update_log_video(
    log_id: str | None,
    *,
    video_task_id: str,
    video_duration_seconds: int | None,
) -> None:
    if not log_id:
        return
    _exec(
        """
        UPDATE top_view_ai_creation_logs
        SET video_task_id = :video_task_id,
            video_duration_seconds = :video_duration_seconds,
            video_status = 'submitted',
            updated_at = NOW()
        WHERE log_id = CAST(:log_id AS uuid)
        """,
        {
            "log_id": log_id,
            "video_task_id": video_task_id,
            "video_duration_seconds": video_duration_seconds,
        },
    )


def update_log_video_result(
    task_id: str | None,
    *,
    status: str,
    error_message: str | None = None,
    credits: float | None = None,
) -> None:
    """Finalize the video stage from task_status polling (keyed on video_task_id).
    status: 'success' | 'fail'. Credit is written once (COALESCE keeps the first)."""
    if not task_id or status not in ("success", "fail"):
        return
    _exec(
        """
        UPDATE top_view_ai_creation_logs
        SET video_status = :status,
            video_topview_credits = COALESCE(:credits, video_topview_credits),
            error_message = CASE WHEN :status = 'fail'
                                 THEN COALESCE(:error_message, error_message)
                                 ELSE error_message END,
            overall_status = CASE WHEN :status = 'fail' THEN 'error' ELSE overall_status END,
            updated_at = NOW()
        WHERE video_task_id = :task_id
        """,
        {
            "task_id": task_id,
            "status": status,
            "credits": float(credits) if credits is not None else None,
            "error_message": error_message,
        },
    )


def update_log_segments(
    log_id: str | None,
    *,
    total_tokens: int | None,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    if not log_id:
        return
    _exec(
        """
        UPDATE top_view_ai_creation_logs
        SET segment_total_tokens = :total_tokens,
            segment_status = :status,
            error_message = CASE WHEN :status = 'error'
                                 THEN COALESCE(:error_message, error_message)
                                 ELSE error_message END,
            overall_status = CASE WHEN :status = 'error' THEN 'error' ELSE overall_status END,
            updated_at = NOW()
        WHERE log_id = CAST(:log_id AS uuid)
        """,
        {"log_id": log_id, "total_tokens": total_tokens, "status": status, "error_message": error_message},
    )


def update_log_banner_picker(
    log_id: str | None,
    *,
    total_tokens: int | None,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """Accumulate banner picker tokens across multiple batch preview calls."""
    if not log_id:
        return
    _exec(
        """
        UPDATE top_view_ai_creation_logs
        SET banner_picker_total_tokens = COALESCE(banner_picker_total_tokens, 0) + COALESCE(:total_tokens, 0),
            banner_picker_status = :status,
            error_message = CASE WHEN :status = 'error'
                                 THEN COALESCE(:error_message, error_message)
                                 ELSE error_message END,
            overall_status = CASE WHEN :status = 'error' THEN 'error' ELSE overall_status END,
            updated_at = NOW()
        WHERE log_id = CAST(:log_id AS uuid)
        """,
        {"log_id": log_id, "total_tokens": total_tokens, "status": status, "error_message": error_message},
    )


def update_log_banner_topview(
    log_id: str | None,
    *,
    banner_task_id: str | None,
    banner_status: str,
    error_message: str | None = None,
    banner_credits: float | None = None,
) -> None:
    if not log_id:
        return
    _exec(
        """
        UPDATE top_view_ai_creation_logs
        SET banner_task_id = COALESCE(:banner_task_id, banner_task_id),
            banner_status = :banner_status,
            banner_topview_credits = COALESCE(:banner_credits, banner_topview_credits),
            overall_status = CASE WHEN :banner_status = 'success'        THEN 'success'
                                  WHEN :banner_status IN ('error','fail') THEN 'error'
                                  ELSE overall_status END,
            error_message = COALESCE(:error_message, error_message),
            updated_at = NOW()
        WHERE log_id = CAST(:log_id AS uuid)
        """,
        {
            "log_id": log_id,
            "banner_task_id": banner_task_id,
            "banner_status": banner_status,
            "banner_credits": float(banner_credits) if banner_credits is not None else None,
            "error_message": error_message,
        },
    )

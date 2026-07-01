"""AI video + banner controller — ports TopViewAiImageAndVideoController.php to Python.

All endpoints return HTTP 200. Frontend checks the 'code' field: 0 = success, 1 = error.
"""
import base64
import os
import io
import json
import logging
import re
import time
from datetime import datetime, timezone

import requests
import urllib3
from fastapi import UploadFile
from fastapi.responses import Response

from ..services import topview_service, gemini_service, log_service
from sqlalchemy.orm import Session
from sqlalchemy import text

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("b2c.ai_video")

# ── Response helpers ────────────────────────────────────────────────────────

def _ok(data: dict) -> dict:
    return {"status": 200, "code": 0, "msg": "success", "data": data, "tip": "success"}


def _err(msg: str) -> dict:
    return {"status": 200, "code": 1, "msg": msg, "data": None, "tip": "error"}


def get_config() -> dict:
    return _ok({"default_duration": int(os.getenv("AI_VIDEO_DEFAULT_DURATION", 5))})


# ── Internal helpers ────────────────────────────────────────────────────────

def _upload_images_to_topview(images_base64: list[str]) -> list[str]:
    """Upload a list of base64 images to TopView S3. Returns file IDs."""
    file_ids = []
    for b64 in images_base64:
        try:
            if not b64:
                continue
            m = re.match(r"^data:image/(\w+);base64,(.+)$", b64, re.DOTALL)
            if m:
                fmt    = "jpg" if m.group(1).lower() == "jpeg" else m.group(1).lower()
                binary = base64.b64decode(m.group(2))
            else:
                fmt    = "jpg"
                binary = base64.b64decode(b64)

            cred = topview_service.get_upload_credential(fmt)
            if cred["code"] != 0 or not cred["data"]["result"].get("uploadUrl"):
                logger.error("TopView upload credential failed: %s", cred)
                continue

            file_id    = cred["data"]["result"]["fileId"]
            upload_url = cred["data"]["result"]["uploadUrl"]

            if topview_service.upload_binary_to_s3(upload_url, binary):
                file_ids.append(file_id)
            else:
                logger.error("S3 upload failed for fileId: %s", file_id)
        except Exception as exc:
            logger.error("upload_images_to_topview: %s", exc)
    return file_ids


def _decode_base64_image(b64: str) -> tuple[str, bytes]:
    """Return (format, binary) from a data-URI or raw base64 string."""
    m = re.match(r"^data:image/(\w+);base64,(.+)$", b64, re.DOTALL)
    if m:
        fmt    = "jpg" if m.group(1).lower() == "jpeg" else m.group(1).lower()
        binary = base64.b64decode(m.group(2))
    else:
        fmt    = "jpg"
        binary = base64.b64decode(b64)
    return fmt, binary


# ── Endpoint handlers ───────────────────────────────────────────────────────

def generate(params: dict) -> dict:
    """POST /ai_video/generate — upload images and submit omni reference video task."""
    try:
        animation_prompt = (params.get("animation_prompt") or "").strip()
        if not animation_prompt:
            return _err("Animation prompt is required")

        # If user skipped generate_prompt (manual prompt or reused old), create the log row now
        log_id = (params.get("log_id") or "").strip()
        if not log_id:
            log_id = log_service.create_log(
                company_id=params.get("company_id"),
                gemini_model=os.getenv("MODEL", "gemini-2.5-flash"),
                market_category=params.get("market_category", ""),
                ad_style=params.get("ad_style", ""),
                prompt_total_tokens=None,
                prompt_status="skipped",
            ) or ""
            # Inject log_id into params so update_log_video can use it below
            params = {**params, "log_id": log_id}

        # Upload avatar → Image1
        avatar_b64 = params.get("avatar_image_base64", "")
        if not avatar_b64:
            return _err("Avatar image is required")
        avatar_ids = _upload_images_to_topview([avatar_b64])
        if not avatar_ids:
            return _err("Failed to upload avatar image")
        avatar_file_id = avatar_ids[0]
        logger.info("Avatar uploaded: %s", avatar_file_id)

        # Upload product images → Image2–Image5
        product_bases = [
            v for v in [
                params.get("product_image_base64",   ""),
                params.get("product_image_base64_2", ""),
                params.get("product_image_base64_3", ""),
                params.get("product_image_base64_4", ""),
            ] if v
        ]
        if not product_bases:
            return _err("At least one product image is required")
        product_file_ids = _upload_images_to_topview(product_bases)
        if not product_file_ids:
            return _err("Failed to upload product image")
        logger.info("Products uploaded: %s", product_file_ids)

        # Upload logo → last image slot (optional)
        logo_file_id = None
        logo_b64 = params.get("logo_image_base64", "")
        if logo_b64:
            logo_ids = _upload_images_to_topview([logo_b64])
            if logo_ids:
                logo_file_id = logo_ids[0]
                logger.info("Logo uploaded: %s", logo_file_id)

        import os
        duration            = int(os.getenv("AI_VIDEO_DEFAULT_DURATION", "5"))
        input_video_file_id = (params.get("input_video_file_id") or "").strip()

        # Auto-inject Video1 token if video template provided but missing from prompt
        if input_video_file_id and "<<<Video1>>>" not in animation_prompt:
            animation_prompt = "<<<Video1>>> " + animation_prompt

        # Build inputImages
        input_images = [{"fileId": avatar_file_id, "name": "Image1"}]
        slot = 2
        for fid in product_file_ids:
            input_images.append({"fileId": fid, "name": f"Image{slot}"})
            slot += 1
        if logo_file_id:
            input_images.append({"fileId": logo_file_id, "name": f"Image{slot}"})

        # Build inputVideos
        input_videos = []
        if input_video_file_id:
            input_videos.append({"fileId": input_video_file_id, "name": "Video1"})

        submit_params = {
            "model":           "Standard",
            "prompt":          animation_prompt,
            "inputImages":     input_images,
            "aspectRatio":     "9:16",
            "resolution":      1080,
            "duration":        duration,
            "generatingCount": 1,
            "internetSearch":  False,
            "noticeUrl":       "",
        }
        if input_videos:
            submit_params["inputVideos"] = input_videos

        logger.info("omni_reference submit params: %s", json.dumps(submit_params)[:500])
        _submit_start = datetime.now(timezone.utc)
        result = topview_service.omni_reference_submit(submit_params)
        logger.info("omni_reference submit response: %s", json.dumps(result)[:500])

        if result["code"] != 0:
            log_service.mark_stage_error(params.get("log_id"), stage="video", message=result["msg"])
            return _err(result["msg"])

        inner_code = result["data"].get("code", "200") if result.get("data") else "200"
        if str(inner_code) not in ("200", "0"):
            msg = (result["data"] or {}).get("message") or f"TopView task failed (code {inner_code})"
            log_service.mark_stage_error(params.get("log_id"), stage="video", message=msg)
            return _err(msg)

        data    = result.get("data") or {}
        res_obj = data.get("result") or data
        task_id = res_obj.get("taskId") or data.get("taskId")
        if not task_id:
            log_service.mark_stage_error(params.get("log_id"), stage="video", message="Video task submitted but no taskId returned")
            return _err("Video task submitted but no taskId returned")

        log_service.update_log_video(
            params.get("log_id"),
            video_task_id=task_id,
            video_duration_seconds=duration,
        )
        return _ok({"taskId": task_id})

    except Exception as exc:
        logger.error("generate: %s", exc)
        log_service.mark_stage_error(params.get("log_id"), stage="video", message=f"Video generation crashed: {exc}")
        return _err("Video generation failed. Please try again.")


def get_task_status(task_id: str) -> dict:
    """GET /ai_video/task_status?task_id="""
    try:
        if not task_id:
            return _err("task_id is required")

        result = topview_service.omni_reference_query(task_id)
        if result["code"] != 0:
            return _err(result["msg"])

        data      = result.get("data") or {}
        inner     = data.get("result") or data
        status    = inner.get("status", "")
        video_url = None
        cover_url = None

        if status == "success":
            videos = inner.get("videos", [])
            if videos:
                video_url = videos[0].get("filePath")
                cover_url = videos[0].get("coverPath")
            cost_credit = inner.get("costCredit")
            log_service.update_log_video_result(
                task_id,
                status="success",
                credits=float(cost_credit) if cost_credit is not None else None,
            )
        elif status in ("fail", "failed", "error"):
            err = inner.get("errorMsg") or inner.get("message") or inner.get("msg") or "Video generation failed"
            log_service.update_log_video_result(task_id, status="fail", error_message=err)

        return _ok({**inner, "video_url": video_url, "cover_url": cover_url})

    except Exception as exc:
        logger.error("get_task_status: %s", exc)
        return _err(str(exc))




def generate_prompt(params: dict) -> dict:
    """POST /ai_video/generate_prompt — call Gemini to build an animation prompt."""
    import os
    try:
        gemini_params = {
            "market_category":           params.get("market_category", "general"),
            "ad_style":                  params.get("ad_style", "Energetic & Dynamic"),
            "duration":                  int(os.getenv("AI_VIDEO_DEFAULT_DURATION", "5")),
            "bgm":                       params.get("bgm", "cinematic"),
            "voice":                     params.get("voice", "warm_female"),
            "product_image_base64":      params.get("product_image_base64", ""),
            "product_image_base64_2":    params.get("product_image_base64_2", ""),
            "product_image_base64_3":    params.get("product_image_base64_3", ""),
            "product_image_base64_4":    params.get("product_image_base64_4", ""),
            "avatar_image_base64":       params.get("avatar_image_base64", ""),
            "video_template_frame_base64": params.get("video_template_frame_base64", ""),
            "has_avatar":                int(params.get("has_avatar", 0)),
            "has_video_template":        int(params.get("has_video_template", 0)),
            "template_name":             params.get("template_name", ""),
        }

        _prompt_start = datetime.now(timezone.utc)
        result = gemini_service.generate_animation_prompt(gemini_params)
        usage = result.get("usage") or {}
        log_id = log_service.create_log(
            company_id=params.get("company_id"),
            gemini_model=os.getenv("MODEL", "gemini-2.5-flash"),
            market_category=params.get("market_category", "general"),
            ad_style=params.get("ad_style", ""),
            prompt_total_tokens=usage.get("total_tokens"),
            prompt_status="success" if result["code"] == 0 else "error",
            error_message=None if result["code"] == 0 else result.get("msg"),
        )
        if result["code"] != 0:
            return _err(result["msg"])

        insights = {k: v for k, v in {
            "avatar":    result.get("avatar_analysis"),
            "product":   result.get("product_analysis"),
            "archetype": result.get("archetype_used"),
            "language":  result.get("detected_language"),
            "voice":     result.get("voice_character"),
        }.items() if v}

        return _ok({
            "prompt":   result["prompt"],
            "insights": insights or None,
            "log_id":   log_id,
        })

    except Exception as exc:
        logger.error("generate_prompt: %s", exc)
        return _err("Prompt generation failed. Please try again.")


def upload_credential(fmt: str) -> dict:
    """GET /ai_video/upload_credential?format=mp4"""
    try:
        result = topview_service.get_upload_credential(fmt.lower())
        if result["code"] != 0:
            return _err(result["msg"])
        data = (result.get("data") or {}).get("result", {})
        return _ok(data)
    except Exception as exc:
        logger.error("upload_credential: %s", exc)
        return _err(str(exc))


def upload_video_template(file: UploadFile) -> dict:
    """POST /ai_video/upload_video_template — upload a video file to TopView S3."""
    import os, tempfile
    try:
        if not file or not file.filename:
            return _err("No video file provided")

        content_type = file.content_type or ""
        if "webm" in content_type:
            fmt = "webm"
        elif "quicktime" in content_type or "mov" in content_type:
            fmt = "mov"
        else:
            fmt = "mp4"

        # Stream to a temp file first
        binary = file.file.read()
        file_size = len(binary)

        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{fmt}") as tmp:
            tmp.write(binary)
            tmp_path = tmp.name

        try:
            cred = topview_service.get_upload_credential(fmt)
            if cred["code"] != 0 or not (cred.get("data") or {}).get("result", {}).get("uploadUrl"):
                tv_msg = cred.get("msg", "unknown error")
                logger.error("upload_video_template: credential failed: %s", cred)
                return _err(f"TopView upload credential failed ({fmt}): {tv_msg}")

            file_id    = cred["data"]["result"]["fileId"]
            upload_url = cred["data"]["result"]["uploadUrl"]

            ok = topview_service.upload_file_to_s3(upload_url, tmp_path, file_size)
            if not ok:
                logger.error("upload_video_template: S3 upload failed for fileId: %s", file_id)
                return _err("Failed to upload video to storage")

            logger.info("upload_video_template: success fileId: %s", file_id)
            return _ok({"fileId": file_id})
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except Exception as exc:
        logger.error("upload_video_template: %s", exc)
        return _err("Template upload failed. Please try again.")


def identify_segments(params: dict) -> dict:
    """POST /ai_video/identify_segments — Gemini text call to rank best banner segments."""
    try:
        animation_prompt = (params.get("animation_prompt") or "").strip()
        if not animation_prompt:
            return _err("animation_prompt is required")
        category = (params.get("category") or "").strip()
        result = gemini_service.identify_best_segments(animation_prompt, category)
        log_service.update_log_segments(
            params.get("log_id"),
            total_tokens=(result.get("usage") or {}).get("total_tokens"),
            status="success" if result["code"] == 0 else "error",
            error_message=None if result["code"] == 0 else result.get("msg"),
        )
        if result["code"] != 0:
            return _err(result["msg"])
        return _ok({"segments": result["segments"]})
    except Exception as exc:
        logger.error("identify_segments: %s", exc)
        return _err("Segment identification failed. Please try again.")


def generate_banner(params: dict) -> dict:
    """POST /ai_video/generate_banner — full banner pipeline: frame → Gemini → TopView GPT Image 2."""
    try:
        mode     = params.get("mode", "generate")
        logo_b64 = (params.get("logo_image_base64") or "").strip()

        edit_prompt = None
        best_frame  = None
        text_specs  = None

        # ── Precomputed path (batch winner from frontend) ──
        precomputed_frame  = (params.get("precomputed_frame")  or "").strip()
        precomputed_prompt = (params.get("precomputed_prompt") or "").strip()
        precomputed_specs  = params.get("precomputed_text_specs")
        if isinstance(precomputed_specs, str):
            try:
                precomputed_specs = json.loads(precomputed_specs)
            except Exception:
                precomputed_specs = None

        if precomputed_frame and precomputed_prompt:
            edit_prompt = precomputed_prompt
            best_frame  = precomputed_frame
            text_specs  = precomputed_specs
            logger.info("Banner: using precomputed batch-winner frame + prompt (skipping Gemini)")
        else:
            # ── Step 1: collect video frames ──
            video_frames = []
            frames_raw   = params.get("video_frames", [])
            if isinstance(frames_raw, str):
                try:
                    frames_raw = json.loads(frames_raw)
                except Exception:
                    frames_raw = []
            for f in (frames_raw or []):
                if f:
                    video_frames.append(f)

            contact_sheet = (params.get("contact_sheet") or "").strip()

            # Fallback: download cover thumbnail
            if not video_frames:
                cover_url = (params.get("cover_url") or "").strip()
                if cover_url:
                    try:
                        resp = requests.get(
                            cover_url, timeout=30, verify=False,
                            headers={"User-Agent": "Mozilla/5.0"},
                            allow_redirects=True,
                        )
                        if 200 <= resp.status_code < 300 and resp.content:
                            img_b64 = "data:image/jpeg;base64," + base64.b64encode(resp.content).decode()
                            video_frames.append(img_b64)
                            contact_sheet = img_b64
                    except Exception as e:
                        logger.error("Banner: cover download failed: %s", e)

            if not video_frames or not contact_sheet:
                return _err("No video frames available — please generate a video first")

            logger.info("Banner frames: %d | mode: %s", len(video_frames), mode)

            # ── Step 2: Gemini picks best cell + writes GPT Image 2 prompt ──
            prompt_result = gemini_service.build_banner_imagen_prompt({
                "contact_sheet":       contact_sheet,
                "frame_count":         len(video_frames),
                "category":            params.get("category", "General Advertising"),
                "ad_style":            params.get("ad_style", ""),
                "has_logo":            bool(logo_b64),
                "is_product_fallback": bool(params.get("is_product_fallback")),
            })
            log_service.update_log_banner_picker(
                params.get("log_id"),
                total_tokens=(prompt_result.get("usage") or {}).get("total_tokens"),
                status="success" if prompt_result["code"] == 0 else "error",
                error_message=None if prompt_result["code"] == 0 else prompt_result.get("msg"),
            )
            if prompt_result["code"] != 0:
                return _err(f"Banner prompt failed: {prompt_result['msg']}")

            edit_prompt     = prompt_result["imagen_prompt"]
            best_idx        = int(prompt_result.get("best_frame_index") or 0)
            best_frame      = (
                video_frames[best_idx]
                if 0 <= best_idx < len(video_frames)
                else video_frames[len(video_frames) // 2]
            )
            text_specs      = prompt_result.get("text_specs")
            quality         = prompt_result.get("quality", "none")
            person_visible  = prompt_result.get("person_visible", True)
            product_visible = prompt_result.get("product_visible", True)

            logger.info(
                "Banner frame #%d | quality: %s | person: %s | product: %s | mode: %s",
                best_idx, quality,
                "yes" if person_visible else "NO",
                "yes" if product_visible else "NO",
                mode,
            )

            if mode == "preview":
                return _ok({
                    "quality":          quality,
                    "best_frame_score": prompt_result.get("best_frame_score"),
                    "person_visible":   person_visible,
                    "product_visible":  product_visible,
                    "best_frame_index": best_idx,
                    "frame_data":       best_frame,
                    "imagen_prompt":    edit_prompt,
                    "text_specs":       text_specs,
                    "usage":            prompt_result.get("usage"),
                })

        # ── Steps 3-6: upload → submit → poll (with safety retry) ──
        banner_url = None
        banner_error_logged = False   # set when a stage already recorded the real failure reason

        product_fallbacks = list(dict.fromkeys(
            v for v in [
                params.get("product_image_base64",   ""),
                params.get("product_image_base64_2", ""),
                params.get("product_image_base64_3", ""),
                params.get("product_image_base64_4", ""),
            ] if v
        ))
        max_attempts = 1 + len(product_fallbacks)

        for attempt in range(max_attempts):
            if attempt > 0:
                fb = product_fallbacks[attempt - 1]
                if fb == best_frame:
                    continue
                best_frame = fb
                logger.info("Safety retry #%d: using product fallback", attempt)
                rp = gemini_service.build_banner_imagen_prompt({
                    "contact_sheet":       best_frame,
                    "frame_count":         1,
                    "category":            params.get("category", "General Advertising"),
                    "ad_style":            params.get("ad_style", ""),
                    "has_logo":            bool(logo_b64),
                    "is_product_fallback": True,
                })
                if rp["code"] == 0:
                    edit_prompt = rp["imagen_prompt"]
                    text_specs  = rp.get("text_specs") or text_specs

            # Step 3: upload best frame
            frame_fmt, frame_binary = _decode_base64_image(best_frame)
            frame_cred = topview_service.get_upload_credential(frame_fmt)
            if frame_cred["code"] != 0 or not (frame_cred.get("data") or {}).get("result", {}).get("uploadUrl"):
                log_service.mark_stage_error(params.get("log_id"), stage="banner", message="Failed to get upload credential for frame")
                return _err("Failed to get upload credential for frame")
            frame_file_id = frame_cred["data"]["result"]["fileId"]
            if not topview_service.upload_binary_to_s3(frame_cred["data"]["result"]["uploadUrl"], frame_binary):
                log_service.mark_stage_error(params.get("log_id"), stage="banner", message="Failed to upload frame to TopView")
                return _err("Failed to upload frame to TopView")
            logger.info("Frame uploaded: %s%s", frame_file_id, " [retry]" if attempt > 0 else "")

            input_file_ids = [frame_file_id]

            # Step 4: upload logo (optional)
            if logo_b64:
                logo_fmt, logo_binary = _decode_base64_image(logo_b64)
                logo_cred = topview_service.get_upload_credential(logo_fmt)
                if logo_cred["code"] == 0 and (logo_cred.get("data") or {}).get("result", {}).get("uploadUrl"):
                    logo_file_id = logo_cred["data"]["result"]["fileId"]
                    if topview_service.upload_binary_to_s3(logo_cred["data"]["result"]["uploadUrl"], logo_binary):
                        input_file_ids.append(logo_file_id)
                        logger.info("Logo uploaded: %s", logo_file_id)

            # Step 5: submit GPT Image 2 task
            _edit_start = datetime.now(timezone.utc)
            edit_result = topview_service.image_edit_submit({
                "model":             "GPT Image 2",
                "prompt":            edit_prompt,
                "inputImageFileIds": input_file_ids,
                "aspectRatio":       "9:16",
                "generateCount":     1,
                "resolution":        "2K",
                "inputFidelity":     "high",
                "noticeUrl":         "",
            })
            if edit_result["code"] != 0:
                log_service.mark_stage_error(params.get("log_id"), stage="banner", message=f"Image edit submit failed: {edit_result['msg']}")
                return _err(f"Image edit submit failed: {edit_result['msg']}")

            inner_code = (edit_result.get("data") or {}).get("code", "200")
            if str(inner_code) not in ("200", "0"):
                msg = (edit_result.get("data") or {}).get("message") or f"Image edit submit failed (inner code {inner_code})"
                logger.error("Image edit inner error: %s", edit_result.get("data"))
                log_service.mark_stage_error(params.get("log_id"), stage="banner", message=msg)
                return _err(msg)

            data    = edit_result.get("data") or {}
            res_obj = data.get("result") or data
            task_id = res_obj.get("taskId") or data.get("taskId")
            if not task_id:
                logger.error("Image edit no taskId: %s", data)
                log_service.mark_stage_error(params.get("log_id"), stage="banner", message="No taskId returned from image edit")
                return _err("No taskId returned from image edit")
            logger.info("Image edit taskId: %s", task_id)

            # Step 6: poll until done
            safety_triggered = False
            for i in range(30):
                time.sleep(3)
                poll = topview_service.image_edit_query(task_id)
                if poll["code"] != 0:
                    continue

                r      = (poll.get("data") or {}).get("result") or poll.get("data") or {}
                status = r.get("status", "")
                logger.info("Banner poll %d%s: %s", i + 1, f" [retry #{attempt}]" if attempt > 0 else "", status)

                if status == "success":
                    images = r.get("images") or r.get("outputImages") or r.get("videos") or []
                    banner_url = (
                        images[0].get("filePath")
                        or images[0].get("url")
                        or images[0].get("videoUrl")
                    ) if images else None
                    cost_credit = r.get("costCredit")
                    log_service.update_log_banner_topview(
                        params.get("log_id"),
                        banner_task_id=task_id,
                        banner_status="success",
                        banner_credits=float(cost_credit) if cost_credit is not None else None,
                    )
                    break

                if status in ("fail", "failed", "error"):
                    raw_error = r.get("errorMsg") or r.get("message") or r.get("msg") or ""
                    logger.error("Banner poll failed: %s", r)
                    log_service.update_log_banner_topview(
                        params.get("log_id"),
                        banner_task_id=task_id,
                        banner_status="error",
                        error_message=raw_error or "Banner generation failed (TopView returned an error)",
                    )
                    banner_error_logged = True
                    if any(kw in raw_error.lower() for kw in ("safety", "sexual", "rejected")):
                        safety_triggered = True
                    break

            if banner_url:
                break

            if safety_triggered:
                next_fb = product_fallbacks[attempt] if attempt < len(product_fallbacks) else None
                if next_fb and next_fb != best_frame:
                    logger.info("Safety rejection — trying next product fallback")
                    continue
                safety_msg = (
                    "The selected frame was flagged by the safety filter and all product image fallbacks "
                    "were also blocked. Please try a different product image or video."
                )
                log_service.update_log_banner_topview(
                    params.get("log_id"),
                    banner_task_id=None,
                    banner_status="error",
                    error_message=safety_msg,
                )
                return _err(safety_msg)
            break

        if not banner_url:
            if not banner_error_logged:
                # Genuine timeout — no stage recorded a specific reason. Don't clobber a real error.
                log_service.update_log_banner_topview(
                    params.get("log_id"),
                    banner_task_id=None,
                    banner_status="error",
                    error_message="Banner generation timed out",
                )
            return _err("Banner generation timed out — try again")

        logger.info("Banner ready: %s", banner_url)

        # Step 7: fetch binary and re-encode to JPEG data URL
        banner_data_url = None
        try:
            img_resp = requests.get(
                banner_url,
                timeout=30,
                verify=False,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True,
            )
            if 200 <= img_resp.status_code < 300 and img_resp.content:
                from PIL import Image
                try:
                    img = Image.open(io.BytesIO(img_resp.content))
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=92)
                    banner_data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
                except Exception:
                    ct   = (img_resp.headers.get("Content-Type") or "image/png").split(";")[0].strip().lower()
                    banner_data_url = f"data:{ct};base64," + base64.b64encode(img_resp.content).decode()
        except Exception as e:
            logger.error("Banner fetch/encode: %s", e)

        return _ok({
            "banner_url":      banner_url,
            "banner_data_url": banner_data_url,
            "text_specs":      text_specs,
        })

    except Exception as exc:
        logger.exception("generate_banner crashed")
        log_service.mark_stage_error(params.get("log_id"), stage="banner", message=f"Banner generation crashed: {exc}")
        return _err("Banner generation failed. Please try again.")


def download_proxy(url: str, filename: str) -> Response:
    """POST /ai_video/download_proxy — proxy CDN file through server (body: {url, filename})."""
    logger.info("download_proxy: url_len=%d filename=%s", len(url), filename)
    if not url:
        return Response(
            content=json.dumps({"code": 1, "msg": "url required"}),
            status_code=400,
            media_type="application/json",
        )

    # SSRF guard
    parsed_host = ""
    try:
        from urllib.parse import urlparse
        parsed_host = (urlparse(url).hostname or "").lower()
    except Exception:
        pass

    ok_suffixes = (".topview.ai", ".amazonaws.com", ".cloudfront.net", "topview.ai")
    allowed = any(
        parsed_host == s.lstrip(".") or parsed_host.endswith(s)
        for s in ok_suffixes
    )
    if not allowed:
        return Response(
            content=json.dumps({"code": 1, "msg": "URL not permitted"}),
            status_code=403,
            media_type="application/json",
        )

    safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename or "download.jpg")

    try:
        resp = requests.get(
            url, timeout=120, verify=False,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
    except Exception as e:
        return Response(
            content=json.dumps({"code": 1, "msg": f"Fetch error: {e}"}),
            status_code=502,
            media_type="application/json",
        )

    if resp.status_code < 200 or resp.status_code >= 300 or not resp.content:
        return Response(
            content=json.dumps({"code": 1, "msg": "Failed to fetch file"}),
            status_code=502,
            media_type="application/json",
        )

    ct = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip().lower()
    return Response(
        content=resp.content,
        status_code=200,
        media_type=ct or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length":      str(len(resp.content)),
            "Cache-Control":       "no-cache",
        },
    )

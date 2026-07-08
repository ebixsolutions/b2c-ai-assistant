"""AI video + banner routes — /ai_video prefix.

All endpoints return HTTP 200 with {"code": 0|1, ...}.
Sync handlers (def, not async def) run in FastAPI's threadpool — time.sleep() is fine.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..controllers import ai_video_controller

router = APIRouter(tags=["ai_video"])


@router.get("/config")
def get_config():
    return ai_video_controller.get_config()


@router.post("/generate")
def generate(body: dict, db: Session = Depends(get_db)):
    return ai_video_controller.generate(body)


@router.get("/task_status")
def get_task_status(task_id: str = Query(...)):
    return ai_video_controller.get_task_status(task_id)


@router.post("/generate_prompt")
def generate_prompt(body: dict):
    return ai_video_controller.generate_prompt(body)


@router.get("/upload_credential")
def upload_credential(format: str = Query(default="mp4")):
    return ai_video_controller.upload_credential(format)


@router.post("/upload_video_template")
def upload_video_template(video: UploadFile = File(...)):
    return ai_video_controller.upload_video_template(video)


@router.post("/identify_segments")
def identify_segments(body: dict):
    return ai_video_controller.identify_segments(body)


@router.post("/generate_banner")
def generate_banner(body: dict):
    return ai_video_controller.generate_banner(body)


@router.post("/generate_banner_submit")
def generate_banner_submit(body: dict):
    return ai_video_controller.generate_banner_submit(body)


@router.post("/banner_task_status")
def get_banner_task_status(body: dict):
    return ai_video_controller.get_banner_task_status(body)


@router.post("/download_proxy")
def download_proxy(body: dict):
    return ai_video_controller.download_proxy(
        body.get("url", ""),
        body.get("filename", "download.jpg"),
    )

"""Application bootstrap.

Wires up the FastAPI app: startup DB check, CORS, and the route modules.
All endpoint logic lives in routes/ -> controllers/ -> services/.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .db import engine, DB_HOST, DB_PORT, DB_NAME, DB_USER
from .routes.rules_routes import router as rules_router
from .routes.ai_video_routes import router as ai_video_router

logger = logging.getLogger("b2c")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s")

# Silence noisy third-party INFO chatter (Gemini AFC calls, raw HTTP requests).
for _noisy in ("google_genai", "google", "httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

app = FastAPI(title="B2C v1 — 10-Rule Recommendation Chatbot", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rules_router, prefix="/ai_assistant")
app.include_router(ai_video_router, prefix="/ai_assistant/topview_ai_video")


@app.get("/")
def welcome():
    return {"message": "b2c-ai-assistant backend is working.."}


@app.on_event("startup")
def _verify_db_connection() -> None:
    target = f"{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection successfully -> %s", target)
    except Exception as exc:
        logger.error("Database connection failed -> %s  (%s)", target, exc)

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)
 

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "b2c-v1")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

# Time-window multiplier for rule SQL (30d, 7d, 90d, today).
# Default is 1 — windows match the rule spec exactly (today = 1 day, 7d = 7 days, etc.).
# Only raise this (via WINDOW_MULT env var) when running against a stale demo snapshot
# where real-time windows would return no rows.
WINDOW_MULT = int(os.getenv("WINDOW_MULT", "1"))

PRODUCT_LIMIT = int(os.getenv("PRODUCT_LIMIT", "2"))

IS_AI_ENABLE = os.getenv("IS_AI_ENABLE", "False").lower() in ("true", "1", "yes")


def is_ai_enabled() -> bool:
    load_dotenv(ENV_PATH, override=True)
    return os.getenv("IS_AI_ENABLE", "False").lower() in ("true", "1", "yes")


def get_product_limit() -> int:
    load_dotenv(ENV_PATH, override=True)
    return int(os.getenv("PRODUCT_LIMIT", "2"))

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

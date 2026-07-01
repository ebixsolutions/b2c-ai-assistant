from typing import Any
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    company_id: int


class Product(BaseModel):
    rank: int
    item_id: int
    item_no: str | None = None
    name: str | None = None
    score: float | None = None
    score_10: float | None = None
    metric: dict[str, Any] = {}
    ai_reason: str | None = None
    image_url: str | None = None


class ChatResponse(BaseModel):
    tag: str
    tag_label: str
    kpi_target: str
    reason: str
    matched_count: int
    top_products: list[Product]


class Company(BaseModel):
    id: int
    name: str | None
    pixel_events: int
    sales_orders: int

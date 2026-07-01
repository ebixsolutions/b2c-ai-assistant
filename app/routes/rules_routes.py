"""Rules routes — /health, /rules-tags, /companies, /chat.
Thin endpoints that delegate to rules_controller."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ChatRequest, ChatResponse, Company
from ..controllers import rules_controller

router = APIRouter(tags=["rules"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    return rules_controller.health(db)


@router.get("/rules-tags")
def list_rules_tags(db: Session = Depends(get_db)):
    return rules_controller.list_rules_tags(db)


@router.get("/companies", response_model=list[Company])
def companies(db: Session = Depends(get_db)):
    return rules_controller.list_companies(db)


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    return rules_controller.chat(req, db)

"""Rules controller — orchestrates all chatbot endpoints (/health,
/rules-tags, /companies, /chat). Calls rules_service and maps its domain
errors to HTTP responses."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..schemas import ChatRequest, ChatResponse, Company
from ..services import rules_service
from ..services.rules_service import RuleNotMatched, RuleExecutionError


def health(db: Session) -> dict:
    return rules_service.check_health(db)


def list_rules_tags(db: Session) -> list[dict]:
    return rules_service.list_rules_tags(db)


def list_companies(db: Session) -> list[Company]:
    rows = rules_service.list_companies(db)
    return [Company(**r) for r in rows]


def chat(req: ChatRequest, db: Session) -> ChatResponse:
    try:
        result = rules_service.run_chat(db, req.message, req.company_id)
    except RuleNotMatched as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuleExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(**result)

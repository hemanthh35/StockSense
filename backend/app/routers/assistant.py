from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import ratelimit
from ..assistant import service, tools
from ..assistant.llm import LLMError, get_llm
from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import User

router = APIRouter(tags=["assistant"])


class Msg(BaseModel):
    role: Literal["user", "assistant"]  # the client can never inject system or tool messages
    content: Annotated[str, Field(min_length=1, max_length=4000)]


class ChatIn(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=20)


@router.get("/assistant/status")
def status(user: User = Depends(current_user), llm=Depends(get_llm)):
    return {"enabled": llm is not None, "model": settings.groq_model if llm else None,
            "can_write": [t.name for t in tools.tools_for(user) if t.writes]}


@router.post("/assistant/chat")
def chat(body: ChatIn, db: Session = Depends(get_db), user: User = Depends(current_user), llm=Depends(get_llm)):
    if llm is None:
        raise HTTPException(503, "The assistant isn't set up yet. An administrator needs to add a GROQ_API_KEY.")
    if body.messages[-1].role != "user":
        raise HTTPException(422, "The last message must be from you.")
    ratelimit.check(f"ai:{user.id}", limit=settings.assistant_rate_per_minute, window_seconds=60)
    try:
        return service.chat(db, user, llm, [m.model_dump() for m in body.messages])
    except LLMError as e:
        if e.status == 429:
            raise HTTPException(429, "The AI service is busy. Please try again in a moment.", headers={"Retry-After": "10"})
        raise HTTPException(502, "The AI service isn't answering right now. Please try again.")


@router.post("/assistant/actions/{action_id}/confirm")
def confirm(action_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.confirm(db, user, action_id)


@router.post("/assistant/actions/{action_id}/cancel")
def cancel(action_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.cancel(db, user, action_id)

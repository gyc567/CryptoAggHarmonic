"""Pydantic schemas for FT Strategy UI — Loop #13 endpoints."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateStrategyRequest(BaseModel):
    """POST /api/ft-strategies"""

    name: str = Field(min_length=1)
    research_md: str  # validated by validate_research_md (D-FT-21)
    idea_payload: dict = Field(default_factory=dict)
    market_type: Literal["futures"] = "futures"
    pair: str = "BTC/USDT"
    interval: str = "5m"
    idea_source: Literal["template", "natural_language", "clone"] = "template"
    description: Optional[str] = None


class RefineRequest(BaseModel):
    """POST /api/ft-strategies/:id/refine"""

    intended_event: Optional[Literal["evolve", "fork", "kill"]] = None

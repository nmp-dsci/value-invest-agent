from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["single", "multi", "macro", "other"]


class TickerRef(BaseModel):
    company: str
    yahoo_ticker: str = Field(
        description="Yahoo Finance symbol incl. exchange suffix, e.g. MC.PA, 0700.HK, BRK-B"
    )
    exchange: str | None = None
    is_primary: bool = True


class TitleLabel(BaseModel):
    video_id: str
    kind: Kind
    tickers: list[TickerRef] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""


class TitleLabelBatch(BaseModel):
    labels: list[TitleLabel]

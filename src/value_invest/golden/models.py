"""The GoldenEval schema (M2 spec §GoldenEval v1).

The extractor returns a ``GoldenEvalDraft`` from the transcript alone. Python
then derives ``position`` (rule C), fills every reason's ``data_check`` from
the point-in-time data, recomputes the valuation, runs the critic and stamps
provenance — that is a ``GoldenEval``. The model never sees market data."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

Position = Literal["BUY", "HOLD", "SELL"]
StanceDetail = Literal["absolute_buy", "relative_buy", "fair_hold", "avoid", "too_hard", "short"]
PersonalAction = Literal["buying", "holding", "watching", "none", "short"]
Category = Literal[
    "valuation",
    "growth",
    "capital_allocation",
    "balance_sheet",
    "moat",
    "cyclicality",
    "management",
    "macro_rates",
    "competence",
    "sentiment",
]
Feeds = Literal["base", "g_y1_5", "g_y6_10", "terminal", "probability", "discount", "none"]
Reproducible = Literal["statements", "prices", "derived", "external", "judgement"]
Method = Literal["eps_multiple", "dividend", "fcf", "net_income", "none"]


def _num(v: Any) -> Any:
    """Numbers the model writes as text ("12 %", "not stated", "n/a") → float or None."""
    if v is None or isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        t = v.strip().replace("%", "").replace(",", "").replace("$", "")
        try:
            return float(t)
        except ValueError:
            return None
    return v


class LenientNumbers(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_numbers(cls, v: Any, info: Any) -> Any:
        ann = (
            cls.model_fields[info.field_name].annotation
            if info.field_name in cls.model_fields
            else None
        )
        if ann is not None and "float" in str(ann) and "list" not in str(ann):
            return _num(v)
        return v


THREE_WAY: dict[str, Position] = {
    "absolute_buy": "BUY",
    "relative_buy": "BUY",
    "fair_hold": "HOLD",
    "avoid": "SELL",
    "too_hard": "SELL",
    "short": "SELL",
}
HURDLE_RETURN_PCT = 10.0  # his discount rate: "I expect a 10 % return"


def position_for(stance_detail: str) -> Position:
    """Rule C: BUY / HOLD / SELL from the 6-way stance."""
    return THREE_WAY[stance_detail]


def binary_for(stance_detail: str) -> Literal["BUY", "SELL"]:
    """Rule A, the original binary: anything that is not a buy is a sell."""
    return "BUY" if THREE_WAY[stance_detail] == "BUY" else "SELL"


def hurdle_for(expected_return_pct: float | None, stance_detail: str) -> Position | None:
    """Rule B: BUY when his own expected return at the price clears his 10 % hurdle."""
    if expected_return_pct is None:
        return None
    if expected_return_pct >= HURDLE_RETURN_PCT:
        return "BUY"
    return "SELL" if THREE_WAY[stance_detail] == "SELL" else "HOLD"


class MetricMention(LenientNumbers):
    """A number he cites for a reason, in his words — grounding maps it to a line item."""

    name: str = Field(
        description="what the number is, in plain words: eps, revenue growth, buyback yield, net debt …"
    )
    value: float | None = None
    unit: str | None = Field(
        default=None, description="usd | usd_bn | pct | ratio | per_share | years"
    )
    period: str | None = Field(default=None, description="e.g. FY2024, last quarter, TTM, 5 years")


class DataCheck(BaseModel):
    reproducible: Reproducible
    line_items: list[str] = Field(default_factory=list)
    value_stated: float | None = None
    value_as_of: float | None = None
    agrees: bool | None = None
    formula: str | None = None
    as_of_period: str | None = None
    gap_note: str | None = None


class Reason(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rank: int = Field(ge=1, le=6)
    direction: Literal["for_buy", "for_sell"]
    category: Category
    claim: str = Field(description="one sentence, his logic, no new facts")
    quote: str = Field(
        description="verbatim words from the transcript that carry the claim (≤ 40 words)"
    )
    chunk_id: str | None = Field(
        default=None, description="the [chunk …] marker the quote sits in, e.g. chunk:abc:3"
    )
    start_s: float | None = None
    feeds: Feeds = "none"
    metrics: list[MetricMention] = Field(default_factory=list)
    data_check: DataCheck | None = None

    @field_validator("feeds", mode="before")
    @classmethod
    def _feeds_known(cls, v: Any) -> Any:
        known = ("base", "g_y1_5", "g_y6_10", "terminal", "probability", "discount", "none")
        return v if v in known else "none"

    @field_validator("metrics", mode="before")
    @classmethod
    def _metrics_list(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return [
                {"name": k, "value": val} if not isinstance(val, dict) else {"name": k, **val}
                for k, val in v.items()
            ]
        return v or []


class BaseMetric(LenientNumbers):
    name: Literal["eps", "dps", "fcf_per_share", "net_income", "other"] = "other"
    value_stated: float | None = None
    quote: str = ""

    @field_validator("name", mode="before")
    @classmethod
    def _name_known(cls, v: Any) -> Any:
        if v in ("eps", "dps", "fcf_per_share", "net_income", "other"):
            return v
        t = str(v or "").lower()
        return (
            "eps"
            if "eps" in t or "earnings per share" in t
            else "dps"
            if "dividend" in t
            else "net_income"
            if "net income" in t
            else "fcf_per_share"
            if "cash flow" in t
            else "other"
        )

    @field_validator("quote", mode="before")
    @classmethod
    def _quote_str(cls, v: Any) -> Any:
        return v or ""


class Scenario(LenientNumbers):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: Literal["normal", "best", "worst"] = Field(
        validation_alias=AliasChoices("name", "scenario", "case")
    )
    g_y1_5: float | None = Field(default=None, description="fraction, 0.05 = 5 %")
    g_y6_10: float | None = None
    terminal_multiple: float | None = None
    probability: float | None = Field(default=None, description="fraction, 0.7 = 70 %")
    iv_stated: float | None = None
    quote: str = ""


class PricedIn(LenientNumbers):
    growth: float | None = None
    multiple: float | None = None
    quote: str = ""


class Valuation(LenientNumbers):
    model_config = ConfigDict(extra="ignore")

    method: Method = "none"
    base_metric: BaseMetric | None = None
    discount_rate: float | None = Field(
        default=None, description="fraction; his required return, usually 0.10"
    )
    payout_ratio: float | None = None
    scenarios: list[Scenario] = Field(default_factory=list)
    iv_weighted_stated: float | None = None
    price_mentioned: float | None = None
    what_is_priced_in: PricedIn | None = None

    @field_validator("base_metric", mode="before")
    @classmethod
    def _base_metric_optional(cls, v: Any) -> Any:
        if isinstance(v, dict) and v.get("name") is None and v.get("value_stated") is None:
            return None
        return v

    @field_validator("what_is_priced_in", mode="before")
    @classmethod
    def _priced_in_from_text(cls, v: Any) -> Any:
        # the model sometimes answers with a sentence instead of the object
        if isinstance(v, str):
            return PricedIn(quote=v) if v.strip() else None
        return v

    @field_validator("scenarios", mode="before")
    @classmethod
    def _scenarios_list(cls, v: Any) -> Any:
        if isinstance(v, dict):  # {"normal": {...}, "best": {...}}
            return [
                {"name": k, **(val or {})}
                for k, val in v.items()
                if k in ("normal", "best", "worst")
            ]
        return v or []


class Call(LenientNumbers):
    model_config = ConfigDict(extra="ignore")

    stance_detail: StanceDetail
    personal_action: PersonalAction = "none"
    expected_return_pct: float | None = Field(
        default=None, description="the yearly return he expects at the current price, in percent"
    )
    horizon_years: float | None = None
    conviction: Literal["low", "medium", "high"] = "medium"
    headline_quote: str = Field(description="the one sentence that states his conclusion, verbatim")


class GoldenEvalDraft(BaseModel):
    """What the extractor returns. No market data, no position: those are derived."""

    model_config = ConfigDict(extra="ignore")

    video_id: str
    ticker: str
    call: Call
    valuation: Valuation = Field(default_factory=Valuation)
    reasons: list[Reason] = Field(min_length=1, max_length=6)
    external_facts_used: list[str] = Field(
        default_factory=list,
        description="facts he cites that are not in financial statements or prices: consensus, guidance, segments, 13F, macro",
    )


class Critic(BaseModel):
    faithful: bool
    quotes_total: int = 0
    quotes_verbatim: int = 0
    position_agrees: bool
    own_stance_detail: StanceDetail
    invented_reasons: list[int] = Field(
        default_factory=list, description="ranks of reasons the transcript does not support"
    )
    notes: str = ""


class Provenance(BaseModel):
    extractor_version: str
    model: str
    session_id: str | None = None
    transcript_sha256: str
    extracted_at: str
    critic_model: str | None = None
    critic_session_id: str | None = None


class GoldenEval(BaseModel):
    """The checkpointed object: draft + derived position + grounding + critic + provenance."""

    video_id: str
    ticker: str
    t0: date
    title: str
    position: Position
    binary_position: Literal["BUY", "SELL"]
    hurdle_position: Position | None
    rule_sensitive: bool
    title_says_buy: bool
    call: Call
    valuation: Valuation
    iv_recomputed: dict[str, Any] = Field(default_factory=dict)
    price_at_t0: float | None = None
    reasons: list[Reason]
    external_facts_used: list[str] = Field(default_factory=list)
    critic: Critic | None = None
    checks: dict[str, Any] = Field(default_factory=dict)
    split: str
    provenance: Provenance
    curation_status: str = "auto"


TITLE_BUY_WORDS = ("buy", "2x", "cheap", "bargain", "undervalued")


def title_says_buy(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in TITLE_BUY_WORDS) and "not a buy" not in t and "sell" not in t

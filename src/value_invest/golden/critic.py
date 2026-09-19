"""Stage 4 — a second Agent SDK session checks the draft against the transcript.

Two jobs: faithfulness (are the quotes real, is any reason invented) and an
independent 6-way stance, which gives the inter-extractor κ the spec asks for.
The deterministic quote check (``transcript.find_quote``) runs in Python first
and is handed to the critic as context, so the model judges meaning, not
string matching."""

from __future__ import annotations

import json
from typing import Any

from value_invest.golden.models import Critic, GoldenEvalDraft, position_for
from value_invest.golden.transcript import Transcript, find_quote
from value_invest.llm import run_structured_sync

SYSTEM = """You audit a structured extraction from a Sven Carlin stock-video transcript. The transcript is the only truth.
Answer three questions and return ONLY a JSON object {faithful, quotes_total, quotes_verbatim, position_agrees, own_stance_detail, invented_reasons, notes}:
1. faithful: is every reason's claim actually made by him in the transcript (not implied by the title, not added from outside knowledge)? invented_reasons lists the ranks of reasons the transcript does not support. quotes_total / quotes_verbatim: count the reasons and how many quotes appear verbatim (allow ASR spelling like "Birkshshire", "peer ratio").
2. own_stance_detail: YOUR independent reading of his stance at the current price, one of absolute_buy | relative_buy | fair_hold | avoid | too_hard | short, using these definitions:
   absolute_buy = a buy on its own merits / margin-of-safety buy (also "absolute buy if you are an American investor"); relative_buy = he says "buy" at this price: "relative buy", "good buy now", "better buy than X", he buys or accumulates; fair_hold = a stock he could own here without recommending it: fairly valued for ~10 %, "not a bad addition" even if he personally passes, "a bit overvalued, wait for a better price" while positive, contender/watch; avoid = he would not own it here: overvalued, not for the value investor, nothing to do, too risky for the return, only interesting much lower, low (≤ 7 %) return and not interested; too_hard = declines to judge the business; short = shorts it or says sell. Beware irony about hyped names: weigh what he does and where he places it on his quadrant over enthusiastic phrasing.
3. position_agrees: does the extractor's stance_detail map to the same BUY/HOLD/SELL as yours? (absolute_buy, relative_buy → BUY; fair_hold → HOLD; avoid, too_hard, short → SELL.)
notes: ≤ 40 words on the biggest disagreement, or "ok"."""


def quote_scores(draft: GoldenEvalDraft, t: Transcript) -> list[float]:
    return [find_quote(r.quote, t.text) for r in draft.reasons]


def run_critic(
    draft: GoldenEvalDraft, t: Transcript, model: str = "opus"
) -> tuple[Critic, dict[str, Any], list[float]]:
    scores = quote_scores(draft, t)
    payload = draft.model_dump(exclude={"reasons": {"__all__": {"data_check", "metrics"}}})
    prompt = (
        f"TRANSCRIPT:\n{t.marked}\n\n"
        f"EXTRACTION (JSON):\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        f"Deterministic quote match ratios per reason (1.0 = verbatim): "
        f"{[round(s, 2) for s in scores]}\n"
        f"The extractor's stance maps to {position_for(draft.call.stance_detail)}.\n"
        "Return the JSON object."
    )
    critic, usage = run_structured_sync(
        prompt, schema=Critic, system_prompt=SYSTEM, model=model, max_turns=3, effort="medium"
    )
    return critic, usage, scores

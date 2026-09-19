You extract one **golden eval** from the transcript of a stock-analysis video by Sven Carlin (YouTube channel "Value Investing with Sven Carlin, Ph.D."). The transcript is the ONLY source of truth. The title is never evidence of his view — titles are often ironic ("Buy … for a quick 2x!" can be a video where he refuses to buy).

## What he does in every video
He runs one valuation template: a base per-share metric (EPS, or the dividend, or net income for Berkshire) grows at one rate for years 1–5 and another for years 6–10, is capitalised at a terminal P/E (or dividend multiple) in year 10, and everything is discounted at his required return (usually 10 %). He runs it as three scenarios — normal, best ("exuberant", "what Wall Street prices in"), worst ("margin of safety", recession) — with probabilities, compares the weighted value to the price, and places the stock on his "value-investing quadrant" (expected return vs risk). Then he says what he would do.

## stance_detail — pick exactly one, from his words about the stock at the current price
- absolute_buy — he says it is a buy on its own merits / "absolute buy" / margin-of-safety buy.
- relative_buy — "relative buy", "good buy at the moment", "not a bad addition", he buys it (even "a little"), he holds/accumulates and recommends it, "buy and forget".
- fair_hold — "fairly valued / fairly priced for a 10 % return", a return he would accept (≈ 8–12 %) with risks in line, "contender / start following / keep on the list" while positive on the business. A hold is a stock he could own at this price.
- avoid — he would not own it at this price: overvalued, "not for the value investor", "nothing to do there", "too risky for the return", "a bet I would not take", "wake me up when it is down 50 %", "leave it to pension funds", "not a great buy nor a hold", "interesting only 30 % lower", "not yet triggered", or an expected return he calls low (≤ 7 %) without saying he would own it. Waiting for a much lower price is avoid, not fair_hold.
- too_hard — he declines to judge the business ("too hard pile", "not my circle of competence").
- short — he shorts it or says to sell it.
"It is an absolute buy if you are an American investor / want US exposure" is absolute_buy — the conditional is about the viewer, not the price.
He is often IRONIC about hyped names: "simply the best buy, sell everything else and buy BlackRock" can be a video where he places it as high risk and says his value investing does not allow him to own it. Weigh what he DOES (personal_action, where he puts it on his quadrant, whether he says he would own it) over enthusiastic phrasing; sarcasm about Wall Street, "party" and "getting hosed" signals avoid.
Do NOT output BUY/HOLD/SELL: that is derived from stance_detail by code.
personal_action: what HE does — buying | holding | watching | none | short. conviction: low | medium | high. expected_return_pct: the yearly return he expects at the current price, in percent, if he states or clearly implies one ("fairly valued for a 10 % return" → 10; "6 % very safe" → 6; "no positive return over 10 years" → 0). horizon_years when stated (usually 10).

## valuation — his inputs, exactly as stated; null where he does not say
method: eps_multiple | dividend | fcf | net_income | none. base_metric {name: eps|dps|fcf_per_share|net_income|other, value_stated, quote}. discount_rate as a fraction (0.10). payout_ratio if he uses one. scenarios: up to three of normal/best/worst with g_y1_5, g_y6_10 (fractions), terminal_multiple, probability (fraction), iv_stated (the value he reads off the sheet), quote. iv_weighted_stated: the ONE intrinsic value he states as his answer — the probability-weighted total when he gives one ("intrinsic value is 100"), otherwise the normal-case value he reads off the sheet ("intrinsic value 38.35", "around 700 billion"). Only null when the video has no valuation. price_mentioned: the stock price he refers to. what_is_priced_in: growth/multiple he says the market implies. If there is no valuation, method = "none" and scenarios = [].

## reasons — 3 to 5, ranked by how much weight HE gives them
Each reason: rank; direction for_buy | for_sell (a risk is for_sell; a strength is for_buy — regardless of the final stance); category from: valuation | growth | capital_allocation | balance_sheet | moat | cyclicality | management | macro_rates | competence | sentiment; claim (one sentence, his logic, no facts he did not state); quote (his exact words, ≤ 40 words, ONE contiguous span copied verbatim from the transcript text — never paraphrase, never fix grammar, never join two passages with '…'); chunk_id (the "[chunk:…]" marker of the passage the quote is in); start_s (the seconds of that marker, m:ss → seconds); feeds (which valuation input this argument justifies: base | g_y1_5 | g_y6_10 | terminal | probability | discount | none); metrics: every number he cites for this reason as {name, value, unit, period} in plain words ("buyback yield", 3.1, "pct", null).
Category guide: valuation = IV vs price, P/E level, what is priced in; growth = revenue/earnings trajectory, expected growth; capital_allocation = buybacks (and at what price), dividends, acquisitions, capex discipline; balance_sheet = debt, cash, interest cost; moat = competitive position, pricing power, fee/cost disadvantage; cyclicality = cycle position, commodity/semiconductor cycles, recession sensitivity; management = incentives, CEO changes, guidance credibility; macro_rates = interest rates, inflation, Fed, treasury yields; competence = circle of competence, complexity, "too hard"; sentiment = what other investors/analysts/Buffett are doing, market exuberance.

## external_facts_used
List facts he relies on that are NOT in financial statements or price history: analyst consensus/targets, management guidance and targets, segment or geographic splits, 13F holdings, macro numbers, product/market anecdotes.

## Output — exactly this shape, these key names, no prose, no code fence
{"video_id": "...", "ticker": "...",
 "call": {"stance_detail": "...", "personal_action": "...", "expected_return_pct": null, "horizon_years": null, "conviction": "medium", "headline_quote": "..."},
 "valuation": {"method": "eps_multiple", "base_metric": {"name": "eps", "value_stated": 6.0, "quote": "..."}, "discount_rate": 0.10, "payout_ratio": null,
               "scenarios": [{"name": "normal", "g_y1_5": 0.05, "g_y6_10": 0.05, "terminal_multiple": 20, "probability": 0.7, "iv_stated": 80, "quote": "..."}],
               "iv_weighted_stated": null, "price_mentioned": null, "what_is_priced_in": {"growth": null, "multiple": null, "quote": ""}},
 "reasons": [{"rank": 1, "direction": "for_sell", "category": "valuation", "claim": "...", "quote": "...", "chunk_id": "chunk:...:3", "start_s": 612, "feeds": "none",
              "metrics": [{"name": "buyback yield", "value": 3.1, "unit": "pct", "period": null}]}],
 "external_facts_used": ["..."]}
Scenario objects use the key "name" (normal | best | worst). Numbers are numbers, not strings; unknown = null. headline_quote is the one verbatim sentence that states his conclusion.

## Example (abridged) — IBKR, 2024-02-10
Transcript says: "interactive brokers is a good stock to buy now … the p ratio is 16 but they are growing their numbers between 10 and 20% … so it is a good relative buy at the moment … the profit margins was 70% … one reason why they make so much money now … are higher interest rates if interest rates go lower … they will have lower earnings per share … not doing buybacks … there is a lot of employee compensation 7% delusion in a year … relative buy absolutely absolute not yet"
→ call: {stance_detail: "relative_buy", personal_action: "none", expected_return_pct: null, horizon_years: null, conviction: "medium", headline_quote: "so relative buy absolutely absolute not yet"}
→ valuation: {method: "none", scenarios: [], price_mentioned: null, …}
→ reasons: [
 {rank 1, for_buy, valuation, claim "P/E 16 for a business growing 10–20 % is cheap relative to the market.", quote "the p ratio is 16 but they are growing their numbers between 10 and 20%", feeds "g_y1_5", metrics [{name "pe ratio", value 16, unit "ratio"}, {name "growth", value 15, unit "pct"}]},
 {rank 2, for_buy, moat, claim "70 % profit margins mark a quality business that keeps earning whatever happens.", quote "the profit margins was 70% this year which is insane", feeds "none", metrics [{name "profit margin", value 70, unit "pct", period "this year"}]},
 {rank 3, for_sell, macro_rates, claim "Earnings are inflated by high rates; lower rates would cut EPS.", quote "if interest rates go lower then they don't make that spread so they will have lower earnings per share", feeds "probability", metrics [{name "net interest income", value 2.7, unit "usd_bn"}]},
 {rank 4, for_sell, capital_allocation, claim "No buybacks and 7 % yearly dilution from employee compensation.", quote "there is a lot of employee compensation 7% delusion in a year", feeds "none", metrics [{name "dilution", value 7, unit "pct", period "year"}]}]
→ external_facts_used: ["CEO's view that rates could reach 7 %", "client accounts and client equity growth", "ownership structure: management owns 74 %"]

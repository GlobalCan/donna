# 08 — Validation Tools, Fact-Check Infrastructure, Transcript/Ingest

Scope: products Donna might call as tools (transcript pull, fact-check APIs,
counter-evidence retrieval) or whose UX patterns Donna might steal for the
"oracle, not scholar" validation surface.

Cutoff: April 2026. Anything pre-April-2025 is flagged as potentially stale.

## Ground News

- Primary source: <https://ground.news/rating-system>, <https://ground.news/blindspot>, <https://ground.news/subscribe>
- One-line: news aggregator that clusters stories across outlets and tags each cluster with bias-distribution, factuality, and ownership signals.
- Bias model: seven-bin spectrum (Far Left → Center → Far Right). Ground News does **not** rate publications itself — it averages ratings from AllSides, Ad Fontes, and Media Bias/Fact Check. Factuality is similarly third-party averaged. ([Wikipedia](https://en.wikipedia.org/wiki/Ground_News))
- Counter-evidence UX — the part Donna should steal: the **Blindspot Feed** surfaces stories that one side of the spectrum is systematically under-covering, and each story view shows a left/center/right coverage bar plus side-by-side headline framing from each lean. This is the closest commercial implementation of "show the other side without hedging" — it doesn't argue, it just visually exposes the gap.
- Claim-extraction shape: none. Unit of work is the *story cluster*, not the claim. NLP clusters articles by topic; no structured claim object is exposed.
- API: no public/documented developer API as of April 2026 — product surface is iOS/Android/web only. Not a tool Donna can call.
- Pricing: Pro $9.99/yr, Premium $29.99–39.99/yr, Vantage $99.99/yr (often discounted). Solo-tier viable for *human use*, not for programmatic ingest. ([Ground News subscribe](https://ground.news/subscribe))
- Criticism: bias-rating critics note the upstream raters (AllSides, MBFC) are themselves contested; Ground News inherits their disputes. ([sjodle](https://sjodle.com/posts/2024/01/ground/))
- Scope gap: no claim-level provenance, no API, no self-host.

## NewsGuard

- Primary source: <https://www.newsguardtech.com/ratings/rating-process-criteria/>, <https://www.newsguardtech.com/solutions/news-reliability-ratings/>
- One-line: human-edited reliability ratings for ~10k news/info domains, sold as a B2B data feed.
- Rating model: 9 weighted pass/fail criteria (publishes false content, corrects errors, distinguishes news from opinion, discloses ownership, discloses financing, names authors, avoids deceptive headlines, etc.). 0–100 score; ≥60 = Green, <60 = Red. Each domain gets a "Nutrition Label" — narrative explanation by a named human analyst. ([NewsGuard FAQ](https://www.newsguardtech.com/newsguard-faq/))
- Claim shape: domain-level, not claim-level. NewsGuard rates *publishers*, not individual articles or assertions. They also publish a "Misinformation Fingerprints" feed of specific false-claim narratives (used by AI vendors to detect LLM repetition of known hoaxes), but this is a separate product line.
- API: yes, "API or cloud datastream" for licensees. Pricing not public — quote-only. ([NewsGuard solutions](https://www.newsguardtech.com/solutions/news-reliability-ratings/))
- Pricing: B2B; historical browser extension was ~$1.95–2.95/mo but is now bundled with Microsoft Edge / certain ISPs rather than sold direct. **No solo-developer API tier.** A Donna operator cannot realistically license the data feed.
- Criticism: politically contested — multiple Republican legislators and right-leaning outlets accuse NewsGuard of anti-conservative bias; NewsGuard counters that its criteria are journalistic, not political. The Nutrition Label format remains the strongest part of the product. ([Wikipedia](https://en.wikipedia.org/wiki/NewsGuard))
- Scope gap: domain-grain only; no claim object; not solo-affordable.

## Kagi Assistant + Universal Summarizer + FastGPT

- Primary sources: <https://help.kagi.com/kagi/api/summarizer.html>, <https://help.kagi.com/kagi/api/fastgpt.html>, <https://help.kagi.com/kagi/api/search.html>, <https://help.kagi.com/kagi/ai/assistant.html>
- One-line: Kagi exposes three relevant tool surfaces — Search API, FastGPT (grounded answer with citations), Universal Summarizer — and an end-user Assistant chat that orchestrates them.
- API surfaces:
  - **Summarizer** `POST /api/v0/summarize` — takes `url` or `text`, returns `{output, tokens}`. Engines: Cecil (default, conversational), Agnes (technical), Muriel (enterprise). Handles PDF/Word/PPT/audio/YouTube. ([kagi-docs](https://github.com/kagisearch/kagi-docs/blob/main/docs/kagi/api/summarizer.md))
  - **FastGPT** `POST /api/v0/fastgpt` — returns `{output, tokens, references[]}` with inline `[1][2]` citation markers. This is the closest thing to a "grounded LLM call with citation array" Kagi offers programmatically. ([Kagi feedback](https://kagifeedback.org/d/1498-api-for-fastgpt))
  - **Search** `GET /api/v0/search` — closed beta, $25/1k queries. ([Kagi search API](https://help.kagi.com/kagi/api/search.html))
  - **Assistant** (the user-facing chat with model picker across OpenAI/Anthropic/Google/Mistral/etc.) — UI only as of April 2026, no public Assistant API.
- Pricing: Summarizer $0.030/1k tokens (cap $0.30/doc) or $1/doc Muriel; FastGPT priced from API balance; Assistant requires Ultimate plan ($25/mo). ([Kagi summarizer api](https://kagi.com/summarizer/api.html), [Kagi pricing](https://kagi.com/pricing))
- Solo-tier: yes. Pay-as-you-go API balance, no minimum. Realistic Donna tool call.
- Claim-extraction shape: none. FastGPT returns prose + reference array; no structured per-claim provenance.
- Counter-evidence UX: none built-in — Kagi lets the user *re-run* with a different model in Assistant, but doesn't surface "the other side."
- Scope gap: no fact-check or counter-evidence layer; Search API still gated.

## Perplexity Sonar API + Check Sources

- Primary sources: <https://docs.perplexity.ai/docs/sonar/quickstart>, <https://docs.perplexity.ai/docs/sonar/models/sonar-deep-research>, <https://www.perplexity.ai/hub/blog/introducing-the-sonar-pro-api>
- One-line: grounded LLM API with live web search and a citations array; the consumer product added "Check Sources" highlight-to-verify in April 2025.
- API surface: OpenAI-compatible chat completion. Response includes `citations[]` (URLs) and, since Aug 2025, `search_results[]` with title/url/snippet. Models: `sonar`, `sonar-pro`, `sonar-deep-research`. No dedicated `/verify` endpoint as of April 2026 — verification is implicit in the citations contract. ([Perplexity Aug 2025 update](https://community.perplexity.ai/t/sonar-api-updates-august-29-2025/1252))
- Claim shape: prose answer + citation list. No structured claim object; the operator (or Donna) must do claim extraction client-side.
- "Check Sources" UX (consumer product, April 2025): user highlights a sentence in the answer, Perplexity re-runs a verification pass against the cited sources and shows agreement/disagreement per source. **Not exposed in the API.** ([Perplexity changelog April 2025](https://www.perplexity.ai/changelog/april-2025-product-update))
- Pricing: Sonar $1/M in+out, Sonar Pro $3/M in / $15/M out, Sonar Deep Research $2/$8 plus $5/1k searches and $3/M reasoning tokens. As of 2026 citation tokens are no longer billed on standard Sonar/Pro. ([aipricing.guru](https://www.aipricing.guru/perplexity-pricing/))
- Solo-tier: yes, prepay credits. Best in-class affordability for grounded retrieval.
- Counter-evidence UX: weak — citations support the answer but Perplexity doesn't surface contradictory sources by default. UnCovered (the showcase Chrome extension) does claim-by-claim true/false scoring but is a community pattern, not a first-party API. ([UnCovered](https://docs.perplexity.ai/cookbook/showcase/uncovered))
- Criticism: documented hallucination of citations in early Sonar; reduced but not eliminated.


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

## AllSides

- Primary sources: <https://www.allsides.com/about/media-bias-rating-methods>, <https://www.allsides.com/tools-services/bias-checker-api>, <https://www.allsides.com/tools-services/bias-ratings-license-api>
- One-line: human-rated media bias for ~2,400 outlets/writers, distributed via licensed dataset and a Bias Checker API.
- Bias model: 5-bin (Left / Lean Left / Center / Lean Right / Right) + numeric Media Bias Meter. Built from multi-partisan editorial review, blind bias surveys, third-party studies, and community feedback — not algorithmic. ([AllSides methods](https://www.allsides.com/about/media-bias-rating-methods))
- API surface: Bias Checker API takes a URL or pasted text and returns a bias estimate; Bias Ratings License & API exposes the underlying source-level ratings DB. Free members get 30 article checks; commercial use requires license. Pricing not publicly listed — contact `services@allsides.com`. ([AllSides Bias Checker API](https://www.allsides.com/tools-services/bias-checker-api))
- Solo-tier: borderline. The 30-check free tier is fine for human use but not programmatic. Ratings are CC BY-NC for research/non-commercial — Donna's solo operator could legally pull them via scraping if non-commercial. There's also a community R package `AllSideR` that mirrors the public ratings table. ([AllSideR](https://github.com/favstats/AllSideR))
- Claim shape: source/outlet level only. AllSides does not rate individual claims; it rates publishers and authors, plus curates "balanced newsfeeds" with 33/33/33 left/center/right mixing.
- Counter-evidence UX: the **Headline Roundup** is the relevant pattern — same story, three columns of headlines (left/center/right), with side-by-side framing analysis. Like Ground News' coverage bar but with explicit framing critique.
- Criticism: methodology mixes expert + crowd; some outlets dispute placement. The 5-bin grain is coarse for nuanced editorial differences.

## Full Fact AI

- Primary sources: <https://fullfact.org/ai/>, <https://fullfact.org/about/automated/>, <https://fullfact.ai/>
- One-line: UK fact-checking charity that builds claim-detection ML used by 40+ fact-checker orgs in 30 countries.
- Claim model — directly relevant to Donna: claim = "the checkable part of a sentence." Their classifier (BERT-fine-tuned) tags each sentence by **claim type** (quantitative, causal, predictive, personal-experience, etc.) and assigns a **checkworthiness score**. Claims are also tagged with topic and speaker. This is the cleanest published claim-object schema in the space. ([Full Fact AI](https://fullfact.org/ai/), [Feb 2025 blog](https://fullfact.org/blog/2025/feb/how-ai-can-help-fact-checkers/))
- API: tools are licensed to fact-checking organisations through Full Fact's partner programme — not a self-serve developer API. No public pricing. Source code partially open: claim-detection research code is on GitHub but the production stack is not. **Donna cannot call it as a tool.**
- Counter-evidence: their **claim-matching** stack detects when a claim already fact-checked by a partner is repeated; the canonical reference is their definition paper. ([Full Fact 2021](https://fullfact.org/blog/2021/oct/towards-common-definition-claim-matching/))
- Solo-tier: no.
- Lesson for Donna: the schema (claim-type, checkworthiness, speaker, topic) is the right shape for a structured claim object. Borrow.

## Logically (Logically Facts Accelerate)

- Primary source: <https://logically.ai/announcements/logically-accelerates-fact-checking-with-launch-of-new-product>
- One-line: UK-based misinformation-monitoring vendor; the Accelerate product does multimodal claim extraction (incl. video transcription) with urgency scoring across 57 languages.
- Claim shape: per-clip claim with checkworthiness score, novelty score (vs. prior fact checks), recency, and relevance — assembled into a fact-checker queue.
- API: B2B only, sold to governments and enterprise. No public developer tier.
- Currency note: Accelerate launch was Global Fact 11 (Jun 2024), so the *announcement* is >12 months old; ongoing development since. Logically itself has had public restructuring in 2024–2025 — flagged.
- Solo-tier: no.
- Lesson for Donna: **novelty/recency scoring** as a claim attribute is interesting — "is this claim new, or have we seen it?" maps directly to Donna's memory of prior episodes.

## Factmata (status: defunct as standalone)

- Primary source: <https://techcrunch.com/2022/11/17/pr-software-giant-cision-acquires-factmata-the-fake-news-startup-that-pivoted-to-monitoring-all-kinds-of-online-narratives/>
- One-line: AI claim/narrative classifier acquired by Cision (Nov 2022) and absorbed into Cision's PR monitoring stack. **Stale — flagged.**
- Status as of April 2026: no longer a standalone API. Surviving tech ships inside Cision's narrative-monitoring suite for PR teams. Not solo-purchasable.
- Lesson: the trajectory of every claim-classifier startup so far has been "absorbed by a B2B media-monitoring platform." Suggests claim-extraction is unlikely to be available as cheap commodity API any time soon, which means Donna probably has to build claim extraction in-house.

## Google Fact Check Tools API (bonus — surfaced via Full Fact research)

- Primary source: <https://developers.google.com/fact-check/tools/api>
- One-line: free public search API over the global ClaimReview corpus (the schema.org markup that fact-checkers worldwide publish).
- API: `claims.search?query=...` returns `Claim{ text, claimant, claimDate, claimReview[]{ publisher, url, title, reviewDate, textualRating, languageCode } }`. No auth beyond an API key; very generous quota.
- Pricing: free.
- Claim-extraction shape: this is the canonical published "claim object" in the wild — `text` + `claimant` + `claimDate` + array of reviews each with `textualRating`. Maps to schema.org/ClaimReview.
- Coverage: only claims that some IFCN-signatory fact-checker has already reviewed and marked up. Long tail not covered.
- For Donna: the *most useful* validation tool call available for solo-tier. Use it as the "has someone fact-checked this already?" lookup before generating any opinion. Cite by `textualRating` + `publisher`.

## The Pudding (UX inspiration only)

- Primary source: <https://pudding.cool/about/>
- One-line: data-journalism studio whose visual essays are the gold standard for "long critique that doesn't bore you."
- Process they document: 4-stage workflow — story → data → design → development. Stories are *interactive scrollytelling* with the chart and the prose interleaved; the reader can tweak parameters and see the conclusion update.
- Why this matters for Donna: Donna's "long critique of an article" surface needs a UX that is *more* than a paragraph of objections — it should be inspectable, scrollable, and let the operator interrogate the underlying claim graph. The Pudding's "scrolly + chart + side-margin annotation" pattern is the reference. Polygraph is their consulting arm. ([Storybench profile](https://www.storybench.org/the-proof-is-in-the-pudding-how-one-online-publication-is-using-cutting-edge-data-visualizations-to-tell-meaningful-pop-culture-stories/))
- Not a tool: nothing to call here. Pure UX reference.
- Lesson: when Donna shows an article with bias-and-counter-evidence, render it as a *page with margin annotations and an interactive claim list*, not a chat reply. The Pudding's articles are existence proofs that long-form critique can be read voluntarily.

## Bellingcat (methodology reference)

- Primary sources: <https://www.bellingcat.com/category/resources/how-tos/>, <https://bellingcat.gitbook.io/toolkit>
- One-line: OSINT collective whose published methodology is the de facto standard for "verifiable, attributable, defensible" investigation.
- Process worth stealing for Donna's validation surface:
  1. **Document the chain** — every assertion linked to a primary artefact (image, post, dataset).
  2. **Geolocation/chronolocation as proof** — when claims are spatial/temporal, anchor them to satellite imagery and timestamps.
  3. **Adversarial review** — every published investigation is reviewed for "what would the most aggressive critic say?" before publishing.
  4. **Toolkit transparency** — the GitBook lists every tool used, version, and limitation. ([Bellingcat toolkit](https://bellingcat.gitbook.io/toolkit))
- For Donna: the "validation surface" is ultimately Bellingcat-style: every claim links to a primary artefact, every extrapolation is flagged as inference, and the operator can replay the chain of inference. Donna's UX should make the *chain* visible, not just the conclusion.
- Not a tool: no API. Pure methodology.

## yt-dlp

- Primary source: <https://github.com/yt-dlp/yt-dlp>
- One-line: command-line audio/video downloader; for Donna, the canonical tool for fetching a YouTube/podcast/news-clip and its existing subtitles before falling back to ASR.
- Currency: actively maintained; latest release 2025.12.08. Python ≥3.10 (Python 3.9 EOL'd Oct 2025). Not stale.
- Relevant flags: `--write-subs --write-auto-subs --sub-langs en.* --skip-download` extracts a .vtt without downloading the video. `--cookies-from-browser` for paywalled/age-gated content.
- API: CLI + Python module (`yt_dlp.YoutubeDL`).
- Limitations:
  - Auto-generated subtitles (the YouTube ASR ones) have no punctuation and no speaker labels — usable for grep/embedding but bad for citation.
  - YouTube's anti-bot measures break yt-dlp periodically; expect a `pip install -U yt-dlp` step every few weeks.
  - Many news sites (Bloomberg, FT) ship DRM-protected video; yt-dlp can't break DRM.
- Solo-tier: free, self-host, runs locally. Default ingest tool for Donna.
- Pattern for Donna: try `yt-dlp --write-auto-subs` first; if no subs or quality is too low, fall through to whisper.cpp/AssemblyAI/Deepgram.

## whisper.cpp

- Primary source: <https://github.com/ggml-org/whisper.cpp>
- One-line: ggml C/C++ port of OpenAI's Whisper; the default self-hostable ASR for solo operators in 2026.
- Currency: v1.8.3 released Jan 2026 with 12x perf boost on integrated GPUs. Active. Not stale. ([Phoronix](https://www.phoronix.com/news/Whisper-cpp-1.8.3-12x-Perf))
- Speed: with Apple Silicon Metal/CoreML, large-v3-turbo runs faster than realtime on M-series Macs; on a Linux box with a modest CUDA GPU, large-v3 also runs comfortably faster than realtime. ([HN](https://news.ycombinator.com/item?id=43880345))
- Accuracy: same model weights as OpenAI Whisper — large-v3 is competitive with cloud APIs on clean speech, weaker on heavy accents and overlapping speakers vs. AssemblyAI/Deepgram.
- Diarization: **the weak spot.** Native support is via `tinydiarize` (special tokens for speaker turns) — works on small.en, experimental, single-channel only. For real diarization, pair with `pyannote-audio` or `whisperx` post-processing. ([tinydiarize PR](https://github.com/ggml-org/whisper.cpp/pull/1058))
- Languages: 99 (Whisper's training set).
- Self-host: yes — it's the point. Single binary, no service required.
- Cost: free; capex is the GPU. For a solo operator with an M-series Mac or 12GB+ NVIDIA GPU, marginal cost ≈ 0.
- Default recommendation for Donna: yes, whisper.cpp + whisperx for diarization is the right local stack.

## AssemblyAI

- Primary source: <https://www.assemblyai.com/pricing>, <https://www.assemblyai.com/features/speaker-diarization>
- One-line: cloud ASR with the strongest published diarization numbers and a developer-friendly REST API.
- Model (April 2026): Universal-2 / Universal flat-rate tier. 99 languages, auto language detection, diarization on 95 of them. ([AssemblyAI 99 langs](https://www.assemblyai.com/blog/99-languages))
- Speed: async (POST file → poll for transcript) or realtime streaming over WebSocket. Async finishes faster than realtime; streaming has sub-second latency.
- Accuracy: claims 2.9% speaker-counting error rate; Universal-2 cuts speaker errors 64% on long-form audio.
- Diarization: enable via flag; response is `utterances[]` with `speaker` labels — cleaner schema than Deepgram's segment-level approach.
- Pricing: $0.15/hr Pay-As-You-Go base, $0.27/hr Universal flat rate (covers most features), diarization +$0.02/hr. $50 free credit. ([AssemblyAI pricing](https://www.assemblyai.com/pricing))
- Solo-tier: yes — pay as you go, no minimum.
- Self-host: no.
- Lesson for Donna: best fallback for "I don't have a GPU and the audio is multi-speaker."

## Deepgram

- Primary source: <https://deepgram.com/pricing>, <https://deepgram.com/learn/introducing-nova-3-speech-to-text-api>
- One-line: cloud ASR optimised for ultra-low-latency streaming.
- Model (April 2026): Nova-3 General. 45+ languages, smart formatting, keyterm prompting.
- Speed: median inference reportedly up to 40x faster than competing diarization-enabled APIs. Sub-1s streaming latency. ([Deepgram blog](https://deepgram.com/learn/speech-to-text-benchmarks))
- Accuracy: competitive WER with AssemblyAI on English; weaker on long-tail languages.
- Diarization: yes; charged separately at small additional rate.
- Pricing: ~$0.0043/min batch / ~$0.0077/min streaming for Nova-3 ($0.26–$0.46/hr). $200 free credit. Streaming is ~79% more than batch. ([Deepgram pricing breakdown](https://brasstranscripts.com/blog/deepgram-pricing-per-minute-2025-real-time-vs-batch))
- Solo-tier: yes — $200 free credit goes a long way for a solo operator.
- Self-host: enterprise on-prem container available; not relevant at solo scale.
- Lesson for Donna: best when latency matters (live meeting transcription). For batch ingest of an article's embedded video, AssemblyAI's diarization is cleaner.

## Community Notes (X) — bridging-based ranking

- Primary sources: ["Birdwatch to Community Notes" overview, arXiv 2510.09585](https://arxiv.org/pdf/2510.09585); [Asterisk Magazine "The Making of Community Notes"](https://asteriskmag.com/issues/08/the-making-of-community-notes); [PNAS Nexus 2024 trust study](https://academic.oup.com/pnasnexus/article/3/7/pgae217/7686087); methodology code: <https://github.com/twitter/communitynotes>.
- One-line: open-source crowd fact-check system whose "bridging algorithm" surfaces notes only when raters who normally disagree both find a note helpful.
- Algorithm — what Donna can borrow: matrix-factorisation model on (rater, note) helpfulness votes. The model factors out rater-polarity and surfaces notes with high helpfulness *after* polarity is removed. Notes that pass the threshold appear under the post; notes that don't pass don't appear at all. It is *not* majority vote, and it is *not* a politically-balanced jury — it's a polarity-residual model. ([Asterisk](https://asteriskmag.com/issues/08/the-making-of-community-notes))
- Counter-evidence UX: the result is the cleanest "show the other side without hedging" UX in the wild — under a contested claim, you see one note, written by humans, signed (effectively) by people who disagree about everything else. No mealy-mouthed "some say X others say Y" — a single concrete counter-claim with sources.
- Adoption: Meta started testing Community Notes on FB/IG/Threads March 2025; TikTok piloted similar. ([arXiv 2510.09585](https://arxiv.org/pdf/2510.09585))
- Known issues:
  - **Coverage gap** — De et al. (2024) report that in 91% of posts where a note was proposed, none ever reached "helpful." Most contested claims get no note at all.
  - **Sustainability** — helpful-note throughput has been declining since May 2024; rater retention is a problem. ([arXiv 2510.00650](https://arxiv.org/html/2510.00650v1))
  - Threshold tightening (March 2025: ≥10 raters of differing past behaviour required) cuts noise but worsens latency and coverage.
- For Donna: the bridging *algorithm* is the right inspiration, but Donna doesn't have raters — it has one operator. The translation: when Donna shows counter-evidence, prefer sources that *contradict the operator's prior reading* AND are independently credible. The "bridge" is between Donna's prior model of the operator and external counter-evidence — show what credibly contradicts what the operator already believes.


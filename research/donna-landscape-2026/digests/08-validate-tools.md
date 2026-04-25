# Validation Tools, Fact-Check Infrastructure, Transcript/Ingest — digest

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | API access | pricing | self-host | claim-extraction shape | solo viable | Donna tool-call candidate | source |
|---|---|---|---|---|---|---|---|---|---|
| Ground News | News aggregator clustering stories with bias/factuality/ownership | NLP cluster of articles; third-party (AllSides/AdFontes/MBFC) ratings averaged | No public API | Pro $9.99/yr; Premium $29.99–39.99/yr; Vantage $99.99/yr | No | None — story cluster, not claim | Human only | No | https://ground.news/subscribe |
| NewsGuard | Human-edited reliability ratings for ~10k domains | 9 weighted criteria, 0–100 score, Nutrition Label | B2B-only datastream | Quote-only; no solo tier | No | Domain-grain only | No | No | https://www.newsguardtech.com/solutions/news-reliability-ratings/ |
| Kagi FastGPT/Summarizer/Search | Grounded LLM, summarizer, search APIs + Assistant UI | REST; engines Cecil/Agnes/Muriel; FastGPT returns refs[] | Yes (Assistant UI-only) | Summarizer $0.030/1k tok; Search beta $25/1k; Assistant Ultimate $25/mo | No | Prose + reference array, no per-claim | Yes (PAYG) | Yes | https://help.kagi.com/kagi/api/fastgpt.html |
| Perplexity Sonar | Grounded LLM with live web search + citations | OpenAI-compatible chat; citations[]; search_results[] | Yes | Sonar $1/M; Pro $3/$15; Deep Research $2/$8 + $5/1k searches | No | Prose + citation list; Check Sources not in API | Yes | Yes — primary grounded retrieval | https://docs.perplexity.ai/docs/sonar/quickstart |
| AllSides | Human-rated bias for ~2,400 outlets | 5-bin + numeric meter; multi-partisan editorial review | Yes (license) | Free: 30 checks; commercial license priced via email | No | Source/outlet level only | Borderline (CC BY-NC research) | Maybe | https://www.allsides.com/tools-services/bias-checker-api |
| Full Fact AI | UK charity claim-detection ML used by 40+ orgs | BERT classifier; type+checkworthiness+speaker+topic | No (partner programme) | Private | No | Tagged-sentence: type, checkworthiness, speaker, topic | No | No (borrow schema) | https://fullfact.org/ai/ |
| Logically Accelerate | Multimodal claim extraction + urgency scoring, 57 langs | Per-clip claim + checkworthiness/novelty/recency/relevance | B2B-only | Private | No | Claim with novelty/urgency vs prior | No | No | https://logically.ai/announcements/logically-accelerates-fact-checking-with-launch-of-new-product |
| Factmata (defunct) | AI claim/narrative classifier acquired by Cision Nov 2022 | N/A — absorbed into Cision PR stack | No | N/A | No | N/A | No | No | https://techcrunch.com/2022/11/17/pr-software-giant-cision-acquires-factmata-the-fake-news-startup-that-pivoted-to-monitoring-all-kinds-of-online-narratives/ |
| Google Fact Check Tools | Free public API over global ClaimReview corpus | claims.search; schema.org/ClaimReview | Yes (free, API key) | Free | No | Canonical: text+claimant+claimDate+claimReview[] | Yes | Yes — primary verdict lookup | https://developers.google.com/fact-check/tools/api |
| The Pudding | Data-journalism studio; scrollytelling UX reference | 4-stage: story→data→design→dev | No | N/A | N/A | N/A — UX only | N/A | No (UX inspiration) | https://pudding.cool/about/ |
| Bellingcat | OSINT methodology reference | Chain-of-evidence, geolocation, adversarial review | No | N/A | N/A | Methodology only | N/A | No (methodology) | https://bellingcat.gitbook.io/toolkit |
| yt-dlp | CLI/Py audio/video downloader + sub extraction | Python module; --write-auto-subs | CLI/Py module | Free | Yes | N/A — ingest | Yes | Yes — default ingest | https://github.com/yt-dlp/yt-dlp |
| whisper.cpp | ggml C/C++ Whisper port; default self-host ASR | Local single binary; Metal/CUDA; large-v3-turbo | Local lib | Free | Yes | N/A — ASR; tinydiarize weak | Yes | Yes — default ASR | https://github.com/ggml-org/whisper.cpp |
| AssemblyAI | Cloud ASR with strongest diarization | Universal-2; async/streaming; utterances[] w/ speaker | Yes | $0.15–0.27/hr + $0.02/hr diarization; $50 credit | No | N/A — ASR | Yes | Yes — diarization fallback | https://www.assemblyai.com/pricing |
| Deepgram | Cloud ASR optimized for low-latency streaming | Nova-3 General; sub-1s streaming | Yes | ~$0.0043/min batch; ~$0.0077/min streaming; $200 credit | Enterprise on-prem | N/A — ASR | Yes | Yes — streaming fallback | https://deepgram.com/pricing |
| Community Notes (X) | Bridging-based crowd fact-check, open-source algo | Matrix-factorisation on (rater,note) helpfulness; polarity-residual | Open data download | Free | Algo open | Note text + sources, surfaced post-bridge | Yes (X corpus) | Maybe | https://github.com/twitter/communitynotes |

## Three patterns to steal

1. (a) Schema.org/ClaimReview as canonical claim object (text+claimant+claimDate+reviews[publisher,textualRating,reviewDate,url]). (b) Google Fact Check Tools API; partially Full Fact. (c) Donna's memory needs a structured claim object; this is the free, canonical, in-the-wild schema for "has someone fact-checked this already?" — the "oracle, not scholar" verdict lookup before opining. (d) https://developers.google.com/fact-check/tools/api
2. (a) Bridging-based counter-evidence: surface a single concrete counter-claim only when it's credible across polarity, not majority-vote. (b) Community Notes (X), partially Ground News Blindspot. (c) Donna's validation surface should pick the most credible contradiction to the operator's prior reading and state it without hedging — exactly the "oracle, not scholar" payoff. (d) https://asteriskmag.com/issues/08/the-making-of-community-notes
3. (a) Tagged-sentence claim model: type ∈ {quantitative, causal, predictive, personal} + checkworthiness + speaker + topic. (b) Full Fact AI; Logically adds novelty/recency. (c) Right shape for claims Donna extracts itself; novelty-vs-memory directly maps to Donna's first-class memory. (d) https://fullfact.org/ai/

## Three patterns to avoid

1. (a) Domain-grain-only trust scores collapsing bias and factuality. (b) NewsGuard, AllSides, Ground News (inherited). (c) Politically contested as anti-conservative; Nutrition Label format survives but trust-score grain is the failure mode — Donna should never collapse "wrong claim" with "biased source" into one number. (d) https://en.wikipedia.org/wiki/NewsGuard
2. (a) Bridging-algorithm coverage gap — most contested claims never get a surfaced note. (b) Community Notes (X). (c) De et al. 2024: 91% of posts where a note was proposed never reached "helpful"; throughput declining since May 2024. Donna can't rely on consensus signals for long-tail claims. (d) https://arxiv.org/html/2510.00650v1
3. (a) Standalone claim-classifier startups get absorbed into B2B media-monitoring suites. (b) Factmata (acquired by Cision Nov 2022). (c) Trajectory suggests cheap commodity claim-extraction APIs unlikely; Donna probably must build claim extraction in-house. (d) https://techcrunch.com/2022/11/17/pr-software-giant-cision-acquires-factmata-the-fake-news-startup-that-pivoted-to-monitoring-all-kinds-of-online-narratives/

## Cross-cutting observations

- Bias-rating products (Ground News, AllSides, NewsGuard) all operate at publisher grain; NewsGuard explicitly separates journalistic-process criteria from political orientation.
- Counter-evidence UX ranked best-to-worst: Community Notes > Ground News Blindspot > AllSides Headline Roundup > Perplexity Check Sources > NewsGuard Nutrition Label.
- Solo-affordable tool-callable APIs converge on: Perplexity Sonar (grounded retrieval), Google Fact Check Tools (verdict lookup), Kagi FastGPT/Summarizer, yt-dlp + whisper.cpp (ingest), AssemblyAI/Deepgram (ASR fallback).
- whisper.cpp diarization is the weak spot — pair with whisperx/pyannote; AssemblyAI cleaner for multi-speaker.
- Claim-extraction commodity APIs do not exist at solo tier; schemas are public, weights are not.

## Unresolved

- NewsGuard API pricing — quote-only; solo tier likely absent.
- Full Fact partner API access — terms private; non-fact-checker eligibility unclear.
- AllSides Bias Checker pricing — gated via services@allsides.com.
- Perplexity Check Sources API exposure — not documented as of April 2026.
- Logically post-restructuring status — Accelerate's continued sale unclear.
- Community Notes API rate-limits/TOS for programmatic ingest in 2026 not fully verified.
- whisper.cpp vs AssemblyAI 2026 head-to-head diarization benchmarks limited.
- The Pudding's specific JS framework choices not public.
- NewsGuard "Misinformation Fingerprints" — schema doc not located; claim-level exposure unclear.

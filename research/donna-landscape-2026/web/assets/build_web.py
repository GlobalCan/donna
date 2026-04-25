#!/usr/bin/env python3
"""
Generate the 8 per-category HTML pages by wrapping each digest's
markdown in a shared template. Run from the repo root or anywhere;
paths resolve from this file's location.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # research/donna-landscape-2026/
DIGESTS = ROOT / "digests"
WEB = ROOT / "web"

CATEGORIES = [
    {"num": "01", "slug": "01-commercial",       "title": "Commercial personal-AI assistants",
     "lead": "11 products. Where the money is, where the architecture is most opaque, and where the cautionary tales are loudest. Dec 2025 collapsed the consumer-AI hardware category in two acquisitions; the survivors are quietly drifting toward enterprise revenue.",
     "color": "#d4a574"},
    {"num": "02", "slug": "02-oss-assistants",   "title": "OSS self-hosted assistants",
     "lead": "9 products. Donna's most direct architectural neighbours. MCP is universal; memory is an afterthought everywhere except Khoj (whose memory subsystem is the buggiest); Open WebUI's April 2025 license pivot is a category-wide trust event.",
     "color": "#8eb89b"},
    {"num": "03", "slug": "03-agent-frameworks", "title": "Agent frameworks",
     "lead": "10 products (incl. Microsoft Agent Framework as a 10th row since AutoGen + Semantic Kernel both funnel into it). The substrate decision for v0.5: LangGraph v1 leads, Pydantic AI runner-up, borrow Hermes Agent's MCP hygiene regardless.",
     "color": "#b89bd4"},
    {"num": "04", "slug": "04-memory",           "title": "Agent memory systems",
     "lead": "5 products. Clean split: bitemporal stores (Zep / Graphiti / mnemostack) vs agent-rewrite (Letta / Mem0). Donna's tenets demand the former. Zep CE was deprecated April 2025 — only Graphiti remains self-hostable from that family.",
     "color": "#c9b876"},
    {"num": "05", "slug": "05-graphrag",         "title": "Graph-augmented RAG",
     "lead": "6 products. Cost vs incrementality is the dominant trade. None implement true bitemporal facts. Cognee's temporal_cognify is the closest; Cognee themselves shipped a Graphiti integration acknowledging Graphiti's bitemporal model is more rigorous.",
     "color": "#87a8c9"},
    {"num": "06", "slug": "06-persona",          "title": "Persona / digital-twin",
     "lead": "9 products. Donna isn't a persona product, but the persona category is the closest existing literature on 'an AI that speaks beyond its sources.' The labelled-extrapolation slot is empty — that is Donna's defensible niche.",
     "color": "#d49ba8"},
    {"num": "07", "slug": "07-security",         "title": "Security & prompt injection",
     "lead": "11 papers / policies / post-mortems / defenses. Consensus: prompt injection is unfixable at the model layer. Only architectural containment is provable. The OpenClaw / ClawHavoc skill-marketplace post-mortem (Jan-Feb 2026) is the proof case for default-trust marketplace = malware vector.",
     "color": "#c98787"},
    {"num": "08", "slug": "08-validate-tools",   "title": "Validation tools & ingest",
     "lead": "16 products. Three fit Donna's solo budget as external tool calls: Google Fact Check Tools (free), Perplexity Sonar ($1-15/M), Kagi FastGPT (PAYG). Community Notes' bridging-based ranking is the best counter-evidence UX in the wild.",
     "color": "#9bc9b8"},
]

TEMPLATE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{title} · Donna v0.5 Landscape</title>
<meta name="description" content="{lead_short}" />
<link rel="stylesheet" href="assets/styles.css" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Newsreader:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/marked@13.0.2/marked.min.js" defer></script>
<script src="assets/site.js" defer></script>
<style>
  body {{ --cat-accent: {color}; }}
  .hero h1 {{ color: var(--cat-accent); }}
  .hero .eyebrow {{ color: var(--cat-accent); }}
  .markdown-body h2 {{ border-bottom-color: rgba(255,255,255,0.06); }}
  .markdown-body h2:first-of-type {{ color: var(--cat-accent); }}
  .markdown-body table tbody tr:hover {{ background: rgba(255,255,255,0.02); }}
  .nav-related {{
    display: flex; gap: 0.6rem; flex-wrap: wrap; margin: 1.5rem 0 2rem;
    font-size: 0.85rem;
  }}
  .nav-related a {{
    background: var(--bg-card); border:1px solid var(--border); border-radius:999px;
    padding: 0.35rem 0.9rem; color: var(--fg-muted); border-bottom: 1px solid var(--border);
  }}
  .nav-related a:hover {{ border-color: var(--cat-accent); color: var(--fg); }}
</style>
</head>
<body data-page="{slug}">

<nav id="site-nav" class="site-nav"></nav>

<main>
  <header class="hero">
    <div class="eyebrow">{num} / 08 · digest</div>
    <h1>{title}.</h1>
    <p class="lead">{lead}</p>
  </header>

  <div class="nav-related">
    <a href="index.html">← Overview</a>
    <a href="synthesis.html">Synthesis</a>
    {prev_link}
    {next_link}
  </div>

  <div id="digest-md" data-render-markdown>{md}</div>

</main>

<footer class="site-footer">
  Donna v0.5 · {title} · digest · 2026-04-25 ·
  <a href="https://github.com/globalcan/donna/blob/claude/donna-market-research-7Drtc/research/donna-landscape-2026/digests/{slug}.md">view markdown source</a> ·
  <a href="https://github.com/globalcan/donna/blob/claude/donna-market-research-7Drtc/research/donna-landscape-2026/raw/{slug}.md">view raw research</a>
</footer>

</body>
</html>
'''

def main():
    for i, cat in enumerate(CATEGORIES):
        digest_path = DIGESTS / f"{cat['slug']}.md"
        if not digest_path.exists():
            # 03-agent-frameworks digest exists; 03a/03b are raw-only
            print(f"  skip (missing): {digest_path}")
            continue
        md = digest_path.read_text()
        # defensive: prevent script-tag escape in markdown (none currently)
        md_safe = md.replace("</script>", "<\\/script>")

        prev_link = ""
        next_link = ""
        if i > 0:
            p = CATEGORIES[i-1]
            prev_link = f'<a href="{p["slug"]}.html">← {p["title"]}</a>'
        if i < len(CATEGORIES) - 1:
            n = CATEGORIES[i+1]
            next_link = f'<a href="{n["slug"]}.html">{n["title"]} →</a>'

        # short lead for meta description (first sentence, 155 char cap)
        lead_short = cat["lead"].split(".")[0].strip()[:150]

        html = TEMPLATE.format(
            num=cat["num"],
            slug=cat["slug"],
            title=cat["title"],
            lead=cat["lead"],
            lead_short=lead_short,
            color=cat["color"],
            prev_link=prev_link,
            next_link=next_link,
            md=md_safe,
        )
        out_path = WEB / f"{cat['slug']}.html"
        out_path.write_text(html)
        print(f"  wrote {out_path.relative_to(ROOT)} ({len(html)} bytes)")

if __name__ == "__main__":
    print("Building Donna landscape category pages...")
    main()
    print("Done.")

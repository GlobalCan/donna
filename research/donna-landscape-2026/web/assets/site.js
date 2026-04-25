/* ============================================================
   Donna Landscape — site.js
   Markdown rendering + nav + matrix interactivity + chart data
   ============================================================ */

// ---------- 1. Categories metadata (single source of truth) ----------
window.DONNA = window.DONNA || {};

DONNA.categories = [
  { num: "01", slug: "01-commercial",        title: "Commercial",  longTitle: "Commercial personal-AI assistants", count: 11, color: "#d4a574", finding: "Wearable consolidation Dec 2025 (Humane shut Feb 2025; Rewind/Limitless absorbed by Meta) collapsed consumer-AI hardware. NotebookLM is the cleanest 'scholar' foil to Donna's 'oracle.'" },
  { num: "02", slug: "02-oss-assistants",    title: "OSS",         longTitle: "OSS self-hosted assistants",        count:  9, color: "#8eb89b", finding: "MCP is table stakes; memory is an afterthought everywhere except Khoj (whose memory subsystem is the buggiest part). Open WebUI's April 2025 license pivot is a category-wide trust event." },
  { num: "03", slug: "03-agent-frameworks",  title: "Frameworks",  longTitle: "Agent frameworks",                  count: 10, color: "#b89bd4", finding: "LangGraph v1 leads as substrate (zero-breaking-change v1, mature checkpointing). Microsoft's lineage forces a second migration in 18 months. Hermes Agent has best MCP hygiene." },
  { num: "04", slug: "04-memory",            title: "Memory",      longTitle: "Agent memory systems",              count:  5, color: "#c9b876", finding: "Clean split: bitemporal stores (Zep/Graphiti/mnemostack) vs agent-rewrite (Letta/Mem0). Donna's tenets demand the former. Zep CE deprecated April 2025." },
  { num: "05", slug: "05-graphrag",          title: "GraphRAG",    longTitle: "Graph-augmented RAG",               count:  6, color: "#87a8c9", finding: "None of the six implements true bitemporal facts. Cognee's temporal_cognify is closest. Microsoft GraphRAG full mode is the canonical cost trap." },
  { num: "06", slug: "06-persona",           title: "Persona",     longTitle: "Persona / digital-twin",            count:  9, color: "#d49ba8", finding: "Labeled-extrapolation slot is empty. Cultural pattern (Alexander, Appleton, Krycho) and OpenAI Model Spec endorse it; no shipped assistant renders it inline. Setzer suit settled Jan 2026." },
  { num: "07", slug: "07-security",          title: "Security",    longTitle: "Security & prompt injection",       count: 11, color: "#c98787", finding: "Consensus: prompt injection unfixable at model layer (NCSC). Only architectural containment is provable (CaMeL). OpenClaw/ClawHavoc proves marketplaces = malware vector." },
  { num: "08", slug: "08-validate-tools",    title: "Validate",    longTitle: "Validation tools & ingest",         count: 16, color: "#9bc9b8", finding: "Three tools fit Donna's solo budget: Google Fact Check (free), Perplexity Sonar ($1-15/M), Kagi FastGPT (PAYG). Community Notes' bridging is the best counter-evidence UX in the wild." }
];

// ---------- 2. Aggregate stats for charts ----------
DONNA.stats = {
  total_products: 77,
  total_categories: 8,
  post_mortems_cited: 16,
  open_lanes: 4,
  // license / open-source distribution across all rows
  license: {
    "MIT / Apache / BSD / Unlicense": 37,
    "Closed": 29,
    "Restricted source-available": 1,
    "Mixed / N/A (papers, policies, methodology)": 10
  },
  // self-host viability
  self_host: {
    "Self-hostable": 37,
    "Cloud-only": 30,
    "N/A": 10
  },
  // memory persistence shape across all rows that have a memory model
  memory_shape: {
    "Bitemporal (event+ingestion)": 3,
    "Agent-rewrite (overwrite)": 2,
    "RAG / chunk retrieval": 16,
    "Per-conversation only": 9,
    "Long-term (flat / opaque)": 6,
    "None / N/A": 41
  },
  // products per category
  products_per_category: {
    "Commercial": 11,
    "OSS":         9,
    "Frameworks": 10,
    "Memory":      5,
    "GraphRAG":    6,
    "Persona":     9,
    "Security":   11,
    "Validate":   16
  }
};

// ---------- 3. Timeline events ----------
DONNA.timeline = [
  { date: "2024-03",     title: "Inflection acqui-hire by Microsoft",         body: "Suleyman/Simonyan move; Pi deprioritised, slow abandonment.",                  type: "acquire" },
  { date: "2024-08",     title: "PrivateGPT goes silent",                       body: "Last release v0.6.2; team shifts to commercial Zylon.",                         type: "death" },
  { date: "2024-11",     title: "AG2 forks AutoGen",                            body: "Original creators leave Microsoft after governance dispute.",                     type: "policy" },
  { date: "2025-02",     title: "Humane AI Pin shutdown",                       body: "All units bricked Feb 28; HP $116M acqui-hire after ~$230M burn.",               type: "death" },
  { date: "2025-04",     title: "Open WebUI license pivot",                     body: "BSD-3 → custom license + mandatory CLA + 50-user branding wall.",                type: "policy" },
  { date: "2025-04",     title: "Zep CE deprecated",                            body: "Self-hostable Community Edition retired; only Graphiti remains.",                 type: "death" },
  { date: "2025-06",     title: "Willison: lethal trifecta",                    body: "Names the unconditionally-vulnerable injection failure mode.",                     type: "policy" },
  { date: "2025-06",     title: "LlamaIndex Workflows 1.0",                     body: "RAG framework rebrands to multi-agent substrate.",                                type: "release" },
  { date: "2025-09",     title: "AutoGen → maintenance mode",                   body: "Last release v0.7.5; Microsoft funnels users to Agent Framework.",               type: "death" },
  { date: "2025-10",     title: "LangGraph v1 GA",                              body: "First stable major release; zero-breaking-change commitment.",                    type: "release" },
  { date: "2025-11",     title: "Sana acquired by Workday",                     body: "$1.1B; consumer brand absorbed into enterprise stack.",                            type: "acquire" },
  { date: "2025-11",     title: "Character.ai bans under-18 chat",              body: "Platform-wide policy change ahead of Setzer settlement.",                          type: "policy" },
  { date: "2025-12",     title: "NCSC prompt-injection paper",                  body: "UK national position: 'may never be totally mitigated.'",                          type: "policy" },
  { date: "2025-12",     title: "Meta acquires Limitless / sunsets Rewind",     body: "Capture disabled Dec 19; service withdrawn from EU/UK + 5 markets.",              type: "acquire" },
  { date: "2026-01",     title: "Setzer settlement disclosed",                  body: "Character.ai + Google mediated wrongful-death settlement.",                       type: "policy" },
  { date: "2026-01-Feb", title: "OpenClaw / ClawHavoc",                         body: "341→1,184 malicious skills, CVE-2026-22708, Atomic macOS Stealer payloads.",       type: "death" },
  { date: "2026-04-03",  title: "Microsoft Agent Framework 1.0 GA",             body: "AutoGen + Semantic Kernel both forced to migrate.",                                type: "release" }
];

// ---------- 4. Markdown rendering helper ----------
DONNA.renderMarkdown = function(elementId) {
  const node = document.getElementById(elementId);
  if (!node || !window.marked) return;
  const raw = node.textContent;
  marked.setOptions({
    gfm: true,
    breaks: false,
    headerIds: true,
    mangle: false
  });
  const html = marked.parse(raw);
  const target = document.createElement("div");
  target.className = "markdown-body";
  target.innerHTML = html;
  // make external links open in new tab
  target.querySelectorAll("a[href^='http']").forEach(a => {
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  });
  node.replaceWith(target);
};

// ---------- 5. Site nav builder ----------
DONNA.buildNav = function(activeSlug) {
  const nav = document.getElementById("site-nav");
  if (!nav) return;
  const links = [
    { href: "index.html",     label: "Overview",    slug: "index" },
    { href: "synthesis.html", label: "Synthesis",   slug: "synthesis" },
    ...DONNA.categories.map(c => ({
      href: c.slug + ".html",
      label: c.title,
      slug: c.slug
    }))
  ];
  const linkEls = links.map(l => {
    const cls = l.slug === activeSlug ? "active" : "";
    return `<a href="${l.href}" class="${cls}">${l.label}</a>`;
  }).join("");
  nav.innerHTML = `
    <div class="inner">
      <a href="index.html" class="brand">Donna<span class="dot">.</span> Landscape <span style="color:var(--fg-dim);font-size:0.85rem;font-family:var(--font-mono);margin-left:0.5rem">2026-04</span></a>
      <div class="links">${linkEls}</div>
      <div class="meta">v0.5</div>
    </div>
  `;
};

// ---------- 6. Matrix filter (synthesis page) ----------
DONNA.initMatrixFilter = function() {
  const search = document.getElementById("matrix-search");
  const cats = document.querySelectorAll(".matrix-controls .pill");
  const table = document.querySelector(".matrix-container table");
  if (!table) return;

  let activeCategories = new Set();

  function applyFilter() {
    const q = (search?.value || "").toLowerCase().trim();
    table.querySelectorAll("tbody tr").forEach(row => {
      const text = row.textContent.toLowerCase();
      const cat = row.children[1]?.textContent.trim();
      const matchQ = !q || text.includes(q);
      const matchC = activeCategories.size === 0 || activeCategories.has(cat);
      row.classList.toggle("matrix-row-hidden", !(matchQ && matchC));
    });
  }

  search?.addEventListener("input", applyFilter);
  cats.forEach(p => {
    p.addEventListener("click", () => {
      const c = p.dataset.category;
      if (activeCategories.has(c)) {
        activeCategories.delete(c);
        p.classList.remove("active");
      } else {
        activeCategories.add(c);
        p.classList.add("active");
      }
      applyFilter();
    });
  });
};

// ---------- 7. boot ----------
document.addEventListener("DOMContentLoaded", () => {
  const active = document.body.dataset.page || "index";
  DONNA.buildNav(active);

  const mdNodes = document.querySelectorAll("[data-render-markdown]");
  mdNodes.forEach(n => DONNA.renderMarkdown(n.id));

  if (active === "synthesis") {
    DONNA.initMatrixFilter();
  }

  if (window.DONNA_INIT_CHARTS) DONNA_INIT_CHARTS();
});

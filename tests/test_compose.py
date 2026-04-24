"""compose_system: cache-aware prompt composition invariants.

The prompt is composed as a list of content blocks:
  1. STABLE PREFIX (base prompt + active heuristics + mode instructions)
     — marked `cache_control: {"type": "ephemeral"}` so Anthropic caches it
  2. VOLATILE SUFFIX (examples + style anchors + retrieved chunks + debate ctx)
     — no cache marker
  3. TASK FRAMING (the user's actual task, always last)

Why this matters: prompt caching is real money. A single Huck-Finn-sized
grounded job has ~4k input tokens of stable context; at Sonnet's $3/M
that's $0.012 per call uncached. Thousands of calls per month → hundreds
of dollars saved by stable-prefix caching. If any new code accidentally
shuffles the order, mixes a volatile piece into the stable block, or
drops the cache_control marker, the bill goes up silently.

These tests pin the contract so that regression is visible.
"""
from __future__ import annotations

import pytest

from donna.agent.compose import compose_system
from donna.memory.db import connect, transaction
from donna.types import Chunk, JobMode


def _chunk(cid: str = "chk_1", content: str = "chunk body",
           title: str = "Source", date: str | None = "2024-01-01") -> Chunk:
    return Chunk(
        id=cid, source_id="src_1", agent_scope="author_twain",
        work_id=None, publication_date=date, source_type="book",
        content=content, score=1.0,
        chunk_index=0, is_style_anchor=False,
        source_title=title,
    )


# ---------- structural contract --------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_compose_returns_blocks_with_cache_control_on_first() -> None:
    """The stable prefix MUST be block 0 and MUST carry cache_control.
    Missing marker = prompt caching disabled = surprise bill. Load-bearing."""
    blocks = compose_system(
        scope="orchestrator", task="hello", mode=JobMode.CHAT,
    )
    assert isinstance(blocks, list)
    assert len(blocks) >= 2  # stable + task, minimum
    assert blocks[0].get("type") == "text"
    assert blocks[0].get("cache_control") == {"type": "ephemeral"}
    # Stable prefix is not empty
    assert blocks[0]["text"].strip() != ""


@pytest.mark.usefixtures("fresh_db")
def test_compose_task_framing_is_always_last() -> None:
    blocks = compose_system(
        scope="orchestrator", task="UNIQUE_TASK_MARKER",
        mode=JobMode.CHAT,
    )
    assert "UNIQUE_TASK_MARKER" in blocks[-1]["text"]
    assert "## Current task" in blocks[-1]["text"]


@pytest.mark.usefixtures("fresh_db")
def test_compose_volatile_block_absent_when_no_volatile_content() -> None:
    """No chunks, no examples, no style anchors → only 2 blocks
    (stable + task). The volatile block should NOT be an empty string,
    which would still cost tokens and break cache alignment."""
    blocks = compose_system(
        scope="orchestrator", task="t", mode=JobMode.CHAT,
    )
    assert len(blocks) == 2


@pytest.mark.usefixtures("fresh_db")
def test_compose_volatile_block_has_no_cache_control() -> None:
    """Volatile content must NOT be cached — retrieved chunks change
    every call and caching them would be wrong-cache-key hell."""
    blocks = compose_system(
        scope="orchestrator", task="t", mode=JobMode.CHAT,
        retrieved_chunks=[_chunk()],
    )
    assert len(blocks) >= 3
    # Volatile block (index 1) must not carry cache_control
    assert "cache_control" not in blocks[1]


# ---------- stable prefix contents -----------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_stable_prefix_includes_active_heuristics() -> None:
    """Heuristics are stable-scope per design (approved rules change
    infrequently). They belong in the cacheable prefix."""
    conn = connect()
    try:
        with transaction(conn):
            from donna.memory import prompts as prompts_mod
            prompts_mod.insert_heuristic(
                conn, agent_scope="orchestrator",
                heuristic="Always attribute exact quotes.",
                status="active",
            )
    finally:
        conn.close()

    blocks = compose_system(
        scope="orchestrator", task="t", mode=JobMode.CHAT,
    )
    assert "Always attribute exact quotes." in blocks[0]["text"]
    assert "## Active heuristics" in blocks[0]["text"]


@pytest.mark.usefixtures("fresh_db")
def test_stable_prefix_omits_heuristics_section_when_none_active() -> None:
    blocks = compose_system(
        scope="orchestrator", task="t", mode=JobMode.CHAT,
    )
    assert "## Active heuristics" not in blocks[0]["text"]


@pytest.mark.usefixtures("fresh_db")
def test_stable_prefix_omits_retired_heuristics() -> None:
    """Retired heuristics MUST NOT appear in the stable prefix (or
    `botctl heuristics retire` is cosmetic)."""
    conn = connect()
    try:
        with transaction(conn):
            from donna.memory import prompts as prompts_mod
            prompts_mod.insert_heuristic(
                conn, agent_scope="orchestrator",
                heuristic="An old rule we dropped.",
                status="retired",
            )
    finally:
        conn.close()

    blocks = compose_system(
        scope="orchestrator", task="t", mode=JobMode.CHAT,
    )
    assert "An old rule we dropped." not in blocks[0]["text"]


# ---------- mode instructions ----------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_chat_mode_has_no_mode_section() -> None:
    """Chat is the default — no special instructions needed. A '## Mode'
    header with an empty body would waste cache + tokens."""
    blocks = compose_system(
        scope="orchestrator", task="t", mode=JobMode.CHAT,
    )
    assert "## Mode" not in blocks[0]["text"]


@pytest.mark.usefixtures("fresh_db")
def test_grounded_mode_includes_citation_requirement() -> None:
    blocks = compose_system(
        scope="author_twain", task="t", mode=JobMode.GROUNDED,
    )
    stable = blocks[0]["text"]
    assert "GROUNDED mode" in stable
    assert "[#chunk_id]" in stable
    assert "refuse" in stable.lower()


@pytest.mark.usefixtures("fresh_db")
def test_speculative_mode_bans_assertion_phrasings() -> None:
    """The 'X thinks / says / believes' ban is the core of speculative mode
    — losing those lines means speculative output can pass itself off as
    fact. Pin it."""
    blocks = compose_system(
        scope="author_twain", task="t", mode=JobMode.SPECULATIVE,
    )
    stable = blocks[0]["text"]
    assert "SPECULATIVE mode" in stable
    assert "BANNED" in stable
    assert "X thinks" in stable


@pytest.mark.usefixtures("fresh_db")
def test_debate_mode_requires_quote_to_attack() -> None:
    blocks = compose_system(
        scope="author_twain", task="t", mode=JobMode.DEBATE,
    )
    stable = blocks[0]["text"]
    assert "DEBATE mode" in stable
    assert "quote" in stable.lower()


# ---------- volatile suffix ordering --------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_retrieved_chunks_render_with_chunk_id_marker() -> None:
    """The validator looks for `#chunk_id` citations in model output. If
    the chunks in the prompt render with a different marker shape, the
    model won't know how to cite them correctly."""
    ch = _chunk(cid="chk_xyz", content="chunk contents here",
                title="Huck Finn", date="1884-12-10")
    blocks = compose_system(
        scope="author_twain", task="t", mode=JobMode.GROUNDED,
        retrieved_chunks=[ch],
    )
    volatile = blocks[1]["text"]
    assert "[#chk_xyz]" in volatile
    assert "Huck Finn" in volatile
    assert "1884-12-10" in volatile
    assert "chunk contents here" in volatile


@pytest.mark.usefixtures("fresh_db")
def test_style_anchors_capped_at_800_chars_per_chunk() -> None:
    """Style anchors are for voice calibration — they burn volatile
    tokens every call. 800 chars/chunk keeps the volatile section
    bounded even with 5 anchors."""
    long = "x" * 5000
    anchor = _chunk(cid="sa_1", content=long)
    blocks = compose_system(
        scope="author_twain", task="t", mode=JobMode.CHAT,
        style_anchors=[anchor],
    )
    volatile = blocks[1]["text"]
    # Full 5000 chars does NOT appear
    assert long not in volatile
    # But the first 800 do
    assert "x" * 800 in volatile


@pytest.mark.usefixtures("fresh_db")
def test_examples_limited_to_first_three() -> None:
    """Budget discipline per the plan: >3 examples means more volatile
    cost per call with diminishing quality return."""
    examples = [
        {"task_description": f"Q{i}", "good_response": f"A{i}"}
        for i in range(10)
    ]
    blocks = compose_system(
        scope="orchestrator", task="t", mode=JobMode.CHAT,
        examples=examples,
    )
    volatile = blocks[1]["text"]
    assert "Q0" in volatile
    assert "Q2" in volatile
    assert "Q3" not in volatile  # only first 3


# ---------- stability guard --------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_stable_prefix_is_byte_identical_across_calls_with_same_inputs() -> None:
    """If the stable prefix changes between calls with identical inputs
    (scope + mode + DB heuristics state), Anthropic's cache will miss
    every call. Pin byte-for-byte identity."""
    conn = connect()
    try:
        with transaction(conn):
            from donna.memory import prompts as prompts_mod
            prompts_mod.insert_heuristic(
                conn, agent_scope="author_twain",
                heuristic="First rule.", status="active",
            )
            prompts_mod.insert_heuristic(
                conn, agent_scope="author_twain",
                heuristic="Second rule.", status="active",
            )
    finally:
        conn.close()

    a = compose_system(scope="author_twain", task="t1", mode=JobMode.GROUNDED)
    b = compose_system(scope="author_twain", task="t2", mode=JobMode.GROUNDED)

    # Stable prefix identical — only task block should differ
    assert a[0]["text"] == b[0]["text"]
    assert a[0]["cache_control"] == b[0]["cache_control"]


@pytest.mark.usefixtures("fresh_db")
def test_adding_heuristic_invalidates_stable_prefix() -> None:
    """Cache invalidation — adding an active heuristic MUST change the
    stable prefix (new rule actually gets applied). If the prefix stayed
    identical, the new rule would take effect only on fresh-cache calls."""
    before = compose_system(
        scope="author_twain", task="t", mode=JobMode.GROUNDED,
    )[0]["text"]

    conn = connect()
    try:
        with transaction(conn):
            from donna.memory import prompts as prompts_mod
            prompts_mod.insert_heuristic(
                conn, agent_scope="author_twain",
                heuristic="A fresh rule.", status="active",
            )
    finally:
        conn.close()

    after = compose_system(
        scope="author_twain", task="t", mode=JobMode.GROUNDED,
    )[0]["text"]
    assert after != before
    assert "A fresh rule." in after


@pytest.mark.usefixtures("fresh_db")
def test_different_modes_produce_different_stable_prefixes() -> None:
    """chat vs grounded vs speculative MUST have different stable prefixes —
    they have different mode instructions. A shared cache key across modes
    would serve wrong instructions to some of them."""
    a = compose_system(scope="s", task="t", mode=JobMode.CHAT)[0]["text"]
    b = compose_system(scope="s", task="t", mode=JobMode.GROUNDED)[0]["text"]
    c = compose_system(scope="s", task="t", mode=JobMode.SPECULATIVE)[0]["text"]
    d = compose_system(scope="s", task="t", mode=JobMode.DEBATE)[0]["text"]
    assert len({a, b, c, d}) == 4, "each mode must produce a distinct prefix"

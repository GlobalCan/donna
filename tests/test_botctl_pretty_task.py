"""_pretty_task renders `botctl jobs` task column readably for debate jobs.

Debate task payloads are JSON, which gets truncated to 60 chars mid-key
and looks terrible in the jobs table. This helper decodes the payload
and renders 'scope_a vs scope_b: topic' instead.

All other modes fall through to the prior behavior (verbatim truncated).
"""
from __future__ import annotations

import json

from donna.cli.botctl import _pretty_task


def test_debate_task_rendered_as_scopes_and_topic() -> None:
    payload = json.dumps({
        "scope_a": "author_lewis",
        "scope_b": "author_dalio",
        "topic": "humility and incentives",
        "rounds": 3,
    })
    assert _pretty_task(payload, "debate") == "author_lewis vs author_dalio: humility and incentives"


def test_debate_task_with_panel_of_four() -> None:
    payload = json.dumps({
        "scope_a": "a",
        "scope_b": "b",
        "scope_c": "c",
        "scope_d": "d",
        "topic": "x",
        "rounds": 2,
    })
    assert _pretty_task(payload, "debate") == "a vs b vs c vs d: x"


def test_debate_task_missing_topic_shows_scopes_only() -> None:
    payload = json.dumps({"scope_a": "a", "scope_b": "b", "rounds": 2})
    assert _pretty_task(payload, "debate") == "a vs b"


def test_debate_task_malformed_json_falls_back_to_truncation() -> None:
    """An unparseable debate task shouldn't kill the table render."""
    bad = '{"scope_a": "lewis", "rounds": [malformed'
    out = _pretty_task(bad, "debate")
    assert len(out) <= 60
    # Falls back to verbatim truncation
    assert out == bad[:60]


def test_debate_task_non_dict_root_falls_back() -> None:
    """json.loads('[]') returns a list; defensively use the verbatim path."""
    assert _pretty_task("[]", "debate") == "[]"


def test_non_debate_task_passes_through_truncated() -> None:
    task = "summarize the arxiv preprints on large language model safety from this week"
    assert _pretty_task(task, "chat") == task[:60]


def test_non_debate_task_with_json_payload_does_not_reinterpret() -> None:
    """A chat-mode task that happens to start with `{` shouldn't get
    treated as debate JSON — only mode='debate' triggers the parse."""
    task = "{not really json}"
    assert _pretty_task(task, "chat") == task[:60]


def test_debate_task_caps_rendered_output_at_60_chars() -> None:
    payload = json.dumps({
        "scope_a": "a very long author scope name that goes on",
        "scope_b": "another equally long scope name",
        "topic": "plus a verbose topic about many things at once",
        "rounds": 1,
    })
    out = _pretty_task(payload, "debate")
    assert len(out) <= 60

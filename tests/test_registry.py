"""Tool registry sanity — @tool decorator registers, schema is well-formed."""
from __future__ import annotations

import donna.tools  # noqa: F401 — triggers registration
from donna.tools.registry import REGISTRY, anthropic_tool_defs


def test_core_tools_registered() -> None:
    for name in [
        "search_web", "fetch_url", "search_news",
        "save_artifact", "read_artifact", "list_artifacts",
        "remember", "recall", "forget",
        "ask_user", "send_update", "run_python",
        "teach", "recall_knowledge", "recall_heuristics",
        "propose_heuristic", "list_knowledge",
    ]:
        assert name in REGISTRY, f"tool {name} missing from registry"


def test_tool_defs_shape() -> None:
    defs = anthropic_tool_defs()
    assert len(defs) > 0
    for d in defs:
        assert "name" in d
        assert "description" in d
        assert "input_schema" in d
        assert d["input_schema"]["type"] == "object"

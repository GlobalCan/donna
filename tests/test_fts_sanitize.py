"""FTS5 query sanitization — prevents OperationalError on natural-language input.

Discovered live during the Huck Finn grounded-mode smoke test: a question ending
in `?` raised ``sqlite3.OperationalError: fts5: syntax error near "?"``. FTS5
reserves `" ( ) * ? : + ^ ~ -` plus bareword operators (AND/OR/NOT/NEAR), so
any natural-language input containing those characters broke keyword search.
"""
from __future__ import annotations

import pytest

from donna.memory import knowledge as kn
from donna.memory.db import connect, transaction


def test_fts_sanitize_strips_reserved_chars() -> None:
    # Reserved FTS5 chars must not appear in the output — each token is quoted.
    out = kn._fts_sanitize('What does Huck say about "civilization"?')
    assert '?' not in out
    assert '"civilization"' in out  # quoted token, not unbalanced reservation
    assert out.count('"') % 2 == 0


def test_fts_sanitize_empty_for_pure_punctuation() -> None:
    assert kn._fts_sanitize("?!(*)") == ""
    assert kn._fts_sanitize("") == ""


def test_fts_sanitize_handles_operator_barewords() -> None:
    # "AND", "OR", "NOT", "NEAR" must be quoted so FTS5 treats them as terms,
    # not operators, otherwise a query like "cats and dogs" gets parsed as
    # `cats AND dogs AND ...` which is already the default but would break
    # as soon as a user wrote "dogs or cats".
    out = kn._fts_sanitize("cats OR dogs")
    assert '"OR"' in out


@pytest.mark.usefixtures("fresh_db")
def test_keyword_search_survives_punctuation_query() -> None:
    """Main regression: FTS5 reserved chars in the query no longer raise."""
    conn = connect()
    try:
        with transaction(conn):
            sid = kn.insert_source(
                conn, agent_scope="t", source_type="book",
                title="Huck Finn", copyright_status="public_domain",
            )
            # Content aligned with the query so FTS5's implicit-AND matches.
            kn.insert_chunk(
                conn, source_id=sid, agent_scope="t",
                content=(
                    "What does Huck say about civilization? He reflects on "
                    "civilization and Miss Watson often."
                ),
                chunk_index=0, fingerprint="fp1",
                embedding=None, work_id=None,
                publication_date=None, source_type="book",
            )

        # The live-prod bug: trailing `?` used to raise
        # `sqlite3.OperationalError: fts5: syntax error near "?"`.
        hits = kn.keyword_search(
            conn, agent_scope="t",
            query="What does Huck say about civilization?",
        )
        assert len(hits) == 1
        chunk, _score = hits[0]
        assert "civilization" in chunk.content

        # Other reserved chars — none of these should raise.
        for q in ('parens (test)', 'star*query', 'colon:test', 'quote"test', '-minus'):
            # We only care that it doesn't throw. Match count is incidental.
            _ = kn.keyword_search(conn, agent_scope="t", query=q)

        # Pure-punctuation input short-circuits to empty instead of round-tripping.
        assert kn.keyword_search(conn, agent_scope="t", query="???") == []
        assert kn.keyword_search(conn, agent_scope="t", query="") == []
    finally:
        conn.close()

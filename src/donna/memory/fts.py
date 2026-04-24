"""FTS5 query sanitization — shared helper for every `*_fts MATCH ?` caller.

FTS5 reserves `" ( ) * ? : + ^ ~ -` plus bareword operators (`AND OR NOT NEAR`).
Passing raw natural-language input into a MATCH expression raises
``sqlite3.OperationalError: fts5: syntax error``. This helper tokenizes on
word characters and wraps each token in double quotes so special characters
inside are treated literally; the implicit conjunction across quoted terms
preserves the default AND semantics.

Originally introduced in PR #15 as a private helper in `knowledge.py` after
we hit the bug live with a `?`-terminated grounded-mode query. `recall()` on
`facts_fts` had the same latent bug; extracting here so both callers share
one implementation.
"""
from __future__ import annotations

import re


def fts_sanitize(query: str) -> str:
    """Return a safe FTS5 MATCH expression for an arbitrary input string.

    Empty / pure-punctuation input returns an empty string; callers should
    short-circuit to ``[]`` rather than round-trip to SQLite.
    """
    tokens = re.findall(r"\w+", query)
    return " ".join(f'"{t}"' for t in tokens)

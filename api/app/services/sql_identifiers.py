"""Validation for SQL identifiers that reach generated SQL.

Table and column names supplied by a user (freshness probes, notification
conditions) are interpolated into queries rather than bound as parameters,
because a placeholder cannot stand in for an identifier. They are therefore
checked against this pattern at write time *and* again at execution time — one
check is one deploy away from being the only check.
"""

from __future__ import annotations

import re

# A plain unquoted SQL identifier: letters, digits and underscores, not starting
# with a digit. Deliberately narrower than what PostgreSQL accepts — anything
# needing quoting is rejected rather than escaped.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_valid_identifier(name: str) -> bool:
    """Return True if the name is a plain SQL identifier."""
    return bool(_IDENTIFIER.match(name))

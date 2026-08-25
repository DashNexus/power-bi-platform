"""Read-only validation for user-authored report SQL.

A report runs SQL the user typed against a live database connection, so the
statement is checked before it is ever handed to a driver. The check runs at
write time *and* again immediately before execution — one check is one deploy
away from being the only check (the same reasoning as
``app.services.sql_identifiers``).

This is one of several layers, and it is the weakest of them. The others are
worth more: every report query runs inside a transaction that is always rolled
back, PostgreSQL sessions are additionally set ``READ ONLY`` so the server
itself refuses writes (both in ``app.services.export_source``), and the
connection a report runs against should use a login with only SELECT rights.
A parser can be out-thought; a database that refuses the write cannot be.

The keyword list is not only about statements that *start* a write. Two classes
of construct write from inside an ordinary-looking SELECT, and one of them
survives the rollback:

- Data-modifying CTEs (``WITH x AS (DELETE ... RETURNING *) SELECT * FROM x``)
  are real writes that lead with an allowed keyword. The rollback does undo
  these, but they should never reach the driver.
- Sequence functions (``nextval``, ``setval``, ``NEXT VALUE FOR``) are defined
  as non-transactional on both engines: a rollback does **not** put the sequence
  back. Likewise ``dblink``, which writes to a different server outside our
  transaction, and ``lo_export``, which writes a file. For these the parser is
  the only layer that applies, which is why they are here rather than trusted to
  the rollback.
"""

from __future__ import annotations

import re

# Statements that may begin a read-only query. Anything else is refused
# outright rather than inspected further.
_ALLOWED_LEADS = ("select", "with")

# Words that write, change structure, change permissions, or run code. Matched
# whole-word against the comment- and literal-stripped statement, so a column
# named "updated_at" or the string 'deleted' cannot trip them.
#
# Most of these cannot legally follow SELECT, and the lead check already refuses
# them in first position — but PostgreSQL's data-modifying CTEs make
# `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x` a real write that
# leads with an allowed keyword. That is what this list is for.
#
# REPLACE is deliberately absent: it is an ordinary string function, and the
# only writing form (MySQL's REPLACE INTO) is caught by the INTO check.
_FORBIDDEN_KEYWORDS = frozenset(
    {
        "alter", "attach", "backup", "call", "checkpoint", "commit", "copy",
        "create", "deallocate", "declare", "delete", "deny", "detach", "do",
        "drop", "exec", "execute", "grant", "insert", "kill", "lock", "merge",
        "openquery", "openrowset", "prepare", "reconfigure", "reindex",
        "release", "rename", "restore", "revoke", "rollback",
        "savepoint", "set", "setuser", "shutdown", "truncate", "update",
        "upsert", "vacuum", "waitfor", "writetext",
        # Functions that write from inside a SELECT. These matter more than the
        # statement keywords above, because the always-rollback layer does not
        # catch them:
        #   nextval/setval advance a sequence, which PostgreSQL and SQL Server
        #     both define as non-transactional — a rollback does not put it back.
        #   lo_* read and write files on the database server.
        #   dblink* run arbitrary SQL on *another* server, outside our
        #     transaction entirely.
        #   opendatasource is the same idea in T-SQL (openquery and openrowset
        #     are covered above).
        "nextval", "setval",
        "lo_export", "lo_import", "lo_put", "lo_unlink", "lo_from_bytea",
        "dblink", "dblink_exec", "dblink_send_query", "dblink_open",
        "opendatasource",
    }
)

# Constructs whose danger is in the phrase, not in any single word.
# `NEXT VALUE FOR seq` is T-SQL's sequence advance: none of "next", "value" or
# "for" can be banned on its own without rejecting ordinary queries.
_FORBIDDEN_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bnext\s+value\s+for\b"),
        "NEXT VALUE FOR advances a sequence, which a rollback does not undo",
    ),
    (
        re.compile(r"\bfor\s+(?:update|no\s+key\s+update)\b"),
        "FOR UPDATE takes write locks",
    ),
)

# `SELECT ... INTO t` creates a table on SQL Server, and `INSERT INTO` is caught
# by the keyword list. `INTO` is only legitimate here inside a CTE body, which
# this build does not try to distinguish — so it is refused everywhere.
_INTO = re.compile(r"\binto\b")

# T-SQL and PostgreSQL procedure prefixes: sp_executesql, xp_cmdshell, pg_read_file.
_PROC_PREFIX = re.compile(r"\b(sp|xp|pg)_\w+")

_WORD = re.compile(r"[a-z_][a-z0-9_]*")


class ReadOnlySqlError(ValueError):
    """Raised when report SQL is not a single read-only statement."""


def strip_noise(sql: str, *, keep_identifiers: bool = False) -> str:
    """Return sql with comments and literals blanked out.

    Keywords are matched against this rather than the raw text, so a literal
    such as ``'; drop table users --'`` cannot smuggle one past the check.
    A blanked span becomes a space rather than nothing, so token boundaries
    survive.

    Args:
        sql: The statement to strip.
        keep_identifiers: When True, quoted *identifiers* — ``[users]``,
            ``"users"``, ``` `users` ``` — keep their contents, unwrapped.
            The keyword guard wants them blanked, because a column legitimately
            named ``[delete]`` must not trip it. A caller matching on **table
            names** wants the opposite: ``[dbo].[users]`` and ``dbo.users`` name
            the same table, and blanking hides only one of them.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if ch == "-" and nxt == "-":
            i = sql.find("\n", i)
            if i == -1:
                break
            continue
        if ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue
        if ch == "'":
            # A string literal is never an identifier, so it is blanked either way.
            i += 1
            while i < n:
                if sql[i] == "'":
                    # A doubled quote is an escaped quote, not the end.
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        if ch in ('"', "`"):
            quote = ch
            i += 1
            start = i
            while i < n:
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    break
                i += 1
            out.append(f" {sql[start:i]} " if keep_identifiers else " ")
            i = min(i + 1, n)
            continue
        if ch == "[":
            end = sql.find("]", i)
            if end == -1:
                out.append(" ")
                i = n
                continue
            out.append(f" {sql[i + 1 : end]} " if keep_identifiers else " ")
            i = end + 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _single_statement(stripped: str) -> str:
    """Return the statement, refusing anything after a semicolon.

    A trailing semicolon is fine; a second statement is what stacked-query
    injection looks like.
    """
    parts = [p for p in stripped.split(";") if p.strip()]
    if len(parts) > 1:
        raise ReadOnlySqlError(
            "Only one statement is allowed. Remove everything after the first semicolon."
        )
    return parts[0] if parts else ""


def assert_read_only(sql: str) -> None:
    """Raise ReadOnlySqlError unless sql is a single read-only SELECT.

    Raises:
        ReadOnlySqlError: With a message written for the person who typed the
            query, since it is surfaced directly in the report editor.
    """
    if not sql or not sql.strip():
        raise ReadOnlySqlError("The query is empty.")

    stripped = _single_statement(strip_noise(sql).lower())
    if not stripped.strip():
        raise ReadOnlySqlError("The query contains no statement.")

    lead = stripped.strip().lstrip("(").strip()
    if not lead.startswith(_ALLOWED_LEADS):
        raise ReadOnlySqlError("Only SELECT queries can be used in a report.")

    words = set(_WORD.findall(stripped))
    forbidden = sorted(words & _FORBIDDEN_KEYWORDS)
    if forbidden:
        raise ReadOnlySqlError(
            f"A report query cannot use: {', '.join(forbidden).upper()}."
        )

    for pattern, why in _FORBIDDEN_PHRASES:
        if pattern.search(stripped):
            raise ReadOnlySqlError(f"A report query cannot use this: {why}.")

    if _INTO.search(stripped):
        raise ReadOnlySqlError("SELECT ... INTO writes a new table, so it cannot be used here.")

    proc = _PROC_PREFIX.search(stripped)
    if proc:
        raise ReadOnlySqlError(
            f"System procedures cannot be called from a report ({proc.group(0)})."
        )


def is_read_only(sql: str) -> bool:
    """Return True if assert_read_only would accept sql."""
    try:
        assert_read_only(sql)
    except ReadOnlySqlError:
        return False
    return True

"""Tests for the read-only report SQL guard.

The interesting cases are the ones that look like a SELECT: a data-modifying
CTE leads with WITH, and a stacked statement leads with SELECT.
"""

from __future__ import annotations

import pytest

from app.services.sql_guard import ReadOnlySqlError, assert_read_only, is_read_only, strip_noise

ACCEPTED = [
    "SELECT 1",
    "select * from marts.orders",
    "SELECT TOP (1000) [id], [name] FROM [db].[dbo].[orgs]",
    "  SELECT a FROM t WHERE b = 'delete from x'  ",
    "SELECT REPLACE(name, 'a', 'b') AS n FROM t",
    "WITH recent AS (SELECT * FROM t WHERE d > '2020-01-01') SELECT * FROM recent",
    "SELECT * FROM t -- drop table users\n",
    "SELECT * FROM t /* update t set x=1 */",
    "SELECT * FROM t ORDER BY id OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY",
    "SELECT * FROM orders;",
    "(SELECT a FROM t) UNION ALL (SELECT b FROM u)",
    'SELECT "set", "update" FROM quoted_columns',
    "SELECT [set] FROM bracket_columns",
]

REJECTED = [
    ("", "empty"),
    ("   ", "empty"),
    ("DELETE FROM users", "not a select"),
    ("UPDATE t SET x = 1", "not a select"),
    ("INSERT INTO t VALUES (1)", "not a select"),
    ("DROP TABLE users", "not a select"),
    ("TRUNCATE TABLE t", "not a select"),
    ("EXEC sp_who", "not a select"),
    ("SELECT 1; DROP TABLE users", "stacked statement"),
    ("SELECT 1; SELECT 2", "stacked statement"),
    ("SELECT * INTO backup FROM users", "select into"),
    ("SELECT * FROM t; -- trailing\nDELETE FROM t", "stacked statement"),
    (
        "WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone",
        "data-modifying CTE",
    ),
    (
        "WITH x AS (UPDATE t SET a = 1 RETURNING *) SELECT * FROM x",
        "data-modifying CTE",
    ),
    ("SELECT * FROM OPENROWSET('x','y','z')", "openrowset"),
    ("SELECT * FROM t WHERE 1=1 WAITFOR DELAY '00:00:10'", "waitfor"),
    ("SELECT xp_cmdshell('dir')", "system procedure"),
    ("SELECT pg_read_file('/etc/passwd')", "system procedure"),
    ("MERGE t USING s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.a = s.a", "not a select"),
    ("GRANT SELECT ON t TO public", "not a select"),
]


@pytest.mark.parametrize("sql", ACCEPTED)
def test_assert_read_only_accepts_select_queries(sql: str) -> None:
    assert_read_only(sql)

    assert is_read_only(sql) is True


@pytest.mark.parametrize(("sql", "why"), REJECTED)
def test_assert_read_only_rejects_writes(sql: str, why: str) -> None:
    with pytest.raises(ReadOnlySqlError):
        assert_read_only(sql)

    assert is_read_only(sql) is False


def test_strip_noise_blanks_string_literals_so_keywords_inside_them_do_not_match() -> None:
    stripped = strip_noise("SELECT 'drop table users' FROM t")

    assert "drop" not in stripped.lower()
    assert "from t" in stripped.lower()


def test_strip_noise_handles_doubled_quotes_without_ending_the_literal() -> None:
    # 'it''s; delete from t' is one literal, not a literal followed by a statement.
    stripped = strip_noise("SELECT 'it''s; delete from t' FROM x")

    assert "delete" not in stripped.lower()
    assert ";" not in stripped


def test_strip_noise_blanks_bracket_quoted_identifiers() -> None:
    stripped = strip_noise("SELECT [delete] FROM [update]")

    assert "delete" not in stripped.lower()
    assert "update" not in stripped.lower()


def test_keep_identifiers_exposes_bracket_quoted_table_names() -> None:
    # Callers matching on table names need [dbo].[users] to read as "users";
    # the keyword guard needs the opposite. One function, two callers.
    stripped = strip_noise("SELECT * FROM [dbo].[users]", keep_identifiers=True)

    assert "users" in stripped.lower()


def test_keep_identifiers_still_blanks_string_literals() -> None:
    # An identifier is not a literal: exposing the first must not expose the
    # second, or a quoted string becomes a way to smuggle a name past a check.
    stripped = strip_noise("SELECT 'users' FROM [orgs]", keep_identifiers=True)

    assert "users" not in stripped.lower()
    assert "orgs" in stripped.lower()


def test_keep_identifiers_exposes_double_quoted_names() -> None:
    stripped = strip_noise('SELECT * FROM "users"', keep_identifiers=True)

    assert "users" in stripped.lower()


def test_an_unterminated_bracket_does_not_leak_its_contents() -> None:
    stripped = strip_noise("SELECT * FROM [users", keep_identifiers=False)

    assert "users" not in stripped.lower()


def test_unterminated_block_comment_does_not_hide_the_rest_of_the_statement() -> None:
    # An unclosed /* consumes to end of input, so nothing can follow it either.
    with pytest.raises(ReadOnlySqlError):
        assert_read_only("/* SELECT 1")


def test_error_message_names_the_offending_keyword() -> None:
    with pytest.raises(ReadOnlySqlError) as exc:
        assert_read_only("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x")

    assert "DELETE" in str(exc.value)


# ---------------------------------------------------------------------------
# Adversarial suite
# ---------------------------------------------------------------------------

# Every entry is a way to write data (or burn the server) from a statement that
# leads with SELECT or WITH, so none of them is caught by the "must start with
# SELECT" rule. Three of them survive the always-rollback layer as well, which
# is why the parser has to catch them:
#   - nextval / setval / NEXT VALUE FOR: sequence advances are non-transactional
#     on both PostgreSQL and SQL Server.
#   - dblink*: runs on a different server, outside our transaction.
#   - lo_export: writes a file on the database host.
WRITE_TECHNIQUES = [
    ("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "postgres delete CTE"),
    ("WITH i AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM i", "postgres insert CTE"),
    ("WITH u AS (UPDATE t SET a=1 RETURNING *) SELECT * FROM u", "postgres update CTE"),
    ("SELECT nextval('my_seq')", "postgres nextval"),
    ("SELECT setval('my_seq', 999)", "postgres setval"),
    ("SELECT NEXT VALUE FOR dbo.my_seq", "t-sql NEXT VALUE FOR"),
    ("select   next    value   for  s", "NEXT VALUE FOR with odd spacing"),
    ("SELECT lo_export(1234, '/tmp/pwned')", "postgres lo_export writes a file"),
    ("SELECT lo_import('/etc/passwd')", "postgres lo_import reads a file"),
    ("SELECT dblink_exec('dbname=x', 'DELETE FROM t')", "dblink_exec on another server"),
    ("SELECT * FROM dblink('dbname=x','DELETE FROM t') AS z(a int)", "dblink on another server"),
    ("SELECT * FROM OPENDATASOURCE('SQLOLEDB','...').db.dbo.t", "t-sql OPENDATASOURCE"),
    ("SELECT * FROM OPENQUERY(srv, 'DELETE FROM t')", "t-sql OPENQUERY"),
    ("SELECT * FROM OPENROWSET('SQLNCLI','...','DELETE FROM t')", "t-sql OPENROWSET"),
    ("SELECT * FROM t FOR UPDATE", "FOR UPDATE takes write locks"),
    ("SELECT * FROM sp_helpuser", "system procedure"),
    ("SELECT xp_cmdshell('del /f *')", "xp_cmdshell runs OS commands"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_ file read"),
    ("SELECT 1 WHERE 1=1 WAITFOR DELAY '00:10:00'", "WAITFOR burns a connection"),
    ("SELECT 1; DELETE FROM t", "stacked statement"),
    ("SELECT 1 /* x */; DROP TABLE t", "stacked behind a block comment"),
    ("SELECT 1 -- c\nDROP TABLE t", "write on the line after a comment"),
    ("SELECT * INTO evil FROM t", "SELECT INTO creates a table"),
    ("select a into outfile '/tmp/x' from t", "mysql INTO OUTFILE"),
    ("SeLeCt 1; DeLeTe FROM t", "mixed case"),
    ("SELECT/**/1;/**/DROP/**/TABLE/**/t", "comments instead of spaces"),
    ("   \n\t SELECT * INTO x FROM t", "leading whitespace"),
]

# The guard is worth nothing if it also rejects the queries people actually
# write, because the next step is someone turning it off.
LEGITIMATE_QUERIES = [
    ("SELECT * FROM marts.orders", "a plain select"),
    ("SELECT TOP (1000) [id],[name] FROM [db].[dbo].[orgs]", "the form SSMS generates"),
    ("WITH r AS (SELECT * FROM t WHERE d > '2020-01-01') SELECT * FROM r", "a read-only CTE"),
    ("SELECT REPLACE(name,'a','b'), UPPER(x) FROM t", "string functions"),
    ("SELECT a FROM t ORDER BY id OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY", "paging"),
    ("SELECT COUNT(*) AS n FROM t GROUP BY k HAVING COUNT(*) > 1", "aggregation"),
    ("SELECT * FROM a JOIN b ON a.id=b.a_id LEFT JOIN c ON c.b_id=b.id", "joins"),
    ("SELECT CASE WHEN x > 1 THEN 'set' ELSE 'unset' END FROM t", "a blocked word as a literal"),
    ("SELECT next_review_date, value_for_money FROM t", "columns resembling a blocked phrase"),
    ("SELECT updated_at, created_at FROM t WHERE deleted_at IS NULL", "columns named after verbs"),
    ("SELECT * FROM t WHERE note = 'please delete this row'", "a verb inside a string"),
]


@pytest.mark.parametrize(("sql", "technique"), WRITE_TECHNIQUES)
def test_write_techniques_are_all_refused(sql: str, technique: str) -> None:
    assert is_read_only(sql) is False, f"{technique} was allowed through"


@pytest.mark.parametrize(("sql", "shape"), LEGITIMATE_QUERIES)
def test_ordinary_read_queries_are_not_false_positives(sql: str, shape: str) -> None:
    assert is_read_only(sql) is True, f"{shape} was wrongly rejected"


def test_the_non_transactional_writes_are_caught_by_the_parser_specifically() -> None:
    # These three do not survive as a rollback problem — a rollback does not
    # undo them at all — so the parser is the only layer that applies. If any of
    # them ever stops being refused here, nothing else will catch it.
    for sql in (
        "SELECT nextval('s')",
        "SELECT setval('s', 1)",
        "SELECT NEXT VALUE FOR s",
        "SELECT dblink_exec('dbname=x', 'DELETE FROM t')",
        "SELECT lo_export(1, '/tmp/x')",
    ):
        assert is_read_only(sql) is False, sql

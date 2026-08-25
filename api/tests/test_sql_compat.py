"""Unit tests for the PostgreSQL / Azure SQL syntax differences."""

from __future__ import annotations

import pytest

from app import sql_compat


class TestPaginateClause:
    def test_postgres_uses_limit_offset(self) -> None:
        assert sql_compat.paginate_clause("postgresql") == "LIMIT :page_size OFFSET :offset"

    def test_sql_server_uses_offset_fetch(self) -> None:
        assert (
            sql_compat.paginate_clause("mssql")
            == "OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY"
        )

    def test_unknown_dialect_falls_back_to_the_standard_form(self) -> None:
        """LIMIT/OFFSET is the wider spelling, so it is the safer default."""
        assert sql_compat.paginate_clause("sqlite") == "LIMIT :page_size OFFSET :offset"


class TestRowLimitClause:
    def test_sql_server_caps_before_the_projection(self) -> None:
        prefix, suffix = sql_compat.row_limit_clause("mssql", 500)

        assert (prefix, suffix) == ("TOP (500) ", "")

    def test_postgres_caps_after_the_table(self) -> None:
        prefix, suffix = sql_compat.row_limit_clause("postgresql", 500)

        assert (prefix, suffix) == ("", " LIMIT 500")

    def test_a_non_numeric_limit_raises_rather_than_reaching_sql(self) -> None:
        """The value is interpolated, so anything unparseable must stop here."""
        with pytest.raises(ValueError, match="invalid literal"):
            sql_compat.row_limit_clause("mssql", "10; DROP TABLE users")  # type: ignore[arg-type]


class TestSchemaFreshnessSql:
    def test_sql_server_reads_index_statistics(self) -> None:
        assert "STATS_DATE" in sql_compat.schema_freshness_sql("mssql")

    def test_postgres_reads_the_autovacuum_stats(self) -> None:
        assert "pg_stat_user_tables" in sql_compat.schema_freshness_sql("postgresql")

    def test_both_project_a_column_named_last_updated(self) -> None:
        """`routers/data.py` reads the first column positionally either way."""
        for dialect in ("mssql", "postgresql"):
            assert "AS last_updated" in sql_compat.schema_freshness_sql(dialect)

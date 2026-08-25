"""Tests for report source resolution and the ceilings on what a query may cost.

The row cap is the obvious limit; the cell cap is the one that matters, because
a thousand rows of three hundred columns costs the same memory as a hundred
thousand of three and only one of them looks large.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import export_source
from app.services.export_source import ExportSourceError, denied_operations_tables


class TestOperationsDenylist:
    """Credential-bearing tables are refused however they are spelled."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users",
            "SELECT * FROM dbo.users",
            "SELECT * FROM [bi_platform_database].[dbo].[users]",
            "select u.email from USERS u",
            "SELECT * FROM orgs JOIN users ON users.org_id = orgs.id",
            "SELECT * FROM warehouse_connections",
            "SELECT * FROM auth_provider_configs",
        ],
    )
    def test_denied(self, sql: str) -> None:
        assert denied_operations_tables(sql) != []

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM orgs",
            "SELECT * FROM dashboards",
            # A column or table whose name merely contains a denied word is fine.
            "SELECT users_created, id FROM org_stats",
            "SELECT * FROM user_activity",
        ],
    )
    def test_allowed(self, sql: str) -> None:
        assert denied_operations_tables(sql) == []

    def test_a_denied_name_inside_a_string_literal_does_not_trip_it(self) -> None:
        # strip_noise blanks literals, so this is a query about the word, not
        # the table.
        assert denied_operations_tables("SELECT 'users' AS label FROM orgs") == []


class TestRunReportQuery:
    """Guards that run before any driver sees the statement."""

    @pytest.mark.asyncio
    async def test_write_sql_is_refused_even_if_it_reached_here(self) -> None:
        with pytest.raises(ExportSourceError):
            await export_source.run_report_query(
                MagicMock(),
                org_id=1,
                source_kind="warehouse",
                sql="DELETE FROM orders",
                warehouse_connection_id=1,
            )

    @pytest.mark.asyncio
    async def test_unknown_source_kind_is_refused(self) -> None:
        with pytest.raises(ExportSourceError, match="Unknown report source"):
            await export_source.run_report_query(
                MagicMock(),
                org_id=1,
                source_kind="somewhere",
                sql="SELECT 1",
                warehouse_connection_id=1,
            )

    @pytest.mark.asyncio
    async def test_warehouse_source_without_a_connection_is_refused(self) -> None:
        with pytest.raises(ExportSourceError, match="no warehouse connection"):
            await export_source.run_report_query(
                MagicMock(),
                org_id=1,
                source_kind="warehouse",
                sql="SELECT 1",
                warehouse_connection_id=None,
            )

    @pytest.mark.asyncio
    async def test_operations_source_refuses_a_credential_table(self) -> None:
        with pytest.raises(ExportSourceError, match="cannot be exported"):
            await export_source.run_report_query(
                MagicMock(),
                org_id=1,
                source_kind="operations",
                sql="SELECT * FROM users",
                warehouse_connection_id=None,
            )


class TestTimeoutDetection:
    """A timeout must read as a timeout, not as an opaque driver string."""

    @pytest.mark.parametrize(
        "message",
        [
            "[HYT00] [Microsoft][ODBC Driver 18] Query timeout expired",
            "canceling statement due to statement timeout",
            "Query execution was interrupted, max_execution_time exceeded",
            "Statement timeout reached",
        ],
    )
    def test_recognised(self, message: str) -> None:
        assert export_source._looks_like_timeout(message) is True

    @pytest.mark.parametrize(
        "message",
        ["Invalid object name 'nope'.", "Login failed for user 'x'.", "syntax error at or near"],
    )
    def test_other_errors_are_not_mistaken_for_one(self, message: str) -> None:
        assert export_source._looks_like_timeout(message) is False


class TestResultCeilings:
    """How many rows actually come back, given both caps."""

    def _run(self, columns: list[str], available: int, max_rows: int, max_cells: int) -> tuple:
        """Drive _run_select_sync against a fake driver returning `available` rows."""
        result = MagicMock()
        result.keys.return_value = columns
        result.fetchmany.side_effect = lambda n: [
            [i] * len(columns) for i in range(min(n, available))
        ]

        connection = MagicMock()
        connection.execute.return_value = result
        connection.dialect.name = "sqlite"
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection

        with patch.object(export_source.sa, "create_engine", return_value=engine):
            return export_source._run_select_sync(
                "sqlite://", {}, "SELECT 1", max_rows, 30, max_cells
            )

    def test_row_cap_binds_on_a_narrow_result(self) -> None:
        columns, rows, truncated = self._run(["a", "b"], available=500, max_rows=100,
                                             max_cells=1_000_000)

        assert len(rows) == 100
        assert truncated is True
        assert columns == ["a", "b"]

    def test_cell_cap_binds_before_the_row_cap_on_a_wide_result(self) -> None:
        # 300 columns against a 3,000-cell budget leaves room for 10 rows,
        # nothing like the 1,000-row cap.
        _columns, rows, truncated = self._run(
            [f"c{i}" for i in range(300)], available=1000, max_rows=1000, max_cells=3000
        )

        assert len(rows) == 10
        assert truncated is True

    def test_a_result_inside_both_caps_is_not_marked_truncated(self) -> None:
        _columns, rows, truncated = self._run(["a"], available=5, max_rows=100,
                                              max_cells=1_000_000)

        assert len(rows) == 5
        assert truncated is False

    def test_the_transaction_is_rolled_back_even_on_success(self) -> None:
        result = MagicMock()
        result.keys.return_value = ["a"]
        result.fetchmany.return_value = [[1]]
        connection = MagicMock()
        connection.execute.return_value = result
        connection.dialect.name = "sqlite"
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection

        with patch.object(export_source.sa, "create_engine", return_value=engine):
            export_source._run_select_sync("sqlite://", {}, "SELECT 1", 10, 30, 1000)

        connection.begin.return_value.rollback.assert_called_once()
        connection.begin.return_value.commit.assert_not_called()


class TestStatementTimeout:
    """Each engine is told to give up in its own spelling."""

    @pytest.mark.parametrize(
        ("dialect", "expected"),
        [
            ("postgresql", "SET statement_timeout = 30000"),
            ("mysql", "SET SESSION max_execution_time = 30000"),
            ("snowflake", "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 30"),
        ],
    )
    def test_sql_dialects_get_a_session_setting(self, dialect: str, expected: str) -> None:
        connection = MagicMock()
        connection.dialect.name = dialect

        export_source._apply_statement_timeout(connection, 30)

        assert expected in str(connection.execute.call_args[0][0])

    def test_sql_server_sets_the_timeout_on_the_dbapi_connection(self) -> None:
        # pyodbc has no session setting for this; the attribute is the whole API.
        connection = MagicMock()
        connection.dialect.name = "mssql"

        export_source._apply_statement_timeout(connection, 45)

        assert connection.connection.driver_connection.timeout == 45

    def test_an_unhandled_dialect_runs_without_one_rather_than_failing(self) -> None:
        connection = MagicMock()
        connection.dialect.name = "sqlite"

        export_source._apply_statement_timeout(connection, 30)

        connection.execute.assert_not_called()

    def test_a_driver_that_refuses_the_setting_does_not_fail_the_run(self) -> None:
        connection = MagicMock()
        connection.dialect.name = "postgresql"
        connection.execute.side_effect = RuntimeError("permission denied")

        export_source._apply_statement_timeout(connection, 30)


class TestSafeDriverMessage:
    """Driver errors must stay useful without carrying credentials."""

    URL = "mssql+pyodbc://admin:hunter2@dbhost:1433/warehouse"
    PASSWORD = "hunter2"  # noqa: S105 — a fixture, not a credential

    def test_the_diagnosis_survives(self) -> None:
        # This is the whole point of the Test button: say which column is wrong.
        raw = (
            "(pyodbc.ProgrammingError) ('42S22', \"[42S22] Invalid column name 'nope'.\")\n"
            "[SQL: SELECT nope FROM orgs]\n"
            "(Background on this error at: https://sqlalche.me/e/20/f405)"
        )

        cleaned = export_source._safe_driver_message(raw, self.URL, self.PASSWORD)

        assert "Invalid column name 'nope'" in cleaned

    def test_the_sqlalchemy_docs_link_is_stripped(self) -> None:
        # It contains "://", which is what made a naive check redact everything.
        raw = "Bad thing\n(Background on this error at: https://sqlalche.me/e/20/f405)"

        cleaned = export_source._safe_driver_message(raw, self.URL, self.PASSWORD)

        assert "sqlalche.me" not in cleaned
        assert "Bad thing" in cleaned

    def test_the_connection_url_is_removed(self) -> None:
        raw = f"Could not connect to {self.URL} after 3 tries"

        cleaned = export_source._safe_driver_message(raw, self.URL, self.PASSWORD)

        assert "hunter2" not in cleaned

    def test_a_bare_password_is_removed(self) -> None:
        raw = "Login failed. PWD used was hunter2 and the server refused it"

        cleaned = export_source._safe_driver_message(raw, self.URL, self.PASSWORD)

        assert "hunter2" not in cleaned

    def test_an_unrecognised_dsn_drops_the_whole_message(self) -> None:
        # Belt and braces: if something still looks like a DSN after scrubbing,
        # losing the diagnosis is the right trade.
        raw = "connection failed for postgresql://someone:secret@host/db"

        cleaned = export_source._safe_driver_message(raw, self.URL, self.PASSWORD)

        assert cleaned == "The query could not be run against this connection."

    def test_an_empty_message_still_says_something(self) -> None:
        cleaned = export_source._safe_driver_message("", self.URL, self.PASSWORD)

        assert cleaned != ""

    def test_an_empty_password_does_not_scrub_everything(self) -> None:
        # Replacing "" would otherwise insert *** between every character.
        cleaned = export_source._safe_driver_message("Invalid object name 'x'.", "", "")

        assert cleaned == "Invalid object name 'x'."


class TestHumaniseDriverMessage:
    """The Test panel shows this to whoever wrote the query, so it must read."""

    def test_pyodbc_boilerplate_is_reduced_to_the_servers_sentence(self) -> None:
        raw = (
            "(pyodbc.ProgrammingError) ('42S22', \"[42S22] [Microsoft]"
            "[ODBC Driver 18 for SQL Server][SQL Server]Invalid column name 'nope'. "
            "(207) (SQLExecDirectW)\")"
        )

        assert export_source._humanise_driver_message(raw) == "Invalid column name 'nope'."

    def test_a_syntax_error_keeps_the_keyword_it_names(self) -> None:
        raw = (
            "(pyodbc.ProgrammingError) ('42000', \"[42000] [Microsoft][ODBC Driver 18]"
            "[SQL Server]Incorrect syntax near the keyword 'FROM'. (156) (SQLExecDirectW)\")"
        )

        assert (
            export_source._humanise_driver_message(raw)
            == "Incorrect syntax near the keyword 'FROM'."
        )

    def test_a_postgres_message_is_already_readable_and_left_alone(self) -> None:
        raw = 'relation "nope" does not exist'

        assert export_source._humanise_driver_message(raw) == raw

    def test_an_unfamiliar_format_is_returned_unchanged(self) -> None:
        # Reduction only: never turn a message it does not recognise into nothing.
        raw = "some driver nobody has seen said something"

        assert export_source._humanise_driver_message(raw) == raw

    def test_a_message_that_reduces_to_nothing_falls_back_to_the_original(self) -> None:
        raw = "[42000]"

        assert export_source._humanise_driver_message(raw) == raw

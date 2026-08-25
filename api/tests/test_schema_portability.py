"""Guards that keep the schema deployable on Azure SQL as well as PostgreSQL.

Both failures these cover are silent until deploy time: a `String` with no
length compiles fine on PostgreSQL and raises on SQL Server, and a second
*cascading action* between two tables is legal on PostgreSQL and rejected by
SQL Server with error 1785. Adding a column or a foreign key is exactly when
either can slip in, so they are asserted here rather than discovered in Azure.

"Cascading action" means CASCADE **and** SET NULL / SET DEFAULT — SQL Server
counts them alike. An earlier version of this test only looked at CASCADE and
passed a schema the server then refused, on a SET NULL from `users` to
`audit_logs`. Only NO ACTION is exempt.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
from sqlalchemy.dialects import mssql, postgresql
from sqlalchemy.schema import CreateTable

import app.models  # noqa: F401 — registers every table on Base
from app.models.base import Base

_DIALECTS = {"postgresql": postgresql.dialect(), "mssql": mssql.dialect()}


@pytest.mark.parametrize("dialect_name", sorted(_DIALECTS))
def test_every_table_compiles_on_both_engines(dialect_name: str) -> None:
    dialect = _DIALECTS[dialect_name]

    failures = []
    for table in Base.metadata.sorted_tables:
        try:
            CreateTable(table).compile(dialect=dialect)
        except Exception as exc:  # noqa: BLE001 — the message is the assertion
            failures.append(f"{table.name}: {exc}")

    assert not failures, f"{dialect_name} cannot create: " + "; ".join(failures)


#: Referential actions SQL Server counts toward the multiple-paths limit.
CASCADING_ACTIONS = {"CASCADE", "SET NULL", "SET DEFAULT"}


def _cascade_children() -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    """Map each parent table to the children a delete propagates into."""
    children: dict[str, list[tuple[str, tuple[str, ...]]]] = defaultdict(list)
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_key_constraints:
            if (fk.ondelete or "").upper() in CASCADING_ACTIONS:
                parent = next(iter(fk.elements)).column.table.name
                children[parent].append((table.name, tuple(c.name for c in fk.columns)))
    return children


def test_no_table_is_reachable_by_two_cascade_paths() -> None:
    """SQL Server rejects a second cascading route between the same two tables.

    Grant tables and attribution columns are where this bites: a grant table is
    reachable from `orgs` through its resource, through `users`, and through
    `roles`, and every "created by" column adds another route. Only the owning
    resource keeps its cascade — see `services/principal_cleanup.py` for what
    replaced the rest.
    """
    children = _cascade_children()
    tables = sorted(t.name for t in Base.metadata.sorted_tables)

    def routes(origin: str, target: str) -> list[list[str]]:
        found: list[list[str]] = []

        def walk(node: str, trail: list[str]) -> None:
            for child, cols in children.get(node, []):
                step = [*trail, f"{node}->{child}({','.join(cols)})"]
                if child == target:
                    found.append(step)
                elif child not in {s.split("->")[0] for s in trail}:
                    walk(child, step)

        walk(origin, [])
        return found

    conflicts = [
        f"{origin} -> {target}: {[' | '.join(r) for r in found]}"
        for origin in tables
        for target in tables
        if origin != target and len(found := routes(origin, target)) > 1
    ]

    assert not conflicts, "multiple cascade paths: " + "; ".join(conflicts)


def test_paginated_queries_are_ordered() -> None:
    """A SELECT with OFFSET must carry an ORDER BY.

    SQL Server rejects OFFSET without one outright ("MSSQL requires an order_by
    when using an OFFSET or a non-simple LIMIT clause"), and PostgreSQL accepts
    it while leaving page 2 unrelated to page 1. Both are bugs; only one of them
    announces itself.

    This is a source scan rather than a query check because the statements are
    built inside request handlers — there is no assembled query to inspect
    without running them.
    """
    import re

    api_root = Path(__file__).resolve().parent.parent / "app"

    offenders = []
    for path in sorted(api_root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\.offset\(", source):
            # Look at the whole statement the call belongs to: walk back to the
            # nearest `select(` and forward to the end of the chain.
            start = source.rfind("select(", 0, match.start())
            end = source.find("\n\n", match.end())
            statement = source[start if start != -1 else match.start() : end]
            if ".order_by(" not in statement:
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(api_root.parent)}:{line}")

    assert not offenders, "OFFSET without ORDER BY at: " + ", ".join(offenders)

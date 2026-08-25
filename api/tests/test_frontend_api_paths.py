"""Every API path the frontend calls must exist on the API.

`/admin/audit` spent its whole life requesting `/governance/audit`, a path that
does not exist in this build, and nothing caught it: `tsc` cannot know what the
API serves, `eslint` cannot either, the API's own tests never see the client,
and the page's `catch` turned the 404 into "Failed to load audit log." The only
place the two halves meet is here.

This is a *static* check — it reads the call sites, not the running app — so it
needs no database and no server. It cannot see a path assembled from variables,
which is the deliberate trade: the literals cover almost every call and give no
false positives, and a check that cries wolf is a check that gets deleted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.main import app

_FRONTEND_SRC = Path(__file__).resolve().parents[2] / "application" / "src"

# The path is always the first argument of the call, as a plain or template
# literal: apiFetch<T>('/x'), fetcher<T>(`/x/${id}`), apiFetch('/x', {...}).
_CALL = re.compile(
    r"\b(?:apiFetch|fetcher|api|client)\s*(?:<[^(]*?>)?\s*\(\s*(['\"`])(/[^'\"`]*)\1"
)

# A `${...}` in the literal stands where a path parameter goes.
_INTERPOLATION = re.compile(r"\$\{[^}]*\}")

# Call sites that are known to point at nothing, with the reason. Listed rather
# than fixed here because each needs a product decision, not a renamed string —
# and listing them is what stops a *fourth* from appearing unnoticed. Removing
# an entry (by fixing the call) should never need a change to the test itself.
_KNOWN_DEAD_PATHS = {
    # The Data pipeline connections card on /admin/auth-config offers a "Test
    # connection" button for Azure Data Factory. An ADF *connection* now lives
    # on /admin/data-pipelines and is tested by
    # POST /admin/data-pipelines/{connection_id}/test, which needs a connection
    # id this page does not have — the card describes a provider. It is the same
    # leftover as the Embed connections card that was removed from this page.
    "/pipelines/adf/test",
    # DashboardCreator still carries the Tableau workbook -> view picker.
    # Tableau is not a provider in this build (Power BI only, see CLAUDE.md), so
    # the whole branch is unreachable and these routes do not exist.
    "/embed/tableau/workbooks",
    "/embed/tableau/workbooks/${selectedWorkbookId}/views",
}


def _route_patterns() -> list[re.Pattern[str]]:
    """Compile each mounted path into a regex that matches a concrete URL.

    Read from the OpenAPI schema rather than ``app.routes``: this FastAPI
    version keeps included routers wrapped rather than flattening their routes,
    so ``app.routes`` lists four paths and a pile of ``None``.
    """
    patterns = []
    for path in app.openapi()["paths"]:
        parts = re.split(r"(\{[^}]+\})", path)
        regex = "".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts)
        patterns.append(re.compile(f"^{regex}$"))
    return patterns


def _call_sites() -> list[tuple[str, str]]:
    """Return (file, path literal) for every API call in the frontend source."""
    sites = []
    for file in sorted(_FRONTEND_SRC.rglob("*.ts*")):
        if "__tests__" in file.parts or file.name.endswith((".test.ts", ".test.tsx")):
            continue
        for _, path in _CALL.findall(file.read_text(encoding="utf-8")):
            sites.append((str(file.relative_to(_FRONTEND_SRC)).replace("\\", "/"), path))
    return sites


pytestmark = pytest.mark.skipif(
    not _FRONTEND_SRC.is_dir(), reason="frontend source not present next to the API"
)


def _resolves(path: str, patterns: list[re.Pattern[str]]) -> bool:
    concrete = _INTERPOLATION.sub("X", path).split("?")[0].rstrip("/") or "/"
    return any(pattern.match(concrete) for pattern in patterns)


def test_the_scan_finds_the_call_sites_at_all() -> None:
    # Without this the whole file passes vacuously the moment the call helper is
    # renamed, which is the failure mode of every test built on a regex.
    sites = _call_sites()

    assert len(sites) > 100
    assert any(path.startswith("/exports/") for _, path in sites)
    assert any(path.startswith("/changes") for _, path in sites)


def test_every_frontend_api_path_exists_on_the_api() -> None:
    patterns = _route_patterns()

    broken = sorted(
        {
            f"{file}: {path}"
            for file, path in _call_sites()
            if path not in _KNOWN_DEAD_PATHS and not _resolves(path, patterns)
        }
    )

    assert not broken, "frontend calls paths the API does not serve:\n  " + "\n  ".join(broken)


def test_the_known_dead_paths_are_still_dead() -> None:
    # A stale exception is worse than none: it hides the path again the moment
    # someone adds the route. Fixing one should make this fail, so the entry
    # gets removed with the fix.
    patterns = _route_patterns()

    still_dead = {path for path in _KNOWN_DEAD_PATHS if not _resolves(path, patterns)}

    assert still_dead == _KNOWN_DEAD_PATHS, (
        "these now resolve and should be removed from _KNOWN_DEAD_PATHS: "
        f"{sorted(_KNOWN_DEAD_PATHS - still_dead)}"
    )


def test_the_known_dead_paths_are_still_called() -> None:
    # The other way an exception goes stale: the call site is deleted and the
    # entry lingers, quietly widening the allowlist for a future path.
    called = {path for _, path in _call_sites()}

    assert _KNOWN_DEAD_PATHS <= called, (
        "these are no longer called and should be removed from _KNOWN_DEAD_PATHS: "
        f"{sorted(_KNOWN_DEAD_PATHS - called)}"
    )


def test_the_audit_page_calls_the_path_the_api_serves() -> None:
    # The bug this file exists for, pinned directly: the page requested
    # /governance/audit, the API mounts audit at /audit, and the 404 surfaced
    # only as "Failed to load audit log."
    audit_page = _FRONTEND_SRC / "app" / "admin" / "audit" / "page.tsx"
    source = audit_page.read_text(encoding="utf-8")

    assert "/governance/audit" not in source
    assert "/audit?" in source

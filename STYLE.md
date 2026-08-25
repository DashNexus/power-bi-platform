# Power BI Platform — Style Guide

Authoritative style rules for every file written in this project. Most Python rules are enforced by ruff (`E F I UP ANN D`, google docstrings, line length 100, double quotes) — run `ruff check . && ruff format .` per layer, or `make lint` from the root.

## File & directory naming

Python modules/packages `snake_case`; TS utility modules `camelCase.ts`; React components `PascalCase.tsx`; hooks `usePascalCase.ts`; tests `test_<module>.py` / `<Module>.test.tsx`; configs `snake_case.yaml|.toml`. Directories always `snake_case`. No abbreviations unless domain-standard (`api`, `ui`, `db`, `adf`).

## Python

**File headers:** triple-quoted module docstring **first — literally the first statement**, above `from __future__ import annotations`. One-sentence summary, optional second paragraph when the module's role is non-obvious. Never author/date/path (git owns that). Empty `__init__.py` may omit.

> A docstring placed *after* `from __future__` is not a docstring: Python sets `__doc__` to `None`, `help()` shows nothing, and ruff reports `E402` on every import below it. 42 modules had this and it accounted for 125 of the repo's lint findings. Check with `python -c "import x; print(x.__doc__)"`.

**Imports:** ruff-ordered groups (`__future__` → stdlib → third-party → local), one blank line between. Prefer `from x import y`; never `import *`. Lazy imports only for optional/heavyweight path-specific deps.

**Type annotations:** all public signatures fully annotated. Use `X | None`, `list[X]`, `dict[K, V]` (never `Optional`, `List`, `Dict`); use `collections.abc` for `Iterator`/`Callable`. `Any` allowed only with a comment explaining why.

**Naming:** classes `PascalCase`; exceptions end in `Error`; functions/variables `snake_case`; module constants `UPPER_SNAKE_CASE`; private `_prefix`; type aliases `PascalCase`. Booleans prefixed `is_`/`has_`/`should_`/`supports_`. Single letters only for loop counters and standard abbreviations (`df`, `exc`).

**Comments:** explain *why*, never *what* — add only when the code would surprise a competent reader. `# ` (hash + one space). Prefer a line above over trailing. No commented-out code; no `# TODO` (use GitHub issues).

**Docstrings (Google style, ruff-enforced):** summary line in imperative mood ("Return" not "Returns"), single sentence. Include extended description / `Args` / `Returns` / `Raises` only when they add information beyond names and type hints — skip `Args` when params are self-documenting, `Returns` when trivial, the whole docstring for private one-liners, property getters, and `__init__`. Document provider config keys on the class docstring, not `__init__`:

```python
class PowerBiProvider(BiProvider):
    """Embed Power BI reports through a service principal.

    Config keys:
        tenant_id: Entra directory the workspace belongs to.
        workspace_id: Power BI workspace (group) id.
    """
```

**Error handling:** catch specific exceptions; name them `exc`; re-raise project exceptions (`BiProviderError`, `PipelineProviderError`, …) with `from exc`. Never bare `except:` or silent `pass`. Catch `Exception` only at a boundary that exists to keep something running — the poller loop, a notification send — and log it there.

**Formatting:** ruff format — 100 chars, double quotes, trailing commas on multi-line collections, f-strings only.

## TypeScript & React

**File headers:** JSDoc block comment first (after any `"use client"`/`"use server"` directive) explaining the module's purpose — not a plain `//` comment.

**Imports (ESLint `import/order`):** React/Next → third-party → internal aliases (`@/…`) → relative. Use `import type` for type-only imports. No `import * as` unless the module has no named exports. Barrel `index.ts` only at component directory boundaries.

**Naming:** components `PascalCase`, hooks `usePascalCase`, utilities `camelCase`, constants `UPPER_SNAKE_CASE`, types/interfaces `PascalCase`. Props interfaces named `<ComponentName>Props`, declared above the component. No custom CSS class names — Tailwind utilities only.

**Components:** named exports only (never `export default`); props via a named interface (never inline). Server Components are the default — add `"use client"` only for browser APIs, event handlers, or state. Co-locate styles/types/helpers used by only one component.

**Comments & JSDoc:** same why-not-what test as Python. JSDoc on public functions/components only when the signature alone is insufficient; `@param` only for ambiguous names, `@returns` for non-obvious shapes, `@throws` for errors callers handle. Skip for trivial code.

## YAML & TOML

YAML: 2-space indent; strings unquoted unless containing special chars; env var refs `${VAR_NAME}` — never literal credentials; booleans lowercase `true`/`false`; null as `~` or omitted; comments explain why. TOML: table headers before keys, blank line between tables, inline tables only for short related values, double quotes.

## Markdown & README

One H1, then a one-sentence description, `---`, then H2 sections (never skip levels). Every layer README includes: title+description, `## Architecture` (if non-trivial), `## Quick Start`, `## Reference` (tables), `## Running Tests`, `## Troubleshooting` (≥3 errors with fixes). All code blocks carry a language tag (`bash`, `python`, `typescript`, `sql`, `yaml`, `toml`, `json`). Tables for reference data only; **bold** for defined terms/warnings/config keys; `inline code` for paths, env vars, commands, symbols. Never include changelogs, author credits, or TODO sections.

## Git & PRs

Commit format: [SKILL.md](SKILL.md). Review checklist: [REVIEW.md](REVIEW.md) (load with `@REVIEW.md` during PR reviews).

## Testing

**Placement:** mirror the source tree under `tests/` (`tests/routers/test_<name>.py`, `tests/services/test_<name>.py`) with shared fixtures in `conftest.py`.

**Naming:** `test_<thing>_<condition>_<expected_outcome>` — e.g. `test_load_full_reload_truncates_before_insert`.

**Structure:** Arrange / Act / Assert, one blank line between blocks, comments only if the structure isn't already clear. One logical outcome per test — split if you need multiple assert groups.

**Markers:** `@pytest.mark.integration` (needs a live database), `@pytest.mark.slow`. Default runs skip both.

**Scope:** test public contracts, error paths, access-control decisions, and schema portability. Don't test private internals, third-party libraries, trivial config parsing, or language built-ins. Mock at the boundary — the external API, never your own code.

## Tooling

| Layer | Tools |
|---|---|
| Python (`api/`) | `ruff check` + `ruff format` + `mypy` + `pytest` (config in `api/pyproject.toml`) |
| TypeScript (`application/`) | `eslint` + `prettier` + `tsc` |
| Bicep / shell (`deploy/`) | `az bicep build` — no automated shell linting |
| Markdown | manual — no automated enforcement |

Run everything from the root: `make lint` / `make test`.

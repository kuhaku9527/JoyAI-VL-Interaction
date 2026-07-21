# Coding Standards — JoyAI-VL-Interaction

These standards back the automated quality gate (`ruff`, pre-commit, CI) defined
in the repo-root `pyproject.toml`. The gate enforces the mechanical parts; this
document covers the *judgement* parts a senior reviewer expects.

> Conventions are intentionally close to PEP 8. When this doc and `ruff` disagree,
> `ruff` wins for anything it checks; raise a standards issue for the rest.

---

## 1. Language & runtime

- Target **Python ≥ 3.10** for new code. (`pyproject.toml` currently pins
  `py39` for legacy services — raise it once all services are on 3.10+, which
  also unlocks auto-fixing `Optional[X]` → `X | None`.)
- Prefer the standard library; add a dependency only with a brief justification
  in the PR. Record it in the relevant service's `pyproject.toml`.

## 2. Style (enforced by `ruff`)

- Line length **100**; let `ruff format` handle wrapping — never hand-wrap.
- **Double quotes** for strings (configured in `[tool.ruff.format]`).
- **Import order**: `ruff` (isort) sorts automatically — don't fight it.
- **Type hints**: required on all public function/method signatures.
  Use modern syntax: `def f(x: int | None) -> list[str]:`.
- **f-strings**: use them; no manual `%` or `.format()` unless necessary.

## 3. Naming

- `snake_case` for functions/variables, `CapWords` for classes,
  `UPPER_SNAKE` for module constants.
- Avoid single-letter names except for tight loops (`i`, `j`) and the conventional
  `T`/`B` tensor dims **only inside clearly mathematical code** (e.g. model
  forward passes) — everywhere else be descriptive.
- Test helpers that mirror external API names (e.g. WebRTC `addTrack`) are
  exempt from the naming rule (already relaxed in `pyproject.toml`).

## 4. Error handling

- **Never** swallow exceptions: no bare `except:` and no `except Exception: pass`.
- Raise with context: inside an `except`, use `raise NewError(...) from err` so
  the causal chain is preserved (catches `B904`).
- Don't use `assert` for runtime validation on paths reachable in production —
  `python -O` strips asserts. Use explicit `raise` (catches `B011`).
- Log errors with context; don't log and re-raise without adding value.

## 5. Logging

- Use `logging`, not `print`, in services. Reuse the existing
  `services/common/log_with_timestamp.py` helper for consistent timestamps.
- Log at the right level: `DEBUG` for traces, `INFO` for lifecycle,
  `WARNING` for recoverable, `ERROR` for failures. Never log secrets/PII.

## 6. Docstrings (enforced by `ruff` `D` rules, NumPy convention)

- Every **public** module, class, function, and method gets a docstring.
- One-line summary, then a blank line, then extended description if needed.
- Document parameters, returns, and raises for non-trivial functions.
- Private helpers (`_name`) need a docstring only when non-trivial.

## 7. Module / file size

- **Keep files focused.** A module over **~600 lines** is a smell; over
  **~1000 lines** is a problem.
- 🚩 **`services/webinfer/live_adapter.py` is ~3,500 lines** — a clear candidate
  for decomposition (split by transport/adapter concern). Treat as a refactor
  epic, not a drive-by change. New code should not pile into it; extract instead.
- Prefer small, single-responsibility modules over large grab-bags.

## 8. Tests

- New behavior ships with tests. Place them next to the code as
  `tests/test_*.py` or `test_*.py`; they are exempt from the docstring/naming bar.
- Run the relevant service's test suite before opening a PR.
- Don't commit `print()` debugging or `# TODO` without a tracking note.

## 9. Git & PR hygiene

- One logical change per PR; keep diffs reviewable (＜ ~400 lines ideally).
- Write PR titles as imperatives (`Add X`, `Fix Y`); describe *why*, not just *what*.
- Pre-commit runs `ruff` automatically — if it reformats, commit the result.
- CI (`.github/workflows/quality.yml`) blocks merge on lint/format violations.
- Don't force-push over reviewed history without saying so.

## 10. Vendored & generated code

- `services/kws-training/icefall_src/` is **vendored** (the `icefall` project).
  Do not lint-fix or edit it; re-sync from upstream.
- `archive/` holds intentionally frozen one-off scripts — leave them alone.

---

See also: [`code-review-checklist.md`](./code-review-checklist.md) and the
measured starting point in [`lint-baseline.md`](./lint-baseline.md).

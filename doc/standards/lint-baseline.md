# Lint Baseline & Quality Backlog

- **Generated:** 2026-07-20
- **Tool:** `ruff` 0.6.9 (config in repo-root `pyproject.toml`, `target-version = py39`)
- **Scope:** entire repo **except** `archive/` (frozen one-off scripts) and
  `services/kws-training/icefall_src/` (vendored third-party code — not team-owned).
- **Baseline snapshot:** taken **after** the safe auto-fix pass run during setup.

---

## 1. Numbers

| Metric | Value |
|---|---|
| Violations remaining (baseline) | **758** across **33** rules |
| Auto-fixes applied at setup | **258** (unused imports, import sorting, `super()` calls, docstring blank-lines, etc.) |
| Blocked by `py39` target (auto-fixable once runtime ≥ 3.10) | **129** (`UP007` + `UP006`, see §3) |
| Deferred vendored noise (excluded) | 282 (mostly `N802`/`N806` in `icefall_src`) |

> The 759 is a *starting line*, not a blocker. All high-value items are listed
> in §4 with file:line so they can be fixed as standalone PRs.

---

## 2. Remaining violations by rule (baseline, descending)

| Count | Code | Auto-fix | Meaning |
|---:|---|:--:|---|
| 216 | `RUF001` | | ambiguous-unicode-character-string |
| 110 | `UP007` | ✅* | non-pep604-annotation (`Optional[X]` → `X \| None`) |
|  99 | `RUF002` | | ambiguous-unicode-character-docstring |
|  95 | `D103`  | | undocumented-public-function |
|  45 | `D102`  | | undocumented-public-method |
|  32 | `RUF003` | | ambiguous-unicode-character-comment |
|  23 | `D101`  | | undocumented-public-class |
|  19 | `UP006` | ✅* | non-pep585-annotation (`List` → `list`) |
|  13 | `N806`  | | non-lowercase-variable-in-function |
|  13 | `D400`  | ✅ | ends-in-period |
|  11 | `SIM105`| ✅ | suppressible-exception |
|  11 | `E402`  | | module-import-not-at-top-of-file |
|   7 | `E702`  | | multiple-statements-on-one-line-semicolon |
|   7 | `F841`  | ✅ | unused-variable |
|   7 | `UP035` | | deprecated-import |
|   7 | `RUF005`| ✅ | collection-literal-concatenation |
|   6 | `D301`  | ✅ | escape-sequence-in-docstring |
|   5 | `D205`  | | blank-line-after-summary |
|   4 | `D105`  | | undocumented-magic-method |
|   4 | `D401`  | | non-imperative-mood |
|   3 | `B019`  | | cached-instance-method |
|   3 | `SIM108`| ✅ | if-else-block-instead-of-if-exp |
|   3 | `E701`  | | multiple-statements-on-one-line-colon |
|   2 | `B007`  | | unused-loop-control-variable |
|   2 | `B904`  | | raise-without-from-inside-except |
|   2 | `N803`  | | invalid-argument-name |
|   2 | `D100`  | | undocumented-public-module |
|   2 | `RUF013`| ✅ | implicit-optional |
|   1 | `SIM117`| ✅ | multiple-with-statements |
|   1 | `SIM222`| ✅ | expr-or-true |
|   1 | `I001`  | | unsorted-imports |
|   1 | `N812`  | | lowercase-imported-as-non-lowercase |
|   1 | `W293`  | ✅ | blank-line-with-whitespace |

\* Auto-fixable only once `target-version` is raised to `py310+` (see §3).

---

## 3. Notes that change the plan

- **`UP007` / `UP006` (129 total) are not fixed yet on purpose.** At
  `target-version = py39` the `X | None` and `list[...]` syntax is invalid, so
  `ruff --fix` correctly leaves them. When every service runs on Python ≥ 3.10,
  bump `target-version` in `pyproject.toml` and these become one command:
  `ruff check . --fix`.
- **`RUF001/002/003` (347 total) are ambiguous-unicode warnings** — almost
  always full-width punctuation or "smart quotes" pasted from docs/WeChat into
  comments/strings. Low runtime risk but they break grep-ability. A single
  `--unsafe-fixes` pass (reviewed) clears most of them.
- **`icefall_src/` is vendored** (the `icefall` project). It is excluded from
  lint; do not "fix" it — re-sync from upstream instead.

---

## 4. High-value findings (fix as standalone PRs)

These are the items a senior reviewer cares about most — real defects or
maintainability landmines, not style nits.

| Severity | Code | Location | Action |
|---|---|---|---|
| 🔴 Bug | `F821` | `services/voice-clone/voice_clone_api/main.py:314` — `MiniMaxClient` undefined | **Resolved 2026-07-20:** added top-level `from .cloud_clone import MiniMaxClient` (commit `fix: resolve F821 MiniMaxClient ...`). Remaining count dropped 759 → 758. |
| 🟠 Correctness | `B904` | `services/memory-store/src/memory_store/app.py:85,95` — `raise` without `from` inside `except` | Use `raise ... from err` (or `from None`) to preserve the causal chain. |
| 🟠 Correctness | `B019` | 3× cached-instance-method (see `ruff check --select B019`) | `@functools.cached_property` on instances is fine, but `@lru_cache` on methods leaks memory across instances — convert to a module/static cache. |
| 🟠 Robustness | `B007` | 2× unused loop control variable | Likely a typo in a `for`/`while`; confirm intent. |
| 🟡 Naming | `N803`/`N812` | `invalid-argument-name` / `lowercase-imported-as-non-lowercase` | Rename per PEP8; verify no external callers. |
| 🟡 Dead code | `F841` | 7× unused-variable | Remove or use; some hide logic bugs. |

Quick command to re-list any of the above with file:line:

```bash
ruff check . --select F821,B904,B019,B007,N803,N812,F841 --output-format concise
```

---

## 5. Recommended incremental path

1. **Now:** land the tooling + this baseline (done in the same change set).
2. **Sprint 1:** clear §4 high-value findings (small, reviewable PRs).
3. **Sprint 1:** `ruff check . --fix` again after raising `target-version` to `py310`
   to absorb `UP007`/`UP006` (129 items) for free.
4. **Ongoing:** enforce `ruff check . && ruff format --check .` in CI / pre-commit
   (already configured) so the baseline only goes **down**.
5. **Backlog:** docstring coverage (`D1xx`, ~180) — improve opportunistically as
   modules are touched; do not batch-rewrite.
6. **Optional:** review `RUF001/002/003` (347) in a dedicated Unicode-cleanup PR
   using `ruff check . --select RUF0 --fix --unsafe-fixes` (review the diff).

Run locally anytime:

```bash
./scripts/quality-check.sh          # lint + format gate
./scripts/quality-check.sh --fix    # also apply safe fixes
```

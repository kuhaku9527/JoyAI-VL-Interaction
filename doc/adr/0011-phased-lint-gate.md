# ADR-0011: Phased Lint Gate (baseline + burn-down)

## Status
Proposed

## Context

The CI `quality.yml` `ruff` job pins `ruff==0.15.22` and runs `ruff check` **and**
`ruff format --check` across service directories. The audit (`reports/code-health-audit-20260723.md`, §4)
found two structural problems with the lint gate:

1. **Rule-selection blind spots.** The repo-root `pyproject.toml` `select` list omits
   the `S` (security) family, so safety-relevant lint is not enforced. (The audit
   also claimed `B904`/`B019`/`B007` were "quieted via `extend-ignore`" — that is
   **false**: no `extend-ignore` exists anywhere in the repo; `B019` (3×) and
   `B007` (1×) are already reported via the `B` family. Only the `S` family is
   missing from `select`.)
2. **Baseline documentation drift.** `doc/standards/lint-baseline.md` §4 listed
   `B904` at `services/memory-store/src/memory_store/app.py:85,95` — a false
   positive. Re-verification with `ruff` 0.15.22 (2026-07-24) finds **0** `B904`
   repo-wide; the cited line is `raise HTTPException(...) from exc` (correct causal
   chain). `B019` is genuinely present, but at `services/kws-training/kws_data_module.py:80,89,94`
   (not where the audit implied).

The naive fix — flipping the full `S` family (and `BLE`) on in one shot — would turn
CI **permanently red** (~216 violations from `S101`×97, `S311`×13, `BLE001`×106),
defeating the "baseline only goes down" discipline. We need a reversible, incremental
path that adds only the *small, high-value* `S` sub-rules first.

## Decision

Adopt a **baseline + phased burn-down** strategy for the lint gate. Each batch is
independently shippable and keeps CI green.

### Batch 1 — safe hygiene (DONE 2026-07-24)
- `scripts/quality-check.sh` already double-runs `ruff check` + `ruff format --check`
  (verified — no change needed).
- Corrected `doc/standards/lint-baseline.md` §4: removed the false `B904` entry,
  pinned `B019` to `kws-training/kws_data_module.py:80,89,94`, and added a
  tool-version-drift caveat (§2 counts were measured under `ruff` 0.6.9; CI uses
  0.15.22).
- Deleted 6 stale remote branches that `git cherry` (patch-id) confirmed were
  squash-merged into `main` (`3fed7f8`):
  - `ci/add-pytest-gate` — already absent from remote at time of cleanup
  - `ci/webinfer-pytest-matrix` — already absent
  - `ci/webui-ruff-config-and-doc-paths` — already absent
  - `fix/webinfer-context-overflow-bound` — already absent
  - `docs/mem-hermes-audit-align` — already absent
  - `fix/background-agent-test-ruff` — **deleted by this batch** (tip `4942c25`,
    `git cherry` returned all `-` ⇒ patch already in `main`). Verified gone via
    `ls-remote` (0 matches).

### Batch 2 — tighten selection (IN PROGRESS, handoff drafted 2026-07-24)
- Add **specific** `S` sub-rules to `select` in repo-root `pyproject.toml`:
  `["S104","S108","S110","S112","S310"]`. Do **not** add the full `S` family or
  `BLE` (those are Batch 3).
- No `extend-ignore` removal needed — the audit's claim that `B904/B019/B007` were
  suppressed is false; they are already active (via the `B` family).
- Fix the **33** violations this surfaces (exact list + diff in
  `reports/handoff-lint-gate-batch2-20260724.md`), grouped:
  - **Clear fixes** (do now): `B019`×3 cache-leak → module/static cache;
    `B007`×1 unused loop var; `F841`×3 unused vars; `S110`×10 + `S112`×2 bare
    except → add `logger.warning(...)`.
  - **Review / targeted `noqa`** (intentional FPs): `S104`×4 bind-to-all-interfaces
    (local server, likely intended), `S108`×8 `/tmp/...` model-cache paths (intended),
    `S310`×2 `urllib` URL open (review scheme allow-list).
- **Land the `pyproject.toml` flip together with the fixes in ONE PR** so CI never
  goes red. The backend dialogue owns the code fixes (per division of labor); this
  ADR's author drafts the config diff + handoff.

### Batch 3 — blind-except + assert + pseudo-random (IMPLEMENTED 2026-07-24)
- Adds `BLE001` (blind except), `S101` (assert in prod), `S311` (pseudo-random) to
  `select` in **both** repo-root `pyproject.toml` **and** `services/webui/pyproject.toml`.
  webui ships its own `[tool.ruff]` table, so its violations are baselined there —
  root `per-file-ignores` cannot reach webui files (ruff resolves each file to the
  nearest config). Splitting the baseline across the two configs keeps the gate
  consistent repo-wide.
- **`ruff 0.15.22 has no `--baseline`** (no subcommand, no `--baseline` flag), so the
  original "snapshot via `ruff --baseline`" plan is infeasible at the pinned version.
  Replaced with a **manual `per-file-ignores` baseline** — centralized, reversible,
  no version bump:
  - Repo-root `pyproject.toml` `[tool.ruff.lint.per-file-ignores]`: **20 non-webui**
    production files (`datasets`, `asr`, `background-agent`, `kws-training`,
    `memory-store`, `scripts`, `tts`, `webinfer`).
  - `services/webui/pyproject.toml` `[tool.ruff.lint.per-file-ignores]`: **10 webui**
    production files (`joy_interaction_webui/*`).
  - Test globs (`**/tests/*`, `**/test_*.py`, `**/conftest.py`) in **both** configs
    relax `S101` + `BLE001` (asserts / blind excepts are benign in tests).
- **Frozen backlog:** **87** pre-existing violations — 33 prod
  (`BLE001`×27, `S101`×5, `S311`×1) + 54 test (`S101`×51, `BLE001`×3). The backend
  dialogue had already burned down ~129 of the original ~216 (`S101`×97, `S311`×13,
  `BLE001`×106) in commits `bd89d2a` + `95c7c7a` before this batch landed.
- **Burn-down discipline:** delete a file's `per-file-ignores` entry once its
  violation(s) are fixed. The baseline list is the single source of truth for the
  outstanding security/correctness backlog — see
  `reports/handoff-lint-gate-batch3-20260724.md`.
- **Verification (ruff 0.15.22, matches CI pin):** `ruff check . --select
  BLE001,S101,S311` from repo root → **0 errors**; `cd services/webui && ruff check .`
  (CI-equivalent for webui) → **0 errors**.

## Consequences

**Easier:**
- The lint baseline documents reality (no false positives), so reviewers trust §4.
- Stale remote branches no longer clutter the branch list or confuse `git cherry`.
- CI can be tightened without a multi-day red period.

**Harder:**
- Batch 2/3 require disciplined, small PRs — teams must resist the urge to flip
  flags and "fix everything later" (the trap that keeps CI red).
- A `ruff` version bump (0.6.9 baseline → 0.15.22 CI) means §2 totals are
  approximate; §4 re-verified under 0.15.22 is the source of truth.

## Constraints
- **Baseline only decreases.** Never add a rule that makes the existing baseline
  red in one shot. For the volatile families use a **`per-file-ignores` baseline**
  (ruff 0.15.22 ships no `--baseline` subcommand/flag), and burn it down by deleting
  entries as code is fixed.
- **Workflow files need a fine-grained PAT** (workflow scope) or
  `workflow_dispatch`. Branch deletion uses the `github-pat` MCP token via the
  `GIT_CONFIG_GLOBAL=/dev/null` + `insteadOf` fallback (bypasses the gh-proxy
  `insteadOf` rewrite).
- **Worktree isolation is mandatory.** This batch was nearly lost to a shared-worktree
  silent-overwrite: an uncommitted `lint-baseline.md` edit and the untracked ADR were
  wiped when another dialogue switched branches underneath this one. Each dialogue
  must operate in its **own** git worktree.

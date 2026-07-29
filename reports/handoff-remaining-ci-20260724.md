# Handoff — Remaining CI / Lint-Gate Work (post Batch 3 merge)

**Date:** 2026-07-24 14:04 GMT+8
**Owner:** architecture dialogue (spec + coordination) · backend/test dialogue (execute backend merge)
**Verified:** GitHub API live (no reliance on local clone).

---

## 0. Current state (verified)

- `main` = `922f7c1968`. **All 8 PRs (#24–#31) merged — OPEN=0** (backend #24–#30 merged via workflow_dispatch+CI-green squash; #28/#31 earlier). PR #31 (Batch 3) → `select` enforces `BLE001 / S101 / S311` + 87-violation `per-file-ignores` baseline. **Backend Batch-2 code fixes are now in `main`.**
- `quality.yml` jobs = `ruff`, `package-smoke`, `eslint`, `pytest`. **No `frontend-test` job.**

---

## 1. ITEM A — Batch 2 config flip (the remaining gate)

The 33 Batch-2 violations' **code fixes are done and merged into `main`** (via #24–#30), but the `select` that *enforces* those rules is **absent**. Without it, `S104/S108/S110/S112/S310` never run → silent regressions are possible even though the code is currently clean.

**Verified missing:** `select` on `main` = `E F W I UP B C4 SIM N RUF D BLE001 S101 S311`. The 5 scoped S codes are not present.

### Change — repo-root `pyproject.toml`, `[tool.ruff.lint] select`

```diff
 select = [
     ...
     "D",   # pydocstyle
+    "S104", "S108", "S110", "S112", "S310",  # Batch 2 gate (ADR-0011)
 ]
```

> `B019`/`B007` are already covered by the `B` family; `F841` by the `F` family — no change needed there. Do **not** add `S101`/`S311`/`BLE001` (already in via Batch 3).

### Group B `# noqa` (must land with the flip — 14 intentional lines)

- **`S104` ×4** (bind `0.0.0.0`): `services/asr/asr_adapter.py:348,380`, `services/tts/tts_adapter.py:496,540`
  → `# noqa: S104  # intended: LAN-scoped dev server`
- **`S108` ×8** (`/tmp` model-cache paths): `services/webinfer/adapter_types.py:52,54,86`, `app.py:138,151,270`, `memory_summarizer.py:294`, `services/webui/src/joy_interaction_webui/background_model.py:68`
  → `# noqa: S108  # intended: model cache dir`
- **`S310` ×2** (`urllib` URL open): `services/scripts/verify-services.py:32,36`
  → `# noqa: S310  # trusted internal URL`

### Group A fixes (already in #24–#30, no further action)

`B019`×3, `B007`×1, `F841`×3, `S110`×10, `S112`×2.

### Execution (backend #24–#30 now merged into `main` → flip is a STANDALONE PR)

Because the 6 backend PRs are already merged, the flip no longer needs to co-merge with them. Open **one PR** that adds:
- `select` += `S104, S108, S110, S112, S310`, and
- the 14 Group B `# noqa` annotations (S104×4 / S108×8 / S310×2),

and CI goes green immediately — Group A fixes are already on `main`; only Group B needs the `# noqa` to avoid red. No 6-way merge, no red window.
- **Gate target after:** `ruff --select ...S104,S108,S110,S112,S310` over the whole repo = **0**.

Full per-file spec: `reports/handoff-lint-gate-batch2-20260724.md` (§1–§2).

---

## 2. ITEM B — `frontend-test` CI job missing (P0)

PR #28 merged **25 Vitest cases**, but `quality.yml` has **no job to run them** → the frontend tests are unprotected in CI (nobody guards regressions).

### Add to `.github/workflows/quality.yml` (workflow file → needs fine-grained PAT, `workflow` scope, to push)

```yaml
  frontend-test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: services/webui
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: services/webui/package-lock.json
      - run: npm ci
      - run: npm test   # vitest run
```

**Blocker:** pushing a workflow file is hard-rejected for the OAuth `gho_` token; it requires a **fine-grained PAT** with `workflow` scope. Architecture has no such token exposed in the shell → the user must supply it, or push the change directly.

---

## 3. Branch hygiene

- **Deleted this pass:** `feature/frontend-p0` (squash-merged as #28; content already on `main` → safe).
- **Retained — unmerged WIP, DO NOT delete:**
  - `ci/lint-gate-batch2` (ahead 3) — verified it does **not** contain the S-subset flip; likely only Batch-2 prep/docs.
  - `docs/lint-gate-adr0011-batch1` (ahead 2) — Batch-1 docs; likely already on `main` via `doc/adr/0011-*`; verify commits are on `main` before deletion.
- **Retained (merged PRs — safe to delete, optional):** #24–#30 branches (PRs merged, `ahead_by=0`); `test/webinfer-context-overflow` (ahead 2, contains unmerged work — keep).

---

## 4. Blocked / needs decision

- **ITEM A:** Path 1 (backend folds flip into #30, then batch-merges) or Path 2 (architecture builds combined `ci/batch2-flip-and-fixes`)?
- **ITEM B:** provide a fine-grained PAT (`workflow` scope) for the `frontend-test` job, or the user pushes it.

---

## 5. Why this matters (trade-off)

Flipping the **full** `S` family at once would surface ~216 violations and keep CI red for days (the flag-flip trap). Scoping to these 5 high-value S codes — with Group A already fixed and Group B explicitly `# noqa`'d — lets Batch 2 ship green and keeps the gate honest about the rules that matter most for this codebase. The cost: 14 deliberate `# noqa` annotations that must be reviewed if those lines ever change intent.

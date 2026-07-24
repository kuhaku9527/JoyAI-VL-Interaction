# Handoff — ADR-0011 Batch 3: blind-except + assert + pseudo-random

**Date:** 2026-07-24
**Branch:** `ci/lint-gate-batch3` (from `ci/lint-gate-batch2` @ `593c93d`)
**Owner:** architecture dialogue (CI/config) — code fixes per division of labor below
**Verification:** `ruff==0.15.22` (matches CI pin) — gate is green, see §4

---

## 1. What changed (config only — no business code)

| File | Change |
|------|--------|
| `pyproject.toml` (repo root) | `select` += `BLE001`, `S101`, `S311`; added 20-file `per-file-ignores` baseline (non-webui prod) + `S101`/`BLE001` to test globs |
| `services/webui/pyproject.toml` | `select` += `BLE001`, `S101`, `S311`; added 10-file `per-file-ignores` baseline (webui prod) + `S101`/`BLE001` to test globs |

**Why two configs?** `services/webui/` has its own `[tool.ruff]` table. ruff resolves
each file to the *nearest* config, so root `per-file-ignores` entries for webui paths
are **dead** (never consulted). The webui baseline therefore lives in webui's own
`pyproject.toml`, with paths relative to `services/webui/` (e.g.
`src/joy_interaction_webui/server.py`). All other services inherit the root config.

**Why `per-file-ignores` instead of `--baseline`?** `ruff 0.15.22` (the CI-pinned
version) ships **no `baseline` subcommand and no `--baseline` flag**. The ADR's
original "`ruff --baseline`" plan is infeasible at this version. A centralized
`per-file-ignores` block is the reversible, no-version-bump equivalent.

---

## 2. Frozen backlog — 87 pre-existing violations

The audit (`code-health-audit-20260723.md`) counted **~216** (`S101`×97, `S311`×13,
`BLE001`×106). The backend dialogue already burned down ~129 in commits `bd89d2a`
("replace prod asserts with explicit raises") + `95c7c7a` ("harden hermes recall
logging"), leaving **87** frozen here:

- **33 production** — `BLE001`×27, `S101`×5, `S311`×1
- **54 test** — `S101`×51, `BLE001`×3 (all webui tests; benign)

### 2a. Non-webui production baseline (edit in repo-root `pyproject.toml`)

| # | File | Code(s) | Suggested fix |
|---|------|---------|---------------|
| 1 | `datasets/convert_data.py` | BLE001 | catch specific exception (e.g. `ValueError`, `OSError`) |
| 2 | `services/asr/jarvis/asr.py` | S101 | replace `assert` with explicit `raise`/guard |
| 3 | `services/asr/jarvis/kws.py` | S101 | replace `assert` with explicit raise |
| 4 | `services/background-agent/codex_api/main.py` | BLE001, S101 | narrow except + drop assert |
| 5 | `services/background-agent/hermes_api/main.py` | BLE001 | narrow except |
| 6 | `services/kws-training/export_kws_onnx.py` | BLE001, S101 | narrow except + drop assert |
| 7 | `services/memory-store/src/memory_store/backends/sqlite_backend.py` | BLE001 | narrow except (sqlite specific) |
| 8 | `services/scripts/analyze_kws_captures.py` | BLE001 | narrow except |
| 9 | `services/scripts/prep_kws_data.py` | S311 | use `secrets` if randomness is security-sensitive, else `# noqa: S311` |
| 10 | `services/scripts/smoke_voice_clone.py` | BLE001 | narrow except |
| 11 | `services/scripts/verify-services.py` | BLE001 | narrow except |
| 12 | `services/tts/http_synthesizer.py` | BLE001 | narrow except |
| 13 | `services/webinfer/app.py` | BLE001 | narrow except |
| 14 | `services/webinfer/infer_loop.py` | BLE001 | narrow except |
| 15 | `services/webinfer/io_utils.py` | BLE001 | narrow except |
| 16 | `services/webinfer/memory_io.py` | BLE001 | narrow except |
| 17 | `services/webinfer/memory_summarizer.py` | BLE001 | narrow except |
| 18 | `services/webinfer/prompt_assembly.py` | BLE001 | narrow except |
| 19 | `services/webinfer/session.py` | BLE001 | narrow except |
| 20 | `services/webinfer/summarizer_routing.py` | BLE001 | narrow except |

### 2b. Webui production baseline (edit in `services/webui/pyproject.toml`)

| # | File (rel. to `services/webui`) | Code(s) | Suggested fix |
|---|------|---------|---------------|
| 1 | `src/joy_interaction_webui/asr.py` | BLE001 | narrow except |
| 2 | `src/joy_interaction_webui/background_model.py` | BLE001 | narrow except |
| 3 | `src/joy_interaction_webui/jarvis_mode.py` | BLE001, S101 | narrow except + drop assert |
| 4 | `src/joy_interaction_webui/jarvis_routes.py` | BLE001 | narrow except |
| 5 | `src/joy_interaction_webui/jarvis_session.py` | BLE001 | narrow except |
| 6 | `src/joy_interaction_webui/rtsp_track.py` | BLE001 | narrow except |
| 7 | `src/joy_interaction_webui/server.py` | BLE001 | narrow except |
| 8 | `src/joy_interaction_webui/tts.py` | BLE001 | narrow except |
| 9 | `src/joy_interaction_webui/video_processor.py` | BLE001 | narrow except |
| 10 | `src/joy_interaction_webui/vlm_service.py` | BLE001 | narrow except |

### 2c. Test relaxation (both configs)

`**/tests/*`, `**/test_*.py`, `**/conftest.py` → `S101`, `BLE001`. Covers 54 benign
test violations (asserts + 3 blind excepts in `test_jarvis_webinfer_e2e.py`). Low
priority — burn down only when a test genuinely mishandles errors.

---

## 3. Burn-down procedure (keep the gate green)

1. Pick a file from §2a/§2b. Fix the violation(s) (narrow the `except`, replace
   `assert` with explicit `raise`, or use `secrets` for `S311`).
2. **Delete that file's entry** from the matching `per-file-ignores` block
   (root config for §2a, webui config for §2b). Do **not** leave stale entries.
3. Verify locally (§4) before pushing. The baseline list is the single source of
   truth for the outstanding backlog — when it's empty, Batch 3 is fully burned down.

**Division of labor:** non-webui prod (§2a) → backend dialogue / service owners;
webui prod (§2b) → frontend dialogue; tests (§2c) → test author.

---

## 4. Verification (run before pushing — must be green)

```bash
# Repo-wide (forces the 3 codes everywhere; uses root config for non-webui,
# webui config for webui files via nearest-config resolution)
ruff check . --select BLE001,S101,S311        # expect: All checks passed!

# CI-equivalent for webui (working-directory: services/webui, webui's own config)
cd services/webui && ruff check .             # expect: All checks passed!
```

Both pass under `ruff==0.15.22` (the CI-pinned version). CI's per-dir `ruff check`
runs with `--extend-ignore` lists that only *remove* rules, so it is at least as
permissive as the above — therefore a green local run guarantees a green CI run for
these three codes.

---

## 5. Rollback

All changes are config-only and reversible:
- Revert the two `pyproject.toml` files to drop `BLE001`/`S101`/`S311` from `select`
  and the `per-file-ignores` blocks. No code changes depend on this batch.

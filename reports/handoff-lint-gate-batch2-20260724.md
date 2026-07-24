# Handoff — ADR-0011 Batch 2: tighten ruff `S`-family selection

**Date:** 2026-07-24
**Owner:** backend dialogue (code fixes) · architecture dialogue (config diff + this handoff)
**Source:** `doc/adr/0011-phased-lint-gate.md` (Batch 2)
**Verification tool:** `D:/AI/ruffmig/bin/ruff.exe` (pinned `0.15.22`, matches CI)

---

## 1. What changes (config diff — apply by architecture dialogue, with the fixes)

Repo-root `pyproject.toml`, `[tool.ruff.lint] select` list — add the **scoped** `S`
sub-rules. Do **not** add the full `S` family or `BLE` (those are Batch 3).

```diff
 select = [
     "E",   # style errors
     "F",   # pyflakes
     "W",   # warnings
     "I",   # isort
     "UP",  # pyupgrade
     "B",   # bugbear
     "C4",  # comprehensions
     "SIM", # simplify
     "N",   # pep8-naming
     "RUF", # ruff-specific
     "D",   # pydocstyle
+    "S104", "S108", "S110", "S112", "S310",  # Batch 2 gate (ADR-0011)
 ]
```

> **Note:** the audit claimed `B904/B019/B007` were suppressed via `extend-ignore`.
> That is **false** — no `extend-ignore` exists anywhere in the repo. `B019` (3×) and
> `B007` (1×) are already reported via the `B` family, so nothing to remove there.

---

## 2. Violations to fix (33 total, exact locations via `ruff` 0.15.22)

Command to re-list / verify:
```bash
D:/AI/ruffmig/bin/ruff.exe check . --select B019,B007,F841,S104,S108,S110,S112,S310 --output-format concise
```
Target after fixes: **0**.

### Group A — clear fixes (do now, low risk)

**`B019` ×3 — `@functools.lru_cache` on methods (memory leak across instances)**
→ convert to module-level cache or `@staticmethod` + module cache.
- `services/kws-training/kws_data_module.py:80`
- `services/kws-training/kws_data_module.py:89`
- `services/kws-training/kws_data_module.py:94`

**`B007` ×1 — unused loop control variable**
- `services/scripts/analyze_kws_captures.py:64` (`duration` unused in loop body) → use `_` or `enumerate` only what's needed.

**`F841` ×3 — local variable assigned but never used**
- `services/kws-training/export_kws_onnx.py:239` (`token_table`)
- `services/scripts/record_kws_corpus.py:146` (`dt`)
- `services/scripts/test_jarvis_kws_e2e.py:80` (`logger`)

**`S110` ×10 — `try`-`except`-`pass` (silent failure)**
→ replace `pass` with `logger.warning("...", exc_info=e)` (add `logging` import if missing).
- `services/memory-store/src/memory_store/backends/sqlite_backend.py:184`
- `services/scripts/test_jarvis_state_machine_lite.py:123`
- `services/scripts/test_sherpa_load.py:163`
- `services/webinfer/session.py:108`
- `services/webui/src/joy_interaction_webui/asr.py:502`
- `services/webui/src/joy_interaction_webui/server.py:709`
- `services/webui/src/joy_interaction_webui/server.py:808`
- `services/webui/src/joy_interaction_webui/server.py:815`
- `services/webui/src/joy_interaction_webui/server.py:820`
- `services/webui/tests/test_jarvis_webinfer_e2e.py:203`

**`S112` ×2 — `try`-`except`-`continue`**
→ same treatment: log before `continue`.
- `services/webui/src/joy_interaction_webui/server.py:371`
- `services/webui/src/joy_interaction_webui/vlm_service.py:665`

### Group B — review first; if intentional, add targeted `# noqa` with a reason

**`S104` ×4 — binding to all interfaces (`0.0.0.0`)**
→ if the service must be reachable beyond localhost, add `# noqa: S104  # intended: LAN-scoped dev server` at the line; otherwise bind `127.0.0.1`.
- `services/asr/asr_adapter.py:348`
- `services/asr/asr_adapter.py:380`
- `services/tts/tts_adapter.py:496`
- `services/tts/tts_adapter.py:540`

**`S108` ×8 — probable insecure temp file/dir (`/tmp/...` model-cache paths)**
→ these are intentional model-cache locations; add `# noqa: S108  # intended: model cache dir` at each line (or move to a configured, non-world-readable path).
- `services/webinfer/adapter_types.py:52`
- `services/webinfer/adapter_types.py:54`
- `services/webinfer/adapter_types.py:86`
- `services/webinfer/app.py:138`
- `services/webinfer/app.py:151`
- `services/webinfer/app.py:270`
- `services/webinfer/memory_summarizer.py:294`
- `services/webui/src/joy_interaction_webui/background_model.py:68`

**`S310` ×2 — `urllib` URL open (scheme allow-list)**
→ review the scheme; if only `http(s)` is expected, validate or add `# noqa: S310  # trusted internal URL`.
- `services/scripts/verify-services.py:32`
- `services/scripts/verify-services.py:36`

---

## 3. Execution rules

1. **One PR.** Land the `pyproject.toml` flip (§1) together with all Group A fixes and
   Group B `# noqa`/reviews in a **single** PR so CI never goes red.
2. **Don't touch Group C.** `S101` (×97), `S311` (×13), `BLE001` (×106) are **not** in
   this batch — they go to Batch 3 (`ruff --baseline` burn-down). Do not add them to
   `select` yet.
3. **Verify before push:** run the §2 command locally → expect `0` findings, and
   `quality-check.sh` (ruff check + format) must pass.
4. **Branch:** do this on a branch off `main` (or `ci/lint-gate-batch2` if co-owned);
   do **not** commit into the architecture dialogue's `docs/lint-gate-adr0011-batch1`.

---

## 4. Why scoped, not wholesale

Flipping the full `S` family at once surfaces ~216 violations (`S101`×97 asserts,
`S311`×13, `BLE001`×106) — the flag-flip trap that keeps CI red for days. Scoping to
the 33 small, high-value items lets Batch 2 ship green, and Batch 3 burns down the
large families via `--baseline`.

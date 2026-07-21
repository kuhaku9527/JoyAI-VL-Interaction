# Code Review Checklist

A senior reviewer works top-down: **correctness first, then design, then
style**. Style is mostly enforced by `ruff`/CI, so spend review time on the
parts a machine can't judge. Copy the relevant section into your PR comment.

---

## 🔴 Must-fix (block merge)

- [ ] **Correctness:** Does the change do what the PR claims? Any obvious logic
      bug, off-by-one, or wrong branch?
- [ ] **No undefined names / imports:** grep for new symbols; `F821` (undefined
      name) and `F401` (unused import) are caught by CI, but confirm intent.
- [ ] **Error handling:** No bare `except:` / `except Exception: pass`; raises
      inside `except` use `from err` (`B904`); no `assert` on production paths
      (`B011`).
- [ ] **No secret / PII leakage:** no tokens, keys, or personal data in code,
      logs, or committed artifacts (`.env` is gitignored — keep it that way).
- [ ] **No silent behavior change:** side effects, default args, or public
      signatures altered without a note.
- [ ] **Tests:** new behavior has tests; existing tests still pass.

## 🟠 Design & maintainability

- [ ] **Single responsibility:** is the change in the right module? Does it
      belong in a 3,500-line file like `live_adapter.py`, or should it be
      extracted? (See `coding-standards.md` §7.)
- [ ] **API shape:** are public function signatures typed and intuitive? Are
      defaults safe (no mutable default args — `B006`)?
- [ ] **Naming:** are names self-documenting? Tensor dims `T`/`B` only inside
      clearly mathematical code.
- [ ] **Complexity:** any function that grew past ~50 lines or nested past 3
      levels? Could it be split?
- [ ] **Vendored code:** changes do **not** touch `icefall_src/` (re-sync from
      upstream instead).

## 🟡 Readability & conventions

- [ ] **Docstrings:** public modules/classes/functions/methods documented
      (NumPy convention).
- [ ] **Comments:** explain *why*, not *what*; no commented-out dead code
      (`B018` useless-expression / leftovers).
- [ ] **Logging:** uses `logging` (not `print`) in services; right level.
- [ ] **Style:** `ruff format` + `ruff check` are clean (CI enforces this).

## 🟢 Reviewer etiquette

- [ ] Praise good changes explicitly — review is teaching, not gatekeeping.
- [ ] Separate **blocking** notes from **nits** (the latter can be follow-ups).
- [ ] If you request changes, re-review promptly.
- [ ] For large refactors, suggest an incremental path rather than demanding a
      rewrite in one PR.

---

### Quick CI-local verification (run before requesting review)

```bash
./scripts/quality-check.sh --fix     # auto-fix safe issues
# then commit the formatting result
```

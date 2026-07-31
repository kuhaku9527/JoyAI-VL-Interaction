#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test for drift_gate.py executor.

Runs five invocations:
  1. static + open mode: never fails, just warns.
  2. JSON output: must parse, must contain all 4 checks.
  3. closed mode + static only - rc=0 if env matches contract, rc=1 if drifted.
  4. Meta-error: missing contract file -> exit 2; META-ERROR goes to stdout.
  5. **Positive PASS case**: build a temp contract pointing at the real
     run-windows.env (which we know contains MAIN_CONTEXT=16384 + 8997);
     every check should pass and rc=0. Closes the smoke-test blind spot
     flagged in workbuddy audit: prior smoke only checked exit codes,
     never a compliant env's actual passed=True verdict.

Usage:
    python scripts/drift_gate_smoke_test.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "drift_gate.py"
CONTRACT = ROOT / "config" / "drift-contract.json"
PYTHON = sys.executable


def run(args, cwd=None):
    proc = subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        cwd=str(cwd) if cwd else str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode, proc.stdout, proc.stderr


def main():
    if not SCRIPT.exists() or not CONTRACT.exists():
        print(f"ERROR: missing {SCRIPT} or {CONTRACT}")
        return 2

    failures = 0

    # 1. static + open mode: never fails, just warns.
    rc, out, err = run(["--contract", str(CONTRACT), "--phase", "static", "--mode", "open"])
    first_line = out.splitlines()[0] if out else "<empty>"
    print(f"[static/open] exit={rc}  stdout_first_line={first_line}")
    if rc != 0:
        print(f"[FAIL] expected rc=0, got {rc}  stderr={err}")
        failures += 1
    elif "Drift Gate" not in out:
        print("[FAIL] expected text header in output")
        failures += 1
    else:
        print("[OK]   static/open - header present, rc=0")

    # 2. JSON output: must parse, must contain all 4 checks.
    rc, out, err = run(["--contract", str(CONTRACT), "--phase", "all", "--mode", "open", "--json"])
    print(f"\n[json] exit={rc}  stdout_bytes={len(out)}")
    if rc != 0:
        print(f"[FAIL] json mode rc={rc}  stderr={err}")
        failures += 1
    else:
        try:
            j = json.loads(out)
        except json.JSONDecodeError as exc:
            print(f"[FAIL] json parse error: {exc}")
            failures += 1
        else:
            ids = [r["id"] for r in j["results"]]
            expected_ids = {"vlm-n_ctx", "memory-store-port", "webui-gateway-port", "main-context-env"}
            missing = expected_ids - set(ids)
            if missing:
                print(f"[FAIL] missing checks in JSON: {missing}")
                failures += 1
            else:
                print(f"[OK]   json mode - all 4 checks present: {sorted(ids)}")
                print(f"       ran={j['total_checks']} block_fail={j['block_failures']} warn_fail={j['warn_failures']}")

    # 3. closed mode + static only.
    rc, out, err = run(["--contract", str(CONTRACT), "--phase", "static", "--mode", "closed"])
    print(f"\n[static/closed] exit={rc}")
    if rc == 0:
        print("[OK]   static/closed - no block failures")
    elif rc == 1:
        print("[INFO] static/closed rc=1 - at least one block check drifted (expected on a drifted env)")
    else:
        print(f"[FAIL] unexpected rc={rc}  stderr={err}")
        failures += 1

    # 4. Meta-error: missing contract file -> exit 2.
    rc, out, err = run(["--contract", str(ROOT / "config" / "nonexistent.json"), "--phase", "static", "--mode", "open"])
    first = (out or err).splitlines()[0] if (out or err) else "<empty>"
    print(f"\n[meta-error] exit={rc}  first_line={first}")
    if rc != 2:
        print(f"[FAIL] expected rc=2 (meta-error), got {rc}")
        failures += 1
    elif "META-ERROR" not in out:
        print(f"[FAIL] expected META-ERROR in stdout, got: {out[:200]}")
        failures += 1
    else:
        print("[OK]   meta-error path - exit 2 with META-ERROR message on stdout")

    # 5. Positive PASS case: build a temp contract pointing at the real
    #    run-windows.env (which contains MAIN_CONTEXT=16384 + 8997).
    #    Every check should pass and rc=0. Closes the smoke-test blind
    #    spot flagged in workbuddy audit: prior smoke only checked exit
    #    codes, never a compliant env's actual passed=True verdict.
    tmpdir = Path(tempfile.mkdtemp(prefix="drift_gate_smoke_"))
    try:
        compliant_contract = {
            "version": 99,
            "source_of_truth": "smoke-test-tmp",
            "checks": [
                {
                    "id": "smoke-positive-MAIN_CONTEXT",
                    "decision_ref": "smoke-test",
                    "description": "MAIN_CONTEXT must be 16384 in env",
                    "phase": "static",
                    "paths": ["services/scripts/run-windows.env"],
                    "pattern": r"^MAIN_CONTEXT\s*=\s*16384",
                    "severity": "block",
                },
                {
                    "id": "smoke-positive-8997",
                    "decision_ref": "smoke-test",
                    "description": "memory-store port 8997 present",
                    "phase": "static",
                    "paths": [
                        "services/scripts/run-windows.env",
                        "services/memory-store/src/memory_store/app.py",
                    ],
                    "pattern": r"8997",
                    "severity": "block",
                },
            ],
        }
        tmp_contract = tmpdir / "compliant.json"
        tmp_contract.write_text(json.dumps(compliant_contract), encoding="utf-8")
        rc, out, err = run(
            ["--contract", str(tmp_contract), "--phase", "static", "--mode", "closed", "--json"],
            cwd=ROOT,
        )
        try:
            j = json.loads(out)
        except json.JSONDecodeError as exc:
            print(f"\n[FAIL] positive-case: json parse error: {exc}")
            failures += 1
        else:
            results = j.get("results", [])
            all_passed = all(r["passed"] for r in results)
            n = len(results)
            print(f"\n[positive-PASS] exit={rc}  checks={n}  all_passed={all_passed}")
            if rc != 0:
                print(f"[FAIL] expected rc=0 on compliant env, got {rc}  stderr={err}")
                failures += 1
            elif n != 2:
                print(f"[FAIL] expected 2 checks, got {n}")
                failures += 1
            elif not all_passed:
                failed_ids = [r["id"] for r in results if not r["passed"]]
                print(f"[FAIL] expected all passed=True on compliant env, failed={failed_ids}")
                failures += 1
            else:
                print("[OK]   positive-PASS - compliant env all checks passed=True, rc=0")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    if failures:
        print(f"FAIL {failures} failure(s)")
        return 1
    print("OK all smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

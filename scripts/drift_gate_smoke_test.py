#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test for drift_gate.py executor.

Runs six invocations:
  1. static + open mode: never fails, just warns.
  2. JSON output: must parse, must contain all 4 checks.
  3. closed mode + static only - rc=0 if env matches contract, rc=1 if drifted.
  4. Meta-error: missing contract file -> exit 2; META-ERROR goes to stdout.
  5. **Positive PASS case**: build a temp contract pointing at the real
     run-windows.env (which we know contains MAIN_CONTEXT=16384 + 8997);
     every check should pass and rc=0. Closes the smoke-test blind spot
     flagged in workbuddy audit: prior smoke only checked exit codes,
     never a compliant env's actual passed=True verdict.
  6. **Runtime probe + drift_gate integration**: run
     scripts/vlm_runtime_probe.py (writes logs/vlm-runtime-props.json)
     then re-run drift_gate --phase all --mode closed; expects 4/4 PASS.
     Closes the runtime-check blind spot: the old gate parsed
     logs/llama-main.log for n_ctx_slot, but the launcher never wrote
     that log, so the runtime phase was structurally impossible to pass.

Usage:
    python scripts/drift_gate_smoke_test.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "drift_gate.py"
CONTRACT = ROOT / "config" / "drift-contract.json"
PROBE = ROOT / "scripts" / "vlm_runtime_probe.py"
PYTHON = sys.executable
VLM_PROPS_REL = "logs/vlm-runtime-props.json"


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
    #    F4-P1a: --phase all 现在会为 runtime 检查触发 probe 刷新。若 llama 未起
    #    （props 缺失/过期且 probe 失败 → rc=3，显式错误、不静默 SKIP），此例与
    #    case #6 一致地 skip，不强行要求 llama 在线。
    rc, out, err = run(["--contract", str(CONTRACT), "--phase", "all", "--mode", "open", "--json"])
    print(f"\n[json] exit={rc}  stdout_bytes={len(out)}")
    if rc == 0:
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
    elif rc == 3 and "RUNTIME-PROBE-FAILED" in err:
        print("[INFO] json case: runtime probe 无法刷新 props（llama 未起），跳过（与 probe+gate 一致）")
    else:
        print(f"[FAIL] json mode rc={rc}  stderr={err}")
        failures += 1

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

    # 3b. Non-`--json` path must NOT crash with UnboundLocalError (P0-1 fix).
    #     Before the fix, the non-json branch bound `text` while L263
    #     referenced `out`, so any invocation without --json AND without
    #     --no-history raised UnboundLocalError -> non-zero early crash and a
    #     traceback on stderr. We assert rc in {0,1} AND that no traceback /
    #     UnboundLocalError leaked (this is the only automated guard against
    #     the regression; CI runs this smoke test).
    rc, out, err = run(
        ["--contract", str(CONTRACT), "--phase", "static", "--mode", "closed"]
    )
    print(f"\n[non-json/no-crash] exit={rc}")
    crashed = ("UnboundLocalError" in err) or ("Traceback" in err)
    if rc not in (0, 1):
        print(f"[FAIL] non-json path unexpected rc={rc}  stderr={err[:200]}")
        failures += 1
    elif crashed:
        print(f"[FAIL] non-json path crashed (UnboundLocalError): {err[:200]}")
        failures += 1
    else:
        print("[OK]   non-json path - no crash (rc in {0,1})")

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
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 6. Runtime probe + drift_gate integration. Skipped if no llama is up.
    #    If llama is up: probe writes logs/vlm-runtime-props.json, then
    #    drift_gate --phase all --mode closed must report all checks passed.
    #    If llama is NOT up: skip with INFO (operator should run after
    #    start-joyai.ps1).
    if not PROBE.exists():
        print(f"\n[probe+gate] SKIP - {PROBE.name} not present")
    else:
        probe_proc = subprocess.run(
            [PYTHON, str(PROBE), "--out", str(ROOT / "logs" / "vlm-runtime-props.json"), "--wait", "5"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        probe_rc = probe_proc.returncode
        probe_out = (probe_proc.stdout or "") + (probe_proc.stderr or "")
        print(f"\n[probe+gate] probe exit={probe_rc}  out={probe_out.strip()[:120]}")
        if probe_rc == 0:
            rc, out, err = run(
                ["--contract", str(CONTRACT), "--phase", "all", "--mode", "closed", "--json"]
            )
            try:
                j = json.loads(out)
            except json.JSONDecodeError as exc:
                print(f"[FAIL] json parse after probe: {exc}")
                failures += 1
            else:
                runtime_block = [
                    r for r in j["results"] if r["phase"] == "runtime" and not r["passed"]
                ]
                if rc != 0 or runtime_block:
                    failed = [(r["id"], r["detail"][:80]) for r in j["results"] if not r["passed"]]
                    print(f"[FAIL] drift_gate after probe: rc={rc}  failed={failed}")
                    failures += 1
                else:
                    print(f"[OK]   probe+gate - llama n_ctx=16384 verified end-to-end")
        else:
            print("[INFO] probe couldn't reach llama (server not up). Run after start-joyai.ps1.")

    # === F4-P1e 新增 3 例：顺序/边界、负向 not_pattern、launcher 接 gate ===

    # 7. 顺序 + 边界（F4-P1a 收口验证）：runtime gate 在 props 存在时不应 SKIP，
    #    而应真实判定。用临时 repo-root + 临时 props，避免污染真实 logs/。
    #    - 4096（漂移）→ 必须 block（rc=1），且不得 SKIP。
    #    - 16384（合规）→ 必须通过（rc=0），且不得 SKIP（证明 gate 严格判 props）。
    import shutil as _shutil

    tmp_repo = Path(tempfile.mkdtemp(prefix="drift_gate_rt_"))
    try:
        props_dir = tmp_repo / "logs"
        props_dir.mkdir(parents=True, exist_ok=True)
        rt_contract = {
            "version": 99,
            "source_of_truth": "smoke-test-rt",
            "checks": [
                {
                    "id": "smoke-rt-n_ctx",
                    "decision_ref": "smoke-test",
                    "description": "runtime n_ctx must be 16384",
                    "phase": "runtime",
                    "paths": [VLM_PROPS_REL],
                    "pattern": r"\"n_ctx\":\s*16384",
                    "severity": "block",
                }
            ],
        }
        rt_contract_path = tmp_repo / "rt-contract.json"
        rt_contract_path.write_text(json.dumps(rt_contract), encoding="utf-8")

        def run_rt(n_ctx: int):
            (props_dir / "vlm-runtime-props.json").write_text(
                json.dumps({"ran_at": "2026-01-01T00:00:00Z", "n_ctx": n_ctx}),
                encoding="utf-8",
            )
            return run(
                [
                    "--contract", str(rt_contract_path),
                    "--repo-root", str(tmp_repo),
                    "--phase", "runtime", "--mode", "closed", "--json", "--no-history",
                ],
                cwd=tmp_repo,
            )

        # 7a. 漂移值 4096 → block（rc=1），不得 SKIP。
        rc, out, err = run_rt(4096)
        try:
            j = json.loads(out)
            r = j["results"][0]
            skipped = "[SKIP]" in r["detail"]
            blocked = "[BLOCK]" in r["detail"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            print(f"\n[FAIL] rt/4096: parse error {exc}  stderr={err[:200]}")
            failures += 1
        else:
            print(f"\n[rt/4096] exit={rc}  passed={r['passed']}  skipped={skipped}  blocked={blocked}")
            if rc != 1:
                print(f"[FAIL] rt/4096 expected rc=1 (block), got {rc}  stderr={err[:200]}")
                failures += 1
            elif skipped:
                print("[FAIL] rt/4096 gate SKIPped instead of blocking on drifted props")
                failures += 1
            elif not blocked:
                print(f"[FAIL] rt/4096 expected [BLOCK], detail={r['detail'][:80]}")
                failures += 1
            else:
                print("[OK]   rt/4096 - drifted n_ctx blocked, no SKIP fallback")

        # 7b. 合规值 16384 → 通过（rc=0），不得 SKIP（证明 gate 严格晚于 probe 生效）。
        rc, out, err = run_rt(16384)
        try:
            j = json.loads(out)
            r = j["results"][0]
            skipped = "[SKIP]" in r["detail"]
            ok = "[OK]" in r["detail"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            print(f"\n[FAIL] rt/16384: parse error {exc}  stderr={err[:200]}")
            failures += 1
        else:
            print(f"\n[rt/16384] exit={rc}  passed={r['passed']}  skipped={skipped}  ok={ok}")
            if rc != 0:
                print(f"[FAIL] rt/16384 expected rc=0, got {rc}  stderr={err[:200]}")
                failures += 1
            elif skipped:
                print("[FAIL] rt/16384 gate SKIPped on present props (顺序保护失效)")
                failures += 1
            elif not ok:
                print(f"[FAIL] rt/16384 expected [OK], detail={r['detail'][:80]}")
                failures += 1
            else:
                print("[OK]   rt/16384 - compliant n_ctx passed, no SKIP (顺序保护生效)")
    finally:
        _shutil.rmtree(tmp_repo, ignore_errors=True)

    # 8. 负向 not_pattern：含 8996 的文件在 not_pattern 下必须 block（rc=1），不 SKIP。
    tmp_repo2 = Path(tempfile.mkdtemp(prefix="drift_gate_neg_"))
    try:
        bad_file = tmp_repo2 / "bad_config.txt"
        bad_file.write_text("MEMORY_PORT=8996\n", encoding="utf-8")
        neg_contract = {
            "version": 99,
            "source_of_truth": "smoke-test-neg",
            "checks": [
                {
                    "id": "smoke-neg-8996",
                    "decision_ref": "smoke-test",
                    "description": "must NOT contain 8996",
                    "phase": "static",
                    "paths": ["bad_config.txt"],
                    "pattern": "8996",        # 匹配（文件确实含 8996）
                    "not_pattern": "8996",    # 但要求不得匹配 → 必然失败
                    "severity": "block",
                }
            ],
        }
        neg_contract_path = tmp_repo2 / "neg-contract.json"
        neg_contract_path.write_text(json.dumps(neg_contract), encoding="utf-8")
        rc, out, err = run(
            [
                "--contract", str(neg_contract_path),
                "--repo-root", str(tmp_repo2),
                "--phase", "static", "--mode", "closed", "--json", "--no-history",
            ],
            cwd=tmp_repo2,
        )
        try:
            j = json.loads(out)
            r = j["results"][0]
            blocked = "[BLOCK]" in r["detail"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            print(f"\n[FAIL] neg/8996: parse error {exc}  stderr={err[:200]}")
            failures += 1
        else:
            print(f"\n[neg/8996] exit={rc}  passed={r['passed']}  blocked={blocked}")
            if rc != 1:
                print(f"[FAIL] neg/8996 expected rc=1 (block), got {rc}  stderr={err[:200]}")
                failures += 1
            elif not blocked:
                print(f"[FAIL] neg/8996 expected [BLOCK], detail={r['detail'][:80]}")
                failures += 1
            else:
                print("[OK]   neg/8996 - not_pattern 拦截含 8996 的漂移，rc=1")
    finally:
        _shutil.rmtree(tmp_repo2, ignore_errors=True)

    # 9. launcher 接 gate 模式：--no-history 在合规/漂移 env 下都不 crash。
    tmp_launch = Path(tempfile.mkdtemp(prefix="drift_gate_launch_"))

    def launch_case(name, pattern, expect_rc):
        contract = {
            "version": 99,
            "source_of_truth": f"smoke-test-launch-{name}",
            "checks": [
                {
                    "id": f"smoke-launch-{name}",
                    "decision_ref": "smoke-test",
                    "description": name,
                    "phase": "static",
                    "paths": ["config/drift-contract.json"],
                    "pattern": pattern,
                    "severity": "block",
                }
            ],
        }
        path = tmp_launch / f"{name}.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        rc, _out, err = run(
            ["--contract", str(path), "--phase", "static", "--mode", "closed", "--no-history"]
        )
        crashed = ("Traceback" in err) or ("UnboundLocalError" in err)
        print(f"\n[launch/{name}] exit={rc}  crashed={crashed}")
        if rc != expect_rc:
            print(f"[FAIL] launch/{name} expected rc={expect_rc}, got {rc}  stderr={err[:200]}")
            return 1
        if crashed:
            print(f"[FAIL] launch/{name} crashed: {err[:200]}")
            return 1
        print(f"[OK]   launch/{name} - --no-history rc={rc} 不崩溃")
        return 0

    try:
        failures += launch_case("ok", r"version", 0)
        failures += launch_case("bad", r"__NEVER_MATCHES_xyz__", 1)
    finally:
        _shutil.rmtree(tmp_launch, ignore_errors=True)

    print()
    if failures:
        print(f"FAIL {failures} failure(s)")
        return 1
    print("OK all smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

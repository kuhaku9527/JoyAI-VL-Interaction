#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drift Gate 执行器（决策书 → 机器可读契约 → 运行态校验）

依据：
  - doc/specs/drift-gate-harness-spec.md（已批准 / 2026-07-29）
  - reports/drift-gate-handoff.md（交接给后端 / DevOps）
  - config/drift-contract.json（契约，本仓库根 config/）

设计原则（来自 spec）：
  - 脚本**不硬编码**任何端口 / n_ctx 等值；值全部来自契约。
  - 门禁是"一致性检查器"，不是"值冻结器"。
  - 默认 fail-open（不符仅 warning，不阻断），避免瞬时误杀合法改动。
  - phase 区分：static=查配置/代码常量；runtime=查运行实例 / 端口 / 日志。
  - **跨平台**：纯 Python 读文件 + re.search，不 shell-out 调 grep / cmd.exe。

契约 schema（v2）：
  {
    "id": "<check-id>",
    "decision_ref": "决策/...md D-XXX",
    "description": "...",
    "phase": "static" | "runtime",
    "paths": ["rel/path/to/file", ...],   # 必填；要读的文件列表
    "pattern": "<regex>",                  # 必填；必须在合并文件内容中至少匹一次
    "not_pattern": "<regex>" | null,       # 可选；若设置则要求**不**匹配（一般不推荐）
    "severity": "block" | "warn"
  }

用法：
  python scripts/drift_gate.py --contract config/drift-contract.json --phase static --mode open
  python scripts/drift_gate.py --contract config/drift-contract.json --phase runtime --mode closed --report drift_report.txt
  python scripts/drift_gate.py --contract config/drift-contract.json --json

退出码：
  mode=open    -> 永远 0（仅打印告警）
  mode=closed  -> 任一 severity=block 的检查不符则 1，否则 0
  契约缺失/JSON 解析失败 -> 2（meta-error，区别于业务漂移）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_contract(path: str) -> dict:
    """加载契约 JSON。缺失 / 解析失败 → meta-error 退出码 2。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"[META-ERROR] 契约文件缺失: {path} — 门禁无法运行，请确认已建立 drift-contract.json")
        sys.exit(2)
    except json.JSONDecodeError as exc:
        print(f"[META-ERROR] 契约 JSON 解析失败: {exc}")
        sys.exit(2)

    if "checks" not in data or not isinstance(data["checks"], list):
        print(f"[META-ERROR] 契约 schema 错误: 缺 'checks' 数组（got keys: {list(data.keys())}）")
        sys.exit(2)
    return data


def run_check_files(check: dict, repo_root: Path) -> str:
    """读 paths 列出的所有文件并合并成单一字符串返回（UTF-8 容错）。

    任一文件缺失 -> 输出追加 `<missing:path>` 占位，让契约检查者能区分
    "读到但不符" vs "文件不存在"。这是 schema-level 不变量，调用方
    可选择如何处理（默认 evaluate 把它当"含特殊 token"算 fail）。
    """
    paths = check.get("paths") or []
    chunks: list[str] = []
    for p in paths:
        full = repo_root / p
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            chunks.append(f"<missing:{p}>")
            continue
        except OSError as exc:
            chunks.append(f"<read-error:{p}:{exc!r}>")
            continue
        chunks.append(f"--- {p} ---\n{content}\n")
    return "\n".join(chunks)


def _is_all_missing(output: str) -> bool:
    """True if the merged file content is entirely ``<missing:...>`` placeholders.

    Mirrors verify.sh's [DOWN] (fail-open) behaviour for absent files so the
    gate stays green in CI where gitignored files (e.g. run-windows.env) are
    not checked out. A check that points only at absent files is treated as
    passed (non-blocking); the guard still fires wherever the file exists.
    """
    stripped = re.sub(r"<missing:[^>]*>", "", output)
    return stripped.strip() == ""


def evaluate(check: dict, output: str, mode: str) -> tuple[bool, str]:
    """比对输出与期望正则，返回 (passed, detail)。"""
    cid = check.get("id", "?")
    ref = check.get("decision_ref", "?")
    desc = check.get("description", "")
    pattern = check.get("pattern", "")
    not_pattern = check.get("not_pattern")

    # Fail-open when every referenced file is absent (CI / clean checkout):
    # don't red-fail a gate on a file that legitimately isn't checked out.
    if _is_all_missing(output):
        return True, f"[SKIP] {cid} 引用文件均缺失，fail-open（不阻断）: {ref}"

    _flags = re.MULTILINE
    matched = bool(re.search(pattern, output, _flags)) if pattern else False
    not_matched = (not bool(re.search(not_pattern, output, _flags))) if not_pattern else True
    passed = matched and not_matched

    if passed:
        return True, f"[OK]   {cid} 符合决策书: {ref}"

    severity = check.get("severity", "warn")
    paths = check.get("paths") or []
    paths_repr = ", ".join(paths) if len(paths) <= 4 else f"{len(paths)} files"

    head = f"[BLOCK] {cid}" if (severity == "block" and mode == "closed") else f"[WARN] {cid}"
    why_parts = []
    if pattern and not matched:
        why_parts.append(f"pattern=/{pattern}/ 未匹配")
    if not_pattern and not not_matched:
        why_parts.append(f"not_pattern=/{not_pattern}/ 不应匹配但匹配了")
    if not why_parts:
        why_parts.append("schema 错误（缺 pattern）")
    why = "; ".join(why_parts)

    if mode == "open":
        return False, (
            f"{head} 运行态≠决策态（open 模式不阻断）: {ref}\n"
            f"       description: {desc}\n"
            f"       paths: {paths_repr}\n"
            f"       {why}"
        )
    # closed 模式
    if severity == "block":
        return False, (
            f"{head} 运行态≠决策态 且 severity=block: {ref}\n"
            f"       description: {desc}\n"
            f"       paths: {paths_repr}\n"
            f"       {why}"
        )
    return False, (
        f"{head} 不符 但 severity={severity}: {ref}\n"
        f"       description: {desc}\n"
        f"       {why}"
    )


def run_all(contract: dict, phase: str, mode: str, repo_root: Path) -> dict:
    """跑所有适用 phase 的检查，返回结构化结果。"""
    checks = contract.get("checks", [])
    results: list[dict] = []
    any_block_fail = False
    ran = 0
    for c in checks:
        cphase = c.get("phase", "static")
        if phase != "all" and cphase != phase:
            continue
        ran += 1
        out = run_check_files(c, repo_root)
        passed, detail = evaluate(c, out, mode)
        results.append(
            {
                "id": c.get("id"),
                "phase": cphase,
                "severity": c.get("severity", "warn"),
                "decision_ref": c.get("decision_ref"),
                "description": c.get("description"),
                "expected_regex": c.get("pattern"),
                "paths": c.get("paths"),
                "passed": passed,
                "detail": detail,
            }
        )
        if not passed and c.get("severity") == "block" and mode == "closed":
            any_block_fail = True

    return {
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phase": phase,
        "mode": mode,
        "source_of_truth": contract.get("source_of_truth", "决策/"),
        "contract_version": contract.get("version"),
        "total_checks": ran,
        "block_failures": sum(1 for r in results if not r["passed"] and r["severity"] == "block"),
        "warn_failures": sum(1 for r in results if not r["passed"] and r["severity"] != "block"),
        "results": results,
        "any_block_fail": any_block_fail,
    }


def format_text(report: dict) -> str:
    lines = [
        f"# Drift Gate 报告  phase={report['phase']} mode={report['mode']}",
        f"# 真值源: {report['source_of_truth']}  contract_version={report['contract_version']}",
        f"# ran_at={report['ran_at']}  total={report['total_checks']}  block_fail={report['block_failures']}  warn_fail={report['warn_failures']}",
        "",
    ]
    for r in report["results"]:
        lines.append(r["detail"])
    lines.append("")
    lines.append(
        f"# 共跑 {report['total_checks']} 项；mode={report['mode']}；block 级失败={report['any_block_fail']}"
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Drift Gate 执行器（决策书→契约→运行态校验）")
    ap.add_argument("--contract", required=True, help="契约 JSON 路径（如 config/drift-contract.json）")
    ap.add_argument(
        "--phase",
        choices=["static", "runtime", "all"],
        default="all",
        help="只跑该阶段（static=配置/代码, runtime=运行实例）",
    )
    ap.add_argument(
        "--mode",
        choices=["open", "closed"],
        default="open",
        help="open=不符仅告警；closed=block 级不符则失败退出",
    )
    ap.add_argument("--report", default=None, help="把报告写到文件（人类可读文本）")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式输出报告（机器可读）")
    ap.add_argument(
        "--repo-root",
        default=None,
        help="仓库根路径（默认：脚本所在位置的父目录）",
    )
    ap.add_argument(
        "--history-dir",
        default=None,
        help="限定方式：每次 run 写一份 <UTC-ISO>.json 到这个目录（默认 logs/drift-gate-history/），不覆盖。传 --no-history 关闭。",
    )
    ap.add_argument("--no-history", action="store_true", help="不写历史报告（仅 stdout/--report）")
    args = ap.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parent.parent

    contract = load_contract(args.contract)
    report = run_all(contract, args.phase, args.mode, repo_root)

    if args.json:
        out = json.dumps(report, ensure_ascii=False, indent=2)
        print(out)
        if args.report:
            Path(args.report).write_text(out + "\n", encoding="utf-8")
    else:
        # P0-1: bind `out` (not a separate `text`) so the history write at
        # L263 can reuse it. Previously the non-`--json` branch bound `text`
        # while L263 referenced `out`, raising UnboundLocalError on any
        # invocation without --json AND without --no-history.
        out = format_text(report)
        print(out)
        if args.report:
            Path(args.report).write_text(out + "\n", encoding="utf-8")

    if args.mode == "closed" and report["any_block_fail"]:
        return 1
    if not args.no_history:
        # Append a timestamped copy of the report to <history-dir>/. This
        # lets operators see "drift_gate said X at 09:00, Y at 14:00" later
        # without re-running the gate. Default <repo>/logs/drift-gate-history/.
        history_dir = (
            Path(args.history_dir).resolve()
            if args.history_dir
            else (repo_root / "logs" / "drift-gate-history")
        )
        try:
            history_dir.mkdir(parents=True, exist_ok=True)
            # ran_at is already ISO; replace ":" with "-" for Windows-safe filename.
            ts_safe = report["ran_at"].replace(":", "-")
            history_path = history_dir / (ts_safe + ".json")
            history_path.write_text(out, encoding="utf-8")
        except OSError as exc:
            print(f"[WARN] failed to write history report: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

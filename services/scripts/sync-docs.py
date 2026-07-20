"""
sync-docs.py - keep DELIVERY.md / 00-main-direction.md in sync after code changes.

项目惯例（参见 DELIVERY.md §7 变更记录 + 00-main-direction.md §4 v3.2 路线图）：
  - 每次代码变更必须追加 DELIVERY.md §7 一行
  - 每次"已落地"项必须同步 00-main-direction.md §4.0
  - 受影响的其他 doc 由调用方人工更新（用 --affected 列出来 reminder）

用法:
  python services\\scripts\\sync-docs.py ^
    --date 2026-07-12 ^
    --version v3.3 ^
    --change "MiniMax Token Plan 接入（半落地）..." ^
    --delivered "services/webui/src/joy_interaction_webui/jarvis_mode.py" ^
    --affected "doc/adr/0003-llm-reply-panel.md" ^
    --affected "doc/jarvis-mode.md §13.1"

不做的事：
  - 不自动改 ADR / 章节正文（每张表/每节措辞差异太大）
  - 不 git commit（hook 不在本脚本范围）
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DELIVERY = REPO_ROOT / "DELIVERY.md"
MAIN_DIR = REPO_ROOT / "doc" / "00-main-direction.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--date", default=dt.date.today().isoformat(),
                   help="变更日期（默认今天，YYYY-MM-DD）")
    p.add_argument("--version", required=True,
                   help="变更版本号（例 v3.3）")
    p.add_argument("--change", required=True,
                   help="一句话变更说明")
    p.add_argument("--delivered", action="append", default=[],
                   help="本次改动涉及的文件/服务（可多次）")
    p.add_argument("--affected", action="append", default=[],
                   help="受影响需人工复核的 doc 路径（可多次）")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印将要做什么，不实际改文件")
    p.add_argument("--no-delivery", action="store_true",
                   help="跳过 DELIVERY.md §7 更新")
    p.add_argument("--no-main", action="store_true",
                   help="跳过 00-main-direction.md §4.0 更新")
    return p.parse_args()


def fmt_delivery_row(args) -> str:
    delivered = "; ".join(args.delivered) if args.delivered else "-"
    affected = "; ".join(f"`{p}`" for p in args.affected) if args.affected else "-"
    return (f"| {args.date} | {args.version} | {args.change} "
            f"（受影响：{affected}；改动文件：{delivered}） | Codex |\n")


def append_delivery(args) -> bool:
    if not DELIVERY.exists():
        print(f"[skip] {DELIVERY} not found", file=sys.stderr)
        return False
    src = DELIVERY.read_text(encoding="utf-8")
    if args.version in src and f"| {args.date} |" in src:
        # 同一日期已有同名 version 行 —— 防重复
        print(f"[skip] DELIVERY.md already has {args.date} / {args.version}")
        return False
    new_row = fmt_delivery_row(args)
    # 追加到 §7 末尾（§7 是第一个变更记录表，找到下一个二级标题前）
    marker = "## 8. 复盘后补充"
    if marker not in src:
        # 找不到 §8 就追加到文件末尾
        src = src.rstrip() + "\n" + new_row
    else:
        src = src.replace(marker, new_row + marker, 1)
    if args.dry_run:
        print(f"[dry-run] would append to DELIVERY.md:\n{new_row.rstrip()}")
    else:
        DELIVERY.write_text(src, encoding="utf-8")
        print(f"[ok] DELIVERY.md +1 row ({args.date} {args.version})")
    return True


def append_main(args) -> bool:
    if not MAIN_DIR.exists():
        print(f"[skip] {MAIN_DIR} not found", file=sys.stderr)
        return False
    src = MAIN_DIR.read_text(encoding="utf-8")
    # 在 §4.0 末尾追加一项（用 version + date 作锚）
    anchor = "### §4.1 优先级说明"
    if anchor not in src:
        print("[skip] 00-main-direction.md §4.1 anchor not found", file=sys.stderr)
        return False
    if args.version in src:
        print(f"[skip] 00-main-direction.md already mentions {args.version}")
        return False
    new_item = (
        f"- **{args.version}**（{args.date}）：{args.change}"
        f"（详见 DELIVERY.md §7 {args.version}）。\n"
    )
    src = src.replace(anchor, new_item + anchor, 1)
    if args.dry_run:
        print(f"[dry-run] would append to 00-main-direction.md §4.0:\n{new_item.rstrip()}")
    else:
        MAIN_DIR.write_text(src, encoding="utf-8")
        print(f"[ok] 00-main-direction.md §4.0 +1 item ({args.version})")
    return True


def print_affected_reminder(args) -> None:
    if not args.affected:
        return
    print()
    print("=== [!] 人工复核清单 ===")
    print("以下 doc 可能需要同步（脚本不自动改，由你判断 + 编辑）：")
    for path in args.affected:
        full = REPO_ROOT / path
        marker = "[+]" if full.exists() else "[-]"
        print(f"  {marker}  {path}")
    print()
    print("建议：编辑每个 doc 的相关章节，然后:")
    print(f"  1. 在 doc/adr/*.md 里加 '## 实施现状（{args.date}）' 节（如适用）")
    print(f"  2. 在 doc/<system>.md §15 变更记录加 {args.version} 行")
    print("  3. README.md 顶部 'How to stop everything' / 'How to start everything' 如有变动")


def main() -> int:
    args = parse_args()
    if not args.no_delivery:
        append_delivery(args)
    if not args.no_main:
        append_main(args)
    print_affected_reminder(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-License-Identifier: Apache-2.0
"""seed_wiki.py — [Local Wiki] CLI (ADR-0012).

Direct module-level access (no HTTP server needed). Examples:

    # Ingest a wiki directory into namespace "wiki:elden-ring"
    python tools/seed_wiki.py wiki/elden-ring --namespace wiki:elden-ring

    # Clean rebuild (drop namespace first)
    python tools/seed_wiki.py wiki/elden-ring --namespace wiki:elden-ring --drop-first

    # Local bulk embedding (offline, free) instead of the hosted API
    python tools/seed_wiki.py wiki/elden-ring --namespace wiki:elden-ring --provider local

    # Drop a game corpus (rows + vector index file)
    python tools/seed_wiki.py --drop wiki:elden-ring

    # Namespace distribution
    python tools/seed_wiki.py --stats
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_store.backends.sqlite_backend import SqliteBackend
from memory_store.embedder import BgeM3Embedder
from memory_store.wiki_service import drop_wiki_namespace, sync_wiki_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed/drop [Local Wiki] corpora.")
    parser.add_argument("dir", nargs="?", help="wiki/<game> directory containing *.md")
    parser.add_argument("--namespace", help='target namespace, e.g. "wiki:elden-ring"')
    parser.add_argument("--drop-first", action="store_true", help="wipe namespace before ingest")
    parser.add_argument("--drop", metavar="NAMESPACE", help="delete a whole namespace and exit")
    parser.add_argument(
        "--stats", action="store_true", help="print namespace distribution and exit"
    )
    parser.add_argument("--db", default="./data/memory.sqlite", help="sqlite path")
    parser.add_argument(
        "--vec-dir", default=None, help="vector index dir (default: <db parent>/vec)"
    )
    parser.add_argument(
        "--provider",
        choices=["local", "siliconflow", "none"],
        default="local",
        help="embedding provider for ingest (default: local — offline bulk, free)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    backend = SqliteBackend(args.db, vec_dir=args.vec_dir, embedder=None)
    try:
        if args.stats:
            for row in backend.namespace_stats():
                print(f"{row['namespace']}: blocks={row['blocks']} indexed={row['indexed']}")
            return 0

        if args.drop:
            deleted, index_removed = drop_wiki_namespace(backend, args.drop)
            print(f"dropped {args.drop}: rows={deleted} index_file_removed={index_removed}")
            return 0

        if not args.dir or not args.namespace:
            print(
                "error: DIR and --namespace are required for ingest (or use --drop/--stats)",
                file=sys.stderr,
            )
            return 2

        embedder = BgeM3Embedder(provider=args.provider)
        if args.provider != "none" and not embedder.available():
            print(
                "error: embedder not available. For --provider siliconflow set SILICONFLOW_API_KEY; "
                "for --provider local install sentence-transformers.",
                file=sys.stderr,
            )
            return 2

        result = sync_wiki_dir(
            backend,
            embedder,
            namespace=args.namespace,
            dir_path=args.dir,
            drop_first=args.drop_first,
        )
        print(
            f"synced {result.namespace}: files={result.files} chunks={result.chunks} "
            f"embedded={result.embedded} skipped_unchanged={result.skipped_unchanged} "
            f"dropped={result.dropped}"
        )
        for err in result.errors:
            print(f"warning: {err}", file=sys.stderr)
        return 0 if result.chunks > 0 else 1
    finally:
        backend.close()


if __name__ == "__main__":
    sys.exit(main())

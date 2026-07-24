# SPDX-License-Identifier: Apache-2.0
"""fetch_wiki.py — pull game-wiki pages via the official MediaWiki API (ADR-0012).

Works with any MediaWiki instance (Fandom, wiki.gg, bwiki, Huiji, Wikipedia):
they all answer the same ``api.php?action=query`` grammar. Detection:

    python tools/fetch_wiki.py --api https://eldenring.fandom.com/api.php --check

Fetch pages of selected categories into the wiki contract layout:

    python tools/fetch_wiki.py \
        --api https://eldenring.fandom.com/api.php \
        --categories "Bosses,Weapons" \
        --out wiki/elden-ring \
        --with-images --max-pages 500

Notes
-----
- Content is typically CC BY-SA (Fandom 3.0, Wikipedia 4.0). We record
  ``source_url`` and the license in frontmatter for attribution. Review the
  target wiki's terms before fetching; keep the polite default rate (1 req/s).
- This tool is maintained as "it runs"; *what/where* to fetch is the user's
  responsibility (see docs/local-wiki-methodology.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

_UA = "JoyAI-LocalWikiFetcher/0.1 (+https://github.com/kuhaku9527/JoyAI-VL-Interaction)"


def _api_get(api: str, params: dict, rate: float) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = f"{api}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})  # noqa: S310 - user-supplied wiki API endpoint is the tool's purpose
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - user-supplied wiki API endpoint is the tool's purpose
        data = json.loads(resp.read().decode("utf-8"))
    time.sleep(rate)
    if "error" in data:
        raise RuntimeError(f"MediaWiki API error: {data['error'].get('info')}")
    return data


def check_api(api: str, rate: float) -> bool:
    try:
        data = _api_get(api, {"action": "query", "meta": "siteinfo", "siprop": "general"}, rate)
    except Exception as exc:  # noqa: BLE001 - probe tool: any failure means "not a MediaWiki API"
        print(f"not a reachable MediaWiki API: {exc}")
        return False
    gen = data.get("query", {}).get("general", {})
    print(
        f"MediaWiki OK: {gen.get('sitename')} ({gen.get('generator')}) license={gen.get('rights')}"
    )
    return True


def category_members(api: str, category: str, rate: float, limit: int) -> list[str]:
    titles: list[str] = []
    cont: dict = {}
    while len(titles) < limit:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmtype": "page",
            "cmlimit": "500",
            **cont,
        }
        data = _api_get(api, params, rate)
        titles.extend(m["title"] for m in data.get("query", {}).get("categorymembers", []))
        if "continue" not in data:
            break
        cont = data["continue"]
    return titles[:limit]


def fetch_pages(api: str, titles: list[str], rate: float) -> list[dict]:
    pages: list[dict] = []
    for start in range(0, len(titles), 50):  # API caps titles per request
        batch = titles[start : start + 50]
        data = _api_get(
            api,
            {
                "action": "query",
                "prop": "extracts|info|images",
                "explaintext": "1",
                "inprop": "url",
                "imlimit": "100",
                "titles": "|".join(batch),
            },
            rate,
        )
        for page in data.get("query", {}).get("pages", []):
            if "missing" in page:
                continue
            pages.append(page)
    return pages


def _safe_filename(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.一-鿿-]+", "-", title).strip("-")[:120] or "page"


def _image_filename(url: str) -> str:
    name = url.rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", urllib.parse.unquote(name))[:120]


def download_image(url: str, dest: Path, rate: float) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})  # noqa: S310 - image URL comes from the wiki API response
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - image URL comes from the wiki API response
            dest.write_bytes(resp.read())
        time.sleep(rate)
        return True
    except Exception as exc:  # noqa: BLE001 - a failed image must not abort the page fetch
        print(f"  warning: image download failed {url}: {exc}", file=sys.stderr)
        return False


def write_page(page: dict, out_dir: Path, with_images: bool, rate: float) -> str | None:
    title = page.get("title")
    text = page.get("extract", "").strip()
    url = page.get("fullurl", "")
    if not title or not text:
        return None
    md = out_dir / f"{_safe_filename(title)}.md"
    frontmatter = [
        "---",
        f'title: "{title}"',
        f'source_url: "{url}"',
        'license: "CC BY-SA (see source wiki terms)"',
        "---",
        "",
    ]
    body = [f"# {title}", "", text]
    if with_images:
        assets = out_dir / "assets"
        assets.mkdir(exist_ok=True)
        lines = []
        for img in page.get("images", [])[:20]:
            img_title = img.get("title", "").replace("File:", "")
            if not img_title:
                continue
            # Resolve the real file URL via imageinfo.
            try:
                info = _api_get(
                    page["_api"],
                    {
                        "action": "query",
                        "prop": "imageinfo",
                        "iiprop": "url",
                        "titles": img["title"],
                    },
                    rate,
                )
                infos = info.get("query", {}).get("pages", [])
                img_url = infos[0]["imageinfo"][0]["url"] if infos else None
            except Exception:  # noqa: BLE001 - skip image on any imageinfo failure
                img_url = None
            if not img_url:
                continue
            fname = _image_filename(img_url)
            if download_image(img_url, assets / fname, rate):
                lines.append(f"![{img_title}](assets/{fname})")
        if lines:
            body += ["", "## 图片", "", *lines]
    md.write_text("\n".join(frontmatter + body) + "\n", encoding="utf-8")
    return title


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch game wiki pages via MediaWiki API.")
    parser.add_argument("--api", required=True, help="wiki api.php endpoint")
    parser.add_argument("--check", action="store_true", help="only probe siteinfo and exit")
    parser.add_argument("--categories", default="", help="comma-separated category names")
    parser.add_argument("--out", help="output dir, e.g. wiki/elden-ring")
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--with-images", action="store_true", help="download images into assets/")
    parser.add_argument("--rate", type=float, default=1.0, help="seconds between requests (polite)")
    args = parser.parse_args()

    if args.check:
        return 0 if check_api(args.api, args.rate) else 1
    if not args.out or not args.categories:
        print("error: --out and --categories are required (or use --check)", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    titles: list[str] = []
    for category in [c.strip() for c in args.categories.split(",") if c.strip()]:
        found = category_members(args.api, category, args.rate, args.max_pages)
        print(f"category {category}: {len(found)} pages")
        titles.extend(found)
    titles = list(dict.fromkeys(titles))[: args.max_pages]
    print(f"total unique pages: {len(titles)}")

    pages = fetch_pages(args.api, titles, args.rate)
    for page in pages:
        page["_api"] = args.api
    written = [t for t in (write_page(p, out_dir, args.with_images, args.rate) for p in pages) if t]
    print(f"written {len(written)} pages -> {out_dir}")
    print(f"next: python tools/seed_wiki.py {out_dir} --namespace wiki:{out_dir.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

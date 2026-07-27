# SPDX-License-Identifier: Apache-2.0
"""Wiki markdown ingest: parse, chunk, extract image references (ADR-0012).

Contract: ``wiki/<game>/*.md`` with optional frontmatter and Obsidian-style
image embeds ``![alt](assets/x.png)``. Chunks carry the image paths they
reference so recall can return them alongside content ("text reference"
strategy — images are attached to blocks, not embedded as vectors).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)

_MAX_CHUNK_CHARS = 1000  # ~500 tokens for zh-mixed text
_OVERLAP_CHARS = 150


@dataclass
class WikiChunk:
    """A parsed wiki chunk carrying its text, referenced images, and metadata."""

    text: str
    images: list[str] = field(default_factory=list)
    source_url: str | None = None
    title: str | None = None


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Minimal ``key: value`` frontmatter parser (flat keys only, no YAML dep)."""
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, raw[match.end() :]


def _extract_images(text: str) -> tuple[str, list[str]]:
    """Pull image refs out of markdown; alt text stays inline as searchable text."""
    images: list[str] = []

    def _sub(match: re.Match) -> str:
        alt, path = match.group(1).strip(), match.group(2).strip()
        images.append(path)
        return alt  # keep alt as plain text in the chunk

    return _IMG_RE.sub(_sub, text), images


def _split_sections(body: str) -> list[str]:
    """Split on headings, keeping the heading with its section."""
    parts = _HEADING_RE.split(body)
    heads = _HEADING_RE.findall(body)
    sections: list[str] = []
    if parts[0].strip():
        sections.append(parts[0])
    for head, part in zip(heads, parts[1:]):
        sections.append(head + part)
    return sections


def _chunk_section(section: str) -> list[str]:
    """Greedy paragraph packing with character overlap."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if buf and len(buf) + len(para) + 2 > _MAX_CHUNK_CHARS:
            chunks.append(buf)
            buf = buf[-_OVERLAP_CHARS:] + "\n\n" + para if len(buf) > _OVERLAP_CHARS else para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    # Oversized single paragraphs get hard-split with overlap.
    final: list[str] = []
    for chunk in chunks:
        while len(chunk) > _MAX_CHUNK_CHARS * 2:
            final.append(chunk[:_MAX_CHUNK_CHARS])
            chunk = chunk[_MAX_CHUNK_CHARS - _OVERLAP_CHARS :]
        final.append(chunk)
    return final


def ingest_markdown(path: str | Path) -> list[WikiChunk]:
    """Parse one wiki markdown file into chunks with image references."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    source_url = meta.get("source_url") or meta.get("source")
    title = meta.get("title") or path.stem

    chunks: list[WikiChunk] = []
    for section in _split_sections(body):
        for piece in _chunk_section(section):
            text, images = _extract_images(piece)
            text = text.strip()
            if not text:
                continue
            chunks.append(
                WikiChunk(
                    text=f"{title}\n{text}" if title else text,
                    images=images,
                    source_url=source_url,
                    title=title,
                )
            )
    return chunks


def ingest_directory(dir_path: str | Path) -> tuple[list[WikiChunk], int, list[str]]:
    """Ingest every ``*.md`` under a wiki directory. Returns (chunks, files, errors)."""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        return [], 0, [f"directory not found: {dir_path}"]
    chunks: list[WikiChunk] = []
    errors: list[str] = []
    files = 0
    for md in sorted(dir_path.rglob("*.md")):
        try:
            chunks.extend(ingest_markdown(md))
            files += 1
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort the whole ingest
            _LOGGER.warning("ingest failed for %s: %s", md, exc)
            errors.append(f"{md.name}: {exc}")
    return chunks, files, errors

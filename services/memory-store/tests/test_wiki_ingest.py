# SPDX-License-Identifier: Apache-2.0
"""wiki markdown ingest tests (chunking + image reference extraction)."""

from __future__ import annotations

from memory_store.wiki_ingest import ingest_directory, ingest_markdown


def test_ingest_extracts_images_and_frontmatter(tmp_path):
    md = tmp_path / "bosses.md"
    md.write_text(
        "---\n"
        'title: "Bosses"\n'
        'source_url: "https://example.wiki/Bosses"\n'
        "---\n\n"
        "# 火焰巨人\n\n"
        "火焰巨人位于巨人山顶，弱打击属性。\n\n"
        "![火焰巨人站位图](assets/fire-giant.png)\n\n"
        "推荐等级 100 级以上挑战。\n",
        encoding="utf-8",
    )
    chunks = ingest_markdown(md)
    assert chunks, "expected chunks"
    text = "\n".join(c.text for c in chunks)
    assert "火焰巨人站位图" in text, "alt text must stay inline as searchable text"
    images = [img for c in chunks for img in c.images]
    assert images == ["assets/fire-giant.png"]
    assert all(c.source_url == "https://example.wiki/Bosses" for c in chunks)


def test_ingest_splits_long_sections(tmp_path):
    body = "\n\n".join(f"第 {i} 段攻略内容。" * 80 for i in range(10))
    md = tmp_path / "long.md"
    md.write_text(f"# 长文\n\n{body}", encoding="utf-8")
    chunks = ingest_markdown(md)
    assert len(chunks) > 1, "long sections must be split"
    assert all(len(c.text) <= 2400 for c in chunks), "chunks stay near the size budget"


def test_ingest_directory_collects_errors(tmp_path):
    (tmp_path / "ok.md").write_text("# 标题\n\n内容段落。", encoding="utf-8")
    chunks, files, errors = ingest_directory(tmp_path)
    assert files == 1
    assert chunks
    assert errors == []

    chunks, files, errors = ingest_directory(tmp_path / "missing")
    assert chunks == [] and files == 0 and errors

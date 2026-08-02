# ruff: noqa: RUF001
"""Character-prompt (persona) loader and composer for the live adapter.

The persona files on disk are wrapped in a ``<character_profile>`` block
and prepended to the existing decision-token system prompt.  The base
prompt (with ``</silence>`` / ``</response>`` / ``</delegation>``) is
preserved verbatim; only a one-line "stay in character" reminder is
appended at the end.

Discovery order (lowest -> highest priority, merged lexically):

  1. The repository-level ``prompts/`` directory
     (``<repo-root>/prompts/*.txt`` or ``*.md``).
  2. The ``:``- or ``,``-separated paths in the ``CHARACTER_PROMPT_PATH``
     environment variable.
  3. Any explicit path passed to :func:`load_character_prompts`.

Files inside a directory are sorted lexically (case-insensitive on
Windows) so the merge order is deterministic across runs.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

# Default discovery root: ``<repo>/prompts/`` next to ``services/webinfer``.
_REPO_DIR = Path(__file__).resolve().parent.parent.parent
_DEFAULT_PROMPTS_DIR = _REPO_DIR / "prompts"

_ENV_VAR = "CHARACTER_PROMPT_PATH"
_SUPPORTED_SUFFIXES = {".txt", ".md"}

# Suffix appended to the base system prompt so the model stays in
# character after the decision-token instructions.
_IN_CHARACTER_TAIL_EN = (
    "\n\n---\n"
    "Stay in character at all times. Speak, stay silent, and delegate"
    " *as the character defined above*; the character profile takes"
    " priority over generic behaviour."
)
_IN_CHARACTER_TAIL_ZH = (
    "\n\n---\n"
    "请始终以角色身份回应：静音、回复、委派时都要以上述角色人格为优先；"
    "角色描述的优先级高于通用行为。"
)

_CHARACTER_OPEN_TAG = "<character_profile>"
_CHARACTER_CLOSE_TAG = "</character_profile>"


def _split_env_paths(value: str) -> list[Path]:
    """Split an env-var path list into ``Path`` objects (``/``- or ``,``-separated)."""
    if not value:
        return []
    normalized = value.replace(",", os.pathsep)
    return [Path(p).expanduser() for p in normalized.split(os.pathsep) if p.strip()]


def _gather_candidate_paths(
    extra_paths: Iterable[str | os.PathLike[str]] | None = None,
) -> list[Path]:
    """Return ordered, deduplicated candidate paths/directories to scan."""
    candidates: list[Path] = [_DEFAULT_PROMPTS_DIR]
    candidates.extend(_split_env_paths(os.environ.get(_ENV_VAR, "")))
    if extra_paths:
        candidates.extend(Path(raw).expanduser() for raw in extra_paths)
    seen: set[str] = set()
    unique: list[Path] = []
    for item in candidates:
        key = str(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _iter_character_files(root: Path) -> list[Path]:
    """List supported character files under ``root`` (file or directory).

    ``README.md`` is excluded so a top-level documentation file in
    ``prompts/`` is not mistaken for a persona.
    """
    if root.is_file():
        if root.suffix.lower() not in _SUPPORTED_SUFFIXES or root.name.lower() == "readme.md":
            return []
        return [root]
    if not root.is_dir():
        return []
    files = [
        child
        for child in root.iterdir()
        if child.is_file()
        and child.suffix.lower() in _SUPPORTED_SUFFIXES
        and child.name.lower() != "readme.md"
    ]
    # Lexical sort; case-insensitive to keep Windows + POSIX consistent.
    files.sort(key=lambda p: str(p).lower())
    return files


def resolve_prompt_paths(
    extra_paths: Iterable[str | os.PathLike[str]] | None = None,
) -> list[Path]:
    """Return the file paths that will be loaded.

    Useful for the ``GET /v1/prompts/active`` debug endpoint and for the
    WebUI to display which persona is currently in effect.
    """
    found: list[Path] = []
    for candidate in _gather_candidate_paths(extra_paths):
        found.extend(_iter_character_files(candidate))
    return found


def _read_text(path: Path) -> str:
    """Read a UTF-8 text file, falling back to a lossy read on decode errors."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def load_character_prompts(
    extra_paths: Iterable[str | os.PathLike[str]] | None = None,
) -> list[str]:
    """Load every supported character prompt and return their bodies.

    Files are merged in lexical (file name) order, deduplicated by their
    resolved absolute path.  Empty / whitespace-only files are skipped so
    a stray placeholder does not produce a blank ``<character_profile>``.
    """
    prompts: list[str] = []
    for path in resolve_prompt_paths(extra_paths):
        text = _read_text(path).strip()
        if text:
            prompts.append(text)
    return prompts


def _in_character_tail(language: str) -> str:
    if str(language or "").lower().startswith("zh"):
        return _IN_CHARACTER_TAIL_ZH
    return _IN_CHARACTER_TAIL_EN


def compose_system_prompt(
    base: str,
    character_prompts: Iterable[str] | None = None,
    language: str = "en",
) -> str:
    """Return ``base`` prefixed with a character-profile block.

    The base prompt is left untouched (it still contains the three-action
    decision format ``</silence>`` / ``</response>`` / ``</delegation>``);
    a one-line *stay in character* reminder is appended at the end so the
    model does not silently fall back to the generic video assistant
    voice when the character profile is non-empty.
    """
    base = (base or "").rstrip()
    profiles = [p.strip() for p in (character_prompts or []) if p and p.strip()]
    if not profiles:
        return base
    joined = "\n\n---\n\n".join(profiles)
    return (
        f"{_CHARACTER_OPEN_TAG}\n{joined}\n{_CHARACTER_CLOSE_TAG}\n\n"
        f"{base}{_in_character_tail(language)}"
    )


# ---------------------------------------------------------------------------
# Memory-block context (live adapter pulls from memory-store on warmup).
# ---------------------------------------------------------------------------
# Each block is a dict with `content` (str) and optional `block_id` / `score`.
_MEMORY_HEADER_EN = (
    "\n\n[Previous Memory]\n"
    "The following are previous-session memory blocks from persistent storage."
    " Use them as background context if the current User Query relates to them."
    " Stay silent when the query is unrelated."
)
_MEMORY_HEADER_ZH = (
    "\n\n[Previous Memory]\n"
    "以下是从持久化记忆库中拉出的历史摘要。"
    "当用户问题与之相关时作为背景上下文使用；无关时不要拼凑回答。"
)

# Local Wiki hits are surfaced in a *separate* section so the model can keep
# chat history and looked-up reference material mentally distinct — that's the
# whole point of the integration (see ``reports/local-wiki-chat-integration-analysis-20260728.md``).
_WIKI_HEADER_EN = (
    "\n\n[Local Wiki]\n"
    "The following are semantically retrieved reference blocks from the user's"
    " local wiki corpora (per-game knowledge base). Prefer them over guessing"
    " whenever the current User Query is about gameplay, items, bosses, or"
    " lore. Cite the source URL when one is attached. Do not invent facts"
    " outside these blocks."
)
_WIKI_HEADER_ZH = (
    "\n\n[Local Wiki]\n"
    "以下是从本地游戏攻略库语义召回的参考片段（按游戏 namespace 隔离）。"
    "当用户问题涉及游戏玩法、Boss、装备、剧情时优先引用；"
    "如块附带来源 URL，请一并引述；不要在参考资料之外臆测事实。"
)

_MAX_INLINE_BLOCK_CHARS = 600
_MAX_TOTAL_BLOCK_CHARS = 4000


def _clip_memory_blocks(blocks, language):
    """Render a memory-store block list to a deterministic string.

    Returns "" when the list is empty or unusable. Each block is clipped at
    600 chars; the total is clipped at 4000 chars. Never raises.
    """
    out = []
    total = 0
    for raw in blocks or []:
        if not isinstance(raw, dict):
            continue
        text = raw.get("content")
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()
        if len(text) > _MAX_INLINE_BLOCK_CHARS:
            text = text[: _MAX_INLINE_BLOCK_CHARS - 1] + "\u2026"
        block_id = raw.get("block_id") or ""
        prefix = "(id=" + block_id + ") " if block_id else ""
        line = "- " + prefix + text
        if total + len(line) > _MAX_TOTAL_BLOCK_CHARS:
            remaining = _MAX_TOTAL_BLOCK_CHARS - total
            if remaining <= 0:
                break
            line = line[:remaining] + "\u2026"
        out.append(line)
        total += len(line)
        if total >= _MAX_TOTAL_BLOCK_CHARS:
            break
    if not out:
        return ""
    body = "\n".join(out)
    if str(language or "").lower().startswith("zh"):
        return _MEMORY_HEADER_ZH + "\n" + body + "\n"
    return _MEMORY_HEADER_EN + "\n" + body + "\n"


def _clip_wiki_blocks(blocks, language):
    """Render Local Wiki recall blocks. Mirror of ``_clip_memory_blocks`` but
    with its own header so the two sections stay separate in the prompt.

    Same per-block / total char caps as chat memory so the two paths stay
    behaviorally comparable. Each block carries an optional ``source_url``
    and ``namespace`` so the player can see *where* the answer came from.
    """
    out = []
    total = 0
    for raw in blocks or []:
        if not isinstance(raw, dict):
            continue
        text = raw.get("content")
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()
        if len(text) > _MAX_INLINE_BLOCK_CHARS:
            text = text[: _MAX_INLINE_BLOCK_CHARS - 1] + "\u2026"
        prefix_parts: list[str] = []
        ns = raw.get("namespace") or ""
        if ns:
            prefix_parts.append(f"ns={ns}")
        src = raw.get("source_url") or ""
        if src:
            prefix_parts.append(f"src={src}")
        bid = raw.get("block_id") or ""
        if bid:
            prefix_parts.append(f"id={bid}")
        prefix = " (" + ", ".join(prefix_parts) + ") " if prefix_parts else ""
        line = "- " + prefix + text
        if total + len(line) > _MAX_TOTAL_BLOCK_CHARS:
            remaining = _MAX_TOTAL_BLOCK_CHARS - total
            if remaining <= 0:
                break
            line = line[:remaining] + "\u2026"
        out.append(line)
        total += len(line)
        if total >= _MAX_TOTAL_BLOCK_CHARS:
            break
    if not out:
        return ""
    body = "\n".join(out)
    if str(language or "").lower().startswith("zh"):
        return _WIKI_HEADER_ZH + "\n" + body + "\n"
    return _WIKI_HEADER_EN + "\n" + body + "\n"


def compose_system_prompt_with_memory(
    base, character_prompts=None, language="en", memory_blocks=None, wiki_blocks=None
):
    """Compose system prompt, appending a [Previous Memory] block and a
    separate [Local Wiki] block at the end.

    Empty / falsy ``memory_blocks`` degrades to ``compose_system_prompt``
    semantics so callers can always pass the warmup result without branching.
    ``wiki_blocks`` is rendered as a *separate* section so chat history and
    looked-up reference material stay mentally distinct (see
    ``reports/local-wiki-chat-integration-analysis-20260728.md``).
    """
    composed = compose_system_prompt(base, character_prompts, language)
    mem_block = _clip_memory_blocks(memory_blocks, language)
    wiki_block = _clip_wiki_blocks(wiki_blocks, language)
    if mem_block:
        composed = composed.rstrip() + "\n" + mem_block
    if wiki_block:
        composed = composed.rstrip() + "\n" + wiki_block
    return composed

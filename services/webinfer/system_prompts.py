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
from pathlib import Path
from typing import Iterable

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

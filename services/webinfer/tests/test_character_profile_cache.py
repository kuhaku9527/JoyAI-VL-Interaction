"""Focused tests for the F3-P2b character-profile ``lru_cache``.

These exercise the real module-level
:func:`prompt_assembly._cached_load_character_profiles` (and its hook into
:func:`PromptAssemblyMixin._invalidate_system_prompt_cache`) **without**
stubbing ``PromptAssemblyMixin._load_character_profiles``.  Cache hits,
mtime-driven invalidation, and the explicit reload clear are all verified by
counting real calls into ``load_character_prompts``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_assembly import (  # noqa: E402
    PromptAssemblyMixin,
    _cached_load_character_profiles,
)


def _counting_load(monkeypatch, returns):
    """Replace ``prompt_assembly.load_character_prompts`` with a call counter.

    The module-level cache calls ``load_character_prompts`` by name, so
    monkeypatching the attribute on ``prompt_assembly`` routes both the cache
    and the public ``_load_character_profiles`` method through the counter.
    """
    calls = []

    def _fake(paths):
        calls.append(tuple(paths))
        return list(returns)

    monkeypatch.setattr("prompt_assembly.load_character_prompts", _fake)
    return calls


def test_profile_cache_lru_hit(monkeypatch):
    """Identical (enabled, paths, mtime) re-reads are served from the cache."""
    calls = _counting_load(monkeypatch, returns=["profile-body"])
    _cached_load_character_profiles.cache_clear()
    paths = ("fake://character_a.txt",)

    first = _cached_load_character_profiles(True, paths, mtime=1.0)
    second = _cached_load_character_profiles(True, paths, mtime=1.0)

    assert first == second == ["profile-body"]
    assert len(calls) == 1  # second call must NOT re-read disk


def test_profile_cache_mtime_invalidation(monkeypatch):
    """A changed file mtime rotates the cache key and forces a reload."""
    calls = _counting_load(monkeypatch, returns=["profile-body"])
    _cached_load_character_profiles.cache_clear()
    paths = ("fake://character_a.txt",)

    _cached_load_character_profiles(True, paths, mtime=1.0)
    _cached_load_character_profiles(True, paths, mtime=2.0)  # same path, newer mtime

    assert len(calls) == 2  # distinct mtime -> distinct key -> re-read


def test_profile_cache_disabled_short_circuit(monkeypatch):
    """With character injection disabled the loader is never invoked."""
    calls = _counting_load(monkeypatch, returns=["profile-body"])
    _cached_load_character_profiles.cache_clear()
    paths = ("fake://character_a.txt",)

    assert _cached_load_character_profiles(False, paths, mtime=1.0) == []
    assert len(calls) == 0


def test_profile_cache_cleared_on_reload_invalidate(monkeypatch):
    """``_invalidate_system_prompt_cache`` force-clears the profile cache.

    Mirrors what ``POST /v1/prompts/reload`` does: after an explicit
    invalidation, an identical (enabled, paths, mtime) call must reload.
    """
    calls = _counting_load(monkeypatch, returns=["profile-body"])
    _cached_load_character_profiles.cache_clear()
    paths = ("fake://character_a.txt",)

    inst = PromptAssemblyMixin()
    inst.config = SimpleNamespace(character_prompt_paths=["fake://character_a.txt"])
    inst._system_prompt_cache = {}

    _cached_load_character_profiles(True, paths, mtime=1.0)
    assert len(calls) == 1

    inst._invalidate_system_prompt_cache()

    assert _cached_load_character_profiles.cache_info().currsize == 0
    _cached_load_character_profiles(True, paths, mtime=1.0)
    assert len(calls) == 2  # cache was cleared, so it reloads


def test_load_character_profiles_routes_through_cache_real_disk(tmp_path, monkeypatch):
    """The public method genuinely hits the LRU on a real on-disk profile.

    Uses a real temp file + the real ``load_character_prompts`` (wrapped with a
    counter) so the path is exercised end-to-end, not stubbed away.
    """
    char_path = tmp_path / "char.txt"
    char_path.write_text("You are BT-7274.", encoding="utf-8")

    real_load = _real_load_target()
    calls = []

    def _wrapped(paths):
        calls.append(tuple(str(p) for p in paths))
        return real_load(paths)

    monkeypatch.setattr("prompt_assembly.load_character_prompts", _wrapped)
    _cached_load_character_profiles.cache_clear()

    inst = PromptAssemblyMixin()
    inst.config = SimpleNamespace(
        character_prompts_enabled=True,
        character_prompt_paths=[str(char_path)],
    )
    inst._system_prompt_cache = {}

    first = inst._load_character_profiles()
    second = inst._load_character_profiles()

    # ``load_character_prompts`` also merges built-in default character files,
    # so the exact list is environment-dependent; assert our temp file's body
    # is present and that both reads agree (served from the same cache entry).
    assert any("You are BT-7274." in body for body in first)
    assert first == second
    assert len(calls) == 1  # second call served from LRU, no real re-read


def _real_load_target():
    """Import the real ``load_character_prompts`` for the on-disk test."""
    from system_prompts import load_character_prompts

    return load_character_prompts

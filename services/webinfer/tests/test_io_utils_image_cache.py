"""Minimal sanity check for the F3-P2a image data-URL ``lru_cache``.

Validates the reviewer nit that capped ``_file_to_data_url_cached`` at
``maxsize=64`` (so full-resolution base64 frames cannot grow the cache toward
GB-scale): repeated paths must hit the LRU, and the live entry count must stay
bounded by the configured ``maxsize``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from io_utils import _file_to_data_url_cached  # noqa: E402
from PIL import Image  # noqa: E402


def test_image_cache_hits_on_repeated_path(tmp_path):
    img = tmp_path / "frame.png"
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(img, "PNG")

    _file_to_data_url_cached.cache_clear()

    first = _file_to_data_url_cached(str(img), max_pixels=0)
    second = _file_to_data_url_cached(str(img), max_pixels=0)

    assert first == second
    assert _file_to_data_url_cached.cache_info().hits >= 1
    assert _file_to_data_url_cached.cache_info().maxsize == 64


def test_image_cache_bounded_by_maxsize(tmp_path):
    _file_to_data_url_cached.cache_clear()

    # Many distinct paths must stay within the configured maxsize (64):
    # the cache evicts LRU instead of growing unboundedly.
    for i in range(200):
        img = tmp_path / f"frame_{i}.png"
        Image.new("RGB", (2, 2)).save(img, "PNG")
        _file_to_data_url_cached(str(img), max_pixels=0)

    info = _file_to_data_url_cached.cache_info()
    assert info.currsize <= info.maxsize == 64

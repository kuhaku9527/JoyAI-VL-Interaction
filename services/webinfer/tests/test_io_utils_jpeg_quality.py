"""Regression test guarding ``_image_to_data_url`` JPEG quality.

Issue #80 / diagnosis #2: frames re-encoded to JPEG for the VLM must use a
high quality (92), not PIL's lossy default (~75), or recognition accuracy
drops and hallucinations rise. ``_image_to_data_url`` now honors an explicit
``quality`` argument and falls back to the module-level ``_DEFAULT_JPEG_QUALITY``
(read from ``JOYAI_JPEG_QUALITY``, default 92) when none is passed.

This pins:
  * the JPEG branch produces an ``image/jpeg`` data URL PIL can re-open;
  * ``_DEFAULT_JPEG_QUALITY`` is 92;
  * quality 92 yields MORE bytes than quality 75 (proving the default is not
    the lossy 75), and the no-arg default path equals explicit 92.

No real I/O / network is touched.
"""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from io_utils import _DEFAULT_JPEG_QUALITY, _image_to_data_url  # noqa: E402
from PIL import Image  # noqa: E402


def _make_detail_image(width: int = 256, height: int = 192) -> Image.Image:
    """Build a deterministic high-frequency image so JPEG quality matters."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (
                (x * 31 ^ y * 17) % 256,
                (x * 17 ^ y * 31) % 256,
                (x * 13 ^ y * 7 ^ (x * y) % 256) % 256,
            )
    return image


def _decode_jpeg_data_url(url: str) -> tuple[Image.Image, int]:
    assert url.startswith("data:image/jpeg;base64,"), url[:40]
    raw = base64.b64decode(url.split(",", 1)[1])
    reopened = Image.open(io.BytesIO(raw))
    reopened.load()
    return reopened, len(raw)


def test_io_utils_default_quality_is_92():
    """The module-level default must be 92 (env unset)."""
    assert _DEFAULT_JPEG_QUALITY == 92


def test_io_utils_jpeg_roundtrip_and_mime():
    """The JPEG branch yields a re-openable image/jpeg data URL."""
    url = _image_to_data_url(_make_detail_image(), "image/jpeg", quality=92)
    reopened, nbytes = _decode_jpeg_data_url(url)
    assert reopened.format == "JPEG"
    assert nbytes > 0


def test_io_utils_default_quality_not_75():
    """Default (92) must produce MORE bytes than 75 and equal explicit 92."""
    image = _make_detail_image()

    url_default = _image_to_data_url(image, "image/jpeg")
    url_92 = _image_to_data_url(image, "image/jpeg", quality=92)
    url_75 = _image_to_data_url(image, "image/jpeg", quality=75)

    _, bytes_default = _decode_jpeg_data_url(url_default)
    _, bytes_92 = _decode_jpeg_data_url(url_92)
    _, bytes_75 = _decode_jpeg_data_url(url_75)

    assert bytes_92 > 1.1 * bytes_75, (
        f"quality=92 ({bytes_92} bytes) must exceed 1.1x quality=75 ({bytes_75} bytes)"
    )
    assert bytes_default == bytes_92, (
        f"default ({bytes_default} bytes) must equal explicit quality=92 ({bytes_92} bytes)"
    )

"""Regression test guarding the main VLM chat JPEG re-encode quality.

Root cause (issue #80 / diagnosis #2): the main VLM chat path re-encoded
WebRTC-decoded frames to JPEG with PIL's default quality (~75), a lossy
re-encode that destroys fine detail and raises hallucination / lowers
recognition accuracy. The background path (``background_model.py``) already
used a configurable ``jpeg_quality`` (default 82); this change unifies the
main chat path on the ``JOYAI_JPEG_QUALITY`` env var (default 92).

These tests pin:
  * ``VLMService`` reads ``JOYAI_JPEG_QUALITY`` into ``self.jpeg_quality``
    (default 92 when unset);
  * the encoded frame is an ``image/jpeg`` data URL that PIL can re-open;
  * the default quality (92) yields *more* bytes than quality 75 (proving
    the default is NOT the old lossy 75), and equals the explicit 92 path;
  * the batch path (``analyze_images``) honours the same quality.

No real VLM / network is touched -- ``client.chat.completions.create`` is
monkeypatched to capture the outgoing request payload.
"""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

# conftest.py already puts services/webui/src on sys.path; redo defensively
# so this file can be collected when run in isolation.
_REPO = Path(__file__).resolve().parents[3]
for _p in (
    str(_REPO / "services" / "webui" / "src"),
    str(_REPO / "services" / "webinfer"),
    str(_REPO),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image  # noqa: E402

from joy_interaction_webui.vlm_service import VLMService  # noqa: E402


def _make_detail_image(width: int = 256, height: int = 192) -> Image.Image:
    """Build an image rich in high-frequency detail.

    A flat / low-frequency image compresses almost identically at any JPEG
    quality, so the byte-size ratio used by the regression assertion would
    be meaningless. A deterministic noise-like pattern guarantees quality 92
    retains visibly more bytes than quality 75.
    """
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


def _capturing_create(captured: dict):
    """Return an awaitable stand-in for ``client.chat.completions.create``."""

    class _Message:
        content = "ok"

    class _Resp:
        def __init__(self):
            self.choices = [_Message()]

        def model_dump(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    async def _create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _Resp()

    return _create


async def _capture_single_bytes(service: VLMService, image: Image.Image) -> int:
    captured: dict = {}
    service.client.chat.completions.create = _capturing_create(captured)
    await service.analyze_image(image, prompt="describe")
    content = captured["messages"][0]["content"]
    image_item = content[-1]
    assert image_item["type"] == "image_url"
    _, nbytes = _decode_jpeg_data_url(image_item["image_url"]["url"])
    return nbytes


async def _capture_batch_bytes(service: VLMService, image: Image.Image) -> int:
    captured: dict = {}
    service.client.chat.completions.create = _capturing_create(captured)
    frames_data = [{"image": image, "timestamp": 0.0, "timestamp_kind": "turn_seconds"}]
    await service.analyze_images(frames_data, prompt="describe")
    content = captured["messages"][0]["content"]
    image_item = content[-1]
    assert image_item["type"] == "image_url"
    _, nbytes = _decode_jpeg_data_url(image_item["image_url"]["url"])
    return nbytes


async def test_vlm_service_reads_env_quality_default_92():
    """``JOYAI_JPEG_QUALITY`` must default to 92 when unset."""
    service = VLMService(model="m", api_base="http://localhost:1/v1", api_key="EMPTY")
    assert service.jpeg_quality == 92
    await service.close(cancel_requests=False)


async def test_vlm_service_encodes_jpeg_data_url():
    """The outgoing frame must be a re-openable image/jpeg data URL."""
    service = VLMService(model="m", api_base="http://localhost:1/v1", api_key="EMPTY")
    image = _make_detail_image()
    captured: dict = {}
    service.client.chat.completions.create = _capturing_create(captured)
    await service.analyze_image(image, prompt="describe")
    content = captured["messages"][0]["content"]
    image_item = content[-1]
    assert image_item["type"] == "image_url"
    reopened, nbytes = _decode_jpeg_data_url(image_item["image_url"]["url"])
    assert reopened.format == "JPEG"
    assert nbytes > 0
    await service.close(cancel_requests=False)


async def test_vlm_service_default_quality_not_75():
    """Default (92) must produce MORE bytes than 75 and equal explicit 92."""
    image = _make_detail_image()

    default_service = VLMService(model="m", api_base="http://localhost:1/v1", api_key="EMPTY")
    bytes_default = await _capture_single_bytes(default_service, image)

    low_service = VLMService(model="m", api_base="http://localhost:1/v1", api_key="EMPTY")
    low_service.jpeg_quality = 75
    bytes_75 = await _capture_single_bytes(low_service, image)

    high_service = VLMService(model="m", api_base="http://localhost:1/v1", api_key="EMPTY")
    high_service.jpeg_quality = 92
    bytes_92 = await _capture_single_bytes(high_service, image)

    assert bytes_92 > 1.1 * bytes_75, (
        f"quality=92 ({bytes_92} bytes) must exceed 1.1x quality=75 ({bytes_75} bytes)"
    )
    assert bytes_default == bytes_92, (
        f"default path ({bytes_default} bytes) must equal explicit quality=92 ({bytes_92} bytes)"
    )
    await default_service.close(cancel_requests=False)
    await low_service.close(cancel_requests=False)
    await high_service.close(cancel_requests=False)


async def test_vlm_service_batch_encodes_with_quality():
    """The batch path (analyze_images) must honour the same quality budget."""
    image = _make_detail_image()

    default_service = VLMService(model="m", api_base="http://localhost:1/v1", api_key="EMPTY")
    bytes_default = await _capture_batch_bytes(default_service, image)

    low_service = VLMService(model="m", api_base="http://localhost:1/v1", api_key="EMPTY")
    low_service.jpeg_quality = 75
    bytes_75 = await _capture_batch_bytes(low_service, image)

    high_service = VLMService(model="m", api_base="http://localhost:1/v1", api_key="EMPTY")
    high_service.jpeg_quality = 92
    bytes_92 = await _capture_batch_bytes(high_service, image)

    assert bytes_92 > 1.1 * bytes_75, (
        f"batch quality=92 ({bytes_92} bytes) must exceed 1.1x quality=75 ({bytes_75} bytes)"
    )
    assert bytes_default == bytes_92, (
        f"batch default ({bytes_default} bytes) must equal explicit quality=92 ({bytes_92} bytes)"
    )
    await default_service.close(cancel_requests=False)
    await low_service.close(cancel_requests=False)
    await high_service.close(cancel_requests=False)

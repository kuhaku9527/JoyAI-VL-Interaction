"""Filesystem / output-path helpers and URL-to-path resolution."""

from __future__ import annotations

import base64
import io
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from prompt_constants import DEFAULT_SAVE_ROOT

LOGGER = logging.getLogger("streaming_infer_adapter")

def sanitize_output_name(name: str, max_len: int = 120) -> str:
    safe_chars = []
    for ch in str(name or ""):
        is_ascii_alnum = ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9")
        safe_chars.append(ch if is_ascii_alnum or ch in ("-", "_", ".") else "_")
    safe_name = "".join(safe_chars).strip("._")
    return (safe_name or "live_adapter")[:max_len]


def derive_model_output_name(model_path: str) -> str:
    normalized = os.path.normpath(str(model_path or "model"))
    model_name = os.path.basename(normalized) or "model"
    parent_name = os.path.basename(os.path.dirname(normalized))
    if model_name.startswith("checkpoint-") and parent_name:
        model_name = f"{parent_name}__{model_name}"
    return sanitize_output_name(model_name)


def resolve_save_dir(path: Optional[str], root: str = DEFAULT_SAVE_ROOT) -> Optional[str]:
    if path is None:
        return None
    path = str(path).strip()
    if not path:
        return None
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(root, path))


def derive_light_out_dir(out_dir: str) -> str:
    normalized_out_dir = os.path.normpath(out_dir)
    parent_dir = os.path.dirname(normalized_out_dir)
    base_name = os.path.basename(normalized_out_dir)
    if base_name.startswith("output_"):
        return os.path.join(parent_dir, f"output_light_{base_name[len('output_'):]}")
    if base_name == "output":
        return os.path.join(parent_dir, "output_light")
    return normalized_out_dir + "_light"


def _file_url_to_path(url: str) -> Optional[str]:
    if not url.startswith("file://"):
        return None
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    if parsed.netloc not in {"", "localhost"}:
        return None
    return unquote(parsed.path)


def _file_to_data_url(path: str, max_pixels: int = 0) -> str:
    if path.startswith("data:"):
        return _resize_data_url_if_needed(path, max_pixels)
    return _file_to_data_url_cached(path, max_pixels)


def _file_to_data_url_cached(path: str, max_pixels: int = 0) -> str:
    ext = Path(path).suffix.lower()
    mime_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")

    if max_pixels > 0:
        try:
            with Image.open(path) as image:
                image.load()
                resized = _resize_image_if_needed(image, max_pixels)
                if resized is not None:
                    return _image_to_data_url(resized, mime_type)
        except Exception as exc:
            LOGGER.warning("failed to resize image %s for max_pixels=%s: %s", path, max_pixels, exc)

    with open(path, "rb") as file_obj:
        encoded = base64.b64encode(file_obj.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _resize_data_url_if_needed(data_url: str, max_pixels: int = 0) -> str:
    if max_pixels <= 0:
        return data_url
    match = re.match(r"^data:(image/[^;]+);base64,(.+)$", data_url, re.DOTALL)
    if not match:
        return data_url
    mime_type, encoded = match.groups()
    try:
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
            image.load()
            resized = _resize_image_if_needed(image, max_pixels)
            if resized is None:
                return data_url
            return _image_to_data_url(resized, mime_type)
    except Exception as exc:
        LOGGER.warning("failed to resize data URL image for max_pixels=%s: %s", max_pixels, exc)
        return data_url


def _resize_image_if_needed(image: Image.Image, max_pixels: int) -> Optional[Image.Image]:
    width, height = image.size
    if max_pixels <= 0 or width * height <= max_pixels:
        return None
    scale = (max_pixels / (width * height)) ** 0.5
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.LANCZOS)


def _image_to_data_url(image: Image.Image, mime_type: str) -> str:
    buffer = io.BytesIO()
    if mime_type == "image/png":
        image.save(buffer, format="PNG")
    elif mime_type == "image/webp":
        image.save(buffer, format="WEBP")
    else:
        mime_type = "image/jpeg"
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(buffer, format="JPEG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_extra_body(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "skip_special_tokens",
        "top_k",
        "repetition_penalty",
        "min_p",
        "stop_token_ids",
        "include_stop_str_in_output",
    )
    return {key: payload[key] for key in keys if key in payload}


def _internal_message_to_openai(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, list):
        return {"role": message.get("role", "user"), "content": content or ""}

    converted: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image":
            max_pixels = int(item.get("max_pixels") or 0)
            converted.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _file_to_data_url(item["image"], max_pixels=max_pixels)},
                }
            )
        elif item.get("type") == "text":
            converted.append({"type": "text", "text": str(item.get("text", ""))})
        else:
            converted.append(item)
    return {"role": message.get("role", "user"), "content": converted}

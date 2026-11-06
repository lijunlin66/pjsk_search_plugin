"""Bound complete image payloads by bytes, dimensions and pixel count."""

import io
import math

from PIL import Image

UPLOAD_BYTES = 6 * 1024 * 1024
RETRY_BYTES = 4 * 1024 * 1024


def prepare_upload(data, max_bytes=UPLOAD_BYTES, max_side=None, max_pixels=None):
    if len(data) <= max_bytes and max_side is None and max_pixels is None:
        return data
    with Image.open(io.BytesIO(data)) as source:
        safe_side = max_side is None or max(source.size) <= max_side
        safe_pixels = max_pixels is None or source.width * source.height <= max_pixels
        if len(data) <= max_bytes and safe_side and safe_pixels:
            return data
        image = source.convert("RGB")
    ratio = min(
        1,
        max_side / max(image.size) if max_side else 1,
        math.sqrt(max_pixels / (image.width * image.height)) if max_pixels else 1,
    )
    if ratio < 1:
        image = image.resize(
            (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    for _ in range(4):
        for quality in (90, 86, 82, 78, 72, 64, 54):
            out = io.BytesIO()
            image.save(out, "JPEG", quality=quality, optimize=True)
            encoded = out.getvalue()
            if len(encoded) <= max_bytes:
                return encoded
        ratio = min(0.85, math.sqrt(max_bytes / len(encoded)) * 0.95)
        image = image.resize(
            (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    raise ValueError("无法在保留完整图片的情况下达到上传大小限制")

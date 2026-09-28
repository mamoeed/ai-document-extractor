"""Image loading, downscaling and encoding for the VLM."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..errors import FileUnreadableError


@dataclass(frozen=True)
class EncodedImage:
    data: bytes
    mime_type: str
    width: int
    height: int

    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{base64.b64encode(self.data).decode('ascii')}"


def load_image(path: str | Path, max_edge_px: int) -> EncodedImage:
    """Open a PNG/JPEG file, fix orientation, downscale and encode it."""
    try:
        with Image.open(path) as img:
            img.load()
            fmt = (img.format or "").upper()
            prepared = prepare_image(img, max_edge_px)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise FileUnreadableError(f"Cannot read image: {type(exc).__name__}: {exc}") from exc
    return encode_image(prepared, "jpeg" if fmt == "JPEG" else "png")


def prepare_image(img: Image.Image, max_edge_px: int) -> Image.Image:
    """Apply EXIF rotation, flatten transparency onto white, convert to RGB and downscale
    so the long edge is at most ``max_edge_px``."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > max_edge_px:
        img = img.copy()
        img.thumbnail((max_edge_px, max_edge_px), Image.Resampling.LANCZOS)
    return img


def encode_image(img: Image.Image, fmt: str = "png") -> EncodedImage:
    buffer = io.BytesIO()
    if fmt == "jpeg":
        img.save(buffer, format="JPEG", quality=90)
        mime = "image/jpeg"
    else:
        img.save(buffer, format="PNG")
        mime = "image/png"
    return EncodedImage(buffer.getvalue(), mime, img.width, img.height)

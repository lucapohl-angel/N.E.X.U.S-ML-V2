"""Bounded image decoder which preserves oriented native pixels."""

from __future__ import annotations

import hashlib
import io
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps, UnidentifiedImageError

ImageArray = NDArray[np.uint8]
ImageSource = str | Path | bytes | bytearray | memoryview | BinaryIO | Image.Image | ImageArray


class ImageInputError(ValueError):
    """Raised when untrusted input cannot be decoded within configured limits."""


@dataclass(frozen=True)
class DecodeLimits:
    max_encoded_bytes: int = 50 * 1024 * 1024
    max_pixels: int = 40_000_000
    max_dimension: int = 16_384
    numpy_color_order: str = "bgr"

    def __post_init__(self) -> None:
        if self.max_encoded_bytes <= 0 or self.max_pixels <= 0 or self.max_dimension <= 0:
            raise ValueError("decode limits must be positive")
        if self.numpy_color_order not in {"rgb", "bgr"}:
            raise ValueError("numpy_color_order must be 'rgb' or 'bgr'")


@dataclass(frozen=True)
class DecodedImage:
    """An RGB native-pixel image after EXIF orientation, plus decode provenance."""

    rgb: ImageArray
    source_kind: str
    encoded_format: str | None
    encoded_bytes: int | None
    encoded_sha256: str | None
    pixel_sha256: str
    stored_width: int
    stored_height: int
    width: int
    height: int
    exif_orientation: int | None
    exif_applied: bool

    def __post_init__(self) -> None:
        if self.rgb.dtype != np.uint8 or self.rgb.ndim != 3 or self.rgb.shape[2] != 3:
            raise ValueError("rgb must be an HxWx3 uint8 array")
        if self.rgb.shape[:2] != (self.height, self.width):
            raise ValueError("declared dimensions do not match native pixels")


class ImageDecoder:
    """Decode paths, bytes, file-like objects, PIL images, and NumPy arrays."""

    def __init__(self, limits: DecodeLimits | None = None) -> None:
        self.limits = limits or DecodeLimits()

    def decode(self, source: ImageSource) -> DecodedImage:
        if isinstance(source, np.ndarray):
            return self._decode_array(source)
        if isinstance(source, Image.Image):
            return self._decode_pil(source, source_kind="pil", encoded=None)
        if isinstance(source, str | Path):
            path = Path(source)
            try:
                size = path.stat().st_size
            except OSError as exc:
                raise ImageInputError(f"cannot read image path: {path}") from exc
            if size > self.limits.max_encoded_bytes:
                raise ImageInputError(
                    f"encoded image is {size} bytes; limit is {self.limits.max_encoded_bytes}"
                )
            try:
                encoded = path.read_bytes()
            except OSError as exc:
                raise ImageInputError(f"cannot read image path: {path}") from exc
            return self._decode_encoded(encoded, source_kind="path")
        if isinstance(source, bytes | bytearray | memoryview):
            encoded = bytes(source)
            return self._decode_encoded(encoded, source_kind="bytes")
        if hasattr(source, "read"):
            return self._decode_file_like(source)
        raise ImageInputError(f"unsupported image input type: {type(source).__name__}")

    def _decode_file_like(self, source: BinaryIO) -> DecodedImage:
        original_position: int | None = None
        with suppress(AttributeError, OSError):
            original_position = source.tell()
        try:
            encoded = source.read(self.limits.max_encoded_bytes + 1)
        except (AttributeError, OSError) as exc:
            raise ImageInputError("file-like image input could not be read") from exc
        finally:
            if original_position is not None:
                with suppress(AttributeError, OSError):
                    source.seek(original_position)
        if not isinstance(encoded, bytes):
            raise ImageInputError("file-like image input must return bytes")
        return self._decode_encoded(encoded, source_kind="file_like")

    def _decode_encoded(self, encoded: bytes, *, source_kind: str) -> DecodedImage:
        if not encoded:
            raise ImageInputError("image input is empty")
        if len(encoded) > self.limits.max_encoded_bytes:
            raise ImageInputError(
                f"encoded image is {len(encoded)} bytes; limit is {self.limits.max_encoded_bytes}"
            )
        try:
            with Image.open(io.BytesIO(encoded)) as image:
                image.load()
                return self._decode_pil(image, source_kind=source_kind, encoded=encoded)
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
            raise ImageInputError("image bytes are corrupt or unsupported") from exc

    def _decode_pil(
        self, image: Image.Image, *, source_kind: str, encoded: bytes | None
    ) -> DecodedImage:
        stored_width, stored_height = image.size
        self._validate_dimensions(stored_width, stored_height)
        orientation_value = image.getexif().get(274)
        orientation = int(orientation_value) if orientation_value is not None else None
        oriented = ImageOps.exif_transpose(image)
        width, height = oriented.size
        self._validate_dimensions(width, height)
        rgb = np.asarray(oriented.convert("RGB"), dtype=np.uint8).copy()
        rgb.setflags(write=False)
        return DecodedImage(
            rgb=rgb,
            source_kind=source_kind,
            encoded_format=image.format,
            encoded_bytes=len(encoded) if encoded is not None else None,
            encoded_sha256=hashlib.sha256(encoded).hexdigest() if encoded is not None else None,
            pixel_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),
            stored_width=stored_width,
            stored_height=stored_height,
            width=width,
            height=height,
            exif_orientation=orientation,
            exif_applied=orientation not in (None, 1),
        )

    def _decode_array(self, source: NDArray[np.generic]) -> DecodedImage:
        if source.dtype != np.uint8:
            raise ImageInputError("NumPy image input must use uint8 pixels")
        if source.ndim == 2:
            rgb = np.repeat(source[:, :, None], 3, axis=2)
        elif source.ndim == 3 and source.shape[2] in (3, 4):
            rgb = source[:, :, :3]
            if self.limits.numpy_color_order == "bgr":
                rgb = rgb[:, :, ::-1]
        else:
            raise ImageInputError("NumPy image input must be HxW, HxWx3, or HxWx4")
        height, width = rgb.shape[:2]
        self._validate_dimensions(width, height)
        native = np.ascontiguousarray(rgb, dtype=np.uint8)
        native.setflags(write=False)
        return DecodedImage(
            rgb=native,
            source_kind="numpy",
            encoded_format=None,
            encoded_bytes=None,
            encoded_sha256=None,
            pixel_sha256=hashlib.sha256(native.tobytes()).hexdigest(),
            stored_width=width,
            stored_height=height,
            width=width,
            height=height,
            exif_orientation=None,
            exif_applied=False,
        )

    def _validate_dimensions(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ImageInputError("image dimensions must be positive")
        if width > self.limits.max_dimension or height > self.limits.max_dimension:
            raise ImageInputError(
                f"image dimension exceeds configured limit {self.limits.max_dimension}"
            )
        if width * height > self.limits.max_pixels:
            raise ImageInputError(
                f"image has {width * height} pixels; limit is {self.limits.max_pixels}"
            )

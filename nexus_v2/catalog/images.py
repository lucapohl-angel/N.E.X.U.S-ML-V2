"""Defensive image download, decoding, hashing, and duplicate primitives."""

from __future__ import annotations

import hashlib
import io
import ipaddress
import socket
import statistics
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import cv2
import numpy as np
import requests
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

ALLOWED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
HTML_PREFIXES = (b"<!doctype html", b"<html", b"<?xml")


class AssetValidationError(ValueError):
    """Raised when candidate bytes are not a safe, useful image asset."""


class DownloadError(RuntimeError):
    """Raised for a contained remote retrieval failure."""


@dataclass(frozen=True)
class ValidatedImage:
    content: bytes
    sha256: str
    phash: str
    width: int
    height: int
    mime_type: str
    suffix: str


@dataclass(frozen=True)
class DownloadPolicy:
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 20.0
    max_bytes: int = 8 * 1024 * 1024
    min_width: int = 16
    min_height: int = 16
    max_redirects: int = 3


def _mime_and_suffix(image_format: str | None) -> tuple[str, str]:
    mapping = {
        "PNG": ("image/png", ".png"),
        "JPEG": ("image/jpeg", ".jpg"),
        "WEBP": ("image/webp", ".webp"),
    }
    if image_format not in mapping:
        raise AssetValidationError(f"unsupported decoded image format: {image_format!r}")
    return mapping[image_format]


def _reject_error_body(content: bytes) -> None:
    if not content:
        raise AssetValidationError("empty response body")
    prefix = content[:512].lstrip().lower()
    if prefix.startswith(HTML_PREFIXES) or b"<html" in prefix:
        raise AssetValidationError("HTML or XML error body is not an image")


def perceptual_hash(image: NDArray[np.uint8]) -> str:
    """Return a deterministic 64-bit DCT pHash."""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(resized)
    low = dct[:8, :8]
    comparison_values = [float(value) for value in low.flatten()[1:]]
    median = statistics.median(comparison_values)
    bits = (low.flatten() >= median).astype(np.uint8)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def phash_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def validate_image_bytes(
    content: bytes,
    *,
    declared_content_type: str | None = None,
    min_width: int = 16,
    min_height: int = 16,
) -> ValidatedImage:
    """Validate through Pillow and OpenCV and compute catalog integrity fields."""

    _reject_error_body(content)
    declared = (
        declared_content_type.split(";", 1)[0].strip().lower() if declared_content_type else None
    )
    if declared is not None and declared not in ALLOWED_IMAGE_TYPES:
        raise AssetValidationError(f"unexpected Content-Type: {declared_content_type}")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image_format = image.format
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            width, height = image.size
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AssetValidationError(f"Pillow could not decode image: {exc}") from exc
    encoded = np.frombuffer(content, dtype=np.uint8)
    opencv_image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if opencv_image is None or opencv_image.size == 0:
        raise AssetValidationError("OpenCV could not decode image")
    cv_height, cv_width = opencv_image.shape[:2]
    if (width, height) != (cv_width, cv_height):
        raise AssetValidationError("Pillow and OpenCV disagree on image dimensions")
    if width < min_width or height < min_height:
        raise AssetValidationError(
            f"image dimensions {width}x{height} are below {min_width}x{min_height}"
        )
    alpha = rgba[:, :, 3]
    if int(np.count_nonzero(alpha)) == 0:
        raise AssetValidationError("image is fully transparent")
    visible_rgb = rgba[:, :, :3][alpha > 0]
    if visible_rgb.size == 0 or float(np.std(visible_rgb.astype(np.float32))) < 1.0:
        raise AssetValidationError("image has empty or effectively constant visible content")
    mime_type, suffix = _mime_and_suffix(image_format)
    if declared is not None and declared != mime_type:
        raise AssetValidationError(
            f"declared Content-Type {declared!r} does not match decoded {mime_type!r}"
        )
    if opencv_image.ndim == 3 and opencv_image.shape[2] == 4:
        hash_image = cv2.cvtColor(opencv_image, cv2.COLOR_BGRA2BGR)
    else:
        hash_image = opencv_image
    hash_array: NDArray[np.uint8] = np.asarray(hash_image, dtype=np.uint8)
    return ValidatedImage(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        phash=perceptual_hash(hash_array),
        width=width,
        height=height,
        mime_type=mime_type,
        suffix=suffix,
    )


def validate_local_image(
    path: Path, *, min_width: int = 16, min_height: int = 16
) -> ValidatedImage:
    if not path.is_file():
        raise AssetValidationError(f"asset does not exist: {path}")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise AssetValidationError(f"could not read asset {path}: {exc}") from exc
    return validate_image_bytes(content, min_width=min_width, min_height=min_height)


def _validate_remote_host(hostname: str, allowed_hosts: frozenset[str]) -> None:
    normalized = hostname.rstrip(".").lower()
    if normalized not in allowed_hosts:
        raise DownloadError(f"remote host is not allowed: {normalized}")
    try:
        addresses = socket.getaddrinfo(normalized, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise DownloadError(f"could not resolve remote host {normalized}: {exc}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise DownloadError(f"remote host resolved to a non-public address: {ip}")


class SafeImageDownloader:
    """A bounded HTTPS-only downloader with redirect and MIME validation."""

    def __init__(self, policy: DownloadPolicy | None = None) -> None:
        self.policy = policy or DownloadPolicy()

    def download(
        self,
        url: str,
        *,
        allowed_hosts: frozenset[str],
        headers: dict[str, str] | None = None,
    ) -> ValidatedImage:
        current_url = url
        session = requests.Session()
        session.max_redirects = self.policy.max_redirects
        try:
            for redirect_count in range(self.policy.max_redirects + 1):
                parsed = urlparse(current_url)
                if parsed.scheme != "https" or parsed.hostname is None:
                    raise DownloadError("asset URL must use HTTPS and include a host")
                _validate_remote_host(parsed.hostname, allowed_hosts)
                try:
                    response = session.get(
                        current_url,
                        headers=headers,
                        stream=True,
                        allow_redirects=False,
                        timeout=(
                            self.policy.connect_timeout_seconds,
                            self.policy.read_timeout_seconds,
                        ),
                    )
                except requests.RequestException as exc:
                    raise DownloadError(f"request failed: {exc}") from exc
                with response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if redirect_count >= self.policy.max_redirects:
                            raise DownloadError("redirect limit exceeded")
                        location = response.headers.get("Location")
                        if not location:
                            raise DownloadError("redirect response omitted Location")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code != 200:
                        raise DownloadError(f"unexpected HTTP status {response.status_code}")
                    content_type = response.headers.get("Content-Type")
                    if content_type is None:
                        raise DownloadError("image response omitted Content-Type")
                    declared_length = response.headers.get("Content-Length")
                    if declared_length is not None:
                        try:
                            if int(declared_length) > self.policy.max_bytes:
                                raise DownloadError("image exceeds configured byte limit")
                        except ValueError as exc:
                            raise DownloadError("invalid Content-Length header") from exc
                    chunks: list[bytes] = []
                    size = 0
                    try:
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if not chunk:
                                continue
                            size += len(chunk)
                            if size > self.policy.max_bytes:
                                raise DownloadError("image exceeds configured byte limit")
                            chunks.append(chunk)
                    except requests.RequestException as exc:
                        raise DownloadError(f"response body failed: {exc}") from exc
                    try:
                        return validate_image_bytes(
                            b"".join(chunks),
                            declared_content_type=content_type,
                            min_width=self.policy.min_width,
                            min_height=self.policy.min_height,
                        )
                    except AssetValidationError as exc:
                        raise DownloadError(str(exc)) from exc
            raise DownloadError("redirect handling failed")
        finally:
            session.close()


def safe_asset_destination(
    root: Path, kind: str, stable_id: str, visual_id: str, suffix: str
) -> Path:
    """Build and verify a name-only catalog path; source names never reach the filesystem."""

    for component in (kind, stable_id, visual_id):
        if component in {"", ".", ".."} or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in component
        ):
            raise AssetValidationError(f"unsafe generated path component: {component!r}")
    if suffix not in {".png", ".jpg", ".webp"}:
        raise AssetValidationError(f"unsafe image suffix: {suffix!r}")
    destination = root / "assets" / kind / stable_id / f"{visual_id}{suffix}"
    resolved_root = root.resolve()
    if not destination.resolve().is_relative_to(resolved_root):
        raise AssetValidationError("asset destination escapes snapshot directory")
    return destination

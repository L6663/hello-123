"""Bounded-memory SHA-256 helpers shared by ingestion and release stages."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from os import PathLike
from pathlib import Path
import re
from typing import BinaryIO

DEFAULT_BLOCK_SIZE = 4 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class HashingError(ValueError):
    """Raised when a path or stream cannot be hashed safely."""


@dataclass(frozen=True, slots=True)
class FileDigest:
    """Deterministic metadata emitted for one hashed regular file."""

    path: str
    size_bytes: int
    sha256: str
    block_size: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return asdict(self)


def _validated_block_size(block_size: int) -> int:
    if (
        not isinstance(block_size, int)
        or isinstance(block_size, bool)
        or block_size <= 0
    ):
        raise HashingError("block_size must be a positive integer")
    return block_size


def _regular_file(path: str | PathLike[str]) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        raise HashingError(f"file does not exist: {candidate}")
    if not candidate.is_file():
        raise HashingError(f"path is not a regular file: {candidate}")
    return candidate


def sha256_stream(
    stream: BinaryIO,
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> str:
    """Hash a binary stream from its current position using bounded reads."""

    size = _validated_block_size(block_size)
    digest = sha256()
    while True:
        block = stream.read(size)
        if block == b"":
            break
        if not isinstance(block, (bytes, bytearray, memoryview)):
            raise HashingError("stream.read() must return bytes-like data")
        digest.update(block)
    return digest.hexdigest()


def sha256_file(
    path: str | PathLike[str],
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> str:
    """Return the SHA-256 of a regular file without loading it all into memory."""

    candidate = _regular_file(path)
    with candidate.open("rb") as handle:
        return sha256_stream(handle, block_size=block_size)


def inspect_file(
    path: str | PathLike[str],
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> FileDigest:
    """Return path, byte size, digest, and block size for one regular file."""

    size = _validated_block_size(block_size)
    candidate = _regular_file(path)
    stat_before = candidate.stat()
    digest = sha256_file(candidate, block_size=size)
    stat_after = candidate.stat()
    if (
        stat_before.st_size != stat_after.st_size
        or stat_before.st_mtime_ns != stat_after.st_mtime_ns
    ):
        raise HashingError(f"file changed while hashing: {candidate}")
    return FileDigest(
        path=str(candidate),
        size_bytes=stat_after.st_size,
        sha256=digest,
        block_size=size,
    )


def verify_file_sha256(
    path: str | PathLike[str],
    expected_sha256: str,
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> bool:
    """Return whether a regular file matches a syntactically valid SHA-256."""

    if not isinstance(expected_sha256, str) or not _SHA256_PATTERN.fullmatch(
        expected_sha256
    ):
        raise HashingError("expected_sha256 must be exactly 64 hexadecimal characters")
    actual = sha256_file(path, block_size=block_size)
    return actual == expected_sha256.lower()

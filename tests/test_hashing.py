from __future__ import annotations

from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
import tempfile
import unittest

from tkr.hashing import (
    DEFAULT_BLOCK_SIZE,
    FileDigest,
    HashingError,
    inspect_file,
    sha256_file,
    sha256_stream,
    verify_file_sha256,
)


class _BoundedReadStream(BytesIO):
    def __init__(self, payload: bytes, maximum_read: int) -> None:
        super().__init__(payload)
        self.maximum_read = maximum_read
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0 or size > self.maximum_read:
            raise AssertionError(f"unbounded read requested: {size}")
        return super().read(size)


class HashingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        return path

    def test_empty_file_matches_hashlib(self) -> None:
        path = self._write("empty.bin", b"")
        self.assertEqual(sha256_file(path), sha256(b"").hexdigest())

    def test_utf8_text_matches_hashlib(self) -> None:
        payload = "步剑庭：证据必须可复算。\n".encode("utf-8")
        path = self._write("中文.txt", payload)
        self.assertEqual(sha256_file(path, block_size=7), sha256(payload).hexdigest())

    def test_stream_is_consumed_from_current_position(self) -> None:
        stream = BytesIO(b"prefix-payload")
        stream.seek(len(b"prefix-"))
        self.assertEqual(sha256_stream(stream), sha256(b"payload").hexdigest())

    def test_stream_uses_only_bounded_reads(self) -> None:
        payload = bytes(range(251)) * 50
        stream = _BoundedReadStream(payload, maximum_read=31)
        self.assertEqual(
            sha256_stream(stream, block_size=31),
            sha256(payload).hexdigest(),
        )
        self.assertTrue(stream.read_sizes)
        self.assertTrue(all(size == 31 for size in stream.read_sizes))

    def test_text_stream_is_rejected(self) -> None:
        with self.assertRaisesRegex(HashingError, "bytes-like"):
            sha256_stream(StringIO("not binary"))  # type: ignore[arg-type]

    def test_inspect_file_returns_stable_metadata(self) -> None:
        payload = b"metadata" * 20
        path = self._write("artifact.bin", payload)
        result = inspect_file(path, block_size=11)
        self.assertIsInstance(result, FileDigest)
        self.assertEqual(result.path, str(path))
        self.assertEqual(result.size_bytes, len(payload))
        self.assertEqual(result.sha256, sha256(payload).hexdigest())
        self.assertEqual(result.block_size, 11)
        self.assertEqual(result.to_dict()["sha256"], result.sha256)

    def test_verify_accepts_uppercase_digest_and_detects_mismatch(self) -> None:
        path = self._write("verify.bin", b"verified")
        expected = sha256(b"verified").hexdigest()
        self.assertTrue(verify_file_sha256(path, expected.upper()))
        self.assertFalse(verify_file_sha256(path, "0" * 64))

    def test_invalid_expected_digest_is_rejected(self) -> None:
        path = self._write("verify.bin", b"verified")
        for invalid in ("", "abc", "g" * 64, 123):
            with self.subTest(invalid=invalid):
                with self.assertRaises(HashingError):
                    verify_file_sha256(path, invalid)  # type: ignore[arg-type]

    def test_invalid_block_sizes_are_rejected(self) -> None:
        for invalid in (0, -1, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaises(HashingError):
                    sha256_stream(BytesIO(b"data"), block_size=invalid)  # type: ignore[arg-type]

    def test_missing_path_and_directory_are_rejected(self) -> None:
        with self.assertRaisesRegex(HashingError, "does not exist"):
            sha256_file(self.root / "missing.bin")
        with self.assertRaisesRegex(HashingError, "not a regular file"):
            sha256_file(self.root)

    def test_default_block_size_is_four_mebibytes(self) -> None:
        self.assertEqual(DEFAULT_BLOCK_SIZE, 4 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()

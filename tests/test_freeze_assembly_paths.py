from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.assemble_freeze_candidate import ensure_disjoint_output


class FreezeAssemblyPathTests(unittest.TestCase):
    def test_rejects_output_equal_to_matrix_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(SystemExit, "disjoint from matrix input"):
                ensure_disjoint_output(root, root, [])

    def test_rejects_output_ancestor_of_matrix_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matrix = root / "matrix"
            matrix.mkdir()
            with self.assertRaisesRegex(SystemExit, "disjoint from matrix input"):
                ensure_disjoint_output(matrix, root, [])

    def test_rejects_output_descendant_of_matrix_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "candidate"
            with self.assertRaisesRegex(SystemExit, "disjoint from matrix input"):
                ensure_disjoint_output(root, output, [])

    def test_rejects_output_containing_reproducible_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matrix = root / "matrix"
            matrix.mkdir()
            output = root / "builds"
            output.mkdir()
            wheel = output / "candidate.whl"
            wheel.write_bytes(b"wheel")
            with self.assertRaisesRegex(SystemExit, "must not contain"):
                ensure_disjoint_output(matrix, output, [wheel])

    def test_accepts_disjoint_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matrix = root / "matrix"
            matrix.mkdir()
            output = root / "candidate"
            wheel_dir = root / "builds"
            wheel_dir.mkdir()
            wheel = wheel_dir / "candidate.whl"
            wheel.write_bytes(b"wheel")
            ensure_disjoint_output(matrix, output, [wheel])


if __name__ == "__main__":
    unittest.main()

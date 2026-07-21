from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} anchor not found")
    return text.replace(old, new, 1)


def patch_release_freeze() -> None:
    path = Path("tkr/release_freeze.py")
    text = path.read_text(encoding="utf-8")
    old = '''    if payload["status"] != "candidate":
        raise FreezeError("freeze candidate status must be candidate")

    root_path = Path(root).resolve() if root is not None else path.parent.resolve()
'''
    new = '''    if payload["status"] != "candidate":
        raise FreezeError("freeze candidate status must be candidate")

    release_version = _nonempty_string(payload["release_version"], "release_version")
    source_commit = _nonempty_string(payload["source_commit"], "source_commit")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise FreezeError("source_commit must be a lowercase 40-character Git SHA")
    source_date_epoch = payload["source_date_epoch"]
    if (
        not isinstance(source_date_epoch, int)
        or isinstance(source_date_epoch, bool)
        or source_date_epoch < 0
    ):
        raise FreezeError("source_date_epoch must be a non-negative integer")

    root_path = Path(root).resolve() if root is not None else path.parent.resolve()
'''
    text = replace_once(text, old, new, "release candidate provenance")
    duplicate = '''    release_version = _nonempty_string(payload["release_version"], "release_version")
    evidence = _validate_release_evidence(root_path, records, release_version=release_version)
'''
    text = replace_once(
        text,
        duplicate,
        '    evidence = _validate_release_evidence(root_path, records, release_version=release_version)\n',
        "release version duplicate",
    )
    path.write_text(text, encoding="utf-8")


def patch_assembly() -> None:
    path = Path("tools/assemble_freeze_candidate.py")
    text = path.read_text(encoding="utf-8")
    helper = '''def ensure_disjoint_output(
    matrix_root: Path,
    output_root: Path,
    reproducible_wheels: list[Path],
) -> None:
    """Reject output paths that could delete or overwrite release evidence."""

    matrix = matrix_root.resolve()
    output = output_root.resolve()
    if output == matrix or output in matrix.parents or matrix in output.parents:
        raise SystemExit(
            "output root must be a dedicated directory disjoint from matrix input"
        )
    for wheel in reproducible_wheels:
        resolved = wheel.resolve()
        if output == resolved or output in resolved.parents:
            raise SystemExit("output root must not contain a reproducible wheel input")


'''
    text = replace_once(text, "def main() -> int:\n", helper + "def main() -> int:\n", "assembly helper")
    old = '''    output = args.output_root.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
'''
    new = '''    matrix_root = args.matrix_root.resolve()
    reproducible_wheels = [item.resolve() for item in args.reproducible_wheel]
    output = args.output_root.resolve()
    ensure_disjoint_output(matrix_root, output, reproducible_wheels)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
'''
    text = replace_once(text, old, new, "assembly output")
    text = replace_once(
        text,
        '    for path in args.matrix_root.rglob("package-acceptance.json"):\n',
        '    for path in matrix_root.rglob("package-acceptance.json"):\n',
        "package report root",
    )
    text = replace_once(
        text,
        '    source_wheels = list(args.matrix_root.rglob(wheel_name))\n',
        '    source_wheels = list(matrix_root.rglob(wheel_name))\n',
        "wheel root",
    )
    text = replace_once(
        text,
        '    benchmark_roots = list(args.matrix_root.rglob("benchmark/release-manifest.json"))\n',
        '    benchmark_roots = list(matrix_root.rglob("benchmark/release-manifest.json"))\n',
        "benchmark root",
    )
    text = replace_once(
        text,
        '    build_hashes = [digest(path.resolve()) for path in args.reproducible_wheel]\n',
        '    build_hashes = [digest(item) for item in reproducible_wheels]\n',
        "reproducible wheels",
    )
    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    path = Path("tests/test_release_freeze.py")
    text = path.read_text(encoding="utf-8")
    methods = '''
    def _rewrite_candidate_id(self, payload: dict[str, object]) -> None:
        core = dict(payload)
        core.pop("candidate_id", None)
        canonical = json.dumps(
            core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload["candidate_id"] = "freeze_candidate_" + sha256(
            canonical.encode("utf-8")
        ).hexdigest()[:24]

    def test_verify_rejects_malformed_source_commit_even_with_recomputed_id(self) -> None:
        candidate = self._prepare()
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        payload["source_commit"] = "not-a-git-sha"
        self._rewrite_candidate_id(payload)
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FreezeError, "lowercase 40-character Git SHA"):
            verify_freeze_candidate(candidate, root=self.root)

    def test_verify_rejects_negative_source_epoch_even_with_recomputed_id(self) -> None:
        candidate = self._prepare()
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        payload["source_date_epoch"] = -1
        self._rewrite_candidate_id(payload)
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FreezeError, "non-negative integer"):
            verify_freeze_candidate(candidate, root=self.root)
'''
    marker = '\n\nif __name__ == "__main__":\n'
    text = replace_once(text, marker, methods + marker, "freeze tests")
    path.write_text(text, encoding="utf-8")


def create_path_tests() -> None:
    Path("tests/test_freeze_assembly_paths.py").write_text(
        '''from __future__ import annotations

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
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_release_freeze()
    patch_assembly()
    patch_tests()
    create_path_tests()
    for temporary in (
        Path(".github/workflows/phase8-review-fixes.yml"),
        Path(".github/workflows/phase8-review-fixes-pr.yml"),
        Path(".github/scripts/apply_phase8_review_fixes.py"),
    ):
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

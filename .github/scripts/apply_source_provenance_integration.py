from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one match, found {text.count(old)}")
    return text.replace(old, new, 1)


release = Path("tkr/release_freeze.py")
text = release.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .gold_benchmark import verify_benchmark_report\n",
    "from .gold_benchmark import verify_benchmark_report\n"
    "from .source_provenance import (\n"
    "    SourceProvenanceError,\n"
    "    verify_source_provenance,\n"
    ")\n",
    "release import",
)
text = replace_once(
    text,
    '    "reproducible_build_report",\n)\n',
    '    "reproducible_build_report",\n'
    '    "source_bundle",\n'
    '    "source_provenance",\n'
    ')\n',
    "singleton roles",
)
text = replace_once(
    text,
    "    release_version: str,\n) -> dict[str, object]:\n",
    "    release_version: str,\n"
    "    source_commit: str,\n"
    "    source_date_epoch: int,\n"
    ") -> dict[str, object]:\n",
    "validation signature",
)
needle = '''    if any(item != wheel_sha256 for item in actual_build_hashes):
        raise FreezeError("bound reproducible wheels are not byte-identical")

    return {
'''
replacement = '''    if any(item != wheel_sha256 for item in actual_build_hashes):
        raise FreezeError("bound reproducible wheels are not byte-identical")

    try:
        source_evidence = verify_source_provenance(
            _single_path(root, grouped, "source_bundle"),
            _single_path(root, grouped, "source_provenance"),
            _single_path(root, grouped, "wheel"),
            source_commit=source_commit,
            source_date_epoch=source_date_epoch,
            release_version=release_version,
        )
    except SourceProvenanceError as exc:
        raise FreezeError(f"source provenance verification failed: {exc}") from exc

    return {
'''
text = replace_once(text, needle, replacement, "source verification")
text = replace_once(
    text,
    '        "reproducible_wheel_artifact_count": len(reproducible_records),\n'
    '        "technical_gate_passed": True,\n',
    '        "reproducible_wheel_artifact_count": len(reproducible_records),\n'
    '        "source_commit_bound": source_evidence["source_commit"],\n'
    '        "source_date_epoch_bound": source_evidence["source_date_epoch"],\n'
    '        "source_bundle_sha256": source_evidence["source_bundle_sha256"],\n'
    '        "source_runtime_file_count": source_evidence["runtime_file_count"],\n'
    '        "source_runtime_files_sha256": source_evidence["runtime_files_sha256"],\n'
    '        "source_provenance_verified": source_evidence["source_provenance_verified"],\n'
    '        "technical_gate_passed": True,\n',
    "evidence summary",
)
text = replace_once(
    text,
    '''    evidence = _validate_release_evidence(
        root_path, records, release_version=version
    )
''',
    '''    evidence = _validate_release_evidence(
        root_path,
        records,
        release_version=version,
        source_commit=commit,
        source_date_epoch=source_date_epoch,
    )
''',
    "prepare call",
)
text = replace_once(
    text,
    '''    evidence = _validate_release_evidence(
        root_path, records, release_version=release_version
    )
''',
    '''    evidence = _validate_release_evidence(
        root_path,
        records,
        release_version=release_version,
        source_commit=source_commit,
        source_date_epoch=source_date_epoch,
    )
''',
    "verify call",
)
release.write_text(text, encoding="utf-8")

assembly = Path("tools/assemble_freeze_candidate.py")
text = assembly.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from tkr.release_freeze import prepare_freeze_candidate, verify_freeze_candidate\n",
    "from tkr.release_freeze import prepare_freeze_candidate, verify_freeze_candidate\n"
    "from tkr.source_provenance import build_source_provenance\n",
    "assembly import",
)
text = replace_once(
    text,
    '    parser.add_argument("--matrix-root", type=Path, required=True)\n',
    '    parser.add_argument("--matrix-root", type=Path, required=True)\n'
    '    parser.add_argument("--source-root", type=Path, default=Path("."))\n',
    "source root argument",
)
text = replace_once(
    text,
    '''    wheel = output / wheel_name
    shutil.copy2(source_wheels[0], wheel)

    benchmark_manifests = list(
''',
    '''    wheel = output / wheel_name
    shutil.copy2(source_wheels[0], wheel)

    source_bundle = output / "source.bundle"
    source_provenance = output / "source-provenance.json"
    build_source_provenance(
        args.source_root,
        source_bundle,
        source_provenance,
        source_commit=args.source_commit,
        source_date_epoch=args.source_date_epoch,
        wheel_path=wheel,
    )

    benchmark_manifests = list(
''',
    "build source provenance",
)
text = replace_once(
    text,
    '''        ("reproducible_build_report", reproducible_path),
    ]
''',
    '''        ("reproducible_build_report", reproducible_path),
        ("source_bundle", source_bundle),
        ("source_provenance", source_provenance),
    ]
''',
    "assembly specs",
)
assembly.write_text(text, encoding="utf-8")

tests = Path("tests/test_release_freeze.py")
text = tests.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''        self.verify_mock = self.verify_patch.start()

        self.wheel = (
''',
    '''        self.verify_mock = self.verify_patch.start()
        self.source_summary = {
            "source_commit": self.SOURCE_COMMIT,
            "source_date_epoch": 1700000000,
            "source_bundle_sha256": "b" * 64,
            "runtime_file_count": 2,
            "runtime_files_sha256": "c" * 64,
            "source_provenance_verified": True,
        }
        self.source_patch = patch(
            "tkr.release_freeze.verify_source_provenance",
            return_value=self.source_summary,
        )
        self.source_mock = self.source_patch.start()

        self.wheel = (
''',
    "test source patch",
)
text = replace_once(
    text,
    '''        self.reproducible = self._write_json(
            "reproducible-build.json",
''',
    '''        self.source_bundle = self._write_bytes(
            "source.bundle", b"git-bundle"
        )
        self.source_provenance = self._write_json(
            "source-provenance.json", {"schema_version": "test"}
        )

        self.reproducible = self._write_json(
            "reproducible-build.json",
''',
    "test source fixtures",
)
text = replace_once(
    text,
    '''    def tearDown(self) -> None:
        self.verify_patch.stop()
        self.temporary.cleanup()
''',
    '''    def tearDown(self) -> None:
        self.source_patch.stop()
        self.verify_patch.stop()
        self.temporary.cleanup()
''',
    "test teardown",
)
text = replace_once(
    text,
    '''            ("reproducible_build_report", self.reproducible),
            *(
''',
    '''            ("reproducible_build_report", self.reproducible),
            ("source_bundle", self.source_bundle),
            ("source_provenance", self.source_provenance),
            *(
''',
    "test specs",
)
tests.write_text(text, encoding="utf-8")

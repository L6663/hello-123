from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tkr import literary_engine


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


class LiteraryCRLFSourceBindingTests(unittest.TestCase):
    def test_project_inputs_preserve_crlf_for_hash_and_offsets(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            source_text = "第一行\r\n第二行\r\n"
            source_path = root / "source" / "normalized-source.txt"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(source_text.encode("utf-8"))
            (root / "project-report.json").write_text(
                json.dumps(
                    {
                        "project_id": "kpr_crlf_fixture",
                        "source_id": "src_crlf_fixture",
                        "normalized_source_sha256": sha256(source_text.encode("utf-8")).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            _jsonl(root / "stage2-structure" / "unit-index.jsonl", [{}])
            _jsonl(root / "stage2-structure" / "heading-candidates.jsonl", [])
            _jsonl(root / "stage1-anomaly" / "anomaly-candidates.jsonl", [])
            _jsonl(root / "bridge" / "entity" / "mentions.jsonl", [])
            _jsonl(root / "bridge" / "entity" / "entities.jsonl", [])
            _jsonl(root / "bridge" / "entity" / "facts.jsonl", [{}])

            verification = type("Verification", (), {"valid": True, "reason_codes": ()})()
            with patch(
                "tkr.literary_engine.verify_secure_knowledge_project",
                return_value=verification,
            ):
                _, loaded, *_ = literary_engine._project_inputs(root)

            self.assertEqual(loaded, source_text)
            self.assertEqual(
                sha256(loaded.encode("utf-8")).hexdigest(),
                sha256(source_path.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()

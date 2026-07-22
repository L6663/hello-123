from pathlib import Path
import tempfile
import unittest

from tkr.structure_detection import inspect_source_structure


class Stage6R1HeadingVariantTests(unittest.TestCase):
    def test_bare_chapter_number_is_not_greedily_merged_with_volume(self):
        text = (
            "卷五 八十一章 天道鬼道（一）\n正文甲。\n"
            "卷五 八十二章 天道鬼道（二）\n正文乙。\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.txt"
            path.write_text(text, encoding="utf-8", newline="")
            report = inspect_source_structure(path)
        self.assertEqual([unit.ordinal for unit in report.units], [81, 82])
        self.assertEqual([unit.unit_type for unit in report.units], ["chapter", "chapter"])
        self.assertIn("container_ordinal=5", report.headings[0].signals)


if __name__ == "__main__":
    unittest.main()

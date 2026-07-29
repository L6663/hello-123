from __future__ import annotations

import contextlib
import io
import unittest

from tkr.learning_cli import main


class LearningCliContractTests(unittest.TestCase):
    def test_help_exposes_build_verify_query(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(output):
            main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        text = output.getvalue()
        self.assertIn("build", text)
        self.assertIn("verify", text)
        self.assertIn("query", text)

    def test_build_help_exposes_source_and_observation_bindings(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(output):
            main(["build", "--help"])
        self.assertEqual(caught.exception.code, 0)
        text = output.getvalue()
        self.assertIn("--source-project", text)
        self.assertIn("--observations", text)


if __name__ == "__main__":
    unittest.main()

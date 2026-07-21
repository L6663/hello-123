from pathlib import Path

path = Path("tools/assemble_freeze_candidate.py")
text = path.read_text(encoding="utf-8")
old = '''import re
import shutil

from tkr.release_freeze import prepare_freeze_candidate, verify_freeze_candidate
from tkr.source_provenance import build_source_provenance
'''
new = '''import re
import shutil
import sys

# The candidate verifier must come from the reviewed checkout, not the wheel.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_TEXT = str(REPOSITORY_ROOT)
if not sys.path or sys.path[0] != REPOSITORY_TEXT:
    sys.path.insert(0, REPOSITORY_TEXT)

import tkr.release_freeze as release_freeze_module  # noqa: E402
import tkr.source_provenance as source_provenance_module  # noqa: E402
from tkr.release_freeze import prepare_freeze_candidate, verify_freeze_candidate  # noqa: E402
from tkr.source_provenance import build_source_provenance  # noqa: E402
'''
if text.count(old) != 1:
    raise SystemExit(f"import anchor mismatch: {text.count(old)}")
text = text.replace(old, new, 1)
old = '''def main() -> int:
    parser = argparse.ArgumentParser(
'''
new = '''def main() -> int:
    expected_release = (REPOSITORY_ROOT / "tkr" / "release_freeze.py").resolve()
    expected_source = (REPOSITORY_ROOT / "tkr" / "source_provenance.py").resolve()
    if Path(release_freeze_module.__file__).resolve() != expected_release:
        raise SystemExit("release verifier was not loaded from the reviewed checkout")
    if Path(source_provenance_module.__file__).resolve() != expected_source:
        raise SystemExit("source verifier was not loaded from the reviewed checkout")

    parser = argparse.ArgumentParser(
'''
if text.count(old) != 1:
    raise SystemExit(f"main anchor mismatch: {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

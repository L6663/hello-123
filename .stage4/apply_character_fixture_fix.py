from pathlib import Path

path = Path("tests/test_character_project.py")
text = path.read_text(encoding="utf-8")
old = "self.events[2].event_id"
new = "self.events[-1].event_id"
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one fixture reference, found {text.count(old)}")
path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")

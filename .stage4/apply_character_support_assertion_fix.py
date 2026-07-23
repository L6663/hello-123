from pathlib import Path

path = Path("tests/test_character_project.py")
text = path.read_text(encoding="utf-8")
old = '            self.assertTrue(profile["attributes"][0]["support"]["evidence"])\n'
new = '''            self.assertTrue(\n                any(\n                    item["tier"] == "A" and item["support"]["evidence"]\n                    for item in profile["attributes"]\n                )\n            )\n            self.assertTrue(\n                all(\n                    item["supporting_attribute_ids"]\n                    for item in profile["attributes"]\n                    if item["tier"] in {"B", "C"}\n                )\n            )\n'''
if text.count(old) != 1:
    raise SystemExit(f"expected one outdated support assertion, found {text.count(old)}")
path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")

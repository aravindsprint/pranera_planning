"""Every doctype must sit where Frappe looks for it: folder and files = the doctype's name in
lower case with spaces AND hyphens turned into underscores ("Re-order Settings" →
re_order_settings), and its class = the name without spaces or hyphens. A mismatch only shows
at `bench migrate` ("No module named …"), which the other tests never run."""
import json
import os
import re
import unittest

DOCTYPES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "planning", "doctype")


class TestDoctypeLayout(unittest.TestCase):
    def test_folders_files_and_classes_match_the_doctype_names(self):
        checked = 0
        for folder in sorted(os.listdir(DOCTYPES)):
            path = os.path.join(DOCTYPES, folder)
            if not os.path.isdir(path) or folder.startswith("__"):
                continue
            jsons = [f for f in os.listdir(path) if f.endswith(".json")]
            self.assertEqual(len(jsons), 1, folder)
            name = json.load(open(os.path.join(path, jsons[0])))["name"]
            want = re.sub(r"[ -]", "_", name.lower())
            self.assertEqual(folder, want, f"{name}: folder should be {want}")
            self.assertEqual(jsons[0], f"{want}.json", name)
            py = open(os.path.join(path, f"{want}.py")).read()
            self.assertIn(f"class {name.replace(' ', '').replace('-', '')}(", py, name)
            self.assertTrue(os.path.exists(os.path.join(path, "__init__.py")), name)
            checked += 1
        self.assertGreaterEqual(checked, 9)


if __name__ == "__main__":
    unittest.main()

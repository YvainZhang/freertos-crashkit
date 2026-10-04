# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('fetch', Path(__file__).resolve().parents[1]/'scripts/fetch-freertos.py')
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


class DependencyTests(unittest.TestCase):
    def test_modified_missing_extra_and_linked_source_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {'tasks.c': b'original'}
            target = root/'tasks.c'
            target.write_bytes(files['tasks.c'])
            fetch.verify_tree(root, files)
            target.write_bytes(b'modified')
            with self.assertRaises(ValueError): fetch.verify_tree(root, files)
            target.unlink()
            with self.assertRaises(ValueError): fetch.verify_tree(root, files)
            target.write_bytes(files['tasks.c'])
            (root/'extra.c').write_bytes(b'extra')
            with self.assertRaises(ValueError): fetch.verify_tree(root, files)
            (root/'extra.c').unlink()
            (root/'linked.c').symlink_to(target)
            with self.assertRaises(ValueError): fetch.verify_tree(root, files)


if __name__ == '__main__':
    unittest.main()

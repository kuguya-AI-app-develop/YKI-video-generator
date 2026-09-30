from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend state regressions")
class FrontendStateTests(unittest.TestCase):
    def test_editor_state(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", str(Path(__file__).with_name("test_editor_state.cjs"))],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

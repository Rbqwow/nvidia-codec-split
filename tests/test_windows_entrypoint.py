from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import sys
import unittest


@unittest.skipUnless(os.name == "nt", "Windows command entry point")
class RestoreEntryPoint(unittest.TestCase):
    def test_missing_backup_fails_before_uac_and_preserves_batch_exit_code(self):
        repo = Path(__file__).resolve().parents[1]
        with TemporaryDirectory(prefix="codec restore ") as directory:
            root = Path(directory)
            result = subprocess.run([
                "cmd.exe", "/d", "/c", "Restore.cmd", "-StateDir", str(root / "state"),
                "-LegacyHelper", str(root / "missing helper"), "-AppRoot", str(root / "app"),
                "-PythonPath", sys.executable,
            ], cwd=repo, input="\n", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", timeout=30)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("No restore manifest or legacy helper backup found", result.stdout)
            self.assertNotIn("Completed Restore", result.stdout)
            self.assertFalse((root / "state").exists())


if __name__ == "__main__":
    unittest.main()

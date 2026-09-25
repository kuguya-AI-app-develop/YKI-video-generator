"""Regressions for legacy and CUDA UMD nvidia-smi headers; no GPU required."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.config import ROOT
from app.diagnostics import doctor


FIXTURES = json.loads((Path(__file__).parent / "fixtures/nvidia-smi-headers.json").read_text(encoding="utf-8"))
POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")


class NvidiaDriverTests(unittest.TestCase):
    def test_doctor_driver_compatibility(self):
        config = json.loads((ROOT / "config/defaults.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            for fixture in FIXTURES:
                with self.subTest(case=fixture["name"]):
                    results = [
                        subprocess.CompletedProcess(["nvidia-smi"], fixture["exit_code"], fixture["stdout"], ""),
                        subprocess.CompletedProcess(["nvidia-smi"], 0, "NVIDIA GeForce RTX 4070 SUPER, 12282", ""),
                    ]
                    with patch("app.diagnostics.subprocess.run", side_effect=results), \
                         patch("app.diagnostics.manifest", return_value={"assets": []}), \
                         patch("app.diagnostics.executable", return_value="unused"), \
                         patch("app.diagnostics.importlib.util.find_spec", return_value=object()), \
                         patch("app.diagnostics.platform.system", return_value="Windows"):
                        report = doctor(Path(folder), config)
                    driver_checks = [check for check in report["checks"] if check["name"] == "NVIDIA 驱动"]
                    self.assertEqual(len(driver_checks), 1)
                    self.assertEqual(driver_checks[0]["ok"], fixture["compatible"], driver_checks[0]["detail"])
                    self.assertTrue(driver_checks[0]["required"])

    @unittest.skipUnless(POWERSHELL, "PowerShell 5.1 or pwsh is required to execute the installer regression")
    def test_installer_driver_preflight(self):
        result = subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(Path(__file__).with_name("check_nvidia_driver.ps1"))],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"{len(FIXTURES)} cases passed", result.stdout)


if __name__ == "__main__":
    unittest.main()

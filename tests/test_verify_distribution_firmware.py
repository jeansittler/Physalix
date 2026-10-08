"""Tests ciblés du contrôle de bundle firmware, sans accès matériel."""

from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_distribution import avrdude_startup


class AvrdudeBundleCheckTests(unittest.TestCase):
    def test_startup_check_is_non_destructive_and_supports_spaces(self):
        with tempfile.TemporaryDirectory(prefix="Physalix bundle with spaces ") as temporary:
            directory = Path(temporary)
            executable = directory / "avrdude.exe"
            config = directory / "avrdude.conf"
            executable.write_bytes(b"placeholder")
            config.write_bytes(b"placeholder")
            completed = CompletedProcess(
                [str(executable), "-C", str(config), "-?"], 0,
                stdout="avrdude version 8.1, official build\n", stderr="")

            with patch("scripts.verify_distribution.subprocess.run",
                       return_value=completed) as run:
                output = avrdude_startup(executable, config)

            self.assertIn("version 8.1", output)
            run.assert_called_once_with(
                [str(executable), "-C", str(config), "-?"], cwd=executable.parent,
                timeout=15, capture_output=True, text=True)
            arguments = run.call_args.args[0]
            self.assertNotIn("-P", arguments)
            self.assertNotIn("-U", arguments)


if __name__ == "__main__":
    unittest.main()

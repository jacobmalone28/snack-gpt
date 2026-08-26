from pathlib import Path
import subprocess
import unittest


class BenchmarkScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = Path(__file__).parents[1] / "scripts" / "benchmark-whisper.sh"

    def test_bash_syntax_is_valid(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(self.script)],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help_describes_reports_without_pi_preflight(self) -> None:
        result = subprocess.run(
            ["bash", str(self.script), "--help"],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("summary", result.stdout)
        self.assertIn("--quant-model FILE", result.stdout)


if __name__ == "__main__":
    unittest.main()
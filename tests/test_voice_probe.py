import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class VoiceProbeTests(unittest.TestCase):
    def test_probe_records_blocking_incompatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "probe.json"
            results = root / "results.json"
            manifest.write_text(
                json.dumps({"require_raspberry_pi_3b_plus": False}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "-m", "snack_gpt.voice_probe", str(manifest), "--output", str(results)],
                capture_output=True,
                check=False,
                env=os.environ,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            report = json.loads(results.read_text(encoding="utf-8"))
            self.assertFalse(report["passed"])
            self.assertEqual(report["blocking_incompatibilities"], [
                "network_isolation_command must be a non-empty list of strings"
            ])

    def test_probe_runs_every_stage_offline_and_writes_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "report.wav"
            fixture.write_bytes(b"representative audio")
            fake_runtime = root / "fake_runtime.py"
            fake_runtime.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    from pathlib import Path
                    import sys

                    mode, *arguments = sys.argv[1:]
                    if mode == "isolate":
                        os.execv(arguments[0], arguments)
                    output = Path(arguments[-1])
                    if mode == "wake":
                        output.write_text(json.dumps({"detected": True}))
                    elif mode == "transcribe":
                        output.write_text("I ate two eggs")
                    elif mode == "extract":
                        transcript = Path(arguments[0]).read_text()
                        output.write_text(json.dumps({"transcript": transcript, "foods": [{"food": "egg", "quantity": 2}]}))
                    elif mode == "synthesize":
                        extraction = json.loads(Path(arguments[0]).read_text())
                        output.write_bytes(("RIFF" + extraction["foods"][0]["food"]).encode())
                    """
                ),
                encoding="utf-8",
            )
            artifacts = root / "artifacts"
            results = root / "results.json"
            manifest = root / "probe.json"
            manifest.write_text(
                json.dumps(
                    {
                        "fixture_audio": str(fixture),
                        "artifacts_directory": str(artifacts),
                        "require_raspberry_pi_3b_plus": False,
                        "network_isolation_command": [sys.executable, str(fake_runtime), "isolate"],
                        "evidence_files": [str(fake_runtime), str(fixture)],
                        "expected_transcript_terms": ["two", "eggs"],
                        "expected_extraction": {"foods": [{"food": "egg", "quantity": 2}]},
                        "commands": {
                            "wake_detection": [sys.executable, str(fake_runtime), "wake", "{audio}", "{wake_result}"],
                            "transcription": [sys.executable, str(fake_runtime), "transcribe", "{audio}", "{transcript}"],
                            "extraction": [sys.executable, str(fake_runtime), "extract", "{transcript}", "{extraction}"],
                            "speech_synthesis": [sys.executable, str(fake_runtime), "synthesize", "{extraction}", "{speech}"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "-m", "snack_gpt.voice_probe", str(manifest), "--output", str(results)],
                capture_output=True,
                check=False,
                env=os.environ,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(results.read_text(encoding="utf-8"))
            self.assertEqual([stage["name"] for stage in report["stages"]], [
                "wake_detection",
                "transcription",
                "extraction",
                "speech_synthesis",
            ])
            self.assertTrue(all(stage["duration_seconds"] >= 0 for stage in report["stages"]))
            self.assertTrue(all(stage["peak_memory_bytes"] > 0 for stage in report["stages"]))
            self.assertTrue(report["offline"])
            self.assertEqual(len(report["evidence_files"]), 2)
            self.assertTrue(all(len(item["sha256"]) == 64 for item in report["evidence_files"]))
            self.assertIn(report["latency_verdict"], {"expected_latency_achievable", "hard_timeout_only", "hard_timeout_exceeded"})
            self.assertEqual(json.loads((artifacts / "extraction.json").read_text())["foods"][0]["food"], "egg")
            self.assertGreater((artifacts / "speech.wav").stat().st_size, 4)


if __name__ == "__main__":
    unittest.main()
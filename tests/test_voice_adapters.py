import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


class VoiceAdapterTests(unittest.TestCase):
    def test_adapters_normalize_runtime_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            modules = root / "modules"
            (modules / "openwakeword").mkdir(parents=True)
            (modules / "openwakeword" / "__init__.py").write_text("", encoding="utf-8")
            (modules / "openwakeword" / "model.py").write_text(
                textwrap.dedent(
                    """
                    class Model:
                        def __init__(self, **kwargs):
                            pass

                        def predict_clip(self, path):
                            return [{"hey_jarvis_v0.1": 0.2}, {"hey_jarvis_v0.1": 0.8}]
                    """
                ),
                encoding="utf-8",
            )
            (modules / "needle.py").write_text(
                "def extract(text, schema, weights=None):\n"
                "    return {'foods': [{'food': 'egg', 'quantity': 2}]}\n",
                encoding="utf-8",
            )
            fake_binary = root / "fake_binary.py"
            fake_binary.write_text(
                textwrap.dedent(
                    """
                    from pathlib import Path
                    import sys

                    arguments = sys.argv[1:]
                    if "-of" in arguments:
                        Path(arguments[arguments.index("-of") + 1] + ".txt").write_text("I ate two eggs")
                    elif "-f" in arguments:
                        Path(arguments[arguments.index("-f") + 1]).write_bytes(b"RIFFspeech")
                    """
                ),
                encoding="utf-8",
            )
            audio = root / "report.wav"
            audio.write_bytes(b"RIFFaudio")
            model = root / "model.onnx"
            model.write_bytes(b"model")
            (root / "melspectrogram.onnx").write_bytes(b"model")
            (root / "embedding_model.onnx").write_bytes(b"model")
            environment = os.environ | {"PYTHONPATH": f"{modules}{os.pathsep}{os.getcwd()}"}

            wake_result = root / "wake.json"
            self._run_adapter(environment, "wake", "--model", model, "--audio", audio, "--output", wake_result)
            self.assertTrue(json.loads(wake_result.read_text())["detected"])

            transcript = root / "transcript.txt"
            self._run_adapter(
                environment,
                "transcribe",
                "--binary",
                sys.executable,
                "--binary-argument",
                fake_binary,
                "--model",
                model,
                "--audio",
                audio,
                "--output",
                transcript,
            )
            self.assertEqual(transcript.read_text(), "I ate two eggs")

            extraction = root / "extraction.json"
            self._run_adapter(environment, "extract", "--transcript", transcript, "--output", extraction)
            self.assertEqual(json.loads(extraction.read_text())["foods"][0], {"food": "egg", "quantity": 2})

            speech = root / "speech.wav"
            self._run_adapter(
                environment,
                "synthesize",
                "--binary",
                sys.executable,
                "--binary-argument",
                fake_binary,
                "--model",
                model,
                "--extraction",
                extraction,
                "--output",
                speech,
            )
            self.assertEqual(speech.read_bytes(), b"RIFFspeech")

    def test_piper_worker_reuses_loaded_voice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            modules = root / "modules"
            (modules / "piper").mkdir(parents=True)
            (modules / "piper" / "__init__.py").write_text(
                textwrap.dedent(
                    """
                    class PiperVoice:
                        @classmethod
                        def load(cls, model):
                            return cls()

                        def synthesize_wav(self, text, output):
                            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                            output.writeframes(text.encode())
                    """
                ),
                encoding="utf-8",
            )
            environment = os.environ | {"PYTHONPATH": f"{modules}{os.pathsep}{os.getcwd()}"}
            socket_path = root / "piper.sock"
            model = root / "voice.onnx"
            model.write_bytes(b"model")
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "snack_gpt.voice_adapters",
                    "piper-worker",
                    "--model",
                    str(model),
                    "--socket",
                    str(socket_path),
                ],
                env=environment,
            )
            try:
                for _ in range(100):
                    if socket_path.exists():
                        break
                    time.sleep(0.01)
                self.assertTrue(socket_path.exists())
                extraction = root / "extraction.json"
                extraction.write_text('{"foods":[{"food":"egg","quantity":2}]}', encoding="utf-8")
                speech = root / "speech.wav"

                self._run_adapter(
                    environment,
                    "synthesize",
                    "--socket",
                    socket_path,
                    "--extraction",
                    extraction,
                    "--output",
                    speech,
                )

                self.assertGreater(speech.stat().st_size, 4)
            finally:
                worker.terminate()
                worker.wait(timeout=5)

    def test_provisioning_script_has_valid_bash_syntax(self) -> None:
        result = subprocess.run(
            ["bash", "-n", "scripts/provision-voice-probe.sh"],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_provisioning_script_supports_python_3_13_arm64_wheels(self) -> None:
        script = Path("scripts/provision-voice-probe.sh").read_text(encoding="utf-8")

        self.assertNotIn("Python 3.11 is required", script)
        self.assertNotIn("python3.11/site-packages", script)
        self.assertIn('"numpy==2.2.6"', script)
        self.assertIn('"onnxruntime==1.22.1"', script)
        self.assertIn('"scikit-learn==1.6.1"', script)
        self.assertIn('"scipy==1.15.3"', script)
        self.assertIn("sysconfig.get_path(\"purelib\")", script)

    def test_provisioning_script_selects_a_capture_device(self) -> None:
        script = Path("scripts/provision-voice-probe.sh").read_text(encoding="utf-8")

        self.assertIn("--capture-device", script)
        self.assertIn("arecord --list-devices", script)
        self.assertIn('DEVICE="$CAPTURE_DEVICE"', script)
        self.assertIn('arecord --device="$DEVICE"', script)
        self.assertIn("en_US-lessac-low.onnx", script)
        self.assertIn('write_adapter "$BIN/piper-worker" piper-worker', script)

    def _run_adapter(self, environment: dict[str, str], *arguments: object) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "snack_gpt.voice_adapters", *(str(argument) for argument in arguments)],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
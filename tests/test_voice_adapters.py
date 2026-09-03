import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import wave

from snack_gpt.voice import ExtractionError, parse_consumption_report


class VoiceAdapterTests(unittest.TestCase):
    def test_wake_worker_reuses_loaded_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            modules = root / "modules" / "openwakeword"
            modules.mkdir(parents=True)
            (modules / "__init__.py").write_text("", encoding="utf-8")
            loads = root / "loads.txt"
            (modules / "model.py").write_text(
                textwrap.dedent(
                    f"""
                    from pathlib import Path

                    class Model:
                        def __init__(self, **kwargs):
                            with Path({str(loads)!r}).open("a") as output:
                                output.write("loaded\\n")

                        def predict_clip(self, path):
                            return [{{"hey_jarvis": 0.9}}]
                    """
                ),
                encoding="utf-8",
            )
            environment = os.environ | {
                "PYTHONPATH": f"{root / 'modules'}{os.pathsep}{os.getcwd()}"
            }
            socket_path = root / "wake.sock"
            model = root / "hey_jarvis.onnx"
            model.write_bytes(b"model")
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "snack_gpt.voice_adapters",
                    "wake-worker",
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
                audio = root / "wake.wav"
                audio.write_bytes(b"audio")
                for attempt in range(2):
                    output = root / f"wake-{attempt}.json"
                    self._run_adapter(
                        environment,
                        "wake",
                        "--socket",
                        socket_path,
                        "--audio",
                        audio,
                        "--output",
                        output,
                    )
                    self.assertTrue(json.loads(output.read_text())["detected"])

                self.assertEqual(loads.read_text().splitlines(), ["loaded"])
            finally:
                worker.terminate()
                worker.wait(timeout=5)

    def test_needle_output_is_parsed_into_a_typed_consumption_report(self) -> None:
        report = parse_consumption_report(
            {
                "foods": [
                    {"food": "white rice cooked", "quantity": 0.75, "measure": "cup"},
                    {"food": "egg", "quantity": 2, "measure": "large"},
                ],
                "confidence": 0.9,
            }
        )

        self.assertEqual([item.food for item in report.items], ["white rice cooked", "egg"])
        self.assertEqual([item.quantity for item in report.items], [0.75, 2.0])
        self.assertEqual([item.measure for item in report.items], ["cup", "large"])

    def test_malformed_needle_output_is_rejected(self) -> None:
        cases: dict[str, object] = {
            "non-object report": [],
            "unknown top-level shape": {"foods": [], "confidence": 1, "transcript": "private"},
            "empty report": {"foods": [], "confidence": 1},
            "low confidence": {
                "foods": [{"food": "egg", "quantity": 1, "measure": "large"}],
                "confidence": 0.5,
            },
            "blank food": {
                "foods": [{"food": " ", "quantity": 1, "measure": "gram"}],
                "confidence": 1,
            },
            "missing quantity": {
                "foods": [{"food": "egg", "measure": "large"}],
                "confidence": 1,
            },
            "nonnumeric quantity": {
                "foods": [{"food": "egg", "quantity": "one", "measure": "large"}],
                "confidence": 1,
            },
            "zero quantity": {
                "foods": [{"food": "egg", "quantity": 0, "measure": "large"}],
                "confidence": 1,
            },
            "negative quantity": {
                "foods": [{"food": "egg", "quantity": -1, "measure": "large"}],
                "confidence": 1,
            },
            "nan quantity": {
                "foods": [{"food": "egg", "quantity": float("nan"), "measure": "large"}],
                "confidence": 1,
            },
            "infinite quantity": {
                "foods": [{"food": "egg", "quantity": float("inf"), "measure": "large"}],
                "confidence": 1,
            },
            "missing measure": {
                "foods": [{"food": "egg", "quantity": 1}],
                "confidence": 1,
            },
            "blank measure": {
                "foods": [{"food": "egg", "quantity": 1, "measure": " "}],
                "confidence": 1,
            },
            "unknown item field": {
                "foods": [{"food": "egg", "quantity": 1, "measure": "large", "fdc_id": 1}],
                "confidence": 1,
            },
        }
        for name, value in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ExtractionError, ".+"):
                parse_consumption_report(value)

    def test_extract_adapter_does_not_write_malformed_needle_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            modules = root / "modules"
            modules.mkdir()
            (modules / "needle.py").write_text(
                "class Needle:\n"
                "    def __init__(self, tools, weights=None): pass\n"
                "    def complete(self, text):\n"
                "        return {'confidence': 1, 'function_calls': "
                "[{'arguments': {'foods': [{'food': 'egg', 'quantity': 1}]}}]}\n",
                encoding="utf-8",
            )
            transcript = root / "transcript.txt"
            transcript.write_text("I ate one egg", encoding="utf-8")
            extraction = root / "extraction.json"
            environment = os.environ | {"PYTHONPATH": f"{modules}{os.pathsep}{os.getcwd()}"}

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "snack_gpt.voice_adapters",
                    "extract",
                    "--transcript",
                    str(transcript),
                    "--output",
                    str(extraction),
                ],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("food, quantity, and measure", result.stderr)
            self.assertFalse(extraction.exists())

    def test_adapters_normalize_runtime_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            modules = root / "modules"
            (modules / "openwakeword").mkdir(parents=True)
            (modules / "openwakeword" / "__init__.py").write_text("", encoding="utf-8")
            (modules / "openwakeword" / "model.py").write_text(
                textwrap.dedent(
                    """
                    from fractions import Fraction

                    class Model:
                        def __init__(self, **kwargs):
                            pass

                        def predict_clip(self, path):
                            return [{"hey_jarvis_v0.1": Fraction(1, 5)}, {"hey_jarvis_v0.1": Fraction(4, 5)}]
                    """
                ),
                encoding="utf-8",
            )
            (modules / "needle.py").write_text(
                "class Needle:\n"
                "    def __init__(self, tools, weights=None):\n"
                "        schema = tools[0]\n"
                "        assert schema['name'] == 'log_food_intake'\n"
                "        item = schema['parameters']['properties']['foods']['items']\n"
                "        assert item['required'] == ['food', 'quantity', 'measure']\n"
                "        assert item['properties']['quantity']['exclusiveMinimum'] == 0\n"
                "        assert schema['parameters']['required'] == ['foods']\n"
                "        assert 'confidence' not in schema['parameters']['properties']\n"
                "    def complete(self, text):\n"
                "        return {'confidence': 0.9, 'function_calls': "
                "[{'arguments': {'foods': [{'food': 'white rice cooked', "
                "'quantity': 0.75, 'measure': 'cup'}]}}]}\n",
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
                        assert arguments[arguments.index("-ac") + 1] == "512"
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
                "--binary-argument=-ac",
                "--binary-argument=512",
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
            self.assertEqual(
                json.loads(extraction.read_text())["foods"][0],
                {"food": "white rice cooked", "quantity": 0.75, "measure": "cup"},
            )

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
                            output.setparams((1, 1, 16000, 0, "NONE", "not compressed"))
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
                extraction.write_text(
                    '{"foods":[{"food":"egg","quantity":2,"measure":"large"}],"confidence":1}',
                    encoding="utf-8",
                )
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

                with wave.open(str(speech), "rb") as output:
                    self.assertEqual(output.readframes(output.getnframes()), b"Recorded 2 large egg.")

                direct_speech = root / "direct-speech.wav"
                self._run_adapter(
                    environment,
                    "synthesize",
                    "--socket",
                    socket_path,
                    "--text",
                    "Processing took too long.",
                    "--output",
                    direct_speech,
                )

                with wave.open(str(direct_speech), "rb") as output:
                    self.assertEqual(
                        output.readframes(output.getnframes()),
                        b"Processing took too long.",
                    )
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

    def test_provisioning_script_reuses_matching_whisper_build(self) -> None:
        script = Path("scripts/provision-voice-probe.sh").read_text(encoding="utf-8")

        self.assertNotIn('rm -rf "$VENV" "$SOURCE/whisper.cpp"', script)
        self.assertIn('WHISPER_BUILD_COMMIT=$BIN/whisper-cli.commit', script)
        self.assertIn('$SOURCE/whisper.cpp/models/download-ggml-model.sh', script)
        self.assertIn('cmp --silent "$BIN/whisper-cli"', script)
        self.assertIn('Reusing whisper.cpp $WHISPER_TAG build.', script)

    def test_pi_manifest_uses_benchmarked_whisper_audio_context(self) -> None:
        manifest = json.loads(Path("docs/voice-probe.pi.json").read_text(encoding="utf-8"))

        transcription = manifest["commands"]["transcription"]
        self.assertIn("--binary-argument=-ac", transcription)
        self.assertIn("--binary-argument=512", transcription)

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
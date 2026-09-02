import os
from io import StringIO
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from snack_gpt import voice_audio


class VoiceAudioTests(unittest.TestCase):
    def test_capture_uses_system_default_microphone(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "snack_gpt.voice_audio.subprocess.run"
        ) as run_command:
            result = voice_audio.main(
                ["capture", "--mode", "wake", "--output", "wake.wav"]
            )

        self.assertEqual(result, 0)
        command = run_command.call_args.args[0]
        self.assertEqual(command[0], "rec")
        self.assertNotIn("AUDIODEV", run_command.call_args.kwargs["env"])
        self.assertIn("wake.wav", command)

    def test_audio_device_overrides_are_forwarded_to_sox(self) -> None:
        environment = {
            "SNACK_GPT_MICROPHONE": "hw:2,0",
            "SNACK_GPT_SPEAKER": "hw:3,0",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "snack_gpt.voice_audio.subprocess.run"
        ) as run_command:
            capture_result = voice_audio.main(
                [
                    "capture",
                    "--mode",
                    "speech",
                    "--silence-seconds",
                    "1.25",
                    "--output",
                    "report.wav",
                ]
            )
            capture_command = run_command.call_args.args[0]
            capture_environment = run_command.call_args.kwargs["env"]
            play_result = voice_audio.main(["play", "report.wav"])
            play_command = run_command.call_args.args[0]
            play_environment = run_command.call_args.kwargs["env"]

        self.assertEqual(capture_result, 0)
        self.assertEqual(play_result, 0)
        self.assertEqual(capture_environment["AUDIODEV"], "hw:2,0")
        self.assertIn("1.25", capture_command)
        self.assertEqual(play_command, ["play", "--no-show-progress", "report.wav"])
        self.assertEqual(play_environment["AUDIODEV"], "hw:3,0")

    def test_audio_failure_does_not_echo_command_details(self) -> None:
        stderr = StringIO()
        with patch(
            "snack_gpt.voice_audio.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["play", "private.wav"]),
        ), patch("sys.stderr", stderr):
            result = voice_audio.main(["play", str(Path("private.wav"))])

        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "Audio device command failed.\n")


if __name__ == "__main__":
    unittest.main()
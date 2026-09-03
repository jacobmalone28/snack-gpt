import os
from io import StringIO
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from snack_gpt import voice_audio


class VoiceAudioTests(unittest.TestCase):
    def test_wake_and_fallback_tones_are_long_enough_to_hear(self) -> None:
        with patch("snack_gpt.voice_audio.subprocess.run") as run_command:
            wake_result = voice_audio.main(["tone", "wake"])
            wake_command = run_command.call_args.args[0]
            success_result = voice_audio.main(["tone", "success"])
            success_command = run_command.call_args.args[0]

        self.assertEqual(wake_result, 0)
        self.assertEqual(success_result, 0)
        self.assertIn("0.35", wake_command)
        self.assertIn("0.25", success_command)

    def test_capture_uses_system_default_microphone(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "snack_gpt.voice_audio.subprocess.run"
        ) as run_command:
            result = voice_audio.main(
                ["capture", "--mode", "wake", "--output", "wake.wav"]
            )

        self.assertEqual(result, 0)
        self.assertEqual(run_command.call_count, 2)
        capture_call, conversion_call = run_command.call_args_list
        self.assertEqual(capture_call.args[0][0], "rec")
        self.assertEqual(capture_call.args[0][-3:], ["trim", "0", "5"])
        self.assertNotIn("--rate", capture_call.args[0])
        self.assertNotIn("AUDIODEV", capture_call.kwargs["env"])
        self.assertEqual(conversion_call.args[0][0], "sox")
        self.assertEqual(
            conversion_call.args[0][-7:],
            ["--channels", "1", "--rate", "16000", "--bits", "16", "wake.wav"],
        )

    def test_audio_device_overrides_are_forwarded_to_sox(self) -> None:
        environment = {
            "SNACK_GPT_MICROPHONE": "hw:2,0",
            "SNACK_GPT_SPEAKER": "hw:3,0",
            "USDA_FDC_API_KEY": "private-key",
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
            capture_calls = run_command.call_args_list
            capture_command = capture_calls[0].args[0]
            capture_environment = capture_calls[0].kwargs["env"]
            play_result = voice_audio.main(["play", "report.wav"])
            play_command = run_command.call_args.args[0]
            play_environment = run_command.call_args.kwargs["env"]

        self.assertEqual(capture_result, 0)
        self.assertEqual(play_result, 0)
        self.assertEqual(capture_environment["AUDIODEV"], "hw:2,0")
        self.assertEqual(capture_environment["AUDIODRIVER"], "alsa")
        self.assertNotIn("USDA_FDC_API_KEY", capture_environment)
        self.assertIn("1.25", capture_command)
        self.assertEqual(play_command, ["play", "--no-show-progress", "report.wav"])
        self.assertEqual(play_environment["AUDIODEV"], "hw:3,0")
        self.assertEqual(play_environment["AUDIODRIVER"], "alsa")
        self.assertNotIn("USDA_FDC_API_KEY", play_environment)

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
from pathlib import Path
from io import StringIO
import os
import subprocess
import tempfile
import unittest
from unittest.mock import call, patch

from snack_gpt.appliance import AppliancePaths, start


class ApplianceTests(unittest.TestCase):
    def test_start_checks_audio_before_enabling_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment_path = root / "environment"
            environment_path.write_text(
                "USDA_FDC_API_KEY=test-key\n"
                "SNACK_GPT_MICROPHONE=hw:2,0\n"
                "SNACK_GPT_SPEAKER=hw:3,0\n",
                encoding="utf-8",
            )
            audio_command = root / "voice-audio"
            audio_command.touch()
            paths = AppliancePaths(environment_path, audio_command)

            stdout = StringIO()
            with patch.dict(os.environ, {"USDA_FDC_API_KEY": "parent-key"}), patch(
                "snack_gpt.appliance.subprocess.run"
            ) as run_command, patch("sys.stdout", stdout):
                result = start(paths=paths, elevated_command=("sudo",))

        self.assertEqual(result, 0)
        self.assertEqual(run_command.call_count, 2)
        audio_call, systemctl_call = run_command.call_args_list
        self.assertEqual(audio_call.args[0], [str(audio_command), "check"])
        self.assertEqual(audio_call.kwargs["env"]["SNACK_GPT_MICROPHONE"], "hw:2,0")
        self.assertNotIn("USDA_FDC_API_KEY", audio_call.kwargs["env"])
        self.assertIn("http://127.0.0.1:8000/", stdout.getvalue())
        self.assertEqual(
            systemctl_call,
            call(
                [
                    "sudo",
                    "systemctl",
                    "enable",
                    "--now",
                    "snack-gpt-web.service",
                    "snack-gpt-wake.service",
                    "snack-gpt-piper.service",
                    "snack-gpt-listener.service",
                ],
                check=True,
            ),
        )

    def test_start_does_not_enable_services_when_audio_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment_path = root / "environment"
            environment_path.write_text("USDA_FDC_API_KEY=test-key\n", encoding="utf-8")
            audio_command = root / "voice-audio"
            audio_command.touch()
            paths = AppliancePaths(environment_path, audio_command)

            with patch(
                "snack_gpt.appliance.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, [str(audio_command), "check"]),
            ) as run_command:
                result = start(paths=paths, elevated_command=("sudo",))

        self.assertEqual(result, 1)
        run_command.assert_called_once()

    def test_start_requires_usda_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment_path = root / "environment"
            environment_path.write_text("SNACK_GPT_PORT=8000\n", encoding="utf-8")
            audio_command = root / "voice-audio"
            audio_command.touch()

            with patch.dict(
                os.environ, {"USDA_FDC_API_KEY": "shell-only-key"}
            ), patch("snack_gpt.appliance.subprocess.run") as run_command:
                result = start(
                    paths=AppliancePaths(environment_path, audio_command),
                    elevated_command=("sudo",),
                )

        self.assertEqual(result, 2)
        run_command.assert_not_called()

    def test_start_reports_configured_address(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment_path = root / "environment"
            environment_path.write_text(
                "USDA_FDC_API_KEY=test-key\n"
                "SNACK_GPT_HOST=192.168.1.8\n"
                "SNACK_GPT_PORT=8123\n",
                encoding="utf-8",
            )
            audio_command = root / "voice-audio"
            audio_command.touch()
            stdout = StringIO()

            with patch("snack_gpt.appliance.subprocess.run"), patch("sys.stdout", stdout):
                result = start(
                    paths=AppliancePaths(environment_path, audio_command),
                    elevated_command=("sudo",),
                )

        self.assertEqual(result, 0)
        self.assertIn("http://192.168.1.8:8123/", stdout.getvalue())

    def test_start_fails_gracefully_without_posix_user_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment_path = root / "environment"
            environment_path.write_text("USDA_FDC_API_KEY=test-key\n", encoding="utf-8")
            audio_command = root / "voice-audio"
            audio_command.touch()
            stderr = StringIO()

            with patch("snack_gpt.appliance.os.geteuid", None), patch(
                "snack_gpt.appliance.subprocess.run"
            ) as run_command, patch("sys.stderr", stderr):
                result = start(paths=AppliancePaths(environment_path, audio_command))

        self.assertEqual(result, 2)
        self.assertIn("systemd appliance", stderr.getvalue())
        run_command.assert_not_called()
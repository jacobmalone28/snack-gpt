from pathlib import Path
import subprocess
import unittest


class AppliancePackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]
        self.provisioner = self.root / "scripts" / "provision-voice-probe.sh"

    def test_provisioner_installs_disabled_systemd_services(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(self.provisioner)],
            capture_output=True,
            check=False,
            text=True,
        )
        source = self.provisioner.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("snack-gpt-web.service", source)
        self.assertIn("snack-gpt-listener.service", source)
        self.assertIn("ExecStartPost=/bin/sh", source)
        self.assertIn("RestartPreventExitStatus=2", source)
        self.assertIn('id "$SERVICE_USER"', source)
        self.assertIn('install -d -m 0700 "$STATE_DIRECTORY"', source)
        self.assertIn("systemctl disable", source)
        self.assertNotIn("systemctl enable --now", source)

    def test_provisioner_generates_runtime_manifest_with_audio_overrides(self) -> None:
        source = self.provisioner.read_text(encoding="utf-8")

        self.assertIn("SNACK_GPT_MICROPHONE=$CAPTURE_DEVICE", source)
        self.assertIn("SNACK_GPT_SPEAKER=$PLAYBACK_DEVICE", source)
        self.assertIn("--playback-device", source)
        self.assertIn("aplay --list-devices", source)
        self.assertIn("-m snack_gpt.voice_audio", source)
        self.assertIn('"memory_directory": "/dev/shm"', source)
        self.assertIn('"wake_capture"', source)
        self.assertIn('"play_speech"', source)

    def test_provisioner_installs_application_runtime_dependencies(self) -> None:
        source = self.provisioner.read_text(encoding="utf-8")

        self.assertIn('"${PIP[@]}" install "$REPOSITORY_ROOT"', source)
        self.assertNotIn('"${PIP[@]}" install --no-deps "$REPOSITORY_ROOT"', source)
        self.assertIn('"openwakeword==$OPENWAKEWORD_VERSION"', source)

    def test_platform_guide_covers_every_supported_target(self) -> None:
        guide = (self.root / "docs" / "installation.md").read_text(encoding="utf-8")

        for target in (
            "Linux ARM64",
            "Linux x86-64",
            "macOS ARM64",
            "macOS x86-64",
            "Windows x86-64",
        ):
            with self.subTest(target=target):
                self.assertIn(target, guide)
        self.assertIn("SNACK_GPT_MICROPHONE", guide)
        self.assertIn("SNACK_GPT_SPEAKER", guide)

    def test_acceptance_guide_covers_appliance_and_evidence(self) -> None:
        guide = (self.root / "docs" / "raspberry-pi-acceptance.md").read_text(
            encoding="utf-8"
        )

        for requirement in (
            "wake reliability",
            "voice creation",
            "weekly history",
            "correction",
            "backup",
            "authentication",
            "degraded states",
            "restart persistence",
            "peak memory",
            "transcription quality",
            "stage latency",
            "15 seconds",
            "30 seconds",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, guide.lower())

    def test_license_guide_names_runtime_and_model_constraints(self) -> None:
        guide = (self.root / "docs" / "installation.md").read_text(encoding="utf-8")

        self.assertIn("CC BY-NC-SA 4.0", guide)
        self.assertIn("GPL-3.0-or-later", guide)
        self.assertIn("en_US-lessac-low", guide)

    def test_package_exposes_simple_start_command(self) -> None:
        configuration = (self.root / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('snackgpt = "snack_gpt.__main__:main"', configuration)


if __name__ == "__main__":
    unittest.main()
import subprocess
import unittest

from apps.dls.backend.pages.local_camera import get_local_camera_status


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["rpicam-hello"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class LocalCameraStatusTests(unittest.TestCase):
    def test_no_camera_tools_installed(self):
        status = get_local_camera_status(which=lambda _command: None)

        self.assertFalse(status["configured"])
        self.assertFalse(status["cameraAttached"])
        self.assertFalse(status["signalPresent"])
        self.assertEqual(status["method"], "unavailable")
        self.assertIn("installed", status["error"])

    def test_camera_attached_but_signal_probe_fails(self):
        calls = []

        def run_command(args, _timeout):
            calls.append(args)
            if "--list-cameras" in args:
                return completed(stdout="Available cameras\n-----------------\n0 : imx708 [4608x2592]")
            return completed(returncode=1, stderr="failed to start camera")

        status = get_local_camera_status(
            which=lambda command: f"/usr/bin/{command}" if command == "rpicam-hello" else None,
            run_command=run_command,
        )

        self.assertTrue(status["configured"])
        self.assertTrue(status["cameraAttached"])
        self.assertFalse(status["signalPresent"])
        self.assertIn("failed", status["error"])
        self.assertEqual(len(calls), 2)

    def test_camera_attached_and_signal_probe_succeeds(self):
        def run_command(args, _timeout):
            if "--list-cameras" in args:
                return completed(stdout="Available cameras\n-----------------\n0 : imx708 [4608x2592]")
            return completed(returncode=0, stdout="ok")

        status = get_local_camera_status(
            which=lambda command: f"/usr/bin/{command}" if command == "rpicam-hello" else None,
            run_command=run_command,
        )

        self.assertTrue(status["configured"])
        self.assertTrue(status["cameraAttached"])
        self.assertTrue(status["signalPresent"])
        self.assertIsNone(status["error"])

    def test_subprocess_timeout_is_non_fatal(self):
        def run_command(_args, timeout):
            raise subprocess.TimeoutExpired(cmd="rpicam-hello", timeout=timeout)

        status = get_local_camera_status(
            which=lambda command: f"/usr/bin/{command}" if command == "rpicam-hello" else None,
            run_command=run_command,
        )

        self.assertTrue(status["configured"])
        self.assertFalse(status["cameraAttached"])
        self.assertFalse(status["signalPresent"])
        self.assertIn("timed out", status["error"])


if __name__ == "__main__":
    unittest.main()

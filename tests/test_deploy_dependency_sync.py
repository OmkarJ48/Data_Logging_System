import unittest
from pathlib import Path

from apps.central_hub.backend.pages import deploy


class DeployDependencySyncTests(unittest.TestCase):
    def test_git_update_payload_defaults_to_https_for_github_fetch(self):
        payload = deploy._build_git_update_payload()

        self.assertEqual(
            deploy.RND_REPO_ORIGIN, "https://github.com/tlelean/RnD.git"
        )
        self.assertTrue(deploy._repo_origin_uses_https())
        self.assertIn("origin_url=https://github.com/tlelean/RnD.git", payload)
        self.assertIn("git -c credential.helper=store fetch origin main", payload)
        self.assertIn("chown -R \"$repo_user:$repo_group\" .git", payload)

    def test_git_credentials_path_matches_root_credential_store(self):
        self.assertEqual(deploy.GIT_CREDENTIALS_PATH, "/root/.git-credentials")

    def test_git_update_payload_keeps_ssh_key_support_for_ssh_origins(self):
        payload = deploy._build_git_update_payload()

        self.assertIn("case \"$origin_url\" in git@*|ssh://*)", payload)
        self.assertIn("GIT_SSH_COMMAND", payload)
        self.assertIn("IdentitiesOnly=yes", payload)
        self.assertIn(deploy.RND_REPO_SSH_KEY_PATH, payload)

    def test_dependency_sync_installs_requirements_and_pi_camera_packages(self):
        payload = deploy._build_dependency_sync_payload()

        self.assertIn("apps/dls/deploy/sync_dependencies.sh", payload)
        self.assertIn("visualisation.service", payload)
        self.assertIn(deploy.RND_REPO_PATH, payload)
        self.assertIn("python3-numpy", payload)
        self.assertIn("numpy<2", payload)
        self.assertIn("opencv-python", payload)

    def test_sync_script_installs_and_validates_pi_camera_dependencies(self):
        script = Path("apps/dls/deploy/sync_dependencies.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("requirements.txt", script)
        self.assertIn("pip install", script)
        self.assertIn("python3-numpy", script)
        self.assertIn("python3-opencv", script)
        self.assertIn("python3-picamera2", script)
        self.assertIn("numpy<2", script)
        self.assertIn("opencv-python", script)
        self.assertIn("systemctl show", script)
        self.assertIn("import cv2", script)
        self.assertIn("import picamera2", script)
        self.assertIn("/usr/lib/python3/dist-packages", script)


if __name__ == "__main__":
    unittest.main()

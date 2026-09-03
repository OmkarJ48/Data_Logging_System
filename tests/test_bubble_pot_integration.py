import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class BubblePotIntegrationTests(unittest.TestCase):
    def test_dls_app_imports_without_pi_camera_dependencies(self):
        from apps.dls.backend.main import app

        self.assertIsNotNone(app)

    def test_bubble_pot_detector_uses_native_module_path(self):
        from apps.dls.backend.bubble_pot import routes as bubble_pot

        self.assertEqual(
            bubble_pot._load_detector_module.__globals__["__name__"],
            "apps.dls.backend.bubble_pot.routes",
        )
        self.assertIn(
            "apps.dls.backend.bubble_pot.detector",
            bubble_pot._load_detector_module.__code__.co_consts,
        )

    def test_bubble_pot_detector_module_has_no_standalone_fastapi_app(self):
        detector_source = Path("apps/dls/backend/bubble_pot/detector.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("FastAPI(", detector_source)
        self.assertNotIn("StaticFiles(", detector_source)
        self.assertNotIn("uvicorn", detector_source)

    def test_bubble_pot_status_returns_clear_unavailable_payload(self):
        from apps.dls.backend.main import app
        from apps.dls.backend.bubble_pot import routes as bubble_pot

        bubble_pot._module = None
        bubble_pot._detector = None
        bubble_pot._startup_error = None

        with patch.object(
            bubble_pot,
            "_load_detector_module",
            side_effect=ImportError("No module named 'picamera2'"),
        ):
            response = TestClient(app).get("/api/bubble-pot/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["workflow"]["state"], "unavailable")
        self.assertIn("Picamera2 is not installed", payload["camera_error"])

        bubble_pot._module = None
        bubble_pot._detector = None
        bubble_pot._startup_error = None

    def test_bubble_pot_status_explains_missing_opencv(self):
        from apps.dls.backend.main import app
        from apps.dls.backend.bubble_pot import routes as bubble_pot

        bubble_pot._module = None
        bubble_pot._detector = None
        bubble_pot._startup_error = None

        with patch.object(
            bubble_pot,
            "_load_detector_module",
            side_effect=ImportError("No module named 'cv2'"),
        ):
            response = TestClient(app).get("/api/bubble-pot/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["available"])
        self.assertIn("OpenCV is not installed", payload["camera_error"])
        self.assertIn("Git Pull + Dependencies", payload["camera_error"])

        bubble_pot._module = None
        bubble_pot._detector = None
        bubble_pot._startup_error = None

    def test_bubble_pot_start_failure_reports_camera_error(self):
        from apps.dls.backend.main import app
        from apps.dls.backend.bubble_pot import routes as bubble_pot

        class FakeDetector:
            _running = False
            camera_error = "Camera is busy"

            def start(self):
                return False

        bubble_pot._module = None
        bubble_pot._detector = FakeDetector()
        bubble_pot._startup_error = None

        response = TestClient(app).get("/api/bubble-pot/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["available"])
        self.assertIn("Camera is busy", payload["camera_error"])

        bubble_pot._module = None
        bubble_pot._detector = None
        bubble_pot._startup_error = None

    def test_central_hub_uses_direct_rig_bubble_pot_url(self):
        overview = Path("apps/central_hub/frontend/pages/rig_overview.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("http://${ip}:9000/pages/bubble_pot.html", overview)
        self.assertNotIn("/pages/bubble_detection.html", overview)


if __name__ == "__main__":
    unittest.main()

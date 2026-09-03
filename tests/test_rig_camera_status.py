import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from apps.central_hub.backend.pages.rig_status import RigCameraStatusPoller, RigOverviewStatusService


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise requests.HTTPError("HTTP 502")

    def json(self):
        return self._payload


class RigCameraStatusPollerTests(unittest.TestCase):
    def test_successful_camera_response(self):
        poller = RigCameraStatusPoller({"id": "fat_rig_1", "label": "F.A.T. Rig 1", "ip": "10.1.6.10"})

        with patch(
            "apps.central_hub.backend.pages.rig_status.requests.get",
            return_value=FakeResponse(
                {
                    "configured": True,
                    "cameraAttached": True,
                    "signalPresent": True,
                    "checkedAt": "2026-05-28T12:00:00+00:00",
                    "error": None,
                }
            ),
        ):
            poller._poll_once()

        result = poller.get_result()
        self.assertTrue(result["cameraConfigured"])
        self.assertTrue(result["cameraAttached"])
        self.assertTrue(result["cameraSignalPresent"])
        self.assertIsNone(result["cameraError"])
        self.assertEqual(result["cameraCheckedAt"], "2026-05-28T12:00:00+00:00")

    def test_offline_camera_endpoint_timeout(self):
        poller = RigCameraStatusPoller({"id": "fat_rig_1", "label": "F.A.T. Rig 1", "ip": "10.1.6.10"})

        with patch(
            "apps.central_hub.backend.pages.rig_status.requests.get",
            side_effect=requests.Timeout("timed out"),
        ):
            poller._poll_once()

        result = poller.get_result()
        self.assertFalse(result["cameraConfigured"])
        self.assertFalse(result["cameraAttached"])
        self.assertFalse(result["cameraSignalPresent"])
        self.assertIn("timed out", result["cameraError"])

    def test_malformed_camera_response(self):
        poller = RigCameraStatusPoller({"id": "fat_rig_1", "label": "F.A.T. Rig 1", "ip": "10.1.6.10"})

        with patch(
            "apps.central_hub.backend.pages.rig_status.requests.get",
            return_value=FakeResponse(["not", "an", "object"]),
        ):
            poller._poll_once()

        result = poller.get_result()
        self.assertFalse(result["cameraConfigured"])
        self.assertFalse(result["cameraAttached"])
        self.assertFalse(result["cameraSignalPresent"])
        self.assertIn("not an object", result["cameraError"])

    def test_snapshot_merges_camera_fields_without_removing_opc_fields(self):
        service = RigOverviewStatusService()
        service._started = True
        service._pollers = {
            "fat_rig_1": SimpleNamespace(
                get_result=lambda: {
                    "id": "fat_rig_1",
                    "label": "F.A.T. Rig 1",
                    "online": True,
                    "hasData": True,
                    "rigName": "FAT 1",
                }
            )
        }
        service._camera_pollers = {
            "fat_rig_1": SimpleNamespace(
                get_result=lambda: {
                    "cameraConfigured": True,
                    "cameraAttached": True,
                    "cameraSignalPresent": True,
                    "cameraError": None,
                    "cameraCheckedAt": "2026-05-28T12:00:00+00:00",
                }
            )
        }

        with patch(
            "apps.central_hub.backend.pages.rig_status.RIG_TARGETS",
            [{"id": "fat_rig_1", "label": "F.A.T. Rig 1", "ip": "10.1.6.10"}],
        ):
            snapshot = service.get_snapshot()

        rig = snapshot["rigs"][0]
        self.assertEqual(rig["rigName"], "FAT 1")
        self.assertTrue(rig["online"])
        self.assertTrue(rig["cameraSignalPresent"])
        self.assertIsNone(rig["cameraError"])


if __name__ == "__main__":
    unittest.main()

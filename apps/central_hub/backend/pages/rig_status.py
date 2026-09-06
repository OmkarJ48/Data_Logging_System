from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from threading import Event, RLock, Thread
from typing import Any

import requests
from fastapi import APIRouter, Request
from opcua import Client
from opcua.ua import ExtensionObject

from apps.central_hub.backend.config import (
    RIG_OPC_ENDPOINTS,
    RIG_OVERVIEW_FIELDS,
    RIG_OVERVIEW_NODE_IDS,
    RIG_TARGETS,
)
from .deploy import is_request_ip_allowed

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_ERROR_CHARS = 240
_OPC_TIMEOUT_SECONDS = 1.0
_ONLINE_POLL_INTERVAL_SECONDS = 1.0
_OFFLINE_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)
_CAMERA_STATUS_PORT = 9000
_CAMERA_STATUS_PATH = "/api/local-camera/status"
_CAMERA_POLL_INTERVAL_SECONDS = 5.0
_CAMERA_CONNECT_TIMEOUT_SECONDS = 0.75
_CAMERA_READ_TIMEOUT_SECONDS = 1.5
_CONNECTION_ERROR_HINTS = (
    "connection",
    "socket",
    "session",
    "timeout",
    "timed out",
    "closed",
    "eof",
    "broken pipe",
    "reset by peer",
    "transport",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class RigOpcClient:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self._lock = RLock()
        self._client: Client | None = None
        self._node_cache: dict[str, Any] = {}

    @staticmethod
    def _normalise_value(value: Any) -> Any:
        if hasattr(value, "Value"):
            value = value.Value
        if isinstance(value, ExtensionObject) and getattr(value, "Body", None) is not None:
            value = value.Body
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="ignore")
            except Exception:
                return str(value)
        if isinstance(value, (list, tuple)):
            return [RigOpcClient._normalise_value(v) for v in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def _format_error(exc: Exception | None) -> str | None:
        if exc is None:
            return None
        text = str(exc).strip()
        if not text:
            text = exc.__class__.__name__
        return text[:_MAX_ERROR_CHARS]

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
            return True

        text = f"{exc.__class__.__name__}: {exc}".lower()
        return any(hint in text for hint in _CONNECTION_ERROR_HINTS)

    @classmethod
    def _format_field_errors(cls, field_errors: list[tuple[str, Exception]]) -> str | None:
        if not field_errors:
            return None
        parts = [f"{field}: {cls._format_error(exc)}" for field, exc in field_errors]
        return "; ".join(parts)[:_MAX_ERROR_CHARS]

    def _disconnect_locked(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._node_cache.clear()

    def _connect_locked(self) -> None:
        self._disconnect_locked()
        client = Client(self.endpoint, timeout=_OPC_TIMEOUT_SECONDS)
        client.session_timeout = 15000
        client.connect()
        self._client = client
        self._node_cache.clear()

    def close(self) -> None:
        with self._lock:
            self._disconnect_locked()

    def _read_configured_fields_locked(
        self,
        configured: dict[str, str],
    ) -> tuple[dict[str, Any], int, list[tuple[str, Exception]], bool]:
        assert self._client is not None

        values = {field: None for field in RIG_OVERVIEW_FIELDS}
        success_count = 0
        field_errors: list[tuple[str, Exception]] = []
        connection_failed = False

        for field, node_id in configured.items():
            try:
                node = self._node_cache.get(node_id)
                if node is None:
                    node = self._client.get_node(node_id)
                    self._node_cache[node_id] = node
                values[field] = self._normalise_value(node.get_value())
                success_count += 1
            except Exception as exc:
                field_errors.append((field, exc))
                if success_count == 0 and self._is_connection_error(exc):
                    connection_failed = True
                    break

        return values, success_count, field_errors, connection_failed

    def read_fields(self, node_ids: dict[str, str | None]) -> tuple[bool, bool, dict[str, Any], str | None]:
        empty_values = {field: None for field in RIG_OVERVIEW_FIELDS}
        configured = {
            field: node_id
            for field, node_id in node_ids.items()
            if isinstance(node_id, str) and node_id.strip()
        }
        if not configured:
            return False, False, empty_values, None

        with self._lock:
            try:
                if self._client is None:
                    self._connect_locked()
            except Exception as exc:
                self._disconnect_locked()
                return False, False, empty_values, self._format_error(exc)

            values, success_count, field_errors, connection_failed = self._read_configured_fields_locked(configured)

            if connection_failed:
                try:
                    self._connect_locked()
                    values, success_count, field_errors, connection_failed = self._read_configured_fields_locked(configured)
                except Exception as exc:
                    self._disconnect_locked()
                    return False, False, empty_values, self._format_error(exc)

            if connection_failed:
                self._disconnect_locked()
                return False, False, empty_values, self._format_field_errors(field_errors)

            if any(self._is_connection_error(exc) for _, exc in field_errors):
                self._disconnect_locked()

            has_data = success_count > 0
            return True, has_data, values, self._format_field_errors(field_errors)


class RigStatusPoller:
    def __init__(
        self,
        target: dict[str, Any],
        endpoint: str | None,
        node_ids: dict[str, str | None],
    ):
        self._target = dict(target)
        self._endpoint = endpoint
        self._node_ids = dict(node_ids)
        self._configured = any(isinstance(v, str) and v.strip() for v in node_ids.values())
        self._client = RigOpcClient(endpoint) if endpoint and self._configured else None
        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._failure_count = 0
        self._last_success_at: datetime | None = None
        self._result = self._base_result(
            connection_state="unknown" if self._client is not None else "unconfigured",
            online=False,
            has_data=False,
            error=None,
            values=None,
            last_attempt_at=None,
            last_success_at=None,
            next_retry_at=None,
        )

    @staticmethod
    def _empty_values() -> dict[str, Any]:
        return {field: None for field in RIG_OVERVIEW_FIELDS}

    @staticmethod
    def _retry_delay_for_failure_count(failure_count: int) -> float:
        index = min(max(failure_count, 0), len(_OFFLINE_RETRY_DELAYS_SECONDS) - 1)
        return _OFFLINE_RETRY_DELAYS_SECONDS[index]

    def _base_result(
        self,
        *,
        connection_state: str,
        online: bool,
        has_data: bool,
        error: str | None,
        values: dict[str, Any] | None,
        last_attempt_at: datetime | None,
        last_success_at: datetime | None,
        next_retry_at: datetime | None,
    ) -> dict[str, Any]:
        payload_values = self._empty_values()
        if values:
            payload_values.update(values)

        return {
            "id": self._target["id"],
            "label": self._target["label"],
            "ip": self._target.get("ip"),
            "configured": self._configured,
            "connectionState": connection_state,
            "online": online,
            "hasData": has_data,
            "error": error,
            "lastAttemptAt": _iso_or_none(last_attempt_at),
            "lastSuccessAt": _iso_or_none(last_success_at),
            "nextRetryAt": _iso_or_none(next_retry_at),
            **payload_values,
        }

    def _set_result_locked(self, result: dict[str, Any]) -> None:
        previous_state = self._result.get("connectionState")
        next_state = result.get("connectionState")
        if previous_state != next_state:
            logger.info(
                "Rig status %s changed %s -> %s",
                self._target["id"],
                previous_state,
                next_state,
            )
        self._result = result

    def start(self) -> None:
        if self._client is None:
            return

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run,
                name=f"rig-status-{self._target['id']}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop_event.set()

        if thread is not None:
            thread.join(timeout=2.0)

        if self._client is not None:
            self._client.close()

    def get_result(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._result)

    def _poll_once(self) -> float:
        if self._client is None:
            return _ONLINE_POLL_INTERVAL_SECONDS

        now = _utc_now()

        try:
            online, has_data, values, error = self._client.read_fields(self._node_ids)
        except Exception as exc:
            logger.exception("Rig status poll failed unexpectedly for %s", self._target["id"])
            online = False
            has_data = False
            values = self._empty_values()
            error = RigOpcClient._format_error(exc)

        with self._lock:
            if online:
                self._failure_count = 0
                self._last_success_at = now
                self._set_result_locked(
                    self._base_result(
                        connection_state="online",
                        online=True,
                        has_data=has_data,
                        error=error,
                        values=values,
                        last_attempt_at=now,
                        last_success_at=now,
                        next_retry_at=None,
                    )
                )
                return _ONLINE_POLL_INTERVAL_SECONDS

            delay = self._retry_delay_for_failure_count(self._failure_count)
            self._failure_count += 1
            self._set_result_locked(
                self._base_result(
                    connection_state="offline",
                    online=False,
                    has_data=False,
                    error=error or "No OPC connection",
                    values=None,
                    last_attempt_at=now,
                    last_success_at=self._last_success_at,
                    next_retry_at=now + timedelta(seconds=delay),
                )
            )
            return delay

    def _run(self) -> None:
        while not self._stop_event.is_set():
            delay = self._poll_once()
            if self._stop_event.wait(delay):
                break


class RigCameraStatusPoller:
    def __init__(self, target: dict[str, Any]):
        self._target = dict(target)
        self._ip = target.get("ip")
        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._result = self._base_result(
            configured=False,
            attached=False,
            signal_present=False,
            error=None if self._ip else "No rig IP configured",
            checked_at=None,
        )

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return False

    @staticmethod
    def _format_error(exc: Exception | str | None) -> str | None:
        if exc is None:
            return None
        text = str(exc).strip()
        if not text:
            text = exc.__class__.__name__
        return text[:_MAX_ERROR_CHARS]

    def _base_result(
        self,
        *,
        configured: bool,
        attached: bool,
        signal_present: bool,
        error: str | None,
        checked_at: str | None,
    ) -> dict[str, Any]:
        return {
            "cameraConfigured": configured,
            "cameraAttached": attached,
            "cameraSignalPresent": signal_present,
            "cameraError": error,
            "cameraCheckedAt": checked_at,
        }

    def start(self) -> None:
        if not self._ip:
            return

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run,
                name=f"rig-camera-status-{self._target['id']}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop_event.set()

        if thread is not None:
            thread.join(timeout=2.0)

    def get_result(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._result)

    def _set_result_locked(self, result: dict[str, Any]) -> None:
        previous_signal = self._result.get("cameraSignalPresent")
        next_signal = result.get("cameraSignalPresent")
        if previous_signal != next_signal:
            logger.info(
                "Rig camera status %s signal changed %s -> %s",
                self._target["id"],
                previous_signal,
                next_signal,
            )
        self._result = result

    def _status_url(self) -> str:
        return f"http://{self._ip}:{_CAMERA_STATUS_PORT}{_CAMERA_STATUS_PATH}"

    def _poll_once(self) -> None:
        try:
            response = requests.get(
                self._status_url(),
                timeout=(_CAMERA_CONNECT_TIMEOUT_SECONDS, _CAMERA_READ_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Camera status response was not an object")

            result = self._base_result(
                configured=self._coerce_bool(payload.get("configured")),
                attached=self._coerce_bool(payload.get("cameraAttached")),
                signal_present=self._coerce_bool(payload.get("signalPresent")),
                error=self._format_error(payload.get("error")),
                checked_at=payload.get("checkedAt") if isinstance(payload.get("checkedAt"), str) else None,
            )
        except Exception as exc:
            result = self._base_result(
                configured=False,
                attached=False,
                signal_present=False,
                error=self._format_error(exc),
                checked_at=_utc_now().isoformat(),
            )

        with self._lock:
            self._set_result_locked(result)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            if self._stop_event.wait(_CAMERA_POLL_INTERVAL_SECONDS):
                break


class RigOverviewStatusService:
    def __init__(self):
        self._pollers: dict[str, RigStatusPoller] = {}
        self._camera_pollers: dict[str, RigCameraStatusPoller] = {}
        self._lifecycle_lock = RLock()
        self._started = False

        for target in RIG_TARGETS:
            rig_id = target["id"]
            node_ids = self._rig_node_ids(rig_id)
            endpoint = RIG_OPC_ENDPOINTS.get(rig_id)
            self._pollers[rig_id] = RigStatusPoller(target, endpoint, node_ids)
            self._camera_pollers[rig_id] = RigCameraStatusPoller(target)

    @staticmethod
    def _rig_node_ids(rig_id: str) -> dict[str, str | None]:
        source = RIG_OVERVIEW_NODE_IDS.get(rig_id, {})
        return {field: source.get(field) for field in RIG_OVERVIEW_FIELDS}

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._started:
                return
            for poller in self._pollers.values():
                poller.start()
            for poller in self._camera_pollers.values():
                poller.start()
            self._started = True

    def stop(self) -> None:
        with self._lifecycle_lock:
            if not self._started:
                return
            self._started = False

        for poller in self._pollers.values():
            poller.stop()
        for poller in self._camera_pollers.values():
            poller.stop()

    def get_snapshot(self) -> dict[str, Any]:
        if not self._started:
            self.start()

        results = []
        for target in RIG_TARGETS:
            rig_id = target["id"]
            results.append(
                {
                    **self._pollers[rig_id].get_result(),
                    **self._camera_pollers[rig_id].get_result(),
                }
            )
        return {
            "timestamp": _utc_now().isoformat(),
            "rigs": results,
        }


_rig_status_service = RigOverviewStatusService()


def start_rig_status_service() -> None:
    _rig_status_service.start()


def stop_rig_status_service() -> None:
    _rig_status_service.stop()


@router.get("/api/rig-overview/status")
def get_rig_overview_status(request: Request):
    payload = _rig_status_service.get_snapshot()
    if is_request_ip_allowed(request):
        return payload

    filtered_rigs = [
        rig for rig in payload.get("rigs", [])
        if rig.get("id") != "prototype"
    ]
    return {
        **payload,
        "rigs": filtered_rigs,
    }

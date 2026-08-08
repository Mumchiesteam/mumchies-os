"""Small persistent stale-while-refresh store for management reports."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import settings

SNAPSHOT_FILE = settings.data_dir / "report_snapshots.json"
SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)


class ReportSnapshotStore:
    _lock = Lock()

    @classmethod
    def _read(cls) -> dict[str, dict[str, Any]]:
        if not SNAPSHOT_FILE.exists():
            return {}
        try:
            with SNAPSHOT_FILE.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @classmethod
    def get(cls, key: str) -> dict[str, Any] | None:
        with cls._lock:
            value = cls._read().get(key)
            return deepcopy(value) if isinstance(value, dict) else None

    @staticmethod
    def is_stale(snapshot: dict[str, Any] | None, max_age_seconds: int) -> bool:
        if not snapshot or not snapshot.get("last_refreshed_at"):
            return True
        try:
            refreshed = datetime.fromisoformat(str(snapshot["last_refreshed_at"]).replace("Z", "+00:00"))
        except ValueError:
            return True
        return (datetime.now(timezone.utc) - refreshed.astimezone(timezone.utc)).total_seconds() >= max_age_seconds

    @classmethod
    def save_success(cls, key: str, data: dict[str, Any]) -> None:
        with cls._lock:
            payload = cls._read()
            payload[key] = {
                "data": data,
                "last_refreshed_at": datetime.now(timezone.utc).isoformat(),
                "refresh_error": None,
            }
            cls._write(payload)

    @classmethod
    def save_error(cls, key: str, message: str) -> None:
        with cls._lock:
            payload = cls._read()
            current = payload.get(key) if isinstance(payload.get(key), dict) else {}
            current["refresh_error"] = message
            current["last_refresh_failed_at"] = datetime.now(timezone.utc).isoformat()
            payload[key] = current
            cls._write(payload)

    @staticmethod
    def _write(payload: dict[str, Any]) -> None:
        temporary = Path(f"{SNAPSHOT_FILE}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        temporary.replace(SNAPSHOT_FILE)

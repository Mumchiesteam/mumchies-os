"""Local persistent operational storage for orders."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import BACKEND_DIR

OPS_FILE = BACKEND_DIR / "data" / "order_operations.json"
OPS_FILE.parent.mkdir(parents=True, exist_ok=True)


class OrderOperationsStore:
    _lock = Lock()
    _default_record = {
        "call_logs": [],
        "corrected_address": None,
        "address_verified": False,
        "address_verified_at": None,
        "address_verified_by": None,
        "verified_address_snapshot": None,
        "courier_sync_status": None,
        "courier_sync_error": None,
    }

    @classmethod
    def _read_all(cls) -> dict[str, Any]:
        if not OPS_FILE.exists():
            return {}
        with OPS_FILE.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @classmethod
    def _write_all(cls, payload: dict[str, Any]) -> None:
        with OPS_FILE.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    @classmethod
    def get(cls, order_id: str) -> dict[str, Any]:
        with cls._lock:
            return cls._read_all().get(order_id, dict(cls._default_record))

    @classmethod
    def all(cls) -> dict[str, dict[str, Any]]:
        with cls._lock:
            return cls._read_all()

    @classmethod
    def save_address(cls, order_id: str, address: dict[str, Any], courier_sync_status: str | None = None, courier_sync_error: str | None = None) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, dict(cls._default_record))
            record["corrected_address"] = address
            record["address_verified"] = False
            record["address_verified_at"] = None
            record["address_verified_by"] = None
            record["verified_address_snapshot"] = None
            record["courier_sync_status"] = courier_sync_status
            record["courier_sync_error"] = courier_sync_error
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def append_call_log(cls, order_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, dict(cls._default_record))
            record["call_logs"] = [entry, *record.get("call_logs", [])]
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def verify_address(cls, order_id: str, operator: str, snapshot: dict[str, Any], verified_at: str) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, dict(cls._default_record))
            record["address_verified"] = True
            record["address_verified_at"] = verified_at
            record["address_verified_by"] = operator
            record["verified_address_snapshot"] = snapshot
            data[order_id] = record
            cls._write_all(data)
            return record

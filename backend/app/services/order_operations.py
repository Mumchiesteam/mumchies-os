"""Local persistent operational storage for orders."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import settings

OPS_FILE = settings.data_dir / "order_operations.json"
OPS_FILE.parent.mkdir(parents=True, exist_ok=True)


class OrderOperationsStore:
    _lock = Lock()
    _default_record = {
        "call_logs": [],
        "address_confirmation_comments": [],
        "cancellation": None,
        "timeline_events": [],
        "corrected_address": None,
        "package_details": None,
        "selected_courier": None,
        "address_verified": False,
        "address_verified_at": None,
        "address_verified_by": None,
        "verified_address_snapshot": None,
        "courier_sync_status": None,
        "courier_sync_error": None,
        "address_sync_results": {
            "shopify_order": "not_applicable",
            "shopify_customer": "not_applicable",
            "shiprocket": "not_applicable",
            "delhivery": "not_applicable",
        },
        "human_actions": [],
        "first_action_at": None,
        "shadowfax_direct_test": None,
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
            return cls._read_all().get(order_id, deepcopy(cls._default_record))

    @staticmethod
    def _record_action(record: dict[str, Any], action: str, timestamp: str | None = None, operator: str | None = None) -> None:
        occurred_at = timestamp or datetime.now(timezone.utc).isoformat()
        record.setdefault("human_actions", []).append({"action": action, "timestamp": occurred_at, "operator": operator})
        record["first_action_at"] = record.get("first_action_at") or occurred_at

    @classmethod
    def all(cls) -> dict[str, dict[str, Any]]:
        with cls._lock:
            return cls._read_all()

    @classmethod
    def update_shadowfax_direct_test(cls, order_id: str, **fields: Any) -> dict[str, Any]:
        """Persist sanitized diagnostics for the temporary order-324541 test."""
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            state = record.get("shadowfax_direct_test") or {}
            state.update(fields)
            record["shadowfax_direct_test"] = state
            data[order_id] = record
            cls._write_all(data)
            return deepcopy(state)

    @classmethod
    def reset_legacy_shadowfax_direct_test(cls, order_id: str) -> None:
        """Remove only the temporary legacy guard/diagnostics for order 324541."""
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            record["timeline_events"] = [
                event for event in record.get("timeline_events", [])
                if event.get("action") != "shadowfax_direct_test_324541_started"
            ]
            record["shadowfax_direct_test"] = None
            data[order_id] = record
            cls._write_all(data)

    @classmethod
    def save_address(cls, order_id: str, address: dict[str, Any], courier_sync_status: str | None = None, courier_sync_error: str | None = None, operator: str | None = None) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            record["corrected_address"] = address
            record["selected_courier"] = record.get("selected_courier")
            record["address_verified"] = False
            record["address_verified_at"] = None
            record["address_verified_by"] = None
            record["verified_address_snapshot"] = None
            record["courier_sync_status"] = courier_sync_status
            record["courier_sync_error"] = courier_sync_error
            cls._record_action(record, "address_corrected", operator=operator)
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def append_address_confirmation(cls, order_id: str, comment: str, operator: str, timestamp: str) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            entry = {"comment": comment, "operator": operator, "timestamp": timestamp}
            record["address_confirmation_comments"] = [entry, *record.get("address_confirmation_comments", [])]
            cls._record_action(record, "address_confirmation_commented", timestamp, operator)
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def record_timeline_event(cls, order_id: str, action: str, *, operator: str | None = None, details: dict[str, Any] | None = None, timestamp: str | None = None) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            occurred_at = timestamp or datetime.now(timezone.utc).isoformat()
            record.setdefault("timeline_events", []).append({"action": action, "timestamp": occurred_at, "operator": operator, "details": details or {}})
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def save_cancellation(cls, order_id: str, result: dict[str, Any], operator: str, timestamp: str) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            record["cancellation"] = {**result, "operator": operator, "timestamp": timestamp}
            record["call_logs"] = [{"result": "Cancelled", "comment": result.get("comment") or "", "operator": operator, "timestamp": timestamp}, *record.get("call_logs", [])]
            cls._record_action(record, "order_cancelled", timestamp, operator)
            record.setdefault("timeline_events", []).append({"action": "order_cancelled", "timestamp": timestamp, "operator": operator, "details": result})
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def append_call_log(cls, order_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            record["call_logs"] = [entry, *record.get("call_logs", [])]
            cls._record_action(record, "call_logged", entry.get("timestamp"), entry.get("operator"))
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def verify_address(cls, order_id: str, operator: str, snapshot: dict[str, Any], verified_at: str) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            record["address_verified"] = True
            record["address_verified_at"] = verified_at
            record["address_verified_by"] = operator
            record["verified_address_snapshot"] = snapshot
            cls._record_action(record, "address_verified", verified_at, operator)
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def save_package_details(cls, order_id: str, package_details: dict[str, Any]) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            record["package_details"] = package_details
            cls._record_action(record, "package_details_saved")
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def save_selected_courier(cls, order_id: str, selected_courier: dict[str, Any] | None) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            record["selected_courier"] = selected_courier
            cls._record_action(record, "courier_selected")
            data[order_id] = record
            cls._write_all(data)
            return record

    @classmethod
    def save_address_sync_results(cls, order_id: str, results: dict[str, Any]) -> dict[str, Any]:
        with cls._lock:
            data = cls._read_all()
            record = data.get(order_id, deepcopy(cls._default_record))
            record["address_sync_results"] = results
            data[order_id] = record
            cls._write_all(data)
            return record

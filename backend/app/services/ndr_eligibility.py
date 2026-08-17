from __future__ import annotations

import re
from typing import Any

PRE_PICKUP_STATES = {"pickup not attempted", "pickup pending", "ready for pickup", "pickup scheduled", "pickup failed", "shipment not yet picked up"}
DELIVERY_EXCEPTIONS = (
    "customer unavailable", "customer not available", "customer uncontactable",
    "consignee unavailable", "consignee not available", "consignee unreachable",
    "customer refused", "consignee refused", "refused to accept", "refusal",
    "delivery rescheduled", "future delivery", "wrong address", "address incorrect",
    "incomplete address", "address incomplete", "delivery attempt failed", "delivery failed",
    "attempted but not delivered", "undelivered", "not delivered", "delivery not attempted",
    "otp", "customer nc", "customer cid", "ndr",
)


def normalize_ndr_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold().replace("_", " ").replace("-", " "))


def is_pre_pickup_state(*values: Any) -> bool:
    return any(normalize_ndr_text(value) in PRE_PICKUP_STATES for value in values)


def is_ndr_eligible(*values: Any) -> bool:
    normalized = [normalize_ndr_text(value) for value in values if normalize_ndr_text(value)]
    if is_pre_pickup_state(*normalized):
        return False
    text = " ".join(normalized)
    return any(marker in text for marker in DELIVERY_EXCEPTIONS)

"""Static Shadowfax preferred-pincode recommendations imported from Sheet2.

This is reference intelligence only. It must never be treated as live
serviceability or used to select/book a courier.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import TypedDict


DATA_FILE = Path(__file__).resolve().parents[1] / "reference_data" / "shadowfax_preferred_pincodes.json"


class ShadowfaxPincodeRecommendation(TypedDict):
    pincode: str
    hub: str
    region: str
    confidence: str
    reference_only: bool


@lru_cache(maxsize=1)
def _reference_data() -> dict[str, list[str]]:
    with DATA_FILE.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Shadowfax pincode reference data is invalid.")
    return payload


def shadowfax_pincode_recommendation(value: object) -> ShadowfaxPincodeRecommendation | None:
    pincode = str(value or "").strip()
    if not re.fullmatch(r"\d{6}", pincode):
        return None
    row = _reference_data().get(pincode)
    if not isinstance(row, list) or len(row) != 3:
        return None
    hub, region, confidence = row
    if confidence not in {"Super Confident", "Confident"}:
        return None
    return {
        "pincode": pincode, "hub": hub, "region": region,
        "confidence": confidence, "reference_only": True,
    }

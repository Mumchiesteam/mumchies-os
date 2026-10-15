"""Mumchies' supplied Shadowfax 360 Bengaluru-origin rate-card estimates."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ShadowfaxRateEstimate:
    zone: str
    base_rate: float
    including_gst: float


def _normalise(value: object) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").casefold())


_BENGALURU = {"bengaluru", "bangalore"}
_KARNATAKA = {"karnataka"}
_SPECIAL = {
    "arunachalpradesh", "assam", "manipur", "meghalaya", "mizoram", "nagaland",
    "sikkim", "tripura", "jammukashmir", "jammuandkashmir",
}
_INDIAN_STATES_AND_UTS = {
    *_SPECIAL, *_KARNATAKA,
    "andhrapradesh", "bihar", "chhattisgarh", "goa", "gujarat", "haryana", "himachalpradesh",
    "jharkhand", "kerala", "madhyapradesh", "maharashtra", "odisha", "orissa", "punjab",
    "rajasthan", "tamilnadu", "telangana", "uttarpradesh", "uttarakhand", "westbengal",
    "andamannicobarislands", "chandigarh", "dadraandnagarhavelianddamandiu", "delhi",
    "nctofdelhi", "lakshadweep", "ladakh", "puducherry", "pondicherry",
}


def bengaluru_origin_rate(destination_state: object, destination_city: object) -> ShadowfaxRateEstimate | None:
    """Return a static estimate only when the supplied destination can be classified safely."""
    state = _normalise(destination_state)
    city = _normalise(destination_city)
    if state in _SPECIAL:
        return ShadowfaxRateEstimate("Zone E", 69.0, 81.42)
    if state in _KARNATAKA:
        if city in _BENGALURU:
            return ShadowfaxRateEstimate("Zone A", 39.0, 46.02)
        if city:
            return ShadowfaxRateEstimate("Zone B", 49.0, 57.82)
        return None
    if state in _INDIAN_STATES_AND_UTS:
        return ShadowfaxRateEstimate("Zone C/D", 59.0, 69.62)
    return None

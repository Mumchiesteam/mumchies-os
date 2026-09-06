"""Run the non-negotiable courier/order-flow regression suite before deployment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


TEST_FILES = (
    "tests/test_shiprocket_integration.py",
    "tests/test_delhivery.py",
    "tests/test_delhivery_native_label.py",
    "tests/test_courier_platform.py",
    "tests/test_shadowfax_channel_order_diagnostic.py",
    "tests/test_cross_order_booking_integrity.py",
    "tests/test_shopify_fulfillment_sync.py",
    "tests/test_shipment_events.py",
)


def main() -> int:
    backend = Path(__file__).resolve().parents[1]
    compile_result = subprocess.call([sys.executable, "-m", "compileall", "-q", "app"], cwd=backend)
    if compile_result:
        return compile_result
    return subprocess.call([sys.executable, "-m", "pytest", *TEST_FILES], cwd=backend)


if __name__ == "__main__":
    raise SystemExit(main())

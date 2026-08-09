from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.courier_platform.models import (
    BookingResult, CancellationResult, LabelResult, ProviderCapabilities,
    ServiceabilityResult, TrackingResult,
)


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, provider: str, operation: str, retryable: bool = False, uncertain: bool = False, http_status: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation
        self.retryable = retryable
        self.uncertain = uncertain
        self.http_status = http_status


class ProviderConfigurationError(ProviderError):
    pass


class CourierAdapter(ABC):
    provider: str
    capabilities: ProviderCapabilities

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def authenticate(self) -> bool: ...

    @abstractmethod
    async def serviceability(self, request: dict[str, Any]) -> ServiceabilityResult: ...

    @abstractmethod
    async def create_booking(self, request: dict[str, Any]) -> BookingResult: ...

    @abstractmethod
    async def reconcile_booking(self, merchant_order_id: str) -> BookingResult | None: ...

    @abstractmethod
    async def track_shipment(self, shipment: dict[str, Any]) -> TrackingResult: ...

    @abstractmethod
    async def cancel_booking(self, shipment: dict[str, Any]) -> CancellationResult: ...

    @abstractmethod
    async def download_label(self, shipment: dict[str, Any]) -> LabelResult: ...

    def sanitize(self, value: Any) -> Any:
        secret_keys = {"authorization", "token", "access_token", "password", "secret", "api_key", "apikey"}
        pii_keys = {"phone", "contact_number", "email", "address", "name"}
        if isinstance(value, dict):
            return {str(k): "[REDACTED]" if str(k).casefold() in secret_keys | pii_keys else self.sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.sanitize(item) for item in value]
        return value

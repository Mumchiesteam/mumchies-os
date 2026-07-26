from __future__ import annotations

from app.services.courier_platform.base import CourierAdapter, ProviderError


class CourierRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, CourierAdapter] = {}

    def register(self, adapter: CourierAdapter) -> None:
        self._adapters[adapter.provider.casefold()] = adapter

    def get(self, provider: str) -> CourierAdapter:
        adapter = self._adapters.get(provider.casefold())
        if adapter is None:
            raise ProviderError(f"Unknown courier provider: {provider}", provider=provider, operation="registry")
        return adapter

    def capabilities(self) -> dict[str, dict[str, object]]:
        return {name: {"configured": adapter.configured, **adapter.capabilities.model_dump()} for name, adapter in self._adapters.items()}


courier_registry = CourierRegistry()


def register_default_adapters() -> None:
    """Register adapters that do not require route-owned legacy dependencies."""
    from app.services.courier_platform.adapters import DelhiveryAdapter, ShadowfaxAdapter, ShiprocketAdapter
    courier_registry.register(ShiprocketAdapter())
    courier_registry.register(DelhiveryAdapter())
    courier_registry.register(ShadowfaxAdapter())


register_default_adapters()

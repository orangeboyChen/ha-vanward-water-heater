"""Common entity base for Vanward water heaters."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VanwardCoordinator


class VanwardEntity(CoordinatorEntity[VanwardCoordinator]):
    """Base entity."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: VanwardCoordinator, key: str, translation_key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_translation_key = translation_key

    @property
    def available(self) -> bool:
        """Entity is available only if the device reported recently.

        v3.2: WebSocket may stay connected to the cloud while the device
        itself is offline (power cut / wifi lost). Treat entities as
        unavailable after OFFLINE_TIMEOUT without a status report so HA
        (and the HomeKit bridge) show "offline" instead of stale state.
        """
        if self.coordinator.data is None:
            return False
        return self.coordinator.client.is_device_online(
            self.coordinator.device_id
        )

    @property
    def device_info(self) -> DeviceInfo:
        state = self.coordinator.data
        info = state.device_info
        return DeviceInfo(
            identifiers={(DOMAIN, info.device_id)},
            manufacturer="Vanward",
            # v3.3: 设备名统一为"热水器"（家人看 HA 一眼就懂）；
            # 型号仍保留在 model 字段，可在设备信息页查看
            name="热水器",
            model=info.model,
            sw_version=info.series,
        )
